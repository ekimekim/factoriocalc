
import math
from collections import namedtuple

from .util import Layout


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
	# TODO how to handle inserter throughput limits?
	PROCESSORS = []

	def __init__(self, name,
		building='assembler',
		inputs=(0,0,0),
		outputs=(0,0,0),
		head=EMPTY, body=EMPTY, tail=EMPTY,
		head_width=0, body_width=0, tail_width=0,
		base_buildings=0, per_body_buildings=0,
	):
		"""Most args are self-evident, see main docstring.
		head, body and tail may be callable, in which case they take the recipe as arg.
		"""
		self.name = name
		self.building = building
		self.inputs = InOutKinds(inputs),
		self.outputs = InOutKinds(outputs),
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
		if self.building != building:
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
		inputs = InOutKinds(inputs)
		outputs = InOutKinds(outputs)
		candidates = [processor for processor in cls.PROCESSORS if processor]
		if not candidates:
			raise ValueError("Could not find processor for {} with {} inputs and {} outputs".format(
				building, inputs, outputs
			))
		return min(candidates, key=lambda processor: processor.match_score())

	def determine_bodies(self, step):
		"""Work out how many body sections are needed for the given step."""
		throughput = step.process.throughput
		throughput_per_building = step.process.recipe.throughput
		buildings = throughput / throughput_per_building
		buildings -= self.base_buildings
		return max(0, int(math.ceil(buildings / self.per_body_buildings)))

	def resolve_layout(self, step, layout):
		if callable(layout):
			return layout(step.process.recipe)
		return layout

	def layout(self, step):
		"""Returns (layout, width) for the given step, which must already be matching."""
		layout = Layout("process: {}".format(self.name))
		layout.place(0, 0, self.resolve_layout(step, self.head))
		body = self.resolve_layout(step, self.body)
		bodies = self.determine_bodies()
		for i in range(bodies):
			layout.place(self.head_width + i * self.body_width, 0, body)
		layout.place(
			self.head_width + bodies * self.body_width,
			0,
			self.resolve_layout(step, self.tail)
		)
		return layout, self.head_width + bodies * self.body_width + self.tail_width


# Processors

Processor('furnaces',
	building='furnace',
	inputs=(0, 1, 0),
	outputs=(0, 1, 0),
	# head TODO
	head_width=6,
	# body: couldn't be simpler. just a pair of assemblers with inserters and sharing
	# power poles on each side
	#  >>>>>>
	#  i oi
	#  ┌─┐┌─┐
	#  │F││F│
	#  └─┘└─┘
	#  i oi
	#  <<<<<<
	body_width=6,
	body=Layout('body',
		(0, 0, primitives.belt(RIGHT, 6)),
		(0, 1, entity(E.inserter, UP)),
		# TODO UPTO
	)
)
