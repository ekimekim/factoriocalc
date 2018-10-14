
from fractions import Fraction

from .datafile import Datafile
from .calculator import Calculator, split_into_steps
from .beltmanager import BeltManager, Placement, Compaction
from .layouter import layout, flatten
from .art_encoder import ArtEncoder


def format_bus(bus):
	return ', '.join(
		"{:.2f}/sec {}".format(float(line.throughput), line.item)
		if line is not None else "-"
		for line in bus
	)


def main(items, data_path='./factorio_recipes', stop_items=''):

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

	print "=== Calculator stage ==="
	processes = calculator.solve_with_oil(items)
	for name, process in processes.items():
		print "{}: {}".format(name, process)

	print "=== Step breakdown stage ==="
	steps, inputs = split_into_steps(processes)
	print "Inputs:"
	for process in inputs:
		print process
	print "Steps:"
	for process in steps:
		print process

	print "=== Belt manager stage ==="
	manager = BeltManager(steps, inputs)
	manager.run()
	for step in manager.output:
		print "Bus: {}".format(format_bus(step.bus))
		if isinstance(step, Placement):
			print "{}: {} -> {}".format(
				step.process,
				", ".join(map(str, sorted(step.inputs.keys()))),
				", ".join(map(str, sorted(step.outputs.keys()))),
			)
		elif isinstance(step, Compaction):
			print "Compact {}".format(", ".join([
				"{} into {}".format(s, d) for d, s in step.compactions
			] + [
				"{} becomes {}".format(s, d) for s, d in step.shifts
			]))
		else:
			print step
	print "Bus: {}".format(format_bus(manager.bus))

	print "=== Layouter stage ==="
	primitives = layout(manager.output, manager.bus)
	for p in primitives:
		print "{}: {}".format(p.position, ", ".join(map(str, p.primitive)))

	print "=== Flattener stage ==="
	entities = flatten(primitives)
	for e in entities:
		print e

	print "=== Encoder stage ==="
	print ArtEncoder().encode(entities)
