
import logging
import math
import os
import re
import sys
from collections import OrderedDict, Counter
from pprint import pformat

from fractions import Fraction


class Process(object):
	"""A process represents the total production of a particular item.
	Attrs:
		item - the item name
		recipe - the ResolvedRecipe for the item, or None for raw inputs
		throughput - the rate at which the item must be produced
	"""
	def __init__(self, item, recipe, throughput):
		self.item = item
		self.recipe = recipe
		self.throughput = throughput

	def buildings(self):
		"""Returns number of buildings needed to achieve the required throughput,
		or None for raw inputs"""
		return None if self.recipe is None else self.throughput / self.recipe.throughput

	def inputs(self):
		"""Returns {item: throughput required} for each input item,
		or None for raw inputs"""
		return None if self.recipe is None else {
			k: v * self.throughput
			for k, v in self.recipe.inputs.items()
		}


def merge_into(a, b):
	for k, v in b.items():
		if k in a:
			assert a[k].recipe == v.recipe
			a[k].throughput += v.throughput
		else:
			a[k] = v


class Calculator(object):
	"""The calculator is concerned with working out what items are required
	to produce a desired product, and in what quantities, along with how many
	buildings are required to produce that quantity.
	"""
	DEFAULT_MODS = 'prod 3, prod 3, prod 3, prod 3, speed 3, speed 3, speed 3, speed 3'

	def __init__(self, datafile, stop_items=[], module_priorities=DEFAULT_MODS, beacon_speed=0):
		"""
		datafile: The Datafile object to take recipes from.
		stop_items: Items whose names are in this list will be treated as raw inputs,
		            even if a recipe to make them exists.
		module_priorities: A list of modules to use in priority order. See Datafile.calc_mods().
		beacon_speed:
			The total speed effect of beacons to use in each process.
			Common values:
				2 (+200%, for 4 beacons, ie. one row of beacons reachable by an assembler)
				4 (+400%, for 8 becaons, ie. two rows of beacons reachable by an assember)
		"""
		self.datafile = datafile
		self.stop_items = stop_items
		self.module_priorities = module_priorities
		self.beacon_speed = beacon_speed


	def solve(self, item, throughput):
		"""Returns a dict {item: Process(recipe, throughput)}
		such that the requested throughput of the input item can be produced.
		"""
		if item not in self.datafile.recipes or item in stop_items:
			# raw input
			return {item: Process(item, None, throughput)}
		recipe = self.datafile.recipes[item]
		recipe = self.datafile.resolve_recipe(recipe, self.module_priorities, self.beacon_speed)
		result = {item: Process(item, recipe, throughput)}
		for name, amount in recipe.inputs.items():
			amount *= throughput
			subresult = self.solve(name, amount)
			merge_into(result, subresult)
		return result

	def solve_all(self, recipes, items):
		"""Solve for all the given items in form {item: desired throughput}. Output as per solve()"""
		results = {}
		for item, throughput in items.items():
			merge_into(results, self.solve(item, throughput))
		return results

# UPTO

	def solve_oil(recipes, targets):
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

		# TODO this is off. cracker amounts aren't being calculated correctly, though they're almost right?
		# sigh, it's a clusterfuck.

		def p(s, *a, **k):
			logging.debug(s.format(*a, **k))

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

		excesses = {}
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
			# first, try to resolve the petrol shortfall by cracking any excess light oil
			petrol_available = -excesses.get('light oil', 0) * petrol_per_light
			if petrol_available > extra_petrol:
				# we can make up for the shortfall entirely
				excesses['light oil'] += extra_petrol / petrol_per_light
				new_light_cracking = refinery_throughput * extra_petrol
				light_cracking += new_light_cracking
				p('used {} excess light to make up extra {} petrol needed with {} crackers', extra_petrol / petrol_per_light, extra_petrol, new_light_cracking)
			else:
				extra_petrol -= petrol_available
				new_light_cracking = refinery_throughput * petrol_available
				light_cracking += new_light_cracking
				p('used {} excess light to help make up extra {} petrol needed with {} crackers', -excesses.get('light oil', 0), petrol_available, new_light_cracking)
				excesses.pop('light oil', None)
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



	def solve_with_oil(recipes, items, stop_items):
		"""As per solve_all, but follow it with a call to solve_oil to resolve any oil products.
		It returns (results, buildings) as per solve_oil()"""
		results = solve_all(recipes, items, stop_items)
		results, further_inputs, buildings = solve_oil(recipes, results)
		merge_into(results, solve_all(recipes, further_inputs, stop_items))
		return results, buildings


	def main(items, rate, datafile='factorio_recipes', modules='prod 3, prod 3, prod 3, prod 3, speed 3, speed 3, speed 3, speed 3', fractional=False, log='WARNING',
			 stop_at='', beacon_speed=0., oil=False, verbose=False):
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
		you would use 8 * .5 = 4, and all buildings would act as having a speed bonus of 400%.

		By default, oil processing is not considered (see limitations). However, oil can be considered
		by including the --oil option. This may become default in the future.

		Give --inputs-visible option to also include recipe inputs for each step. Useful for logistic planning.

		Limitations:
			- Can't know more than one recipe per unique output item (eg. different ways to make Solid Fuel)
			- Can't build recipe in multiple building types (eg. Assembly Machine 1/2/3)
			- Recipes can't have more than one output (eg. oil processing)
			- No dependency cycles (eg. coal liquification, Kovarex enrichment)
		"""
		logging.basicConfig(level=log.upper())

		items = [item.strip().lower() for item in items.split(',')]
		modules = [name.strip().lower() for name in modules.split(',')] if modules else []
		stop_items = [item.strip().lower() for item in stop_at.split(',')] if stop_at else []
		recipes = get_recipes(datafile, modules, beacon_speed)
		rate = Fraction(rate)
		items = OrderedDict((item, rate) for item in items)
		if oil:
			results, oil_buildings = solve_with_oil(recipes, items, stop_items)
		else:
			results = solve_all(recipes, items, stop_items)
			oil_buildings = []

		def maybe_round(amount):
			return '{:.2f}'.format(float(amount)) if fractional else int(math.ceil(amount))

		def mods_str(mods):
			return ' with {}'.format(', '.join(
				'{}x {}'.format(count, name)
				for name, count in sorted(
					Counter(mods).items(), key=lambda (name, count): (count, name)
				)
			)) if mods else ''

		def input_str(throughput, inputs):
			if not verbose or not inputs:
				return ''
			return ' using {}'.format(
				', '.join(
					'{:.2f}/sec {}'.format(float(throughput * item_amount), item)
					for item, item_amount in inputs.items()
				)
			)

		def format_extra(building, amount, throughput, mods, item, inputs):
			MAX_PER_ROW = 40 # one blue belt
			EXCLUDE = ['water', 'crude oil', 'petroleum', 'light oil', 'heavy oil', 'sulfuric acid', 'lubricant']
			to_consider = [
				throughput * item_amount
				for _item, item_amount in inputs.items()
				if _item not in EXCLUDE
			]
			if item not in EXCLUDE:
				to_consider.append(throughput)
			rows = int(math.ceil(max(to_consider) / MAX_PER_ROW)) if to_consider else 1
			if not verbose or rows == 1:
				return ''
			return '\n\tin {} rows of {} each producing {:.2f}/sec{}'.format(
				rows, maybe_round(amount/rows), float(throughput / rows), input_str(throughput/rows, inputs),
			)

		def format_item(building, amount, throughput, mods, item, inputs):
			return '{} {}{} producing {:.2f}/sec of {}{}{}'.format(
				maybe_round(amount),
				building, mods_str(mods), float(throughput), item, input_str(throughput, inputs),
				format_extra(building, amount, throughput, mods, item, inputs),
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
