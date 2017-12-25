
import math
import os
import re
import sys
from collections import OrderedDict, Counter
from pprint import pprint

# We use ceil() at the end of calculations, and don't want floating point error
# to make us slightly over an integer and cause us to add another for no reason.
from fractions import Fraction


def get_datafile_lines(datafile):
	"""Resolve includes and yield (lineno, line) where lineno is a descriptive string of
	'line number', eg. for an include it might look like "1:foo:5" for line 5 of file foo
	included from line 1."""
	with open(datafile) as f:
		for n, line in enumerate(f):
			if line.startswith('include '):
				path = line[len('include '):-1] # -1 for trailing newline
				path = os.path.join(os.path.dirname(datafile), path)
				for lineno, line in get_datafile_lines(path):
					yield '{}:{}:{}'.format(n, path, lineno), line
			else:
				yield n+1, line


def get_recipes(datafile, module_priorities, verbose=False, beacon_speed=0):
	"""Data file consists of one entry per line. Each entry is either an include, a recipe, building or module.
	Include lines look like:
		include PATH
	and result in the other path (relative to the directory this file is in) being read as though it were
	part of this file.
	Building lines look like:
		BUILDING builds at SPEED[ with N modules][, not affected by beacons]
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

	This function returns a dict:
		{
			item: (
				building,
				throughput per building,
				{input: input amount for 1 output, ...},
				list of modules used in building
			), ...
		}
	"""
	buildings = {}
	items = {}
	modules = {}
	for lineno, line in get_datafile_lines(datafile):
		line = line.strip()
		if not line or line.startswith('#'):
			continue

		try:
			match = re.match('^([^,]+) builds at ([0-9.]+(?:/[0-9.]+)?)(?: with (\d+) modules)?(, not affected by beacons)?$', line)
			if match:
				name, speed, mods, can_not_beacon = match.groups()
				mods = int(mods) if mods else 0
				can_beacon = not can_not_beacon
				name = name.lower()
				if name in buildings:
					raise ValueError('Building {!r} already declared'.format(name))
				buildings[name] = Fraction(speed), mods, can_beacon
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
			raise ValueError, ValueError("Error in line {} of {!r}: {}".format(lineno, datafile, e)), tb

	# validate module list
	for mod in module_priorities:
		if mod not in modules:
			raise ValueError("Unknown module type {!r}".format(mod))

	results = {}
	for item, (amount, time, building, inputs, can_prod) in items.items():
		if building not in buildings:
			raise ValueError("Error in {!r}: {!r} is built in {!r}, but no such building declared".format(datafile, item, building))
		speed, slots, can_beacon = buildings[building]
		speed, prod, mods = calc_mods(modules, speed, slots, can_prod, module_priorities, (beacon_speed if can_beacon else 0))
		
		amount = amount * prod
		throughput = speed * amount / time
		inputs = {input_name: Fraction(input_amount) / amount for input_name, input_amount in inputs.items()}
		results[item] = building, throughput, inputs, mods

	if verbose:
		pprint(results)

	return results


def calc_mods(modules, base_speed, slots, can_prod, priorities, beacon_speed):
	"""Calculates final (crafting speed, productivity, list of module names) of a building given:
		- what modules exist
		- building base speed and number of slots
		- whether productivity increases are allowed for this recipe
		- the speed effects of any nearby beacons
		- a list of modules in priority order, including repeats. for example,
		  a list like [A, A, B, A] will result in 2x A module if there's 2 slots, 2 As and 1 B if there's 3, 3 As and 1 B if there's 4 or more.
	"""
	used = []
	speed_total = beacon_speed
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
	if item not in recipes or item in stop_items:
		# raw input, we represent it as one 'building' being one input per second
		return {item: throughput}
	_, per_building, inputs, _ = recipes[item]
	buildings = throughput / per_building
	# We use an ordered dict so later we can print items in dependency order
	result = OrderedDict()
	for name, amount in inputs.items():
		amount *= throughput
		subresult = solve(recipes, name, amount, stop_items)
		merge_into(result, subresult)
	merge_into(result, {item: buildings})
	return result


def solve_oil(recipes, targets, verbose=False):
	"""Special case solver for standard oil products calculations.
	We use a hack to integrate this calculation with existing features
	around modules, beacon speed, etc. Recipes should contain a dummy
	'oil products' product built in a refinery which produces 1 output in 5 seconds
	(currently, all oil recipes take 5 seconds to complete).
	It should also contain a dummy recipe 'oil cracking' built by a chemical plant in 3 seconds.
	Both recipes should take "1 dummy" as input so that productivity effects can be accounted.
	Targets should be a dict output from solve.
	A modified dict will be returned with the oil products removed, a second with any inputs required,
	along with a list of tuples [(dummy recipe name, oil recipe name, number of buildings)].

	For clarity, these are the recipes considered:
		adv oil processing: 100c+50w -> 10h+45l+55p
		heavy cracking: 40h+30w -> 30l
		light cracking: 30l+30w -> 20p
	If we have excess products, we include a raw output for a negative amount of it
	to indicate to the user that it must be dealt with in some external way.
	"""
	def p(s, *a, **k):
		if verbose:
			print s.format(*a, **k)

	HEAVY_PER_PROCESS, LIGHT_PER_PROCESS, PETROL_PER_PROCESS = 10, 45, 55
	PROCESS_INPUTS = {"crude oil": 100, "water": 50}
	HEAVY_LIGHT_IN, HEAVY_LIGHT_OUT = 40, 30
	LIGHT_PETROL_IN, LIGHT_PETROL_OUT = 30, 20
	HEAVY_LIGHT_INPUTS = {"water": 30}
	LIGHT_PETROL_INPUTS = {"water": 30}

	_, refinery_throughput, dummy, _ = recipes['oil products']
	refinery_input_factor = dummy['dummy']
	_, cracking_throughput, dummy, _ = recipes['oil cracking']
	cracking_input_factor = dummy['dummy']

	light_per_heavy = HEAVY_LIGHT_OUT / Fraction(HEAVY_LIGHT_IN * cracking_input_factor)
	petrol_per_light = LIGHT_PETROL_OUT / Fraction(LIGHT_PETROL_IN * cracking_input_factor)
	petrol_per_process = PETROL_PER_PROCESS / Fraction(refinery_input_factor)
	light_per_process = LIGHT_PER_PROCESS / Fraction(refinery_input_factor)
	heavy_per_process = HEAVY_PER_PROCESS / Fraction(refinery_input_factor)

	excesses = {} # note, negative values
	heavy_cracking = 0 # measured in how many refinery processes' of heavy we need to crack
	light_cracking = 0 # as above
	# since we have no other way of getting more heavy oil, we consider it first
	# to get an absolute minimum.
	heavy_throughput = refinery_throughput * heavy_per_process
	refineries = targets.pop('heavy oil', 0) / Fraction(heavy_throughput)
	p('from heavy oil targets: {} refineries', refineries)
	# now, we assume any additional heavy becomes light oil, and calculate what we need for
	# light with that in mind. We also take into account any light oil we're already making.
	extra_light = targets.pop('light oil', 0) - refineries * refinery_throughput * light_per_process
	if extra_light < 0:
		p('got excess {} light from heavy targets', -extra_light)
		excesses['light oil'] = extra_light
	else:
		light_throughput = refinery_throughput * (light_per_process + heavy_per_process * light_per_heavy)
		refineries_for_light = extra_light / Fraction(light_throughput)
		heavy_cracking += refineries_for_light
		refineries += refineries_for_light
		p('from extra {} light oil targets: {} refineries and crackers', extra_light, refineries_for_light)
	# then we do the same for petroleum, assuming all heavy + light is getting cracked
	extra_petrol = targets.pop('petroleum', 0) - refineries * refinery_throughput * petrol_per_process
	if extra_petrol < 0:
		p('got excess {} petrol from earlier targets', -extra_petrol)
		excesses['petroleum'] = extra_petrol
	else:
		petrol_throughput = refinery_throughput * (
			petrol_per_process + petrol_per_light * (
				light_per_process + heavy_per_process * light_per_heavy
			)
		)
		refineries_for_petrol = extra_petrol / Fraction(petrol_throughput)
		heavy_cracking += refineries_for_petrol
		light_cracking += refineries_for_petrol
		refineries += refineries_for_petrol
		p('from extra {} petrol targets: {} refineries and crackers', extra_petrol, refineries_for_petrol)
	# now we calculate inputs, include excesses, and build the outputs.
	heavy_crackers = heavy_cracking * refinery_throughput * heavy_per_process / Fraction(HEAVY_LIGHT_IN * cracking_throughput)
	light_crackers = light_cracking * refinery_throughput * (light_per_process + heavy_per_process * light_per_heavy) / Fraction(LIGHT_PETROL_IN * cracking_throughput)
	merge_into(targets, excesses)
	buildings = []
	further_inputs = OrderedDict()
	if light_crackers:
		merge_into(further_inputs, {k: v * light_crackers * cracking_throughput for k, v in LIGHT_PETROL_INPUTS.items()})
		buildings.append(('oil cracking', 'Light Oil Cracking', light_crackers))
	if heavy_crackers:
		merge_into(further_inputs, {k: v * heavy_crackers * cracking_throughput for k, v in HEAVY_LIGHT_INPUTS.items()})
		buildings.append(('oil cracking', 'Heavy Oil Cracking', heavy_crackers))
	if refineries:
		merge_into(further_inputs, {k: v * refineries * refinery_throughput for k, v in PROCESS_INPUTS.items()})
		buildings.append(('oil products', 'Advanced Oil Processing', refineries))
	return targets, further_inputs, buildings


def solve_all(recipes, items, stop_items):
	"""Solve for all the given items in form {item: desired throughput}. Output as per solve()"""
	results = OrderedDict()
	for item, amount in items.items():
		merge_into(results, solve(recipes, item, amount, stop_items))
	return results


def solve_with_oil(recipes, items, stop_items, verbose=False):
	"""As per solve_all, but follow it with a call to solve_oil to resolve any oil products.
	It returns (results, buildings) as per solve_oil()"""
	results = solve_all(recipes, items, stop_items)
	results, further_inputs, buildings = solve_oil(recipes, results, verbose=verbose)
	merge_into(results, solve_all(recipes, further_inputs, stop_items))
	return results, buildings


def merge_into(a, b):
	for k, v in b.items():
		a[k] = a.get(k, 0) + v


def main(items, rate, datafile='factorio_recipes', modules='', fractional=False, verbose=False,
         stop_at='', beacon_speed=0., oil=False, inputs_visible=False):
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

	beacon-speed can be given to apply a presumed global speed bonus regardless of building modules.
	For example, to model 8 beacons in range of each building, with each beacon full of speed 3s,
	you would use 8 * .5/2 = 2, and all buildings would act as having a speed bonus of 200%.

	By default, oil processing is not considered (see limitations). However, oil can be considered
	by including the --oil option. This may become default in the future.

	Give --inputs-visible option to also include recipe inputs for each step. Useful for logistic planning.

	Limitations:
		- Can't know more than one recipe per unique output item (eg. different ways to make Solid Fuel)
		- Can't build recipe in multiple building types (eg. Assembly Machine 1/2/3)
		- Recipes can't have more than one output (eg. oil processing)
		- No dependency cycles (eg. coal liquification, Kovarex enrichment)
	"""
	items = [item.strip().lower() for item in items.split(',')]
	modules = [name.strip().lower() for name in modules.split(',')] if modules else []
	stop_items = [item.strip().lower() for item in stop_at.split(',')] if stop_at else []
	recipes = get_recipes(datafile, modules, verbose, beacon_speed)
	rate = Fraction(rate)
	items = OrderedDict((item, rate) for item in items)
	if oil:
		results, oil_buildings = solve_with_oil(recipes, items, stop_items, verbose=verbose)
	else:
		results = solve_all(recipes, items, stop_items)
		oil_buildings = []

	def mods_str(mods):
		return ' with {}'.format(', '.join(
			'{}x {}'.format(count, name)
			for name, count in sorted(
				Counter(mods).items(), key=lambda (name, count): (count, name)
			)
		)) if mods else ''

	def input_str(throughput, inputs):
		if not inputs_visible or not inputs:
			return ''
		return ' using {}'.format(
			', '.join(
				'{:.2f}/sec {}'.format(float(throughput * item_amount), item)
				for item, item_amount in inputs.items()
			)
		)

	def format_item(building, amount, throughput, mods, item, inputs):
		return '{} {}{} producing {:.2f}/sec of {}{}'.format(
			(int(math.ceil(amount)) if not fractional else '{:.2f}'.format(float(amount))),
			building, mods_str(mods), float(throughput), item, input_str(throughput, inputs)
		)

	for item, amount in results.items():
		if item in recipes and item not in stop_items:
			building, per_building, inputs, mods = recipes[item]
			throughput = amount * per_building
			print format_item(building, amount, throughput, mods, item, inputs)
		else:
			print '{:.2f}/sec of {}'.format(float(amount), item)
	for recipe, name, amount in oil_buildings:
		building, per_building, _, mods = recipes[recipe]
		throughput = amount * per_building # this doesn't make much sense, it's completed processes per sec
		print format_item(building, amount, throughput, mods, name, {})


if __name__ == '__main__':
	import argh
	argh.dispatch_command(main)
