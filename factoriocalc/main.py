
from fractions import Fraction

from .datafile import Datafile
from .calculator import Calculator


def format_namedtuple(x):
	return '{}({})'.format(
		type(x).__name__,
		', '.join('{}={!r}'.format(k, v) for k, v in x._asdict().items()),
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
	steps, inputs = calculator.split_into_steps(processes)
	print "Inputs:"
	for process in inputs:
		print process
	print "Steps:"
	for process in steps:
		print process
