
from fractions import Fraction

from .datafile import Datafile
from .calculator import Calculator, split_into_steps
from .beltmanager import BeltManager, Placement, Compaction
from .layouter import layout
from .art_encoder import ArtEncoder
from . import blueprint


def format_bus(bus):
	return ', '.join(
		"{:.2f}/sec {}".format(float(line.throughput), line.item)
		if line is not None else "-"
		for line in bus
	)


def main(items, data_path='./factorio_recipes', stop_items='', show_conflicts=False, verbose=False):
	def v(s):
		if verbose:
			print s

	_items = {}
	if items:
		for entry in items.split(','):
			name, throughput = entry.split('=', 1)
			name = name.lower()
			throughput = Fraction(throughput)
			_items[name] = throughput
	items = _items

	if stop_items:
		stop_items = [name.lower() for name in stop_items.split(',')]

	datafile = Datafile(data_path)
	calculator = Calculator(
		datafile,
		stop_items,
		beacon_speed=4, # double-row of beacons
		oil_beacon_speed=6, # double-row of beacons
	)

	v("=== Calculator stage ===")
	processes = calculator.solve_with_oil(items)
	for name, process in processes.items():
		v("{}: {}".format(name, process))

	v("=== Step breakdown stage ===")
	steps, inputs = split_into_steps(processes)
	v("Inputs:")
	for process in inputs:
		v(process)
	v("Steps:")
	for process in steps:
		v(process)

	v("=== Belt manager stage ===")
	manager = BeltManager(steps, inputs)
	manager.run()
	for step in manager.output:
		v("Bus: {}".format(format_bus(step.bus)))
		if isinstance(step, Placement):
			v("{}: {} -> {}".format(
				step.process,
				", ".join(map(str, sorted(step.inputs.keys()))),
				", ".join(map(str, sorted(step.outputs.keys()))),
			))
		elif isinstance(step, Compaction):
			v("Compact {}".format(", ".join([
				"{} into {}".format(s, d) for d, s in step.compactions
			] + [
				"{} becomes {}".format(s, d) for s, d in step.shifts
			])))
		else:
			v(step)
	v("Bus: {}".format(format_bus(manager.bus)))

	v("=== Layouter stage ===")
	l = layout(manager.output, manager.bus)
	v(l)

	v("=== Flattener stage ===")
	entities = l.flatten()
	for pos, e in entities:
		v("{}, {}: {}".format(pos.x, pos.y, e))

	v("=== Encoder stage ===")
	print ArtEncoder(error_on_conflict = not show_conflicts).encode(entities)
	print
	print blueprint.encode(entities)
