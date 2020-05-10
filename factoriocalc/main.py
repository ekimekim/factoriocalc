
from fractions import Fraction

from argh import arg

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


def comma_sep(arg):
	return [part.lower() for part in arg.split(',')]


@arg('-s', '--stop-items', type=comma_sep)
@arg('-m', '--modules', type=comma_sep)
@arg('-b', '--beacon-module-level')
def main(items,
	data_path='./factorio_recipes',
	stop_items='',
	modules='',
	beacon_module_level=3,
	show_conflicts=False,
	verbose=False,
):
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

	datafile = Datafile(data_path)
	beacon_module = datafile.modules["speed {}".format(beacon_module_level)]
	beacon_speed = beacon_module.speed # 2 modules in beacon, but each only has 50% effect
	calculator = Calculator(
		datafile,
		stop_items,
		module_priorities=modules if modules else Calculator.DEFAULT_MODS,
		beacon_speed=8*beacon_speed, # double-row of beacons
		oil_beacon_speed=12*beacon_speed, # double-row of beacons
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
	l = layout(beacon_module.name, manager.output, manager.bus)
	v(l)

	v("=== Flattener stage ===")
	entities = l.flatten()
	for pos, e in entities:
		v("{}, {}: {}".format(pos.x, pos.y, e))

	v("=== Encoder stage ===")
	print ArtEncoder(error_on_conflict = not show_conflicts).encode(entities)
	print
	print blueprint.encode(entities)
