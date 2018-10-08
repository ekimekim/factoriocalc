
from collections import namedtuple
from itertools import count


Point = namedtuple('Point', ['x', 'y'])


PlacedPrimitive = namedtuple('', [
	'position', # Point of upper left corner
	'primitive', # Primitive to place
])


# Notes:
# Steps are layed out as beacon row, processing row, beacon row, etc.
# Processing rows are 7 high, and becaons are 3, so the pattern repeats every 10 units.
# The bus area available for a given step is from 2 above the processing area to 1 below.
# The double-column between beacons and bus is for power.
# Up to 2 columns of padding is then added to keep beacons aligned to a multiple of 3.
# Visual: (b is beacon, e is substation, p is process, X is not allowed, + is optional padding, _ is usable)
#   XXXXXXXXXXbbb
#   ______ee++bbb
#   ______ee++bbb
#   ________++ppp
#   ________++ppp
#   ________++ppp
#   ________++ppp
#   ________++ppp
#   ________++ppp
#   ________++ppp
#   ________++bbb
#   XXXXXXXXXXbbb
#   XXXXXXXXXXbbb
# There's also another double-column for electric poles at the other end,
# this ensures rows are linked by power even if the bus width varies wildly.

# Note this implies the guarentees we give a processing step primitive:
# * Inputs arrive at given y slots
# * Outputs are expected at given y slots
# * The area will have beacons above and below, but not nessecarily extending past
#   the edges, so care must be taken to have buildings fully covered, they must be off the edge a little.
# * Power is provided from 

# Each line in the bus is seperated by a 1 unit gap.
# In general each action involving a line in the bus area should keep to its own column
# plus the one to the right, to avoid issues if two lines are back-to-back.
# Lines that aren't being touched this step are easy - they go underground in the top row
# and come back up at the bottom row. This keeps the space between free for cross traffic.
# Every 4th line must include a medium power pole to carry power along the bus for pumps.
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
	elec_width = 2 + 2 # 2 at start + 2 at end
	padding = 3 - (bus_width + elec_width) % 3
	process_base_x = bus_width + elec_width + padding
	assert process_base_x % 3 == 0

	primitives = layout_bus(step, process_base_x, base_y)
	if isinstance(step, Placement):
		p, process_end = layout_process(step, process_base_x, base_y)
		primitives += p
	else:
		process_end = process_base_x

	return primitives, process_base_x, process_end


def layout_bus(step, process_base_x, base_y):

