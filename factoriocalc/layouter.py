
from collections import namedtuple
from itertools import count

from . import primitives as primitive_types
from .beltmanager import Placement
from .util import is_liquid


Point = namedtuple('Point', ['x', 'y'])


PlacedPrimitive = namedtuple('', [
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

# start bus at 2 so we can have a line of power on left
BUS_START_X = 2


def layout(steps):
	"""Converts a list of Placements and Compactions into
	a collection of Primitives."""
	primitives = []
	prev_beacon_start = None
	prev_beacon_end = 0
	for step, base_y in zip(steps, count(3, 10)):
		p, beacon_start, beacon_end = layout_step(step, base_y)
		primitives += p
		# add beacon row above this step
		primitives += layout_beacons(
			base_y - 3,
			(min(beacon_start, prev_beacon_start) if prev_beacon_start is not None else beacon_start),
			max(beacon_end, prev_beacon_end),
		)
		prev_beacon_start = beacon_start
		prev_beacon_end = beacon_end
	return primitives


def layout_step(step, base_y):
	"""Layout given step with y value of the top of the processing area being base_y.
	Returns:
		primitives
		x position to start beacons at
		how long beacon rows above and below must extend
	"""
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
	If Placement:
	* Offramping inputs to the process
	* Onramping outputs to the bus below
	If Compaction:
	* Performing compactions and shifts
	Returns list of primitives.
	"""
	primitives = []

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
			place(primitives, bus_x, base_y-2, primitive_types.medium_pole)

	if isinstance(step, Placement):
		primitives += layout_in_outs(step, process_base_x, base_y)
	else:
		primitives += layout_compaction(step, base_y)
	return primitives


def layout_beacons(y, x_start, x_end):
	primitives = []
	for x in range(x_start, x_end + 3, 3):
		place(primitives, x, y, primitive_types.beacon)


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
	return [], base_x + 20 # TODO
