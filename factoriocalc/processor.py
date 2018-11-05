# -encoding: utf-8-

import math
from collections import namedtuple, Counter

from . import primitives
from .primitives import E, entity
from .util import Layout, is_liquid, UP, RIGHT, DOWN, LEFT


EMPTY = Layout("empty")


InOutKinds = namedtuple('InOutKinds', ['liquid', 'belt', 'halfbelt'])


class Processor(object):
	"""A Processor represents a way of performing a process.
	Each processor defines its own layouts for processing a particular
	kind of recipe.

	A processor is matched on number and kind of inputs and outputs,
	as well as building type.
	Inputs and outputs have three kinds:
		pipe: A liquid
		belt: An item whose total throughput exceeds half a full belt's throughput.
		half-belt: An item whose total throughput does not exceed half a full belt's throughput.
	The reason for distinguishing belts is that half-belts can be safely joined into one
	belt within the design, which can produce much more space-efficent designs than otherwise.
	When matching, half-belt matches are preferred over belt matches,
	but belts in a processor can still match half-belt inputs/outputs.
	Note that not all combinations of inputs, outputs and building types will exist.
	We only define as many as needed to be able to build all known recipes.

	Inputs and outputs are ordered:
	* Liquids before solids
	* By throughput, highest first
	* By name
	Note inputs are "first" at the top, outputs are "first" at the bottom.

	A processor's layouts are divided into three parts:
	* head
	* body
	* tail
	A fully laid out process consists of head, then N copies of body (which may be 0), then tail.
	Note that in order to correctly lay these out, as well as determine the full width,
	all three layouts also have an associated width.
	To determine how many body sections are required, the process must define a base_buildings
	and a per_body_buildings. This is used along with the recipe's per-building throughput
	to calculate the required number of buildings and thus the required number of body steps.
	Note a base_buildings should include buildings in both head and tail.

	Note that a process is responsible for powering beacons above and below,
	and must pad out enough width that all buildings are maximally covered by beacons.
	"""
	PROCESSORS = []
	MAX_INSERT_RATE = 12 # worst case items/sec of stack inserter, TODO confirm value

	def __init__(self, name,
		building='assembler',
		inputs=(0,0,0),
		outputs=(0,0,0),
		head=EMPTY, body=EMPTY, tail=EMPTY,
		head_width=0, body_width=0, tail_width=0,
		base_buildings=0, per_body_buildings=0,
	):
		"""Most args are self-evident, see main docstring.
		head, body and tail may be callable, in which case they take, as an arg,
		a primitive representing the production building of the recipe.
		Building may be an iterable listing all supported buildings (this only makes
		sense when using the callable-body feature).
		"""
		self.name = name
		self.buildings = [building] if isinstance(building, basestring) else building
		self.inputs = InOutKinds(*inputs)
		self.outputs = InOutKinds(*outputs)
		self.head = head
		self.body = body
		self.tail = tail
		self.head_width = head_width
		self.body_width = body_width
		self.tail_width = tail_width
		self.base_buildings = base_buildings
		self.per_body_buildings = per_body_buildings
		self.PROCESSORS.append(self) # note PROCESSORS is shared between all Processor instances

	def match_score(self, building, inputs, outputs):
		"""Returns a sortable score, the lower the better, or None if no match."""
		# No match if the building is wrong
		if building not in self.buildings:
			return
		# unused counts completely unused inputs/outputs,
		# underused counts full belt slots being used for half-belt in/outs.
		unused = 0
		underused = 0
		# Check each thing in turn for not enough (always a no-match) or excess.
		for have, need in ((self.outputs, outputs), (self.inputs, inputs)):
			if have.liquid < need.liquid:
				return
			unused += have.liquid - need.liquid
			if have.belt < need.belt:
				return
			remaining = have.belt - need.belt
			if remaining + have.halfbelt < need.halfbelt:
				return
			unused += remaining + have.halfbelt - need.halfbelt
			underused += min(remaining, need.halfbelt)
		# Minimising unused is more important than minimising underused
		return (unused, underused)

	@classmethod
	def find_processor(cls, building, inputs, outputs):
		"""Inputs and outputs should be tuples (liquid, full belt, half belt).
		Returns processor or raises."""
		inputs = InOutKinds(*inputs)
		outputs = InOutKinds(*outputs)
		candidates = [processor for processor in cls.PROCESSORS if processor.match_score(building, inputs, outputs)]
		if not candidates:
			raise ValueError("Could not find processor for {} with {} inputs and {} outputs".format(
				building, inputs, outputs
			))
		return min(
			candidates,
			key=lambda processor: processor.match_score(building, inputs, outputs),
		)

	def determine_bodies(self, step):
		"""Work out how many body sections are needed for the given step."""
		throughput = step.process.throughput
		recipe = step.process.recipe
		throughput_per_building = recipe.throughput
		# We need to apply a correction step to slow down buildings where any one
		# (non-liquid) input or output exceeds MAX_INSERT_RATE items/sec.
		# This is to account for the limit of throughput of a single stack inserter,
		# and is generally only an issue for things that can't be prod-modded
		# (so you tend to end up with 4x speed 3s + beacons for a crazy total speed)
		# NOTE: This does not consider multiple outputs. This is fine for now since the only
		# multi-output things only output liquids.
		# XXX Future work: allow a processor to advertise "double inserter" lines
		# that would let buildings run at full speed as long as only one item is the issue.
		item_rates = [
			throughput_per_building * per_output
			for item, per_output in (recipe.inputs.items() + [(recipe.name, 1)]) # extra term stands for output
			if not is_liquid(item)
		]
		if item_rates and max(item_rates) > self.MAX_INSERT_RATE:
			# slow down the building to match the speed of insertion of the highest volume item
			throughput_per_building *= self.MAX_INSERT_RATE / max(item_rates)
		buildings = throughput / throughput_per_building
		buildings -= self.base_buildings
		return max(0, int(math.ceil(buildings / self.per_body_buildings)))

	def resolve_layout(self, building, layout):
		if callable(layout):
			return layout(building)
		return layout

	def get_building_primitive(self, recipe):
		"""For given recipe, return primitive with a correctly configured building,
		including modules, etc.
		"""
		attrs = {}
		# furnaces are a special case that don't need a recipe set
		if recipe.building.name != 'furnace':
			attrs['recipe'] = E[recipe.name]
		if recipe.mods:
			attrs['items'] = {
				E[mod]: count for mod, count in Counter(recipe.mods).items()
			}
		return entity(E[recipe.building.name], **attrs)

	def layout(self, step):
		"""Returns (layout, width) for the given step, which must already be matching."""
		building = self.get_building_primitive(step.process.recipe)
		layout = Layout("process: {}".format(self.name))
		layout.place(0, 0, self.resolve_layout(building, self.head))
		body = self.resolve_layout(building, self.body)
		bodies = self.determine_bodies(step)
		for i in range(bodies):
			layout.place(self.head_width + i * self.body_width, 0, body)
		layout.place(
			self.head_width + bodies * self.body_width,
			0,
			self.resolve_layout(building, self.tail)
		)
		return layout, self.head_width + bodies * self.body_width + self.tail_width


# Useful sub-layouts for common patterns

# A tail section that is empty except for poles to power beacons
#  |
#  | o
#  |
#  |
#  |
#  | o
#  |
pole_tail = Layout('pole tail',
	(1, 1, primitives.medium_pole),
	(1, 5, primitives.medium_pole),
)


# Processors

# Simple processor for basic 1 -> 1 belt recipes, eg. all smelting, iron gears.
# Can support any of the 3x3 building types (furnaces, assemblers, chemical plants).
#   >>>|>>>>>>|
#  ⊂^o |i oi  | o
#      |┌─┐┌─┐|
#      |│F││F│|
#      |└─┘└─┘|
#    o |i oi  | o
#  ⊂<<<|<<<<<<|
Processor('1 -> 1',
	building=('furnace','assembler','chemical plant'),
	inputs=(0, 1, 0),
	outputs=(0, 1, 0),
	per_body_buildings=2,
	# head: Connect y=1 into body at y=0 and y=6 out of body at y=6
	head_width=4,
	head=Layout('head',
		(1, 0, primitives.belt(RIGHT, 3)),
		(0, 1, primitives.belt_from_ground(RIGHT)),
		(1, 1, primitives.entity(E.belt, UP)),
		(2, 1, primitives.medium_pole),
		(2, 5, primitives.medium_pole),
		(0, 6, primitives.belt_to_ground(LEFT)),
		(3, 6, primitives.belt(LEFT, 3)),
	),
	# body: couldn't be simpler. just a pair of assemblers with inserters and sharing
	# power poles on each side
	body_width=6,
	body=lambda building: Layout('body',
		(0, 0, primitives.belt(RIGHT, 6)),
		(0, 1, entity(E.inserter, UP)),
		(2, 1, primitives.medium_pole),
		(3, 1, entity(E.inserter, UP)),
		(0, 2, building),
		(3, 2, building),
		(0, 5, entity(E.inserter, UP)),
		(2, 5, primitives.medium_pole),
		(3, 5, entity(E.inserter, UP)),
		(5, 6, primitives.belt(LEFT, 6)),
	),
	# note tail goes a bit wider than the last thing put down, so that there's enough beacons
	tail_width=3,
	tail=pole_tail,
)
