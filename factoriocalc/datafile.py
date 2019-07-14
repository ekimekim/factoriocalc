
import os
import re
import sys
from collections import namedtuple
from fractions import Fraction


Recipe = namedtuple("Recipe", [
	"name",
	"building", # the Building this recipe is made in
	"throughput", # the rate at which outputs are made
	              # at 1 building speed and without productivity
	"inputs", # a map {item name: amount consumed per output produced} for each input
	          # not including productivity
	"can_prod", # boolean, whether this recipe can use productivity modules
	"delay", # For some things (currently only rocket launches), an unavoidable delay
	         # (the launch itself) must complete before the next process can start.
	         # The difference between this delay and 1/throughput is it's unaffected by modules.
	         # This delay value, like all other values here, is per output.
	"fixed_inputs", # as per inputs, but is not affected by productivity
	"is_virtual", # boolean. Virtual processes don't produce an actual output that needs to be moved.
	              # For example, research, power and non-satellite rocket launches.
])

# As Recipe unless noted
ResolvedRecipe = namedtuple("ResolvedRecipe", [
	"name",
	"building",
	"is_virtual",
	"throughput", # adjusted for building's speed, productivity and delay
	"inputs", # adjusted for building's productivity
	"mods", # list of names of modules in the building
])

Building = namedtuple("Building", [
	"name",
	"speed", # The base production speed of the building
	"mod_slots", # The number of module slots available
	"can_beacon", # Whether the building is affected by beacons
])

Module = namedtuple("Module", [
	"name",
	"speed", # The amount by which this module changes speed
	"prod", # The amount by which this module changes productivity
])

class Datafile(object):
	"""The data loaded from a datafile,
	available as recipes, buildings and modules attributes.
	See load() for full datafile syntax.
	"""

	def __init__(self, filepath):
		self.recipes, self.buildings, self.modules = self.load(filepath)

	def get_datafile_lines(self, filepath):
		"""Resolve includes and yield (lineno, line) where lineno is a descriptive string of
		'line number', eg. for an include it might look like "1:foo:5" for line 5 of file foo
		included from line 1."""
		with open(filepath) as f:
			for n, line in enumerate(f):
				if line.startswith('include '):
					path = line[len('include '):-1] # -1 for trailing newline
					path = os.path.join(os.path.dirname(filepath), path)
					for lineno, line in self.get_datafile_lines(path):
						yield '{}:{}:{}'.format(n, path, lineno), line
				else:
					yield n+1, line

	def load(self, filepath):
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
			[AMOUNT ]OUTPUT takes TIME in BUILDING{, AMOUNT INPUT}[, can take productivity][, plus TIME delay]{, plus AMOUNT INPUT}[, is virtual]
		with delay and "plus" items being unaffected by modules (this is needed for some special cases).
		Virtual processes are ones that don't produce a physical output, eg. research labs.
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
		"""
		buildings = {}
		items = {}
		modules = {}
		for lineno, line in self.get_datafile_lines(filepath):
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
					buildings[name] = Building(name, Fraction(speed), mods, can_beacon)
					continue

				match = re.match(
					'^(\d+ )?(.+) takes ([0-9.]+) in ([^,]+)'
					'((?:, [0-9.]+ [^,]+)*)'
					'(, can take productivity)?'
					'(?:, plus ([0-9.]+) delay)?'
					'((?:, plus [0-9.]+ [^,]+)*)'
					'(, is virtual)?'
					'$'
				, line)
				if match:
					(
						amount,
						name,
						time,
						building,
						inputs_str,
						prod,
						delay,
						fixed_inputs_str,
						is_virtual
					) = match.groups()
					amount = Fraction(amount if amount else 1)
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
							input_amount = Fraction(input_amount)
							inputs[input_name] = input_amount / amount
					delay = Fraction(delay if delay else 0) / amount
					fixed_inputs = {}
					if fixed_inputs_str:
						for part in fixed_inputs_str.split(','):
							part = part.strip()
							if not part:
								continue
							_, input_amount, input_name = part.split(' ', 2)
							input_amount = Fraction(input_amount)
							fixed_inputs[input_name] = input_amount / amount
					if name in items:
						raise ValueError('Recipe for {!r} already declared'.format(name))
					items[name] = Recipe(name, building, amount / time, inputs, prod, delay, fixed_inputs, is_virtual)
					continue

				match = re.match('^([^,]+) module affects speed ([^,]+)(?:, prod ([^,]+))?$', line)
				if match:
					name, speed, prod = match.groups()
					speed = Fraction(speed)
					prod = Fraction(prod) if prod else 0
					name = name.lower()
					if name in modules:
						raise ValueError('Module {!r} already declared'.format(name))
					modules[name] = Module(name, speed, prod)
					continue

				raise ValueError("Unknown entry syntax")
			except Exception as e:
				_, _, tb = sys.exc_info()
				raise ValueError, ValueError("Error in line {} of {!r}: {}".format(lineno, filepath, e)), tb

		# Transform items to resolve to building references, not just names
		for item in items.values():
			if item.building not in buildings:
				raise ValueError("Error in {!r}: {!r} is built in {!r}, but no such building declared".format(filepath, item.name, item.building))
			items[item.name] = item._replace(building=buildings[item.building])

		return items, buildings, modules

	def resolve_recipe(self, recipe, module_priorities, beacon_speed=0):
		"""Resolves a generic recipe into a concrete per-building value,
		for a given module priority spec and beacon speed level."""
		speed, prod, modlist = self.calc_mods(recipe, module_priorities, beacon_speed)
		throughput_no_delay = recipe.throughput * speed * prod
		period_no_delay = 1 / throughput_no_delay
		period = period_no_delay + recipe.delay
		return ResolvedRecipe(
			name = recipe.name,
			building = recipe.building,
			is_virtual = recipe.is_virtual,
			throughput = 1 / period,
			inputs = {
				item: recipe.inputs.get(item, 0) / prod + recipe.fixed_inputs.get(item, 0)
				for item in set(recipe.inputs) | set(recipe.fixed_inputs)
			},
			mods = modlist,
		)

	def calc_mods(self, recipe, priorities, beacon_speed):
		"""Calculates final (crafting speed, productivity, list of module names) of a building given:
			- what modules exist
			- building base speed and number of slots
			- whether productivity increases are allowed for this recipe
			- the speed effects of any beacons
			- a list of modules in priority order, including repeats. for example,
			  a list like [A, A, B, A] will result in 2x A module if there's 2 slots, 2 As and 1 B if there's 3, 3 As and 1 B if there's 4 or more.
		"""
		used = []
		speed_total = beacon_speed
		prod_total = 0
		to_consider = list(priorities)
		while len(used) < recipe.building.mod_slots and to_consider:
			name = to_consider.pop(0)
			module = self.modules[name]
			if module.prod and not recipe.can_prod:
				continue
			speed_total += module.speed
			prod_total += module.prod
			used.append(name)

		return recipe.building.speed * (1 + speed_total), 1 + prod_total, used


def dump_datafile(path='./factorio_recipes', module_priorities=['prod 3'] * 4 + ['speed 3'] * 4, beacon_speed=4):
	"""Test a datafile by dumping the parsed data as json, followed by the resolved recipes with the given args."""
	import json
	datafile = Datafile(path)
	print json.dumps(datafile.recipes, indent=4, default=str)
	print json.dumps(datafile.buildings, indent=4, default=str)
	print json.dumps(datafile.modules, indent=4, default=str)
	print json.dumps({
		item: datafile.resolve_recipe(recipe, module_priorities, beacon_speed)
		for item, recipe in datafile.recipes.items()
	}, indent=4, default=str)


if __name__ == '__main__':
	import argh
	argh.dispatch_command(dump_datafile)
