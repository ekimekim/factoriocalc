
from fractions import Fraction

from .datafile import Datafile
from .calculator import Calculator


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
	processes = calculator.solve_with_oil(items)
	steps = calculator.split_into_steps(processes)
	print steps
