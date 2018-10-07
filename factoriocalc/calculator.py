
import math
from fractions import Fraction


class Process(object):
	"""A process represents the production of a particular item.
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

	def depends(self):
		"""Returns the set of items this process depends on, ie. its parents
		in the DAG of processes."""
		return set() if self.recipe is None else set(self.recipe.inputs.keys())


class ProcessWithExtraDeps(object):
	"""Process with extra dependencies besides its inputs, used to make oil processing
	work in the correct order despite lacking explicit input links."""
	def __init__(self, item, recipe, throughput, *deps):
		super(ProcessWithExtraDeps, self).__init__(item, recipe, throughput)
		self.extra_deps = set(deps)

	def depends(self):
		return super(ProcessWithExtraDeps, self) | self.extra_deps


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

	def __init__(self, datafile, stop_items=[], module_priorities=DEFAULT_MODS,
	             beacon_speed=0, oil_beacon_speed=None):
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
		oil_beacon_speed: Specific alternate beacon speed for oil refineries, which can fit more.
			Common values:
				3 (+300%, for 6 beacons / 1 row)
				6 (+600%, for 12 becaons / 2 rows)
		"""
		self.datafile = datafile
		self.stop_items = stop_items
		self.module_priorities = module_priorities
		self.beacon_speed = beacon_speed
		self.oil_beacon_speed = beacon_speed if oil_beacon_speed is None else oil_beacon_speed

	def solve(self, item, throughput):
		"""Returns a dict {item: Process(item, recipe, throughput)}
		such that the requested throughput of the input item can be produced.
		"""
		if item not in self.datafile.recipes or item in self.stop_items:
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

	def solve_all(self, items):
		"""Solve for all the given items in form {item: desired throughput}. Output as per solve()"""
		results = {}
		for item, throughput in items.items():
			merge_into(results, self.solve(item, throughput))
		return results

	def solve_oil(self, processes):
		"""Special case solver for standard oil products calculations.
		We use a hack to integrate this calculation with existing features
		around modules, beacon speed, etc. Recipes should contain a
		'oil products' product built in a refinery which produces 1 output
		and otherwise has the features of Advanced Oil Processing.
		It should also contain oil cracking recipes.
		Processes should be a dict of processes as returned by solve().
		A modified processes dict will be returned, with the oil products mapping
		to an 'oil products' process, along with any cracking processes.
		Additionally, a dict {item: throughput} is returned detailing any additional inputs
		to be solved for.

		For clarity, these are the recipes considered:
			adv oil processing: 100c+50w -> 10h+45l+55p
			heavy cracking: 40h+30w -> 30l
			light cracking: 30l+30w -> 20p
		If we have excess products, we include a raw output for a negative amount of it
		to indicate to the user that it must be dealt with in some external way.
		"""

		HEAVY_PER_PROCESS, LIGHT_PER_PROCESS, PETROL_PER_PROCESS = 10, 45, 55

		refinery_recipe = self.datafile.recipes['oil products']
		refinery_recipe = self.datafile.resolve_recipe(refinery_recipe, self.module_priorities, self.oil_beacon_speed)
		heavy_crack_recipe = self.datafile.cracking_recipes['heavy oil cracking']
		heavy_crack_recipe = self.datafile.resolve_recipe(heavy_crack_recipe, self.module_priorities, self.beacon_speed)
		light_crack_recipe = self.datafile.cracking_recipes['light oil cracking']
		light_crack_recipe = self.datafile.resolve_recipe(light_crack_recipe, self.module_priorities, self.beacon_speed)
		light_per_heavy = Fraction(1) / heavy_crack_recipe.inputs['heavy oil']
		petrol_per_light = Fraction(1) / light_crack_recipe.inputs['light oil']

		excesses = {}
		heavy_cracking = 0 # measured in how much light oil to produce
		light_cracking = 0 # measured in how much petroleum to produce
		oil_processing = 0 # measured in number of completed Advanced Oil Processing processes per second

		heavy_oil_needed = processes.pop('heavy oil').throughput if 'heavy oil' in processes else 0
		light_oil_needed = processes.pop('light oil').throughput if 'light oil' in processes else 0
		petroleum_needed = processes.pop('petroleum').throughput if 'petroleum' in processes else 0

		# since we have no other way of getting more heavy oil, we consider it first
		# to get an absolute minimum.
		oil_processing = Fraction(heavy_oil_needed) / HEAVY_PER_PROCESS

		# now, we assume any additional heavy becomes light oil, and calculate what we need for
		# light with that in mind. We also take into account any light oil we're already making.
		extra_light = light_oil_needed - oil_processing * LIGHT_PER_PROCESS
		if extra_light < 0:
			excesses['light oil'] = extra_light
		else:
			# with cracking, how much light do we get per process
			total_light_per_process = LIGHT_PER_PROCESS + HEAVY_PER_PROCESS * light_per_heavy
			# this means we need this many extra processes per sec
			processing_for_light = extra_light / total_light_per_process
			# how much of that came from cracking?
			light_from_cracking = extra_light - processing_for_light * LIGHT_PER_PROCESS

			# add to totals
			oil_processing += processing_for_light
			heavy_cracking += light_from_cracking

		# then we do the same for petroleum, assuming all heavy + light is getting cracked
		extra_petrol = petroleum_needed - oil_processing * PETROL_PER_PROCESS
		if extra_petrol < 0:
			excesses['petroleum'] = extra_petrol
		else:
			# first, try to resolve the petrol shortfall by cracking any excess light oil
			petrol_available = -excesses.get('light oil', 0) * petrol_per_light
			if petrol_available > extra_petrol:
				# we can make up for the shortfall entirely
				excesses['light oil'] += extra_petrol / petrol_per_light
				light_cracking += extra_petrol
			else:
				# we make up for the shortfall as much as we can
				extra_petrol -= petrol_available
				light_cracking += petrol_available
				excesses.pop('light oil', None)

				# we handle the rest by adding more oil processing, and cracking everything.
				# when cracking everything down to petrol, how much do we get per process?
				total_petrol_per_process = PETROL_PER_PROCESS + petrol_per_light * (
					LIGHT_PER_PROCESS + light_per_heavy * HEAVY_PER_PROCESS
				)
				# that means we need this many extra processes per sec
				processing_for_petrol = extra_petrol / total_petrol_per_process
				# how much of that came from light cracking?
				petrol_from_cracking = extra_petrol - processing_for_petrol * PETROL_PER_PROCESS
				# and how much of the light for cracking came from heavy cracking?
				light_to_crack = petrol_from_cracking / petrol_per_light
				light_from_cracking = light_to_crack - processing_for_petrol * LIGHT_PER_PROCESS

				# add to totals
				oil_processing += processing_for_petrol
				heavy_cracking += light_from_cracking
				light_cracking += petrol_from_cracking

		# now we build the outputs.
		# note the 'raw inputs' for heavy/light/petrol are replaced by similar Processes,
		# but with an extra dep on 'oil products' and any cracking that produces it.
		new_processes = [
			Process('oil products', refinery_recipe, oil_processing),
			Process('heavy oil cracking', heavy_crack_recipe, heavy_cracking),
			Process('light oil cracking', light_crack_recipe, light_cracking),
			ProcessWithExtraDeps('heavy oil', None, oil_processing * HEAVY_PER_PROCESS, 'oil products'),
			ProcessWithExtraDeps('light oil', None, oil_processing * LIGHT_PER_PROCESS, 'oil products', 'heavy oil cracking'),
			ProcessWithExtraDeps('petroleum', None, oil_processing * PETROL_PER_PROCESS, 'oil products', 'light oil cracking'),
		]
		new_processes = {p.item: p for p in processes if p.throughput}
		new_inputs = excesses
		for process in new_processes.values():
			merge_into(new_inputs, process.inputs())
		merge_into(processes, new_processes)

		return processes, new_inputs

	def solve_with_oil(self, items):
		"""As per solve_all, but follow it with a call to solve_oil to resolve any oil products."""
		results = self.solve_all(items)
		results, further_inputs = self.solve_oil(results)
		merge_into(results, self.solve_all(further_inputs))
		return results

	def split_into_steps(self, processes):
		"""Splits a dict of full processes into an unordered list of steps,
		where each step uses no more than 1 belt for each input or output."""
		LIQUIDS = [
			'petroleum', 'light oil', 'heavy oil', 'sulfuric acid', 'lubricant', 'crude oil', 'water',
			'oil products', 'light oil cracking', 'heavy oil cracking',
		]
		results = []
		for process in processes.values():
			steps = Fraction(math.ceil(max(
				[
					process.throughput * per_item / Fraction(40)
					for input, per_item in process.recipe.inputs.items()
					if input not in LIQUIDS
				] + [1 if process.item in LIQUIDS else process.throughput / Fraction(40)]
			)))
			step = process._replace(throughput=process.throughput/steps)
			results += [step] * steps
		return results
