
from collections import namedtuple

from .util import line_limit


Placement = namedtuple('Placement', [
	'bus', # list of line objects, state of bus preceeding this placement
	'width', # bus width at this point (is max of before/after if it changes here)
	'process', # the Process being done in this step
	'inputs', # map {bus line number -> process input y pos}
	# Output needs item type because, unlike input, we can't just look it up in self.bus
	'outputs', # map {bus line number -> (item type, process output y pos)}
])


Compaction = namedtuple('Compaction', [
	'bus', # as Placement
	'width', # as Placement
	'compactions', # list of pairs of bus line numbers (a, b) compacting with preference to a
	'shifts', # list of pairs of bus line numbers (a, b) moving line at position a into position b
])


Line = namedtuple('Line', [
	'item', # name of item on line
	'throughput', # available throughput on this line
])


class BeltManager(object):
	def __init__(self, steps, inputs):
		"""
		steps should be a list of Processes, split such that no input or output
		exceeds a single line throughput limit.
		inputs should be a list of raw input Processes, in the order and amounts
		that they should be placed in.
		"""
		# we're gonna mutate these, so take copies
		self.pending = list(steps) # list of steps left to do
		self.bus = [Line(input.item, input.throughput) for input in inputs] # list of Line objects
		self.output = [] # list of Placement or Compaction

	def run(self):
		"""Sequence all steps until done"""
		while self.pending:
			self.do_one()

	def do_one(self):
		"""Work out the next output step to do, and do it."""
		candidates = self.find_candidates()
		if candidates:
			step = self.pick_candidate(candidates)
			self.pending.remove(step)
			self.add_step(step)
		else:
			bus = list(self.bus)
			self.compact()
			assert bus != self.bus

	def find_candidates(self):
		"""Return a list of steps which could be done right now"""
		results = []
		for step in self.pending:
			for input, throughput in step.inputs().items():
				if not self.find_lines(input, throughput):
					break
			else:
				results.append(step)
		return results

	def pick_candidate(self, candidates):
		"""Pick the best candidate to do from a list, and return it."""
		return candidates[0] # XXX improve

	def add_step(self, step):
		"""Apply the given step."""
		prev_bus = list(self.bus)

		# pick inputs
		inputs = {}
		inputs_by_throughput = sorted(step.inputs().items(), key=lambda (i, t): -t) # highest to lowest
		# highest throughput input goes in top y slot
		# NOTE: We avoid using y_slot 0 as this is hard to fit into the available space
		for y_slot, (input, throughput) in zip(range(1, 7), inputs_by_throughput):
			lines = self.find_lines(input, throughput)
			# pick least loaded matching line first, falling back to rightmost.
			line_num, line = min(lines, key=lambda (i, l): (l.throughput, -i))
			inputs[line_num] = y_slot
			self.line_take(line_num, throughput)
		assert len(inputs) == len(step.inputs())

		# pick outputs
		outputs = {}
		# output slots count up from bottom, highest throughput at bottom
		y_slots = range(7)[::-1]
		outputs_by_throughput = sorted(step.outputs().items(), key=lambda (i, t): -t)
		for y_slot, (output, throughput) in zip(y_slots, outputs_by_throughput):
			# for now, always allocate a new line for each output, we can compress later.
			line_num = self.add_line(output, throughput)
			outputs[line_num] = (output, y_slot)
		assert len(outputs) == len(step.outputs())

		assert not (set(inputs.values()) & set([
			y_slot for output, y_slot in outputs.values()
		])), "inputs and outputs overlap"

		placement = Placement(
			bus = prev_bus,
			width = max([len(self.bus), len(prev_bus)]),
			process = step,
			inputs = inputs,
			outputs = outputs,
		)
		self.output.append(placement)

	def compact(self):
		"""Apply the best compaction you can. Raise if there is no compacting to do,
		as this indicates we're stuck (which is a logic error).
		May also do shifts (move a single line without compacting)
		"""
		# Choice of which lines to compact is difficult.
		# For now, do the simplest thing.

		# XXX lots of future improvements here. could cram in lots more compactions/shifts
		# by tracking each 2x1 tile section's availability, knowing a lateral movement
		# reserves a y slot + one tile section every few columns, etc.

		# For now we don't do any shifts, and do compactions in a greedy manner
		# and without trying to cross-use available space.

		prev_bus = list(self.bus)
		compactions = []
		position = len(self.bus) - 1
		while position > 0:
			source = self.bus[position]
			if source is None:
				position -= 1
				continue
			# find candidates: lines to our left with the same item that aren't full
			candidates = [
				(i, line) for i, line in enumerate(self.bus[:position])
				if (
					line is not None
					and line.item == source.item
					and line.throughput < line_limit(line.item)
				)
			]
			if not candidates:
				position -= 1
				continue
			# pick least loaded first, then rightmost
			dest_pos, dest = min(candidates, key=lambda (i, line): (line.throughput, -i))
			limit = line_limit(dest.item)
			if dest.throughput + source.throughput > limit:
				new_source = source._replace(throughput = dest.throughput + source.throughput - limit)
				assert new_source.throughput < limit
				new_dest = dest._replace(throughput = limit)
				self.bus[position] = new_source
				self.bus[dest_pos] = new_dest
			else:
				new_dest = dest._replace(throughput = dest.throughput + source.throughput)
				self.bus[dest_pos] = new_dest
				self.line_take(position, source.throughput) # delete source line
			compactions.append((dest_pos, position))
			position = dest_pos - 1

		if not compactions:
			raise ValueError("Could not compact bus any further")

		self.output.append(Compaction(
			bus = prev_bus,
			width = len(prev_bus), # bus width never grows here, only shrinks
			compactions = compactions,
			shifts = [],
		))

	def find_lines(self, input, throughput):
		"""Find any lines in bus of given item type that have at least throughput.
		Returns list of tuples (bus line number, line object).
		"""
		return [
			(i, line) for i, line in enumerate(self.bus)
			if line is not None and line.item == input and line.throughput >= throughput
		]

	def line_take(self, num, throughput):
		"""Remove given throughput from available throughput for line in given position"""
		line = self.bus[num]
		if line is None:
			raise ValueError("Taking from empty line {}".format(num))
		new = line._replace(throughput = line.throughput - throughput)
		if new.throughput < 0:
			raise ValueError("Took too much from line {}: only had {}, took {}".format(num, line.throughput, throughput))
		if new.throughput == 0:
			new = None
		self.bus[num] = new
		while self.bus and self.bus[-1] is None:
			self.bus.pop()

	def add_line(self, item, throughput):
		"""Allocate a new line with given item and throughput. Returns new line's position."""
		# XXX we should try to use an empty slot adjacent to existing line for same item if available
		# try to use an empty slot (leftmost first).
		# if none available, add a new slot (widen the bus)
		if None not in self.bus:
			self.bus.append(None)
		index = self.bus.index(None)
		self.bus[index] = Line(item, throughput)
		return index
