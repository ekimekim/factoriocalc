
import math
import os
from fractions import Fraction

from . import primitives
from .beltmanager import Placement
from .processor import Processor
from .util import is_liquid, UP, RIGHT, DOWN, LEFT, Layout, line_limit


# Notes:
# Steps are layed out as beacon row, processing row, beacon row, etc.
# Processing rows are 7 high, and becaons are 3, so the pattern repeats every 10 units.
# The bus area available for a given step is from 2 above the processing area to 1 below.
# Between 1 and 3 columns of padding is then added to keep beacons aligned to a multiple of 3.
# We always add at least one padding as this is also the space we use to surface all the inputs/outputs.
# Power is passed to process via a medium electric poll on the rightmost bus line top.
# Visual: (b is beacon, e is substation, p is process, X is not allowed, + is optional padding, _ is usable)
#   XXXXXXXXXbbb
#   _____e+++bbb
#   ______+++bbb
#   ______+++ppp
#   ______+++ppp
#   ______+++ppp
#   ______+++ppp
#   ______+++ppp
#   ______+++ppp
#   ______+++ppp
#   ______+++bbb
#   XXXXXXXXXbbb
#   XXXXXXXXXbbb
# There's also another section for electric poles at the other end,
# this ensures rows are linked by power even if the bus width varies wildly.

# Note this implies the guarentees we give a processing step primitive:
# * Inputs arrive (on surface) at given y slots
# * Outputs are expected (on surface) at given y slots
# * The area will have beacons above and below, but not nessecarily extending past
#   the edges, so care must be taken to have buildings fully covered, they must be off the edge a little.
# * Power is provided from a medium electric poll offset from the top-left corner by (2-4, 2),
#   OR offset from the bottom-left corner by (2-4, -2).
#   This is needed because if the bus shrinks this step, the next step's beacons may extend further left
#   than your base x, so the lower pole won't be there. But if the bus expands this step, the opposite is true.
#   Since the bus can't shrink AND expand simultaniously, at least one will be present.

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

# At the end of each y-slot, we have 1-3 tiles of padding in which to surface
# our inputs and outputs.
# If there's one tile, it's easy - just surface.
# If there's two/three tiles, then for belts it's easy - surface then 1-2 belts.
# However, a problem arises with pipes, since they might try to join onto pipes
# above or below them. We solve this for 3 tiles by going surface/underground/surface.
# For 2 tiles, we make use of the fact that underground pipes can go 9 tiles underground,
# even though all our assumptions below treat pipes and belts as both having an 8-tile limit.
# We make use of the extra tile to just do blank, then surface.

# start bus at 4 so we can have a line of power and roboports on left
BUS_START_X = 4


def layout(beacon_module, steps, final_bus):
	"""Converts a list of Placements and Compactions into
	a collection of Primitives."""
	# Our main concerns in this top-level function are intra-row details:
	# * Beacon widths (needs to cover the extremes of above and below rows)
	# * Insert a roboport+radar line every 10 rows,
	#   so that all entities are covered by construction area
	# * Handling oversize rows
	STEP_SIZE = 10 # does not include oversize
	ROBOPORT_AREA_SIZE = 110 - 4 # Construction area is 110, but roboport rows themselves are 4 tall.
	                             # So we can have 106 units between roboport rows.
	layout = Layout('root')
	roboport_rows = [] # list of (bus, y pos)
	prev_beacon_start = None
	prev_beacon_end = 0
	base_y = 3 # leave room for top beacon row before first row
	height_since_roboports = ROBOPORT_AREA_SIZE / 2 # since there's no roboports above, start "halfway" through a roboport section
	height_since_roboports += 1 # ensure top beacon row is included in first roboport section
	max_width = 0
	oversize = 0
	for step in steps:
		# If previous step was oversize, extend the bus to compensate.
		if oversize:
			layout.place(0, base_y, layout_bus_extension(step.bus, oversize))
			base_y += oversize
			height_since_roboports += oversize

		# Step layout doesn't actually depend on exactly where step will be placed,
		# and lets us work out width and height immediately.
		# Note oversize is carried across to next loop iteration.
		step_layout, beacon_start, beacon_end, oversize = layout_step(step)

		# Check if we need roboport row, ie. if this step would extend past the end of roboport area.
		if height_since_roboports + STEP_SIZE + oversize > ROBOPORT_AREA_SIZE:
			# add beacons for bottom of row above if needed
			if prev_beacon_start is not None:
				layout.place(prev_beacon_start, base_y - 3, layout_beacons(beacon_module, prev_beacon_end - prev_beacon_start))
			# mark down where this roboport row will go for later, along with the relevant bus
			roboport_rows.append((step.bus, base_y))
			# adjust state for upcoming step
			prev_beacon_start = None
			prev_beacon_end = 0
			base_y += 3 + 4 # 3 for beacons, 4 for roboports
			height_since_roboports = 3 # to cover next row of beacons

		# ok, now we know where this step is going, place it
		layout.place(0, base_y, step_layout)
		# add beacon row above this step
		row_start = min(beacon_start, prev_beacon_start) if prev_beacon_start is not None else beacon_start
		row_end = max(beacon_end, prev_beacon_end)
		layout.place(row_start, base_y - 3, layout_beacons(beacon_module, row_end - row_start))
		# advance state
		prev_beacon_start = beacon_start
		prev_beacon_end = beacon_end
		if beacon_end > max_width:
			max_width = beacon_end
		base_y += STEP_SIZE
		height_since_roboports += STEP_SIZE

	# check if last row was oversize
	if oversize:
		layout.place(0, base_y, layout_bus_extension(final_bus, oversize))
		base_y += oversize
		height_since_roboports += oversize

	# final beacon row, unless we ended in something weird (eg. roboport row)
	if prev_beacon_start is not None:
		layout.place(prev_beacon_start, base_y - 3, layout_beacons(beacon_module, prev_beacon_end - prev_beacon_start))
	# check if we need a final row of roboports so that last row is in range
	if height_since_roboports > ROBOPORT_AREA_SIZE / 2:
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
		how long beacon rows above and below must extend (0 if beacons not needed)
		how much the step is oversize by
	"""
	layout = Layout(str(step))
	bus_width = step.width * 2
	# We need at least one extra column in addition to the bus, in order to surface all
	# our input/output lines. This space can also be two or three columns in order to
	# line up the process with the beacon rows. We call this space our "padding".
	padding = 3 - (bus_width + BUS_START_X) % 3
	if padding == 0:
		padding = 3
	process_base_x = bus_width + BUS_START_X + padding
	assert process_base_x % 3 == 0

	layout.place(0, 0, layout_bus(step, padding, process_base_x))
	if isinstance(step, Placement):
		process_layout, process_width, oversize = layout_process(step)
		layout.place(process_base_x, 0, process_layout)
		process_end = process_width + process_base_x
	else:
		process_end = 0
		oversize = 0

	return layout, process_base_x, process_end, oversize


def layout_bus_extension(bus, size):
	"""Layout an extension that carries the bus SIZE units downwards,
	to bridge the gap between the previous step's oversize layout and this step."""
	layout = Layout("bus extension")
	for bus_pos, line in enumerate(bus):
		if line is None:
			continue
		bus_x = BUS_START_X + 2 * bus_pos
		primitive_fn = primitives.pipe if is_liquid(line.item) else primitives.belt
		primitive = primitive_fn(DOWN, size)
		layout.place(bus_x, -2, primitive)
	return layout


def layout_bus(step, padding, process_base_x):
	"""Layout the bus area for the given step. This includes:
	* Running power along the bus
	* Running unused lines through to the step below
	* The left-most "infrastructure column" of power and roboports
	If Placement:
	* Offramping inputs to the process
	* Onramping outputs to the bus below
	If Compaction:
	* Performing compactions and shifts
	Special case:
		Because pipe underpasses with a pump encroach on y_slot 0,
		we also get a list of "forbidden" bus indexes where pumps can't go,
		because the inout on that row needed to put something there.
	Returns layout.
	"""
	layout = Layout("bus")

	# infra column - roboport with big pole below it
	layout.place(0, -3, primitives.roboport)
	layout.place(2, 1, primitives.big_pole)

	# input/output lines, or compaction lines
	if isinstance(step, Placement):
		in_outs, forbidden_pump_indexes = layout_in_outs(step, padding, process_base_x)
		layout.place(0, 0, in_outs)
	else:
		layout.place(0, 0, layout_compaction(step))
		forbidden_pump_indexes = []

	# underpasses and power poles
	if isinstance(step, Placement):
		used = set(step.inputs.keys() + step.outputs.keys())
	else:
		used = set().union(*step.compactions).union(*step.shifts)
	for bus_pos, line in enumerate(step.bus):
		bus_x = BUS_START_X + 2 * bus_pos
		# unused lines get underpasses
		if bus_pos not in used and line is not None:
			if not is_liquid(line.item):
				primitive = primitives.underpass_belt
			elif bus_pos in forbidden_pump_indexes:
				primitive = primitives.underpass_pipe_no_pump
			else:
				primitive = primitives.underpass_pipe
			layout.place(bus_x, -2, primitive)
		# used, unused or blank, doesn't matter. Every 4 lines + the last line gets a pole.
		if bus_pos % 4 == 0 or bus_pos == len(step.bus) - 1:
			layout.place(bus_x + 1, -2, primitives.medium_pole)

	return layout


def layout_beacons(beacon_module, width):
	layout = Layout("beacons")
	for x in range(int(math.ceil(width / 3.))):
		layout.place(3*x, 0, primitives.beacon(beacon_module))
	return layout


def layout_in_outs(step, padding, process_base_x):
	"""Return the parts needed to connect inputs and outputs
	from the bus to the process. Also returns a list of bus indexes
	which y_slot 0 is occupying, so that layout_bus() can avoid putting pumps there.
	"""
	# Each in-out has three parts:
	# * The actual split or join component, which occupies
	#   the area (line_x, -2) to (line_x + 1, 8)
	# * The underground line running horizontally from that component to the edge of the process area,
	#   which must run on the assigned y_slot and go under any
	#   split/join components between it and the process.
	#   It comes up for air at least every 10 tiles (ie. max 8 underground).
	# * The padding, where we surface.
	# Note: Since we can only go under 8 tiles max, it may end up that >5 split/joins back-to-back
	# prevent a 5th inout from running under them. But this is extremely unlikely, so we're just
	# going to die if we encounter it and hope we don't.

	layout = Layout("in-outs")
	forbidden_pump_indexes = []

	# Set up some vars for horiz_line
	used = set(step.inputs.keys() + step.outputs.keys()) # bus indexes that have an on/off ramp
	target_index = (process_base_x - padding - BUS_START_X) / 2

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
		# We keep trying to go 5 indexes (10 tiles) at a time, if we're blocked
		# then we walk back left until we find a placable position.
		# We stop when we're in range of process_base_x.
		while bus_index + 5 < target_index:
			for delta in range(5, 0, -1):
				if bus_index + delta not in used:
					bus_index += delta
					place_at_index(bus_index)
					if y_slot == 0:
						forbidden_pump_indexes.append(bus_index)
					break
			else:
				raise ValueError((
					"Failed to place horizontal line for input or output - "
					"too many contiguous on/offramps from {} to {} "
					"means we can't cross it with an underground line."
				).format(bus_index + 1, bus_index + 5))

	def surfacing(item, orientation):
		# what's our into/out of ground primitive? a pipe or a belt, and for belt which one?
		sub_layout = Layout('padding row')
		if is_liquid(item):
			right_pipe = primitives.entity(primitives.E.underground_pipe, RIGHT)
			if padding == 1:
				# easy case, just surface
				sub_layout.place(0, 0, right_pipe)
			elif padding == 2:
				# same but place it one to the right
				sub_layout.place(1, 0, right_pipe)
			else:
				# go up, then down, then up again
				sub_layout.place(0, 0, primitives.pipe_surface(RIGHT))
				sub_layout.place(2, 0, right_pipe)
		else:
			# first, surface
			sub_layout.place(0, 0,
				primitives.belt_from_ground(RIGHT) if orientation == RIGHT
				else primitives.belt_to_ground(LEFT)
			)
			# then fill remaining space with belts
			for i in range(1, padding):
				sub_layout.place(i, 0, primitives.belt(orientation, 1))
		return sub_layout

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
		# place the surfacing in the padding area
		layout.place(BUS_START_X + 2 * target_index, y_slot, surfacing(line.item, RIGHT))

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
		# place the surfacing in the padding area
		layout.place(BUS_START_X + 2 * target_index, y_slot, surfacing(item, LEFT))

	return layout, forbidden_pump_indexes


def layout_compaction(step):
	"""Return the layout needed to perform the compactions and shifts."""
	layout = Layout("compaction")
	bus_x = lambda index: BUS_START_X + 2 * index

	# This is fairly simple for now, and any additional capabilities need to be
	# added both here and in belt manager.
	# We assume a compaction or shift has full use of space y=(1, 7) between the two lines
	# in question.

	# compactions
	for left, right in step.compactions:
		right_ends = step.bus[left].throughput + step.bus[right].throughput <= line_limit(step.bus[left].item)
		liquid = is_liquid(step.bus[left].item)
		pipe_or_belt = primitives.pipe if liquid else primitives.belt
		# right top part
		layout.place(bus_x(right), -2, primitives.pipe_to_left if liquid else primitives.belt_to_left)
		# right to left line
		line_right = bus_x(right) - 1
		line_left = bus_x(left) + 2
		layout.place(line_right, 1, pipe_or_belt(LEFT, line_right - line_left + 1))
		# left part
		if liquid:
			if not right_ends:
				# TODO. Needs a pump and no return line.
				raise NotImplementedError("Compaction with overflow for fluids is not implemented")
			primitive = primitives.compact_pipe
		else:
			primitive = primitives.compact_belts if right_ends else primitives.compact_belts_with_overflow
		layout.place(bus_x(left), -2, primitive)
		# if no overflow, we're done
		if right_ends:
			continue
		# overflow left back to right
		layout.place(line_left, 6, pipe_or_belt(RIGHT, line_right - line_left + 1))
		# right bottom part
		layout.place(bus_x(right), 6, primitives.pipe_from_left if liquid else primitives.belt_from_left)

	# shifts. note we assume source is to the right of dest
	for right, left in step.shifts:
		liquid = is_liquid(step.bus[right].item)
		pipe_or_belt = primitives.pipe if liquid else primitives.belt
		# right part
		layout.place(bus_x(right), -2, primitives.pipe_to_left if liquid else primitives.belt_to_left)
		# right to left line
		line_right = bus_x(right) - 1
		line_left = bus_x(left) + 1
		layout.place(line_right, 1, pipe_or_belt(LEFT, line_right - line_left + 1))
		# left down
		layout.place(bus_x(left), 1, pipe_or_belt(DOWN, 7))

	return layout


def layout_process(step):
	"""Choose the process primitives to use for this Placement and lay them out.
	Returns:
	* layout
	* the end point of the process in the x axis, ie. the width.
	* how much the process is oversize by (normally 0)
	"""
	def classify_items(in_or_out):
		liquids, belts, halfbelts = 0, 0, 0
		for item, throughput in in_or_out.items():
			if is_liquid(item):
				liquids += 1
			elif throughput <= line_limit(item) / 2:
				halfbelts += 1
			else:
				belts += 1
		return liquids, belts, halfbelts
	try:
		processor = Processor.find_processor(
			step.process.recipe.building.name,
			classify_items(step.process.inputs()),
			classify_items(step.process.outputs()),
		)
	except ValueError:
		if os.environ.get("FACTORIOCALC_IGNORE_MISSING_PROCESS", ""):
			# Silently ignore missing processor and provide dummy values
			return Layout("dummy processor"), 9, 0
		# Otherwise let it raise
		raise
	return processor.layout(step)


def layout_roboport_row(bus, width):
	"""Return layout for a row of roboports covering an x region out to width,
	including the bus lines needed.
	"""
	layout = Layout("roboports")


	# Underpasses. Note these are shorter underpasses, without pumps.
	for bus_pos, line in enumerate(bus):
		bus_x = BUS_START_X + 2 * bus_pos
		# Every 4th line + the last line gets a power pole, in order to power prior step if needed
		if bus_pos % 4 == 0 or bus_pos == len(bus) - 1:
			layout.place(bus_x + 1, -2, primitives.medium_pole)
		# No need for underpass on gaps
		if line is None:
			continue
		# Place underpass
		primitive = (
			primitives.roboport_underpass_pipe
			if is_liquid(line.item) else
			primitives.roboport_underpass_belt
		)
		layout.place(bus_x, -2, primitive)

	# Roboport areas
	LOGISTIC_AREA = 50
	CONSTRUCT_AREA = 110

	# Main roboport area. Put a roboport and radar (and accompanying power) every LOGISTIC_AREA,
	# starting at LOGISTIC_AREA so it links with infra column roboports above and below.
	# Since power poles only reach 30 tiles and logistic area is 50 tiles, put a large power pole
	# between each.

	# First roboport is placed at LOGISTIC_AREA, and so covers construction out to:
	#	LOGISTIC_AREA + CONSTRUCT_AREA/2
	# Each extra roboport adds LOGISTIC_AREA to the total reach, so final reach is:
	#	reach = CONSTRUCT_AREA/2 + num_roboports * LOGISTIC_AREA
	# Rearranging to calculate required roboports:
	#	num_roboports = (reach - CONSTRUCT_AREA/2) / LOGISTIC_AREA
	# Then we take ceil of that since we need an integer.
	# We always need at least 1 to ensure radar coverage.
	# XXX Future work: In this case we should just omit the roboport row entirely.
	num_roboports = int(math.ceil(
		Fraction(width - CONSTRUCT_AREA/2) / LOGISTIC_AREA
	))

	for i in range(num_roboports):
		# note x pos is the pos we said above, but -2 because that's measuring from the center,
		# not the top-left.
		x_pos = (i+1) * LOGISTIC_AREA - 2
		# place pole between this and previous roboport (or between first roboport and infra column)
		pole_x_pos = x_pos - LOGISTIC_AREA/2
		layout.place(pole_x_pos, 0, primitives.big_pole)
		layout.place(x_pos, 0, primitives.roboport)
		# power pole for roboport, on its left
		layout.place(x_pos - 2, 0, primitives.big_pole)
		# and the radar to the power pole's left
		layout.place(x_pos - 5, 0, primitives.radar)

	return layout
