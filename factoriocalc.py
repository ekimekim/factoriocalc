
import math
import re
import sys
from collections import OrderedDict

# We use ceil() at the end of calculations, and don't want floating point error
# to make us slightly over an integer and cause us to add another for no reason.
from fractions import Fraction


def parse_data(datafile):
	"""Data file consists of one entry per line. Each entry is either a recipe or a building.
	Building lines look like:
		BUILDING builds at SPEED
	For example:
		Assembler builds at 1.25
	and recipe lines look like:
		[AMOUNT ]OUTPUT takes TIME in BUILDING{, AMOUNT INPUT}
	For example:
		Green circuit takes 0.5 in assembler, 1 iron plate, 3 copper wire
		2 transport belt takes 0.5 in assembler, 1 iron plate, 1 gear
	Lines may also be comments, indicated by beginning with a '#'.
	All names are case insensitive, and may contain any character except newline and comma.

	Not all inputs need a way to produce them. These will be listed as "raw inputs"
	in the results.

	This function returns a dict {item: (building, throughput per building, {input: input amount for 1 output})}
	"""
	with open(datafile) as f:
		buildings = {}
		items = {}
		for n, line in enumerate(f):
			n += 1 # 1-based, not 0-based line numbers
			line = line.strip()
			if not line or line.startswith('#'):
				continue

			try:
				match = re.match('^([^,]+) builds at ([0-9.]+)$', line)
				if match:
					name, speed = match.groups()
					name = name.lower()
					if name in buildings:
						raise ValueError('Building {!r} already declared'.format(name))
					buildings[name] = Fraction(speed)
					continue

				match = re.match('^(\d+ )?(.+) takes ([0-9.]+) in ([^,]+)((?:, \d+ [^,]+)*)$', line)
				if match:
					amount, name, time, building, inputs_str = match.groups()
					amount = int(amount) if amount else 1
					time = Fraction(time)
					name = name.lower()
					building = building.lower()
					inputs = {}
					if inputs_str:
						for part in inputs_str.split(','):
							part = part.strip()
							if not part:
								continue
							input_amount, input_name = part.split(' ', 1)
							input_amount = int(input_amount)
							inputs[input_name] = input_amount
					items[name] = amount, time, building, inputs
					continue

				raise ValueError("Unknown entry syntax")
			except Exception as e:
				_, _, tb = sys.exc_info()
				raise ValueError, ValueError("Error in line {} of {!r}: {}".format(n, datafile, e)), tb

	results = {}
	for item, (amount, time, building, inputs) in items.items():
		if building not in buildings:
			raise ValueError("Error in {!r}: {!r} is built in {!r}, but no such building declared".format(item, building))
		speed = buildings[building]
		throughput = speed * amount / time
		inputs = {input_name: Fraction(input_amount) / amount for input_name, input_amount in inputs.items()}
		results[item] = building, throughput, inputs

	return results


def solve(recipes, item, throughput):
	"""Returns a dict {item: number of buildings needed producing that item}
	such that the requested throughput of the input item can be produced.
	Items which don't have a recipe are also included, but their value is the amount of items
	per second needed as input.
	"""
	_, per_building, inputs = recipes[item]
	buildings = throughput / per_building
	# We use an ordered dict so later we can print items in dependency order
	result = OrderedDict({item: buildings})
	for name, amount in inputs.items():
		amount *= throughput
		if name in recipes:
			subresult = solve(recipes, name, amount)
		else:
			# raw input, we represent it as one 'building' being one input per second
			subresult = {name: amount}
		merge_into(result, subresult)
	return result


def merge_into(a, b):
	for k, v in b.items():
		a[k] = a.get(k, 0) + v


def main(item, rate, datafile='factorio_recipes'):
	"""Calculate ratios and output number of production facilities needed
	to craft a specific output at a specific rate in Factorio.
	Requires a data file specifying available recipies and buildings. See source for syntax.
	Defaults to a file 'factorio_recipes' in the current directory.
	Rate should be expressed in decimal items per second.

	Limitations:
		- Can't know more than one recipe per unique output item (eg. different ways to make Solid Fuel)
		- Can't build recipe in multiple building types (eg. Assembly Machine 1/2/3)
		- Recipes can't have more than one output (eg. oil processing)
		- No dependency cycles (eg. coal liquification, Kovarex enrichment)
		- Doesn't use Modules
	"""
	recipes = parse_data(datafile)
	rate = Fraction(rate)
	results = solve(recipes, item, rate)
	for item, amount in results.items():
		if item in recipes:
			building, _, _ = recipes[item]
			print '{} {} producing {}'.format(int(math.ceil(amount)), building, item)
		else:
			print '{:.2f}/sec of {}'.format(float(amount), item)


if __name__ == '__main__':
	import argh
	argh.dispatch_command(main)
