
import math
from collections import namedtuple

from . import primitives as primitive_types
from .beltmanager import Placement
from .util import is_liquid, Point


PlacedPrimitive = namedtuple('PlacedPrimitive', [
	'position', # Point of upper left corner
	'primitive', # Primitive to place
])

def place(list, x, y, primitive):
	list.append(PlacedPrimitive(Point(x, y), primitive))


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
# There's also another double-column for electric poles at the other end,
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


def flatten(primitives):
	"""Flatten a list of primitives to a list of entities"""
	entities = []
	for primitive in primitives:
		for entity in primitive.primitive:
			entities.append(entity._replace(
				position=Point(
					entity.position.x + primitive.position.x,
					entity.position.y + primitive.position.y,
				)
			))
	return entities


def layout(steps, final_bus):
	"""Converts a list of Placements and Compactions into
	a collection of Primitives."""
	# Our main concerns in this top-level function are intra-row details:
	# * Beacon widths (needs to cover the extremes of above and below rows)
	# * Insert a roboport+radar line every 10 rows,
	#   so that all entities are covered by construction area
	ROW_SIZE = 10 # each step is separated by 10 y-units
	ROWS_PER_ROBOPORT_AREA = 10 # roboports every 10 rows
	primitives = []
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
				primitives += layout_beacons(base_y - 3, prev_beacon_start, prev_beacon_end)
			# mark down where this roboport row will go for later, along with the relevant bus
			roboport_rows.append((step.bus, base_y))
			# adjust state for upcoming step
			prev_beacon_start = None
			prev_beacon_end = 0
			base_y += 3 + 4 # 3 for beacons, 4 for roboports
			steps_since_roboports = 0

		p, beacon_start, beacon_end = layout_step(step, base_y)
		primitives += p
		# add beacon row above this step
		primitives += layout_beacons(
			base_y - 3,
			(min(beacon_start, prev_beacon_start) if prev_beacon_start is not None else beacon_start),
			max(beacon_end, prev_beacon_end),
		)
		# advance state
		prev_beacon_start = beacon_start
		prev_beacon_end = beacon_end
		if beacon_end > max_width:
			max_width = beacon_end
		base_y += ROW_SIZE
		steps_since_roboports += 1

	# final beacon row, unless we ended in something weird (eg. roboport row)
	if prev_beacon_start is not None:
		primitives += layout_beacons(base_y - 3, prev_beacon_start, prev_beacon_end)
	# check if we need a final row of roboports so that last row is in range
	if steps_since_roboports > ROWS_PER_ROBOPORT_AREA / 2:
		roboport_rows.append((final_bus, base_y))

	# resolve roboport rows now that we know max width
	for bus, base_y in roboport_rows:
		primitives += layout_roboport_row(bus, base_y, max_width)

	return primitives


def layout_step(step, base_y):
	"""Layout given step with y value of the top of the processing area being base_y.
	Returns:
		primitives
		x position to start beacons at
		how long beacon rows above and below must extend
	"""
	# TODO include a roboport + radar in the working area, between bus and process
	# maybe also one on far left?
	# not enough coverage. alternate plan: every N rows is an infra row with roboports+radar,
	# that way it can cover whole X range.
	# if we also put a roboport every N/2 rows on the far left (extend bus start to match),
	# that connects them all up logistically, with the N rows giving full construction coverage.
	bus_width = step.width * 2
	padding = 3 - (bus_width + BUS_START_X) % 3
	process_base_x = bus_width + BUS_START_X + padding
	assert process_base_x % 3 == 0

	primitives = layout_bus(step, process_base_x, base_y)
	if isinstance(step, Placement):
		p, process_end = layout_process(step, process_base_x, base_y)
		primitives += p
	else:
		process_end = process_base_x

	return primitives, process_base_x, process_end


def layout_bus(step, process_base_x, base_y):
	"""Layout the bus area for the given step. This includes:
	* Running power along the bus
	* Running unused lines through to the step below
	* The left-most "infrastructure column" of power and roboports
	If Placement:
	* Offramping inputs to the process
	* Onramping outputs to the bus below
	If Compaction:
	* Performing compactions and shifts
	Returns list of primitives.
	"""
	primitives = []

	# infra column - roboport with big pole below it
	place(primitives, 0, base_y - 3, primitive_types.roboport)
	place(primitives, 2, base_y + 1, primitive_types.big_pole)

	# underpasses and power poles
	if isinstance(step, Placement):
		used = set(step.inputs.keys() + step.outputs.keys())
	else:
		used = set().union(*step.compactions).union(*step.shifts)
	for bus_pos, line in enumerate(step.bus):
		bus_x = BUS_START_X + 2 * bus_pos
		# unused lines get underpasses
		if bus_pos not in used and line is not None:
			primitive = primitive_types.underpass_pipe if is_liquid(line.item) else primitive_types.underpass_belt
			place(primitives, bus_x, base_y-2, primitive)
		# used, unused or blank, doesn't matter. Every 4 lines + the last line gets a pole.
		if bus_pos % 4 == 0 or bus_pos == len(step.bus) - 1:
			place(primitives, bus_x+1, base_y-2, primitive_types.medium_pole)

	if isinstance(step, Placement):
		primitives += layout_in_outs(step, process_base_x, base_y)
	else:
		primitives += layout_compaction(step, base_y)
	return primitives


def layout_beacons(y, x_start, x_end):
	primitives = []
	for x in range(x_start, x_end + 3, 3):
		place(primitives, x, y, primitive_types.beacon)
	return primitives


def layout_in_outs(step, process_base_x, base_y):
	"""Return the list of primitives needed to connect inputs and outputs
	from the bus to the process.
	"""
	return [] # TODO


def layout_compaction(step, base_y):
	"""Return the list of primitives needed to perform the compactions and shifts."""
	return [] # TODO


def layout_process(step, base_x, base_y):
	"""Choose the process primitives to use for this Placement and lay them out.
	Returns:
	* list of primitives
	* the end point of the process in the x axis, ie. base_x + width.
	"""
	return [], base_x # TODO


def layout_roboport_row(bus, base_y, width):
	"""Return primitives for a row of roboports covering an x region out to width,
	including the bus lines needed.
	"""
	primitives = []

	# Underpasses. Note these are shorter underpasses, without pumps.
	for bus_pos, line in enumerate(bus):
		if line is None:
			continue
		bus_x = BUS_START_X + 2 * bus_pos
		primitive = (
			primitive_types.roboport_underpass_pipe
			if is_liquid(line.item) else
			primitive_types.roboport_underpass_belt
		)
		place(primitives, bus_x, base_y-2, primitive)

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
		pole_x_pos = max(0, x_pos - LOGISTIC_AREA/2)
		place(primitives, pole_x_pos, base_y, primitive_types.big_pole)
		place(primitives, x_pos, base_y, primitive_types.roboport)
		# power pole for roboport, on its left
		place(primitives, x_pos - 2, base_y, primitive_types.big_pole)

	return primitives
