
from collections import namedtuple

from .util import line_limit, is_liquid


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
	def __init__(self, steps, inputs, belt_type='blue'):
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
		self.belt_type = belt_type

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

		def inout_order((item, throughput)):
			"""Inputs and outputs are sorted for consistent handling by process layouts.
			Liquids are first (top-most for inputs, bottom-most for outputs), then solids.
			Within those categories they are arranged by throughput, with ties broken by name.
			"""
			return (0 if is_liquid(item) else 1), -throughput, item

		# NOTE: We avoid using y_slot 0 unless we absolutely need to.
		# This is because pumps in the bus line encroach on y_slot 0.
		# We can selectively not include pumps when they would conflict,
		# but we don't want to do this too often as it risks liquid flow levels
		# dropping too low. By only doing this when needed (7 total inputs+outputs),
		# we mostly avoid it so it _should_ be fine.
		y_slots = range(7)
		if len(step.inputs()) + len(step.outputs()) <= 6:
			y_slots = y_slots[1:]

		# pick inputs
		inputs = {}
		inputs_in_order = sorted(step.inputs().items(), key=inout_order)
		for y_slot, (input, throughput) in zip(y_slots, inputs_in_order):
			lines = self.find_lines(input, throughput)
			# pick least loaded matching line first, falling back to rightmost.
			line_num, line = min(lines, key=lambda (i, l): (l.throughput, -i))
			inputs[line_num] = y_slot
			self.line_take(line_num, throughput)
		assert len(inputs) == len(step.inputs())

		# pick outputs
		outputs = {}
		# output slots count up from bottom, highest throughput at bottom
		outputs_in_order = sorted(step.outputs().items(), key=inout_order)
		for y_slot, (output, throughput) in zip(y_slots[::-1], outputs_in_order):
			# for now, always allocate a new line for each output, we can compress later.
			line_num = self.add_line(output, throughput)
			outputs[line_num] = (output, y_slot)
		assert len(outputs) == len(step.outputs())

		assert not (set(inputs.values()) & set([
			y_slot for output, y_slot in outputs.values()
		])), "inputs and outputs overlap:\ninputs: {}\noutputs: {}\nstep: {}".format(inputs, outputs, step)

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

		# do compactions in a greedy manner
		# and without trying to cross-use available space.
		# if you can't compact and have empty spots to your left, shift.

		prev_bus = list(self.bus)
		compactions = []
		shifts = []
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
					and line.throughput < line_limit(line.item, self.belt_type)
				)
			]
			if candidates:
				# Do a compaction.
				# pick least loaded first, then rightmost
				dest_pos, dest = min(candidates, key=lambda (i, line): (line.throughput, -i))
				limit = line_limit(dest.item, self.belt_type)
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
				continue

			# can't compact, consider shifting.
			shift_to = position
			# scan left until first non-None (or we hit edge)
			while shift_to > 0 and self.bus[shift_to - 1] is None:
				shift_to -= 1
			if shift_to != position:
				# Do a shift.
				self.bus[shift_to] = self.bus[position]
				self.line_take(position, source.throughput) # delete source line
				shifts.append((position, shift_to))
				position = shift_to - 1
				continue

			# no compact or shift, just step left and try again
			position -= 1


		if not compactions:
			raise ValueError("Could not compact bus any further")

		self.output.append(Compaction(
			bus = prev_bus,
			width = len(prev_bus), # bus width never grows here, only shrinks
			compactions = compactions,
			shifts = shifts,
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
