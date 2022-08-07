# -encoding: utf-8-

import functools
import math
import os
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
	MATCH_CACHE = {} # this is here more for debugging than performance, it maps (building, inputs, outputs) -> processor
	# Worst case items/sec of stack inserter is 11.6 on full belts, but slower down the line when we get gaps.
	# To give us some wiggle room, we take expected max insert rate as 10.
	MAX_INSERT_RATE = 10

	def __init__(self, name,
		building='assembler',
		inputs=(0,0,0),
		outputs=(0,0,0),
		head=EMPTY, body=EMPTY, tail=EMPTY,
		head_width=0, body_width=0, tail_width=0,
		base_buildings=0, per_body_buildings=0,
		oversize=0,
	):
		"""Most args are self-evident, see main docstring.
		head, body and tail may be callable, in which case they take, as args:
			- a primitive representing the production building of the recipe
			- a specialized version of primitives.belt with type set
			- a specialized version of primitives.splitter with type set
		Building may be an iterable listing all supported buildings (this only makes
		sense when using the callable-body feature).
		A process may be oversize, giving it a between-beacons height of 7 + oversize.
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
		self.oversize = oversize
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
			# If the liquid count does not match, then inputs will not be ordered correctly
			# (liquids always come first, so if the liquids in the actual input != liquids
			# in the process, the non-liquid inptus will be offset by the difference).
			# We might be able to be clever about this later, but for now let's just reject.
			if have.liquid != need.liquid:
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
		cache_key = building, inputs, outputs
		if cache_key in cls.MATCH_CACHE:
			return cls.MATCH_CACHE[cache_key]
		inputs = InOutKinds(*inputs)
		outputs = InOutKinds(*outputs)
		candidates = [processor for processor in cls.PROCESSORS if processor.match_score(building, inputs, outputs)]
		report_match = os.environ.get('FACTORIOCALC_PROCESSOR_MATCHES', '')
		verbose = report_match.lower() == 'verbose'
		in_str, out_str = map(
			tuple if verbose else lambda (l,b,h): (l, b+h),
		(inputs, outputs))
		if not candidates:
			if report_match:
				print "No match for {} with {} -> {}".format(building, in_str, out_str)
			raise ValueError("Could not find processor for {} with {} inputs and {} outputs".format(
				building, inputs, outputs
			))
		ret = min(
			candidates,
			key=lambda processor: processor.match_score(building, inputs, outputs),
		)
		if report_match:
			print "Match for {} with {} -> {}: {} with score {}".format(
				building, in_str, out_str,
				ret.name, ret.match_score(building, inputs, outputs),
			)
		cls.MATCH_CACHE[cache_key] = ret
		return ret

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

	def resolve_layout(self, building, belt_type, layout):
		belt = functools.partial(primitives.belt, type=belt_type)
		splitter = functools.partial(primitives.splitter, type=belt_type)
		if callable(layout):
			return layout(building, belt, splitter)
		return layout

	def get_building_primitive(self, recipe):
		"""For given recipe, return primitive with a correctly configured building,
		including modules, etc.
		"""
		attrs = {}
		# furnaces are a special case that don't need a recipe set
		if recipe.building.name != 'furnace':
			attrs['recipe'] = E[recipe.name]
		# rocket silos need auto-launch set
		if recipe.building.name == "rocket-silo":
			attrs['auto_launch'] = True
		if recipe.mods:
			attrs['items'] = {
				E[mod]: count for mod, count in Counter(recipe.mods).items()
			}
		return entity(E[recipe.building.name], **attrs)

	def layout(self, belt_type, step):
		"""Returns (layout, width, oversize) for the given step, which must already be matching."""
		building = self.get_building_primitive(step.process.recipe)
		layout = Layout("process: {}".format(self.name))
		layout.place(0, 0, self.resolve_layout(building, belt_type, self.head))
		body = self.resolve_layout(building, belt_type, self.body)
		bodies = self.determine_bodies(step)
		for i in range(bodies):
			layout.place(self.head_width + i * self.body_width, 0, body)
		layout.place(
			self.head_width + bodies * self.body_width,
			0,
			self.resolve_layout(building, belt_type, self.tail)
		)
		return layout, self.head_width + bodies * self.body_width + self.tail_width, self.oversize


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

# TODO List - min needed for 1000SPM inf science
# * rocket silo 0/0/4 -> 0/0/1

# Simple processor for basic 1 -> 1 belt recipes, eg. all smelting, iron gears.
# Can support any of the 3x3 building types (furnaces, assemblers, chemical plants).
#   >>>|>>>>>>|
#  >^o |i oi  | o
#      |┌─┐┌─┐|
#      |│F││F│|
#      |└─┘└─┘|
#    o |vSioi | o
#  <<<<|<s<<<<|
Processor('1 -> 1',
	building=('furnace','assembler','chemical plant'),
	inputs=(0, 1, 0),
	outputs=(0, 1, 0),
	per_body_buildings=2,
	# head: Connect y=1 into body at y=0 and y=6 out of body at y=6
	head_width=4,
	head=lambda building, belt, splitter: Layout('head',
		(0, 1, belt(RIGHT)),
		(1, 1, belt(UP)),
		(1, 0, belt(RIGHT, 3)),
		(2, 1, primitives.medium_pole),
		(2, 5, primitives.medium_pole),
		(3, 6, belt(LEFT, 4)),
	),
	# body: couldn't be simpler. just a pair of assemblers with inserters and sharing
	# power poles on each side
	body_width=6,
	body=lambda building, belt, splitter: Layout('body',
		(0, 0, belt(RIGHT, 6)),
		(0, 1, entity(E.ins, UP)),
		(2, 1, primitives.medium_pole),
		(3, 1, entity(E.ins, UP)),
		(0, 2, building),
		(3, 2, building),
		(0, 5, belt(DOWN)),
		(1, 5, splitter(LEFT, output_priority='right')),
		(2, 5, entity(E.ins, UP)),
		(3, 5, primitives.medium_pole),
		(4, 5, entity(E.ins, UP)),
		(0, 6, belt(LEFT)),
		(5, 6, belt(LEFT, 4)),
	),
	# note tail goes a bit wider than the last thing put down, so that there's enough beacons
	tail_width=3,
	tail=pole_tail,
)

# Processor specifically for oil refining, ie. 2 pipes -> 3 pipes.
#  o=⊃     o   ⊂⊃o⊂=⊃| o    o⊂=⊃|
#  ⊃∪⊂= =⊃ ⊂=⊃┌───┐= |⊂=⊃┌───┐= | o
#  ⊃  =⊂= =⊃==│RRR│⊂=|⊃==│RRR│⊂=|
#   ∩ =   ∪   │RRR│==|   │RRR│==|
#  == =⊃   ⊂==│RRR│  | ==│RRR│  |
#  ⊃    ⊂=∩ =⊃└───┘= |⊂=⊃└───┘= | o
#  ⊃o    ==o ⊂⊃  o⊂=⊃| o    o⊂=⊃|
Processor('oil refining',
	building='refinery',
	inputs=(2, 0, 0),
	outputs=(3, 0, 0),
	base_buildings=1,
	per_body_buildings=1,
	# head: Shuffle all the input and output pipes from their initial positions
	# to the ones that the body uses, then do the first body but with some special casing.
	head_width=18,
	head=lambda building, belt, splitter: Layout('head',
		(0, 0, entity('medium-electric-pole', UP)),
		(0, 1, entity('pipe-to-ground', LEFT)),
		(0, 2, entity('pipe-to-ground', LEFT)),
		(0, 4, entity('pipe', UP)),
		(0, 5, entity('pipe-to-ground', LEFT)),
		(0, 6, entity('pipe-to-ground', LEFT)),
		(1, 0, entity('pipe', UP)),
		(1, 1, entity('pipe-to-ground', UP)),
		(1, 3, entity('pipe-to-ground', DOWN)),
		(1, 4, entity('pipe', UP)),
		(1, 6, entity('medium-electric-pole', UP)),
		(2, 0, entity('pipe-to-ground', LEFT)),
		(2, 1, entity('pipe-to-ground', RIGHT)),
		(3, 1, entity('pipe', UP)),
		(3, 2, entity('pipe', UP)),
		(3, 3, entity('pipe', UP)),
		(3, 4, entity('pipe', UP)),
		(4, 2, entity('pipe-to-ground', RIGHT)),
		(4, 4, entity('pipe-to-ground', LEFT)),
		(5, 1, entity('pipe', UP)),
		(5, 2, entity('pipe', UP)),
		(5, 5, entity('pipe-to-ground', RIGHT)),
		(6, 1, entity('pipe-to-ground', LEFT)),
		(6, 5, entity('pipe', UP)),
		(6, 6, entity('pipe', UP)),
		(7, 2, entity('pipe', UP)),
		(7, 3, entity('pipe-to-ground', UP)),
		(7, 5, entity('pipe-to-ground', DOWN)),
		(7, 6, entity('pipe', UP)),
		(8, 0, entity('medium-electric-pole', UP)),
		(8, 1, entity('pipe-to-ground', RIGHT)),
		(8, 2, entity('pipe-to-ground', LEFT)),
		(8, 4, entity('pipe-to-ground', RIGHT)),
		(8, 6, entity('medium-electric-pole', UP)),
		(9, 1, entity('pipe', UP)),
		(9, 2, entity('pipe', UP)),
		(9, 4, entity('pipe', UP)),
		(9, 5, entity('pipe', UP)),
		(10, 1, entity('pipe-to-ground', LEFT)),
		(10, 2, entity('pipe', UP)),
		(10, 4, entity('pipe', UP)),
		(10, 5, entity('pipe-to-ground', LEFT)),
		(10, 6, entity('pipe-to-ground', RIGHT)),
		(11, 1, building._replace(orientation=RIGHT)),
		(11, 6, entity('pipe-to-ground', LEFT)),
		(12, 0, entity('pipe-to-ground', RIGHT)),
		(13, 0, entity('pipe-to-ground', LEFT)),
		(14, 0, entity('medium-electric-pole', UP)),
		(14, 6, entity('medium-electric-pole', UP)),
		(15, 0, entity('pipe-to-ground', RIGHT)),
		(15, 6, entity('pipe-to-ground', RIGHT)),
		(16, 0, entity('pipe', UP)),
		(16, 1, entity('pipe', UP)),
		(16, 2, entity('pipe-to-ground', RIGHT)),
		(16, 3, entity('pipe', UP)),
		(16, 5, entity('pipe', UP)),
		(16, 6, entity('pipe', UP)),
		(17, 0, entity('pipe-to-ground', LEFT)),
		(17, 2, entity('pipe', UP)),
		(17, 3, entity('pipe', UP)),
		(17, 6, entity('pipe-to-ground', LEFT)),
	),
	# body: Refinery is placed horizontally, with each liquid running on its own row
	# one row above or below its input or output position.
	body_width=10,
	body=lambda building, belt, splitter: Layout('body',
		(0, 1, entity('pipe-to-ground', RIGHT)),
		(0, 2, entity('pipe-to-ground', LEFT)),
		(0, 5, entity('pipe-to-ground', RIGHT)),
		(1, 0, entity('medium-electric-pole', UP)),
		(1, 1, entity('pipe', UP)),
		(1, 2, entity('pipe', UP)),
		(1, 4, entity('pipe', UP)),
		(1, 5, entity('pipe', UP)),
		(1, 6, entity('medium-electric-pole', UP)),
		(2, 1, entity('pipe-to-ground', LEFT)),
		(2, 2, entity('pipe', UP)),
		(2, 4, entity('pipe', UP)),
		(2, 5, entity('pipe-to-ground', LEFT)),
		(3, 1, building._replace(orientation=RIGHT)),
		(6, 0, entity('medium-electric-pole', UP)),
		(6, 6, entity('medium-electric-pole', UP)),
		(7, 0, entity('pipe-to-ground', RIGHT)),
		(7, 6, entity('pipe-to-ground', RIGHT)),
		(8, 0, entity('pipe', UP)),
		(8, 1, entity('pipe', UP)),
		(8, 2, entity('pipe-to-ground', RIGHT)),
		(8, 3, entity('pipe', UP)),
		(8, 5, entity('pipe', UP)),
		(8, 6, entity('pipe', UP)),
		(9, 0, entity('pipe-to-ground', LEFT)),
		(9, 2, entity('pipe', UP)),
		(9, 3, entity('pipe', UP)),
		(9, 6, entity('pipe-to-ground', LEFT)),
	),
	tail_width=3,
	tail=pole_tail,
)


# Assemblers, 2 full + 1 half belt in, 1 half belt out
# This supports various recipes, including some that don't make full use of all 3 belts
# (eg. this can be used for any 2-belt recipe).
# We pack one full and one half belt into the space of one belt by mixing red and blue
# underground belts. A full red belt (30 items/sec) can safely carry a half-belt (22.5 items/sec).
# This means we need to balance the output red line periodically. To make this work
# requires a 4-assembler body pattern to alternate power poles and rebalancing.
# In the diagram below, we use the normal indicators ∪⊂∩⊃ for underground belt,
# but "crude" indicators ucnↄ for red underground belt.
#  o>ↄ>|⊃ cↄ ⊂⊃ cↄ ⊂|
#  ⊃^⊂^|i iioii iioi| o
#  ⊃^⊂v|┌─┐┌─┐┌─┐┌─┐|
#  >^ v|│A││A││A││A│|
#    ov|└─┘└─┘└─┘└─┘|
#     v|iivSiiioiioi| o
#  ↄ  >|⊃c<sↄ⊂⊃c<<ↄ⊂|
Processor('2 + half -> half',
	building='assembler',
	inputs=(0, 2, 1),
	outputs=(0, 0, 1),
	per_body_buildings=4,
	# head: Run the two high-throughput belts into the starting points,
	# run the third to the top then down into a red underground.
	# In order to power top beacons, need a pole in the upper left.
	# In order to power first body's left side inserters, the pole covering
	# the bottom beacons is almost halfway up.
	head_width=4,
	head=lambda building, belt, splitter: Layout('head',
		# poles
		(0, 0, primitives.medium_pole),
		(2, 4, primitives.medium_pole),
		# first input
		(0, 1, primitives.belt_to_ground(RIGHT)),
		(2, 1, primitives.belt_from_ground(RIGHT)),
		(3, 1, belt(UP)),
		(3, 0, belt(RIGHT)),
		# second input
		(0, 2, primitives.belt_to_ground(RIGHT)),
		(2, 2, primitives.belt_from_ground(RIGHT)),
		(3, 2, belt(DOWN, 4)),
		(3, 6, belt(RIGHT)),
		# third input
		(0, 3, belt(RIGHT)),
		(1, 3, belt(UP, 3)),
		(1, 0, belt(RIGHT)),
		(2, 0, primitives.belt_to_ground(RIGHT, type='red')),
		# output
		(0, 6, primitives.belt_from_ground(LEFT, type='red')),
	),
	# body: Alternate the two underground belt types so we can insert to/from both.
	# We need to re-balance the red belt since we need to use both sides.
	# However, this leaves no room for power poles. We can just manage to reach all inserters
	# by putting power poles on every second pair of assemblers.
	body_width=12,
	body=lambda building, belt, splitter: Layout('body',
		# assemblers
		(0, 2, building),
		(3, 2, building),
		(6, 2, building),
		(9, 2, building),
		# poles and inserters, top line
		(0, 1, entity(E.ins, UP)),
		(2, 1, entity(E.ins, UP)),
		(3, 1, entity(E.ins, UP)),
		(4, 1, primitives.medium_pole),
		(5, 1, entity(E.ins, UP)),
		(6, 1, entity(E.ins, UP)),
		(8, 1, entity(E.ins, UP)),
		(9, 1, entity(E.ins, UP)),
		(10, 1, primitives.medium_pole),
		(11, 1, entity(E.ins, UP)),
		# poles and inserters, bottom line
		(0, 5, entity(E.ins, DOWN)),
		(1, 5, entity(E.ins, UP)),
		(4, 5, entity(E.ins, UP)),
		(5, 5, entity(E.ins, DOWN)),
		(6, 5, entity(E.ins, DOWN)),
		(7, 5, primitives.medium_pole),
		(8, 5, entity(E.ins, UP)),
		(9, 5, entity(E.ins, UP)),
		(10, 5, primitives.medium_pole),
		(11, 5, entity(E.ins, DOWN)),
		# First input
		(0, 0, primitives.belt_to_ground(RIGHT)),
		(5, 0, primitives.belt_from_ground(RIGHT)),
		(6, 0, primitives.belt_to_ground(RIGHT)),
		(11, 0, primitives.belt_from_ground(RIGHT)),
		# Second input
		(0, 6, primitives.belt_to_ground(RIGHT)),
		(5, 6, primitives.belt_from_ground(RIGHT)),
		(6, 6, primitives.belt_to_ground(RIGHT)),
		(11, 6, primitives.belt_from_ground(RIGHT)),
		# Third input
		(2, 0, primitives.belt_from_ground(RIGHT, type='red')),
		(3, 0, primitives.belt_to_ground(RIGHT, type='red')),
		(8, 0, primitives.belt_from_ground(RIGHT, type='red')),
		(9, 0, primitives.belt_to_ground(RIGHT, type='red')),
		# Output
		(10, 6, primitives.belt_from_ground(LEFT, type='red')),
		(9, 6, belt(LEFT, 2)),
		(7, 6, primitives.belt_to_ground(LEFT, type='red')),
		(4, 6, primitives.belt_from_ground(LEFT, type='red')),
		(3, 5, splitter(LEFT, output_priority='right')),
		(2, 5, belt(DOWN)),
		(2, 6, belt(LEFT)),
		(1, 6, primitives.belt_to_ground(LEFT, type='red')),
	),
	# note tail goes a bit wider than the last thing put down, so that there's enough beacons
	tail_width=3,
	tail=pole_tail,
)


# Assemblers, 2 full in, 1 full out
# This supports all kinds of high-throughput 1:1 recipes with 2 inputs.
# We pack one full and one half belt into the space of one belt by mixing red and blue
# underground belts. A full red belt (30 items/sec) can safely carry a half-belt (22.5 items/sec).
# We then have half the outputs go to the top and bottom, so they combine to one full belt.
# This means we need to balance the output red lines periodically. To make this work
# requires a 4-assembler body pattern to alternate power poles and rebalancing.
# Note also the left-side pole in the body which is needed in order to link up with the head.
# In the diagram below, we use the normal indicators ∪⊂∩⊃ for underground belt,
# but "crude" indicators ucnↄ for red underground belt.
#   vↄ>|⊃c<sↄ⊂⊃ cↄ ⊂|
#  ⊃u⊂^|ii^S iioi oi| o
#  >vo |┌─┐┌─┐┌─┐┌─┐|
#   >>v|│A││A││A││A│|
#   nov|└─┘└─┘└─┘└─┘|
#  v< v|iovSiiio i i| o
#  <^ↄ>|⊃c<sↄ⊂⊃c<<ↄ⊂|
Processor('2 -> 1',
	building='assembler',
	inputs=(0, 2, 0),
	outputs=(0, 1, 0),
	per_body_buildings=4,
	# head: Run the two input belts into the starting points,
	# run the two output red lines into a combined output line.
	# In order to power first body's left side inserters, the pole covering
	# the tom/bottom beacons is almost halfway up.
	head_width=4,
	head=lambda building, belt, splitter: Layout('head',
		# poles
		(2, 2, primitives.medium_pole),
		(2, 4, primitives.medium_pole),
		# first input
		(0, 1, primitives.belt_to_ground(RIGHT)),
		(2, 1, primitives.belt_from_ground(RIGHT)),
		(3, 1, belt(UP)),
		(3, 0, belt(RIGHT)),
		# second input
		(0, 2, belt(RIGHT)),
		(1, 2, belt(DOWN)),
		(1, 3, belt(RIGHT, 2)),
		(3, 3, belt(DOWN, 3)),
		(3, 6, belt(RIGHT)),
		# top output
		(2, 0, primitives.belt_from_ground(LEFT, type='red')),
		(1, 0, belt(DOWN)),
		(1, 1, primitives.belt_to_ground(DOWN, type='red')),
		(1, 4, primitives.belt_from_ground(DOWN, type='red')),
		# bottom output
		(2, 6, primitives.belt_from_ground(LEFT, type='red')),
		(1, 6, belt(UP)),
		# combined output
		(1, 5, belt(LEFT)),
		(0, 5, belt(DOWN)),
		(0, 6, belt(LEFT)),
	),
	# body: Alternate the two underground belt types so we can insert to/from both.
	# We need to re-balance the red belt since we need to use both sides.
	# We can just manage to reach all inserters
	# by putting power poles on every second pair of assemblers.
	body_width=12,
	body=lambda building, belt, splitter: Layout('body',
		# assemblers
		(0, 2, building),
		(3, 2, building),
		(6, 2, building),
		(9, 2, building),
		# poles and inserters, top line
		(0, 1, entity(E.ins, UP)),
		(1, 1, entity(E.ins, DOWN)),
		(5, 1, entity(E.ins, UP)),
		(6, 1, entity(E.ins, UP)),
		(7, 1, primitives.medium_pole),
		(8, 1, entity(E.ins, DOWN)),
		(10, 1, primitives.medium_pole),
		(11, 1, entity(E.ins, UP)),
		# poles and inserters, bottom line
		(0, 5, entity(E.ins, DOWN)),
		(1, 5, primitives.medium_pole),
		(4, 5, entity(E.ins, UP)),
		(5, 5, entity(E.ins, DOWN)),
		(6, 5, entity(E.ins, DOWN)),
		(7, 5, primitives.medium_pole),
		(9, 5, entity(E.ins, UP)),
		(11, 5, entity(E.ins, DOWN)),
		# First input
		(0, 0, primitives.belt_to_ground(RIGHT)),
		(5, 0, primitives.belt_from_ground(RIGHT)),
		(6, 0, primitives.belt_to_ground(RIGHT)),
		(11, 0, primitives.belt_from_ground(RIGHT)),
		# Second input
		(0, 6, primitives.belt_to_ground(RIGHT)),
		(5, 6, primitives.belt_from_ground(RIGHT)),
		(6, 6, primitives.belt_to_ground(RIGHT)),
		(11, 6, primitives.belt_from_ground(RIGHT)),
		# Top output
		(9, 0, primitives.belt_from_ground(LEFT, type='red')),
		(8, 0, primitives.belt_to_ground(LEFT, type='red')),
		(4, 0, primitives.belt_from_ground(LEFT, type='red')),
		(3, 0, splitter(LEFT, output_priority='left')),
		(2, 1, belt(UP)),
		(2, 0, belt(LEFT)),
		(1, 0, primitives.belt_to_ground(LEFT, type='red')),
		# Bottom output
		(9, 6, primitives.belt_from_ground(LEFT, type='red')),
		(8, 6, primitives.belt_to_ground(LEFT, type='red')),
		(4, 6, primitives.belt_from_ground(LEFT, type='red')),
		(3, 5, splitter(LEFT, output_priority='right')),
		(2, 5, belt(DOWN)),
		(2, 6, belt(LEFT)),
		(1, 6, primitives.belt_to_ground(LEFT, type='red')),
	),
	# note tail goes a bit wider than the last thing put down, so that there's enough beacons
	tail_width=3,
	tail=pole_tail,
)


# Assemblers, 3 half belt in, 1 full belt out
# This supports a bunch of recipes with large amounts of output compared to their input,
# even if they don't use all three belts.
# We pack one blue belt (two halves) and one red belt (one half) into one line
# by mixing red and blue underground belts.
# In the diagram below, we use the normal indicators ∪⊂∩⊃ for underground belt,
# but "crude" indicators ucnↄ for red underground belt.
#  >ↄ>>|⊃ cↄ ⊂|
#  ^>^o|i iioi| o
#  >^< |┌─┐┌─┐|
#  >>^ |│A││A│|
#      |└─┘└─┘|
#     o|i vSoi| o
#  <<<<|<<<s<<|
Processor('3x half -> full',
	building='assembler',
	inputs=(0, 0, 3),
	outputs=(0, 1, 0),
	per_body_buildings=2,
	# head: Run the highest throughput one onto the red underground
	# (which one doesn't matter, but we pick the highest throughput one
	# on the off chance the inserter becomes a bottleneck, since it only needs)
	# to insert one input instead of 2). Put the other two together.
	head_width=4,
	head=lambda building, belt, splitter: Layout('head',
		# poles
		(3, 1, primitives.medium_pole),
		(3, 5, primitives.medium_pole),
		# first input
		(0, 1, belt(UP)),
		(0, 0, belt(RIGHT)),
		(1, 0, primitives.belt_to_ground(RIGHT, type='red')),
		# second input
		(0, 2, belt(RIGHT)),
		# third input
		(0, 3, belt(RIGHT, 2)),
		(2, 3, belt(UP)),
		(2, 2, belt(LEFT)),
		# 2 + 3
		(1, 2, belt(UP)),
		(1, 1, belt(RIGHT)),
		(2, 1, belt(UP)),
		(2, 0, belt(RIGHT, 2)),
		# output
		(3, 6, belt(LEFT, 4)),
	),
	# body: Alternate the two underground belt types so we can insert to/from both.
	# Rebalance the output each step.
	body_width=6,
	body=lambda building, belt, splitter: Layout('body',
		# assemblers
		(0, 2, building),
		(3, 2, building),
		# poles
		(4, 1, primitives.medium_pole),
		(4, 5, primitives.medium_pole),
		# inserters
		(0, 1, entity(E.ins, UP)),
		(2, 1, entity(E.ins, UP)),
		(3, 1, entity(E.ins, UP)),
		(5, 1, entity(E.ins, UP)),
		(0, 5, entity(E.ins, UP)),
		(5, 5, entity(E.ins, UP)),
		# first input
		(2, 0, primitives.belt_from_ground(RIGHT, type='red')),
		(3, 0, primitives.belt_to_ground(RIGHT, type='red')),
		# combined second and third inputs
		(0, 0, primitives.belt_to_ground(RIGHT)),
		(5, 0, primitives.belt_from_ground(RIGHT)),
		# output
		(5, 6, belt(LEFT, 2)),
		(3, 5, splitter(LEFT, output_priority='right')),
		(2, 5, belt(DOWN)),
		(2, 6, belt(LEFT, 3)),
	),
	# note tail goes a bit wider than the last thing put down, so that there's enough beacons
	tail_width=3,
	tail=pole_tail,
)


# Processor for oil cracking, identified as 2 liquids -> 1 liquid.
# Note there's a narrowly avoided issue here with inputs. In heavy oil cracking,
# there is more heavy oil than water (40 vs 30). But in light oil cracking, they
# are even (30 vs 30). This means that the first input is the oil (which needs to
# go on the top left input for the chemical plant) for heavy, but for light it depends
# on the names. Thankfully light oil sorts before water, so the oil is again in the first input.
# Our second problem is that with no room to run vertical underground pipes, we can't have
# inputs next to each other (as the pipes would mix). This means we need at least 1 gap between
# each plant. But that doesn't tesselate because then 1 in 3 plants would line up with the becaons
# and only be covered by 6 instead of 8. We solve this by making a 2-wide gap every second plant,
# so we have 2 plants in 9 spaces instead of 2 plants in 8 spaces.
# Due to this large gap at the end, the tail doesn't need to be full width.
#  ===⊃| ⊂=⊃ ⊂=⊃ |
#  =  =|=⊃=⊂=⊃=⊂=| o
#  ⊃o⊂=|┌─┐o┌─┐  |
#      |│C│ │C│  |
#   o  |└─┘o└─┘  |
#     =|=⊃ ⊂=⊃  ⊂| o
#  ⊃ ⊂=|         |
Processor('oil cracking',
	building='chemical plant',
	inputs=(2, 0, 0),
	outputs=(1, 0, 0),
	base_buildings=0,
	per_body_buildings=2,
	head_width=4,
	head=lambda building, belt, splitter: Layout('head',
		# poles
		(1, 2, primitives.medium_pole),
		(1, 4, primitives.medium_pole),
		# first input
		(0, 1, entity(E.pipe)),
		(0, 0, primitives.pipe(RIGHT, 3)),
		(3, 0, entity(E.underground_pipe, LEFT)),
		# second input
		(0, 2, entity(E.underground_pipe, LEFT)),
		(2, 2, entity(E.underground_pipe, RIGHT)),
		(3, 2, primitives.pipe(UP, 2)),
		# output
		(3, 5, primitives.pipe(DOWN, 2)),
		(2, 6, entity(E.underground_pipe, RIGHT)),
		(0, 6, entity(E.underground_pipe, LEFT)),
	),
	body_width=9,
	body=lambda building, belt, splitter: Layout('body',
		# buildings and poles
		(0, 2, building),
		(3, 2, primitives.medium_pole),
		(3, 4, primitives.medium_pole),
		(4, 2, building),
		# first input
		(1, 0, entity(E.underground_pipe, RIGHT)),
		(2, 0, entity(E.pipe)),
		(2, 1, entity(E.pipe)),
		(3, 0, entity(E.underground_pipe, LEFT)),
		(5, 0, entity(E.underground_pipe, RIGHT)),
		(6, 0, entity(E.pipe)),
		(6, 1, entity(E.pipe)),
		(7, 0, entity(E.underground_pipe, LEFT)),
		# second input
		(0, 1, entity(E.pipe)),
		(1, 1, entity(E.underground_pipe, LEFT)),
		(3, 1, entity(E.underground_pipe, RIGHT)),
		(4, 1, entity(E.pipe)),
		(5, 1, entity(E.underground_pipe, LEFT)),
		(7, 1, entity(E.underground_pipe, RIGHT)),
		(8, 1, entity(E.pipe)),
		# output
		(8, 5, entity(E.underground_pipe, RIGHT)),
		(5, 5, entity(E.underground_pipe, LEFT)),
		(4, 5, entity(E.pipe)),
		(3, 5, entity(E.underground_pipe, RIGHT)),
		(1, 5, entity(E.underground_pipe, LEFT)),
		(0, 5, entity(E.pipe)),
	),
	# Tail doesn't need to add more beacons, just power the last one.
	tail_width=2,
	tail=pole_tail,
)


# Processor for 2 liquids -> 1 solid, eg. sulfur.
# Again, we hit issues with equal throughput liquid inputs, but again we know water sorts last.
# To avoid having two liquid inputs side by side, every second plant is flipped. We also avoid
# needing to rebalance the output lines by having half the plants output to the top vs the bottom,
# then join the two half-lines at the end.
# The head only barly fits in 4 width. It only works because the top belt's items are on the
# right side, so it can put onto the bottom belt even when going head-first into an underground
# belt. Also, the first body's poles cover the head area's beacons.
# In the diagram below, we use Ɔ (an upside down C) to indiciate an upside down chemical plant.
# We also distinguish between pipe and belt undergrounds by using ucnↄ for belts.
#  =⊃vↄ|o⊂=⊃cↄ|
#  ==u=|=⊃= i⊂| o
#  ⊃=⊂=|┌─┐┌─┐|
#  == ∪|│C││Ɔ│|
#  =o  |└─┘└─┘|
#  =⊃n∩|oi⊂=⊃=| o
#  <<⊃=|⊃cↄ ⊂=|
Processor('2 fluids to belt',
	building='chemical plant',
	inputs=(2, 0, 0),
	outputs=(0, 1, 0),
	base_buildings=0,
	per_body_buildings=2,
	head_width=4,
	head=lambda building, belt, splitter: Layout('head',
		# Pole
		(1, 4, primitives.medium_pole),
		# First input, upper side
		(0, 1, primitives.pipe(UP, 2)),
		(1, 0, entity(E.underground_pipe, LEFT)),
		# lower side
		(1, 1, primitives.pipe(DOWN, 3)),
		(0, 3, primitives.pipe(DOWN, 3)),
		(1, 5, entity(E.underground_pipe, LEFT)),
		# Second input, upper side
		(0, 2, entity(E.underground_pipe, LEFT)),
		(2, 2, entity(E.underground_pipe, RIGHT)),
		(3, 2, primitives.pipe(UP, 2)),
		# lower side
		(3, 3, entity(E.underground_pipe, UP)),
		(3, 5, entity(E.underground_pipe, DOWN)),
		(3, 6, entity(E.pipe)),
		# Output, upper side
		(3, 0, primitives.belt_from_ground(LEFT)),
		(2, 0, belt(DOWN)),
		(2, 1, primitives.belt_to_ground(DOWN)),
		(2, 5, primitives.belt_from_ground(DOWN)),
		# lower side
		(2, 6, primitives.belt_from_ground(LEFT)),
		(1, 6, belt(LEFT, 2)),
	),
	body_width=6,
	body=lambda building, belt, splitter: Layout('body',
		# buildings and poles
		(0, 2, building),
		(3, 2, building._replace(orientation=DOWN)),
		(0, 0, primitives.medium_pole),
		(0, 5, primitives.medium_pole),
		# First input, upper side
		(1, 0, entity(E.underground_pipe, RIGHT)),
		(2, 0, entity(E.pipe)),
		(2, 1, entity(E.pipe)),
		(3, 0, entity(E.underground_pipe, LEFT)),
		# lower side
		(2, 5, entity(E.underground_pipe, RIGHT)),
		(3, 5, entity(E.pipe)),
		(4, 5, entity(E.underground_pipe, LEFT)),
		# Second input, upper side
		(0, 1, entity(E.pipe)),
		(1, 1, entity(E.underground_pipe, LEFT)),
		(5, 1, entity(E.underground_pipe, RIGHT)),
		# lower side
		(0, 6, entity(E.underground_pipe, LEFT)),
		(4, 6, entity(E.underground_pipe, RIGHT)),
		(5, 6, entity(E.pipe)),
		(5, 5, entity(E.pipe)),
		# Output, upper side
		(5, 0, primitives.belt_from_ground(LEFT)),
		(4, 0, primitives.belt_to_ground(LEFT)),
		(4, 1, entity(E.ins, DOWN)),
		# lower side
		(2, 6, primitives.belt_from_ground(LEFT)),
		(1, 6, primitives.belt_to_ground(LEFT)),
		(1, 5, entity(E.ins, UP)),
	),
	tail_width=3,
	tail=pole_tail,
)


# Processor for 1 liquid + 2 solids to a liquid, eg. sulfuric acid.
# Pretty straightforward. We even manage to accept full input lines.
# In the diagram below, we distinguish between pipe and belt undergrounds by using ucnↄ for belts.
#  >ↄ |oc>>ↄ |
# ⊃^ ⊂|=⊃ii⊂=| o
# >^  |┌─┐┌─┐|
# >vo |│C││C│|
#  >v |└─┘└─┘|
# =⊃v⊂|=⊃ii⊂=| o
# = >ↄ|oc>>ↄ |
Processor('1 liquid + 2 solids -> liquid',
	building='chemical plant',
	inputs=(1, 2, 0),
	outputs=(1, 0, 0),
	head_width=4,
	head=lambda building, belt, splitter: Layout('head',
		# single pole, connects to above and below poles.
		# the head beacons are instead powered by the first body section.
		(2, 3, primitives.medium_pole),
		# liquid input
		(0, 1, entity(E.underground_pipe, LEFT)),
		(3, 1, entity(E.underground_pipe, RIGHT)),
		# first belt input
		(0, 2, belt(RIGHT)),
		(1, 2, belt(UP, 2)),
		(1, 0, belt(RIGHT)),
		(2, 0, primitives.belt_to_ground(RIGHT)),
		# second belt input
		(0, 3, belt(RIGHT)),
		(1, 3, belt(DOWN)),
		(1, 4, belt(RIGHT)),
		(2, 4, belt(DOWN, 2)),
		(2, 6, belt(RIGHT)),
		(3, 6, primitives.belt_to_ground(RIGHT)),
		# output
		(3, 5, entity(E.underground_pipe, RIGHT)),
		(1, 5, entity(E.underground_pipe, LEFT)),
		(0, 5, primitives.pipe(DOWN, 2)),
	),
	body_width=6,
	per_body_buildings=2,
	body=lambda building, belt, splitter: Layout('body',
		# poles
		(0, 0, primitives.medium_pole),
		(0, 6, primitives.medium_pole),
		# buildings
		(0, 2, building),
		(3, 2, building),
		# liquid input
		(0, 1, entity(E.pipe)),
		(1, 1, entity(E.underground_pipe, LEFT)),
		(4, 1, entity(E.underground_pipe, RIGHT)),
		(5, 1, entity(E.pipe)),
		# first belt input
		(1, 0, primitives.belt_from_ground(RIGHT)),
		(2, 0, belt(RIGHT, 2)),
		(2, 1, entity(E.ins, UP)),
		(3, 1, entity(E.ins, UP)),
		(4, 0, primitives.belt_to_ground(RIGHT)),
		# second belt input
		(1, 6, primitives.belt_from_ground(RIGHT)),
		(2, 6, belt(RIGHT, 2)),
		(2, 5, entity(E.ins, DOWN)),
		(3, 5, entity(E.ins, DOWN)),
		(4, 6, primitives.belt_to_ground(RIGHT)),
		# output
		(0, 5, entity(E.pipe)),
		(1, 5, entity(E.underground_pipe, LEFT)),
		(4, 5, entity(E.underground_pipe, RIGHT)),
		(5, 5, entity(E.pipe)),
	),
	tail_width=3,
	tail=pole_tail,
)


# Processor for 1 liquid + 2 solids to a solid.
# Similar to previous, except we combine both inputs into one line so we have room for
# the output line.
# In the diagram below, we distinguish between pipe and belt undergrounds by using ucnↄ for belts.
#  >ↄ |oc>>ↄ |
# ⊃^ ⊂|=⊃ii⊂=| o
# >^< |┌─┐┌─┐|
# >>^ |│C││C│|
#  o  |└─┘└─┘|
#     |oivSi | o
# <<<<|<<<s<<|
Processor('1 liquid + 2 solids -> solid',
	building='chemical plant',
	inputs=(1, 0, 2),
	outputs=(0, 1, 0),
	head_width=4,
	head=lambda building, belt, splitter: Layout('head',
		# single power pole connects to top and bottom, the head's beacons are powered
		# by the first body section.
		(1, 4, primitives.medium_pole),
		# liquid input
		(0, 1, entity(E.underground_pipe, LEFT)),
		(3, 1, entity(E.underground_pipe, RIGHT)),
		# first belt input
		(0, 2, belt(RIGHT)),
		# second belt input
		(0, 3, belt(RIGHT, 2)),
		(2, 3, belt(UP)),
		(2, 2, belt(LEFT)),
		# combined belt input
		(1, 2, belt(UP, 2)),
		(1, 0, belt(RIGHT)),
		(2, 0, primitives.belt_to_ground(RIGHT)),
		# output
		(3, 6, belt(LEFT, 4)),
	),
	body_width=6,
	per_body_buildings=2,
	body=lambda building, belt, splitter: Layout('body',
		# poles
		(0, 0, primitives.medium_pole),
		(0, 5, primitives.medium_pole),
		# buildings
		(0, 2, building),
		(3, 2, building),
		# liquid input
		(0, 1, entity(E.pipe)),
		(1, 1, entity(E.underground_pipe, LEFT)),
		(4, 1, entity(E.underground_pipe, RIGHT)),
		(5, 1, entity(E.pipe)),
		# belt input
		(1, 0, primitives.belt_from_ground(RIGHT)),
		(2, 0, belt(RIGHT, 2)),
		(2, 1, entity(E.ins, UP)),
		(3, 1, entity(E.ins, UP)),
		(4, 0, primitives.belt_to_ground(RIGHT)),
		# output
		(5, 6, belt(LEFT, 2)),
		(4, 5, entity(E.ins, UP)),
		(3, 5, splitter(LEFT, output_priority='right')),
		(2, 5, belt(DOWN)),
		(2, 6, belt(LEFT, 3)),
		(1, 5, entity(E.ins, UP)),
	),
	tail_width=3,
	tail=pole_tail,
)


# Processor for assemblers with a liquid input.
# Can additionally take 1 full and 1 half belt input, and outputs to one half.
# Could probably be tweaked to allow a full output?
# In the diagram below, we distinguish between pipe and belt undergrounds by using cↄ for belts,
# and () for red belts.
# =⊃ >|ↄo⊂=⊃c|
# =  ^|i====i| o
# >>>^|┌─┐┌─┐|
# >vo |│A││A│|
#  v  |└─┘└─┘|
#  v  |ioii i| o
# ↄ>)c|ↄ () c|
Processor('assembler with liquid input',
	inputs=(1, 1, 1),
	outputs=(0, 0, 1),
	head_width=4,
	head=lambda building, belt, splitter: Layout('head',
		# poles
		(2, 3, primitives.medium_pole),
		# liquid input
		(0, 1, primitives.pipe(UP, 2)),
		(1, 0, entity(E.underground_pipe, LEFT)),
		# first belt input
		(0, 2, belt(RIGHT, 3)),
		(3, 2, belt(UP, 2)),
		(3, 0, belt(RIGHT)),
		# second belt input
		(0, 3, belt(RIGHT)),
		(1, 3, belt(DOWN, 3)),
		(1, 6, belt(RIGHT)),
		(2, 6, primitives.belt_to_ground(RIGHT, type='red')),
		# output
		(3, 6, primitives.belt_to_ground(LEFT)),
		(0, 6, primitives.belt_from_ground(LEFT)),
	),
	body_width=6,
	per_body_buildings=2,
	body=lambda building, belt, splitter: Layout('body',
		# poles
		(1, 0, primitives.medium_pole),
		(1, 5, primitives.medium_pole),
		# buildings
		(0, 2, building),
		(3, 2, building),
		# liquid input
		(2, 0, entity(E.underground_pipe, RIGHT)),
		(3, 0, entity(E.pipe)),
		(1, 1, primitives.pipe(RIGHT, 4)),
		(4, 0, entity(E.underground_pipe, LEFT)),
		# first belt input
		(0, 0, primitives.belt_to_ground(RIGHT)),
		(0, 1, entity(E.ins, UP)),
		(5, 0, primitives.belt_from_ground(RIGHT)),
		(5, 1, entity(E.ins, UP)),
		# second belt input
		(2, 6, primitives.belt_from_ground(RIGHT, type='red')),
		(2, 5, entity(E.ins, DOWN)),
		(3, 6, primitives.belt_to_ground(RIGHT, type='red')),
		(3, 5, entity(E.ins, DOWN)),
		# output
		(5, 6, primitives.belt_to_ground(LEFT)),
		(5, 5, entity(E.ins, UP)),
		(0, 6, primitives.belt_from_ground(LEFT)),
		(0, 5, entity(E.ins, UP)),
	),
	tail_width=3,
	tail=pole_tail,
)


# 6 inputs to one output, for satellite.
# We relax efficiency here since this is a low-throughput item.
# Note tail doesn't need extended length.
# Note some minor changes could make this 0/2/4 -> 0/1/0 instead,
# but meh.
# >v>>>|>>>>>>|
# ⊃>^⊂v| oi   | o
# >^o >|⊃i┌─┐⊂|
# >v >>|⊃i│A│⊂|
# ⊃>>^⊂|⊃i└─┘⊂|
# >^o  | oi   | o
# <<<<<|<<<<<<|
Processor('6 input assembler',
	inputs=(0, 0, 6),
	outputs=(0, 0, 1),
	head_width=5,
	head=lambda building, belt, splitter: Layout('head',
		# poles
		(2, 2, primitives.medium_pole),
		(2, 5, primitives.medium_pole),
		# first input
		(0, 0, belt(RIGHT)),
		(1, 0, belt(DOWN)),
		# second input
		(0, 1, primitives.belt_to_ground(RIGHT)),
		(3, 1, primitives.belt_from_ground(RIGHT)),
		(4, 1, belt(DOWN)),
		(4, 2, belt(RIGHT)),
		# third input
		(0, 2, belt(RIGHT)),
		(1, 2, belt(UP)),
		# 1+3 input
		(1, 1, belt(RIGHT)),
		(2, 1, belt(UP)),
		(2, 0, belt(RIGHT, 3)),
		# fourth input
		(0, 3, belt(RIGHT)),
		(1, 3, belt(DOWN)),
		# fifth input
		(0, 4, primitives.belt_to_ground(RIGHT)),
		(4, 4, primitives.belt_from_ground(RIGHT)),
		# sixth input (phew)
		(0, 5, belt(RIGHT)),
		(1, 5, belt(UP)),
		# 4+6 input
		(1, 4, belt(RIGHT, 2)),
		(3, 4, belt(UP)),
		(3, 3, belt(RIGHT, 2)),
		# output
		(4, 6, belt(LEFT, 5)),
	),
	body_width=6,
	per_body_buildings=1,
	body=lambda building, belt, splitter: Layout('body',
		# poles and building
		(1, 1, primitives.medium_pole),
		(1, 5, primitives.medium_pole),
		(2, 2, building),
		# 1+3 input
		(0, 0, belt(RIGHT, 6)),
		(2, 1, entity(E.ins, UP)),
		# 2 input
		(0, 2, primitives.belt_to_ground(RIGHT)),
		(1, 2, entity(E.ins, LEFT)),
		(5, 2, primitives.belt_from_ground(RIGHT)),
		# 4+6 input
		(0, 3, primitives.belt_to_ground(RIGHT)),
		(1, 3, entity(E.ins, LEFT)),
		(5, 3, primitives.belt_from_ground(RIGHT)),
		# 5 input
		(0, 4, primitives.belt_to_ground(RIGHT)),
		(1, 4, entity(E.ins, LEFT)),
		(5, 4, primitives.belt_from_ground(RIGHT)),
		# output
		(5, 6, belt(LEFT, 6)),
		(2, 5, entity(E.ins, UP)),
	),
	tail_width=2,
	tail=pole_tail,
)


# 7 inputs to lab, for science!
# This is a particularly large pattern made up of two almost-identical copies.
# We could avoid this, but meh.
# In the diagram below, we use the normal indicators ∪⊂∩⊃ for underground belt,
# but "crude" indicators ucnↄ for red underground belt.
# ↄ>>>|⊃ c>>>ↄ ⊂⊃ c>>>ↄ ⊂|
# >^< |ioi   ioiioi   ioi| o
# ⊃o^ |┌─┐⊂v ┌─┐┌─┐ >⊃┌─┐|
# >>^ |│L│ivi│L││L│i^i│L│|
# >>v |└─┘ >⊃└─┘└─┘⊂^ └─┘|
# >v< |ioi   ioiioi   ioi| o
# ↄ>>>|⊃ c>>>ↄ ⊂⊃ c>>>ↄ ⊂|
# TODO 0/0/7 -> 0/0/0
Processor('lab',
	building='lab',
	inputs=(0, 0, 7),
	outputs=(0, 0, 0),
	head_width=4,
	head=lambda building, belt, splitter: Layout('head',
		# pole
		(1, 2, primitives.medium_pole),
		# input 1
		(0, 0, primitives.belt_to_ground(RIGHT, type='red')),
		# input 2
		(0, 1, belt(RIGHT)),
		# input 3
		(0, 2, primitives.belt_to_ground(RIGHT)),
		# input 4
		(0, 3, belt(RIGHT, 2)),
		(2, 3, belt(UP, 2)),
		(2, 1, belt(LEFT)),
		# input 2+4
		(1, 1, belt(UP)),
		(1, 0, belt(RIGHT, 3)),
		# input 5
		(0, 4, belt(RIGHT, 2)),
		(2, 4, belt(DOWN)),
		(2, 5, belt(LEFT)),
		# input 6
		(0, 5, belt(RIGHT)),
		# input 5+6
		(1, 5, belt(DOWN)),
		(1, 6, belt(RIGHT, 3)),
		# input 7
		(0, 6, primitives.belt_to_ground(RIGHT, type='red')),
	),
	body_width=18,
	per_body_buildings=4,
	body=lambda building, belt, splitter: Layout('body',
		# poles
		(1, 1, primitives.medium_pole),
		(7, 1, primitives.medium_pole),
		(10, 1, primitives.medium_pole),
		(16, 1, primitives.medium_pole),
		(1, 5, primitives.medium_pole),
		(7, 5, primitives.medium_pole),
		(10, 5, primitives.medium_pole),
		(16, 5, primitives.medium_pole),
		# buildings
		(0, 2, building),
		(6, 2, building),
		(9, 2, building),
		(15, 2, building),
		# input 2+4
		(0, 0, primitives.belt_to_ground(RIGHT)),
		(0, 1, entity(E.ins, UP)),
		(8, 0, primitives.belt_from_ground(RIGHT)),
		(8, 1, entity(E.ins, UP)),
		(9, 0, primitives.belt_to_ground(RIGHT)),
		(9, 1, entity(E.ins, UP)),
		(17, 0, primitives.belt_from_ground(RIGHT)),
		(17, 1, entity(E.ins, UP)),
		# input 1
		(2, 0, primitives.belt_from_ground(RIGHT, type='red')),
		(2, 1, entity(E.ins, UP)),
		(3, 0, belt(RIGHT, 3)),
		(6, 0, primitives.belt_to_ground(RIGHT, type='red')),
		(6, 1, entity(E.ins, UP)),
		(11, 0, primitives.belt_from_ground(RIGHT, type='red')),
		(11, 1, entity(E.ins, UP)),
		(12, 0, belt(RIGHT, 3)),
		(15, 0, primitives.belt_to_ground(RIGHT, type='red')),
		(15, 1, entity(E.ins, UP)),
		# input 5+6
		(0, 6, primitives.belt_to_ground(RIGHT)),
		(0, 5, entity(E.ins, DOWN)),
		(8, 6, primitives.belt_from_ground(RIGHT)),
		(8, 5, entity(E.ins, DOWN)),
		(9, 6, primitives.belt_to_ground(RIGHT)),
		(9, 5, entity(E.ins, DOWN)),
		(17, 6, primitives.belt_from_ground(RIGHT)),
		(17, 5, entity(E.ins, DOWN)),
		# input 7
		(2, 6, primitives.belt_from_ground(RIGHT, type='red')),
		(2, 5, entity(E.ins, DOWN)),
		(3, 6, belt(RIGHT, 3)),
		(6, 6, primitives.belt_to_ground(RIGHT, type='red')),
		(6, 5, entity(E.ins, DOWN)),
		(11, 6, primitives.belt_from_ground(RIGHT, type='red')),
		(11, 5, entity(E.ins, DOWN)),
		(12, 6, belt(RIGHT, 3)),
		(15, 6, primitives.belt_to_ground(RIGHT, type='red')),
		(15, 5, entity(E.ins, DOWN)),
		# input 3
		(3, 2, primitives.belt_from_ground(RIGHT)),
		(4, 2, belt(DOWN, 2)),
		(3, 3, entity(E.ins, RIGHT)),
		(5, 3, entity(E.ins, LEFT)),
		(4, 4, belt(RIGHT)),
		(5, 4, primitives.belt_to_ground(RIGHT)),
		(12, 4, primitives.belt_from_ground(RIGHT)),
		(13, 4, belt(UP, 2)),
		(12, 3, entity(E.ins, RIGHT)),
		(14, 3, entity(E.ins, LEFT)),
		(13, 2, belt(RIGHT)),
		(14, 2, primitives.belt_to_ground(RIGHT)),
	),
	tail_width=3,
	tail=pole_tail,
)


# Rocket Silo
# This is a special case, because it can't fit in the normal 7-wide space.
# We mark it as "oversize" (by 4 - it's 11 tall!) and the bus will extend to fit.
# Note that even though oversize, it expects the inputs and outputs in the same
# y-slots as otherwise.
# We fit all the belts into a 2-wide gap between each silo, because it can't run under.
# to make this work we end up with a pretty complex gap between each silo, but
# it's worth trading off width for height here.
# We also need a lot of power poles to ensure all the beacons are powered,
# though note we completely lack a tail since the body section entirely covers the beacons needed.
# Because a rocket will happily fire even if its output is full, we make inserting a satellite
# conditional on a per-silo output buffer box being almost empty.
# We also need to extend the body 2 more spaces than otherwise to ensure the width is a multiple
# of 3, or else some silos will be less beaconed than others.
# The relevant (long-handed) inserter is marked as I instead of i.
# We also use the normal indicators ∪⊂∩⊃ for underground belt,
# but "crude" indicators ucnↄ for red underground belt.
# >>>>|s>>⊃>c ⊂⊃cↄ⊂⊃  cv⊂>>>|
# ^<o |sv>ↄ∪v⊃cↄo cↄ ⊂<∪cv  |
# >^  | ∪^ov<┌───────┐^o v  |
# >vv⊃|  ^⊂< │       │^⊃ v  |
# v∪∪ |  ^ i │       │   v  |
# >v  |  ^o☐i│       │   v  |
# <>>>|>>^ I │   S   │   >>>|
# ^ ∩ | ∩  ^i│       │ ∩    |
# ^<< | >>>^i│       │iv    |
#  ∩o |    ∩ │       │ v    |
#  >>>|>>>>^o└───────┘o>>>>>|
# TODO silo needs "auto launch with cargo" checked
Processor('rocket silo',
	building='rocket silo',
	inputs=(0, 0, 4),
	outputs=(0, 0, 1),
	oversize=4,
	head_width=4,
	head=lambda building, belt, splitter: Layout('head',
		# poles
		(2, 1, primitives.medium_pole),
		(2, 9, primitives.medium_pole),
		# second input merges into first
		(0, 2, belt(RIGHT)),
		(1, 2, belt(UP)),
		(1, 1, belt(LEFT)),
		# first/second input
		(0, 1, belt(UP)),
		(0, 0, belt(RIGHT, 4)),
		# third input
		(0, 3, belt(RIGHT)),
		(1, 3, belt(DOWN)),
		(1, 4, primitives.belt_to_ground(DOWN)),
		(1, 9, primitives.belt_from_ground(DOWN)),
		(1, 10, belt(RIGHT, 3)),
		# fourth input (satellite)
		(0, 4, belt(DOWN)),
		(0, 5, belt(RIGHT)),
		(1, 5, belt(DOWN)),
		(1, 6, belt(RIGHT, 3)),
		# output
		(3, 3, primitives.belt_from_ground(LEFT)),
		(2, 3, belt(DOWN)),
		(2, 4, primitives.belt_to_ground(DOWN)),
		(2, 7, primitives.belt_from_ground(DOWN)),
		(2, 8, belt(LEFT, 2)),
		(0, 8, belt(UP, 2)),
		(0, 6, belt(LEFT)),
	),
	body_width=21, # ouch
	per_body_buildings=1,
	body=lambda building, belt, splitter: Layout('body',
		# poles and silo
		(6, 2, building),
		(3, 2, primitives.medium_pole),
		(9, 1, primitives.medium_pole),
		(16, 2, primitives.medium_pole),
		(3, 5, primitives.medium_pole),
		(5, 10, primitives.medium_pole),
		(15, 10, primitives.medium_pole),
		# first/second input
		(0, 0, splitter(RIGHT)),
		(1, 1, belt(DOWN)),
		(1, 2, primitives.belt_to_ground(DOWN)),
		(1, 7, primitives.belt_from_ground(DOWN)),
		(1, 8, belt(RIGHT, 3)),
		(4, 8, belt(UP, 2)),
		(5, 8, entity(E.ins, LEFT)),
		(5, 7, entity(E.ins, LEFT)),
		(1, 0, belt(RIGHT, 2)), # back to the splitter
		(3, 0, primitives.belt_to_ground(RIGHT)),
		(7, 0, primitives.belt_from_ground(RIGHT)),
		(8, 0, primitives.belt_to_ground(RIGHT)),
		(11, 0, primitives.belt_from_ground(RIGHT)),
		(12, 0, primitives.belt_to_ground(RIGHT)),
		(17, 0, primitives.belt_from_ground(RIGHT)),
		(18, 0, belt(RIGHT, 3)),
		# third input
		(0, 10, belt(RIGHT, 4)),
		(4, 10, belt(UP)),
		(4, 9, primitives.belt_to_ground(UP)),
		(4, 1, primitives.belt_from_ground(UP)),
		(4, 0, belt(RIGHT)),
		(5, 0, primitives.belt_to_ground(RIGHT, type='red')),
		(9, 0, primitives.belt_from_ground(RIGHT, type='red')),
		(10, 0, primitives.belt_to_ground(RIGHT, type='red')),
		(15, 0, primitives.belt_from_ground(RIGHT, type='red')),
		(16, 0, belt(DOWN)),
		(16, 1, primitives.belt_to_ground(DOWN)),
		(16, 7, primitives.belt_from_ground(DOWN)),
		(15, 7, entity(E.ins, RIGHT)),
		(16, 8, belt(DOWN, 2)),
		(16, 10, belt(RIGHT, 5)),
		# fourth input (satellite)
		(0, 6, belt(RIGHT, 2)),
		(2, 6, belt(UP, 5)), # inserter takes from here, but we'll do it later
		(2, 1, belt(RIGHT)),
		(3, 1, primitives.belt_to_ground(RIGHT, type='red')),
		(7, 1, primitives.belt_from_ground(RIGHT, type='red')),
		(8, 1, primitives.belt_to_ground(RIGHT, type='red')),
		(11, 1, primitives.belt_from_ground(RIGHT, type='red')),
		(12, 1, primitives.belt_to_ground(RIGHT, type='red')),
		(17, 1, primitives.belt_from_ground(RIGHT, type='red')),
		(18, 1, belt(DOWN, 5)),
		(18, 6, belt(RIGHT, 3)),
		# satellite inserter, connected to white science output box.
		# only inserts if there is room in the output box.
		(4, 6, entity(
			E.long_inserter, LEFT,
			connections=[primitives.circuit(0, -1)],
			control_behavior={
				"circuit_condition": {
					"comparator": "<",
					"constant": 1000,
					"first_signal": {
						"type": "item",
						"name": "space-science-pack",
					},
				},
			},
		)),
		# output
		(16, 3, primitives.belt_from_ground(LEFT)),
		(15, 3, belt(UP, 2)),
		(15, 1, belt(LEFT)),
		(14, 1, primitives.belt_to_ground(LEFT)),
		(6, 1, primitives.belt_from_ground(LEFT)),
		(5, 1, belt(DOWN)),
		(5, 2, belt(LEFT)),
		(4, 2, belt(DOWN)),
		(4, 3, belt(LEFT)), # inserter outputs here
		(3, 3, primitives.belt_to_ground(LEFT)),
		(5, 5, entity(E.ins, RIGHT)), # silo to box
		(4, 5, entity(E.chest)),
		(4, 4, entity(E.ins, DOWN)), # box to belt
	),
)
