
import math

from . import primitives
from .beltmanager import Placement
from .util import is_liquid, UP, RIGHT, DOWN, LEFT, Layout


# Notes:
# Steps are layed out as beacon row, processing row, beacon row, etc.
# Processing rows are 7 high, and becaons are 3, so the pattern repeats every 10 units.
# The bus area available for a given step is from 2 above the processing area to 1 below.
# Up to 2 columns of padding is then added to keep beacons aligned to a multiple of 3.
# Power is passed to process via a medium electric poll on the rightmost bus line top.
# Visual: (b is beacon, e is substation, p is process, X is not allowed, + is optional padding, _ is usable)
#   XXXXXXXXbbb
#   _____e++bbb
#   ______++bbb
#   ______++ppp
#   ______++ppp
#   ______++ppp
#   ______++ppp
#   ______++ppp
#   ______++ppp
#   ______++ppp
#   ______++bbb
#   XXXXXXXXbbb
#   XXXXXXXXbbb
# There's also another section for electric poles at the other end,
# this ensures rows are linked by power even if the bus width varies wildly.

# Note this implies the guarentees we give a processing step primitive:
# * Inputs arrive at given y slots
# * Outputs are expected at given y slots
# * The area will have beacons above and below, but not nessecarily extending past
#   the edges, so care must be taken to have buildings fully covered, they must be off the edge a little.
# * Power is provided from a medium electric poll offset from the top-left corner by (1-3, 2)

# Each line in the bus is seperated by a 1 unit gap.
# In general each action involving a line in the bus area should keep to its own column
# plus the one to the right, to avoid issues if two lines are back-to-back.
# Lines that aren't being touched this step are easy - they go underground in the top row
# and come back up at the bottom row. This keeps the space between free for cross traffic.
# Every 4th line (plus always the last) must include a medium power pole to carry power along the bus.
# Liquids are pumped each step.
# So a belt that isn't being used this step looks like this (left is top):
#   e
#   >        <
# Where e may or may not contain a pole.
# A liquid pipe that isn't being used:
#   e
#   pp>      <
# where pp is a pump.
# Note y slots 1-6 are still free.
# A pipe or belt which is being used has this space to work with:
#   e_________
#   __________
# This gets in the way of the y-slot for 2 tiles, but we assume there'll never be
# more than 4 of these in a row, so a blue underground belt can still pass under.

# start bus at 4 so we can have a line of power and roboports on left
BUS_START_X = 4


def layout(steps, final_bus):
	"""Converts a list of Placements and Compactions into
	a collection of Primitives."""
	# Our main concerns in this top-level function are intra-row details:
	# * Beacon widths (needs to cover the extremes of above and below rows)
	# * Insert a roboport+radar line every 10 rows,
	#   so that all entities are covered by construction area
	ROW_SIZE = 10 # each step is separated by 10 y-units
	ROWS_PER_ROBOPORT_AREA = 10 # roboports every 10 rows
	layout = Layout('root')
	roboport_rows = [] # list of (bus, y pos)
	prev_beacon_start = None
	prev_beacon_end = 0
	base_y = 3 # leave room for top beacon row before first row
	steps_since_roboports = ROWS_PER_ROBOPORT_AREA / 2 # since there's no roboports above, start "halfway" through a roboport section
	max_width = 0
	for step in steps:
		# check if we need roboport row
		if steps_since_roboports >= ROWS_PER_ROBOPORT_AREA:
			assert steps_since_roboports == ROWS_PER_ROBOPORT_AREA
			# add beacons for bottom of row above if needed
			if prev_beacon_start is not None:
				layout.place(prev_beacon_start, base_y - 3, layout_beacons(prev_beacon_end - prev_beacon_start))
			# mark down where this roboport row will go for later, along with the relevant bus
			roboport_rows.append((step.bus, base_y))
			# adjust state for upcoming step
			prev_beacon_start = None
			prev_beacon_end = 0
			base_y += 3 + 4 # 3 for beacons, 4 for roboports
			steps_since_roboports = 0

		step_layout, beacon_start, beacon_end = layout_step(step)
		layout.place(0, base_y, step_layout)
		# add beacon row above this step
		row_start = min(beacon_start, prev_beacon_start) if prev_beacon_start is not None else beacon_start
		row_end = max(beacon_end, prev_beacon_end)
		layout.place(row_start, base_y - 3, layout_beacons(row_end - row_start))
		# advance state
		prev_beacon_start = beacon_start
		prev_beacon_end = beacon_end
		if beacon_end > max_width:
			max_width = beacon_end
		base_y += ROW_SIZE
		steps_since_roboports += 1

	# final beacon row, unless we ended in something weird (eg. roboport row)
	if prev_beacon_start is not None:
		layout.place(prev_beacon_start, base_y - 3, layout_beacons(prev_beacon_end - prev_beacon_start))
	# check if we need a final row of roboports so that last row is in range
	if steps_since_roboports > ROWS_PER_ROBOPORT_AREA / 2:
		roboport_rows.append((final_bus, base_y))

	# resolve roboport rows now that we know max width
	for bus, base_y in roboport_rows:
		layout.place(0, base_y, layout_roboport_row(bus, max_width))

	return layout


def layout_step(step):
	"""Layout given step with y value of the top of the processing area being y=0.
	Returns:
		layout
		x position to start beacons at
		how long beacon rows above and below must extend
	"""
	layout = Layout(str(step))
	bus_width = step.width * 2
	padding = 3 - (bus_width + BUS_START_X) % 3
	process_base_x = bus_width + BUS_START_X + padding
	assert process_base_x % 3 == 0

	layout.place(0, 0, layout_bus(step, process_base_x))
	if isinstance(step, Placement):
		process_layout, process_width = layout_process(step)
		layout.place(process_base_x, 0, process_layout)
	else:
		process_width = 0
	process_end = process_width + process_base_x

	return layout, process_base_x, process_end


def layout_bus(step, process_base_x):
	"""Layout the bus area for the given step. This includes:
	* Running power along the bus
	* Running unused lines through to the step below
	* The left-most "infrastructure column" of power and roboports
	If Placement:
	* Offramping inputs to the process
	* Onramping outputs to the bus below
	If Compaction:
	* Performing compactions and shifts
	Returns layout.
	"""
	layout = Layout("bus")

	# infra column - roboport with big pole below it
	layout.place(0, -3, primitives.roboport)
	layout.place(2, 1, primitives.big_pole)

	# underpasses and power poles
	if isinstance(step, Placement):
		used = set(step.inputs.keys() + step.outputs.keys())
	else:
		used = set().union(*step.compactions).union(*step.shifts)
	for bus_pos, line in enumerate(step.bus):
		bus_x = BUS_START_X + 2 * bus_pos
		# unused lines get underpasses
		if bus_pos not in used and line is not None:
			primitive = primitives.underpass_pipe if is_liquid(line.item) else primitives.underpass_belt
			layout.place(bus_x, -2, primitive)
		# used, unused or blank, doesn't matter. Every 4 lines + the last line gets a pole.
		if bus_pos % 4 == 0 or bus_pos == len(step.bus) - 1:
			layout.place(bus_x + 1, -2, primitives.medium_pole)

	if isinstance(step, Placement):
		layout.place(0, 0, layout_in_outs(step, process_base_x))
	else:
		layout.place(0, 0, layout_compaction(step))
	return layout


def layout_beacons(width):
	layout = Layout("beacons")
	for x in range(int(math.ceil(width / 3))):
		layout.place(3*x, 0, primitives.beacon)
	return layout


def layout_in_outs(step, process_base_x):
	"""Return the parts needed to connect inputs and outputs
	from the bus to the process.
	"""
	# Each in-out has two parts:
	# * The actual split or join component, which occupies
	#   the area (line_x, -2) to (line_x + 1, 8)
	# * The line running horizontally from that component to the edge of the process area,
	#   which must run on the assigned y_slot and go under any
	#   split/join components between it and the process.
	# Note: Since we can only go under 8 tiles max, it may end up that >4 split/joins back-to-back
	# prevent a 5th inout from running under them. But this is extremely unlikely, so we're just
	# going to die if we encounter it and hope we don't.

	layout = Layout("in-outs")

	# Set up some vars for horiz_line
	used = set(step.inputs.keys() + step.outputs.keys()) # bus indexes that have an on/off ramp
	# Some notes on padding. There are 3 cases:
	#  no padding - no problem
	#  two padding - extra double column is treated as extra bus line, no problem
	#  one padding - special case. We need to treat it as an occupied bus line,
	#  otherwise we might try to put a surface there, which will collide with the left-most
	#  column of the process area.
	target_index = (process_base_x - BUS_START_X) / 2
	if (process_base_x - BUS_START_X) % 2 == 1:
		# uneven padding, forbid the last "line"
		used.add(target_index)
		target_index += 1

	def horiz_line(item, bus_index, y_slot, orientation):
		# Assumes up-line at bus_index is already placed.
		# Runs from left to right working out valid positions.
		primitive_fn = primitives.pipe_surface if is_liquid(item) else primitives.belt_surface
		primitive = primitive_fn(orientation)
		place_at_index = lambda i: layout.place(
			BUS_START_X + 2 * i + (1 if orientation == LEFT else 0),
			y_slot,
			primitive,
		)
		# We keep trying to go 4 indexes (8 tiles) at a time, if we're blocked
		# then we walk back left until we find a placable position.
		# We stop when we're in range of process_base_x.
		while bus_index + 4 < target_index:
			for delta in range(4, 0, -1):
				if bus_index + delta not in used:
					bus_index += delta
					place_at_index(bus_index)
					break
			else:
				raise ValueError("Failed to place horizontal line")

	# inputs (off-ramps and right-running lines)
	for bus_index, y_slot in step.inputs.items():
		bus_x = BUS_START_X + 2 * bus_index
		line = step.bus[bus_index]
		# check if we're consuming all the input
		line_ends = line.throughput == step.process.inputs()[line.item]
		# map from (liquid, ends) to primitive func to call as f(y_slot)
		primitive = {
			(False, False): primitives.belt_offramp,
			(False, True): primitives.belt_offramp_all,
			(True, False): primitives.pipe_ramp,
			(True, True): primitives.pipe_offramp_all,
		}[is_liquid(line.item), line_ends](y_slot)
		# place the off-ramp
		layout.place(bus_x, -2, primitive)
		# run the line right to the end of the bus
		horiz_line(line.item, bus_index, y_slot, RIGHT)

	# outputs (on-ramps and left-running lines)
	for bus_index, (item, y_slot) in step.outputs.items():
		bus_x = BUS_START_X + 2 * bus_index
		# XXX later, support joining with existing line instead of only adding new
		primitive = (
			primitives.pipe_onramp_all(7 - y_slot)
			if is_liquid(item) else
			primitives.belt_onramp_all(7 - y_slot)
		)
		# place the on-ramp
		layout.place(bus_x, y_slot, primitive)
		# run the line left from end of bus to here
		horiz_line(item, bus_index, y_slot, LEFT)

	return layout


def layout_compaction(step):
	"""Return the layout needed to perform the compactions and shifts."""
	return Layout("compaction TODO") # TODO


def layout_process(step):
	"""Choose the process primitives to use for this Placement and lay them out.
	Returns:
	* layout
	* the end point of the process in the x axis, ie. the width.
	"""
	return Layout("process TODO"), 0 # TODO


def layout_roboport_row(bus, width):
	"""Return layout for a row of roboports covering an x region out to width,
	including the bus lines needed.
	"""
	layout = Layout("roboports")

	# Underpasses. Note these are shorter underpasses, without pumps.
	for bus_pos, line in enumerate(bus):
		if line is None:
			continue
		bus_x = BUS_START_X + 2 * bus_pos
		primitive = (
			primitives.roboport_underpass_pipe
			if is_liquid(line.item) else
			primitives.roboport_underpass_belt
		)
		layout.place(bus_x, -2, primitive)

	# Roboport areas
	LOGISTIC_AREA = 50
	CONSTRUCT_AREA = 110

	# Main roboport area. Put a roboport (and accompanying power) every LOGISTIC_AREA,
	# starting at LOGISTIC_AREA/2 so it links with infra column roboports above and below.
	# Since power poles only reach 30 tiles and logistic area is 50 tiles, put a large power pole
	# between each.

	# First roboport is placed at LOGISTIC_AREA/2, and so covers construction out to:
	#	LOGISTIC_AREA/2 + CONSTRUCT_AREA/2
	# Each extra roboport adds LOGISTIC_AREA to the total reach, so final reach is:
	#	reach = LOGISTIC_AREA/2 + CONSTRUCT_AREA/2 + num_roboports * LOGISTIC_AREA
	# Rearranging to calculate required roboports:
	#	num_roboports = (reach - LOGISTIC_AREA/2 - CONSTRUCT_AREA/2) / LOGISTIC_AREA
	# Then we take ceil of that since we need an integer.
	num_roboports = max(1, int(math.ceil(
		(width - LOGISTIC_AREA/2 - CONSTRUCT_AREA/2) / LOGISTIC_AREA
	)))

	for i in range(num_roboports):
		# note x pos is the pos we said above, but -2 because that's measuring from the center,
		# not the top-left.
		x_pos = LOGISTIC_AREA/2 - 2 + i * LOGISTIC_AREA
		# place left-most pole at 2 to align with other rows
		pole_x_pos = max(2, x_pos - LOGISTIC_AREA/2)
		layout.place(pole_x_pos, 0, primitives.big_pole)
		layout.place(x_pos, 0, primitives.roboport)
		# power pole for roboport, on its left
		layout.place(x_pos - 2, 0, primitives.big_pole)

	return layout
