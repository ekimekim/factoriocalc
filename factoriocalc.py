
import math
import re
import sys
from collections import OrderedDict, Counter
from pprint import pprint

# We use ceil() at the end of calculations, and don't want floating point error
# to make us slightly over an integer and cause us to add another for no reason.
from fractions import Fraction


def get_recipes(datafile, module_priorities, verbose=False):
	"""Data file consists of one entry per line. Each entry is either a recipe, building or module.
	Building lines look like:
		BUILDING builds at SPEED[ with N modules]
	For example:
		Assembler builds at 1.25 with 4 modules
	Recipe lines look like:
		[AMOUNT ]OUTPUT takes TIME in BUILDING{, AMOUNT INPUT}[, can take productivity]
	For example:
		Green circuit takes 0.5 in assembler, 1 iron plate, 3 copper wire, can take productivity
		2 transport belt takes 0.5 in assembler, 1 iron plate, 1 gear
	Module lines look like:
		NAME module affects speed AMOUNT[, prod AMOUNT]
	For example:
		prod 2 module affects speed -.15, prod .06
	Lines may also be comments, indicated by beginning with a '#'.
	All names are case insensitive, and may contain any character except newline and comma.

	Not all inputs need a way to produce them. These will be listed as "raw inputs"
	in the results.

	This function returns a dict {item: (building, throughput per building, {input: input amount for 1 output}, list of modules used in building)}
	"""
	with open(datafile) as f:
		buildings = {}
		items = {}
		modules = {}
		for n, line in enumerate(f):
			n += 1 # 1-based, not 0-based line numbers
			line = line.strip()
			if not line or line.startswith('#'):
				continue

			try:
				match = re.match('^([^,]+) builds at ([0-9.]+)(?: with (\d+) modules)?$', line)
				if match:
					name, speed, mods = match.groups()
					mods = int(mods) if mods else 0
					name = name.lower()
					if name in buildings:
						raise ValueError('Building {!r} already declared'.format(name))
					buildings[name] = Fraction(speed), mods
					continue

				match = re.match('^(\d+ )?(.+) takes ([0-9.]+) in ([^,]+)((?:, \d+ [^,]+)*)(, can take productivity)?$', line)
				if match:
					amount, name, time, building, inputs_str, prod = match.groups()
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
					if name in items:
						raise ValueError('Recipe for {!r} already declared'.format(name))
					items[name] = amount, time, building, inputs, prod
					continue

				match = re.match('^([^,]+) module affects speed ([^,]+)(?:, prod ([^,]+))?$', line)
				if match:
					name, speed, prod = match.groups()
					speed = Fraction(speed)
					prod = Fraction(prod) if prod else 0
					name = name.lower()
					if name in modules:
						raise ValueError('Module {!r} already declared'.format(name))
					modules[name] = speed, prod
					continue

				raise ValueError("Unknown entry syntax")
			except Exception as e:
				_, _, tb = sys.exc_info()
				raise ValueError, ValueError("Error in line {} of {!r}: {}".format(n, datafile, e)), tb

	# validate module list
	for mod in module_priorities:
		if mod not in modules:
			raise ValueError("Unknown module type {!r}".format(mod))

	results = {}
	for item, (amount, time, building, inputs, can_prod) in items.items():
		if building not in buildings:
			raise ValueError("Error in {!r}: {!r} is built in {!r}, but no such building declared".format(item, building))
		speed, slots = buildings[building]
		speed, prod, mods = calc_mods(modules, speed, slots, can_prod, module_priorities)
		amount = amount * prod
		throughput = speed * amount / time
		inputs = {input_name: Fraction(input_amount) / amount for input_name, input_amount in inputs.items()}
		results[item] = building, throughput, inputs, mods

	if verbose:
		pprint(results)

	return results


def calc_mods(modules, base_speed, slots, can_prod, priorities):
	"""Calculates final (crafting speed, productivity, list of module names) of a building given:
		- what modules exist
		- building base speed and number of slots
		- whether productivity increases are allowed for this recipe
		- a list of modules in priority order, including repeats. for example,
		  a list like [A, A, B, A] will result in 2x A module if there's 2 slots, 2 As and 1 B if there's 3, 3 As and 1 B if there's 4 or more.
	"""
	used = []
	speed_total = 0
	prod_total = 0
	to_consider = list(priorities)
	while len(used) < slots and to_consider:
		mod = to_consider.pop(0)
		speed, prod = modules[mod]
		if prod and not can_prod:
			continue
		speed_total += speed
		prod_total += prod
		used.append(mod)

	return base_speed * (1 + speed_total), 1 + prod_total, used


def solve(recipes, item, throughput, stop_items):
	"""Returns a dict {item: number of buildings needed producing that item}
	such that the requested throughput of the input item can be produced.
	Items which don't have a recipe are also included, but their value is the amount of items
	per second needed as input, as is anything in stop_items.
	"""
	_, per_building, inputs, _ = recipes[item]
	buildings = throughput / per_building
	# We use an ordered dict so later we can print items in dependency order
	result = OrderedDict()
	for name, amount in inputs.items():
		amount *= throughput
		if name in recipes and name not in stop_items:
			subresult = solve(recipes, name, amount, stop_items)
		else:
			# raw input, we represent it as one 'building' being one input per second
			subresult = {name: amount}
		merge_into(result, subresult)
	merge_into(result, {item: buildings})
	return result


def merge_into(a, b):
	for k, v in b.items():
		a[k] = a.get(k, 0) + v


def main(items, rate, datafile='factorio_recipes', modules='', fractional=False, verbose=False,
         stop_at=''):
	"""Calculate ratios and output number of production facilities needed
	to craft a specific output at a specific rate in Factorio.
	Requires a data file specifying available recipies and buildings. See source for syntax.
	Defaults to a file 'factorio_recipes' in the current directory.
	Item may be a single item, or a comma-seperated list.
	Rate should be expressed in decimal items per second.
	Modules to use can be given as a comma-seperated list, and should list priority order for
	what modules should go in a building, with repeats for more than one of the same kind.
	For example, an input like --modules='prod 1, prod 1, speed 1' will only put a speed module in
	buildings with more than 2 slots.
	stop-at can be given as a list of items to stop breaking down at, ie. to treat them as raw inputs.

	Limitations:
		- Can't know more than one recipe per unique output item (eg. different ways to make Solid Fuel)
		- Can't build recipe in multiple building types (eg. Assembly Machine 1/2/3)
		- Recipes can't have more than one output (eg. oil processing)
		- No dependency cycles (eg. coal liquification, Kovarex enrichment)
	"""
	items = [item.strip().lower() for item in items.split(',')]
	modules = [name.strip().lower() for name in modules.split(',')] if modules else []
	stop_items = [item.strip().lower() for item in stop_at.split(',')] if stop_at else []
	recipes = get_recipes(datafile, modules, verbose)
	rate = Fraction(rate)
	results = OrderedDict()
	for item in items:
		merge_into(results, solve(recipes, item, rate, stop_items))
	for item, amount in results.items():
		if item in recipes and item not in stop_items:
			building, per_building, _, mods = recipes[item]
			mods_str = ' with {}'.format(', '.join(
				'{}x {}'.format(count, name)
				for name, count in sorted(
					Counter(mods).items(), key=lambda (name, count): (count, name)
				)
			)) if mods else ''
			throughput = amount * per_building
			print '{} {}{} producing {:.2f}/sec of {}'.format(
				(int(math.ceil(amount)) if not fractional else '{:.2f}'.format(float(amount))),
				building, mods_str, float(throughput), item
			)
		else:
			print '{:.2f}/sec of {}'.format(float(amount), item)


if __name__ == '__main__':
	import argh
	argh.dispatch_command(main)
