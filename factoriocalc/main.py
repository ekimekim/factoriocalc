
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
	if arg == '':
		return []
	return [part.lower() for part in arg.split(',')]


@arg('-s', '--stop-items', type=comma_sep)
@arg('-m', '--modules', type=comma_sep)
@arg('-b', '--beacon-module-level')
@arg('--belt-type', choices=["blue", "red", "yellow"])
def main(items,
	data_path='./factorio_recipes',
	stop_items=[],
	modules=None,
	beacon_module_level=3,
	belt_type='blue',
	show_conflicts=False,
	verbose=0,
):
	def v(n, s):
		if verbose >= n:
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
	if beacon_module_level > 0:
		beacon_module = datafile.modules["speed {}".format(beacon_module_level)]
		beacon_speed = beacon_module.speed # 2 modules in beacon, but each only has 50% effect
		beacon_module_name = beacon_module.name
	else:
		# no beacons
		beacon_speed = 0
		beacon_module_name = None
	calculator = Calculator(
		datafile,
		stop_items,
		module_priorities=modules if modules is not None else Calculator.DEFAULT_MODS,
		beacon_speed=8*beacon_speed, # double-row of beacons
		oil_beacon_speed=12*beacon_speed, # double-row of beacons
	)

	v(2, "=== Calculator stage ===")
	processes = calculator.solve_with_oil(items)
	for name, process in processes.items():
		v(2, "{}: {}".format(name, process))

	v(1, "=== Step breakdown stage ===")
	steps, inputs = split_into_steps(processes, belt_type=belt_type)
	v(1, "Inputs:")
	for process in inputs:
		v(1, process)
	v(1, "Steps:")
	for process in steps:
		v(1, process)

	v(1, "=== Belt manager stage ===")
	manager = BeltManager(steps, inputs)
	manager.run()
	for step in manager.output:
		v(2, "Bus: {}".format(format_bus(step.bus)))
		if isinstance(step, Placement):
			v(1, "{}: {} -> {}".format(
				step.process,
				", ".join(map(str, sorted(step.inputs.keys()))),
				", ".join(map(str, sorted(step.outputs.keys()))),
			))
		elif isinstance(step, Compaction):
			v(1, "Compact {}".format(", ".join([
				"{} into {}".format(s, d) for d, s in step.compactions
			] + [
				"{} becomes {}".format(s, d) for s, d in step.shifts
			])))
		else:
			v(1, step)
	v(1, "Final Bus: {}".format(format_bus(manager.bus)))

	v(3, "=== Layouter stage ===")
	l = layout(belt_type, beacon_module_name, manager.output, manager.bus)
	v(3, l)

	v(3, "=== Flattener stage ===")
	entities = l.flatten()
	for pos, e in entities:
		v(3, "{}, {}: {}".format(pos.x, pos.y, e))

	v(1, "=== Encoder stage ===")
	print ArtEncoder(error_on_conflict = not show_conflicts).encode(entities)
	print
	print blueprint.encode(entities)
