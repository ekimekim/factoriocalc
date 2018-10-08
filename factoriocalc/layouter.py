
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
# Visual: (b is beacon, e is power pole, p is process, X is not allowed, + is optional padding, _ is usable)
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
#   XXXXXXeeXXbbb
#   XXXXXXeeXXbbb

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
	prev_beacon_width = 0
	for step, base_y in zip(steps, count(3, 10)):
		p, beacon_width = layout_step(step, base_y)
		primitives += p
		# add beacon row above this step
		primitives += layout_beacons(base_y - 3, max(beacon_width, prev_beacon_width))
		prev_beacon_width = beacon_width
	return primitives


def layout_step(step, base_y):
	"""Layout given step with y value of the top of the processing area being base_y.
	Returns (primitives,  how long beacon rows above and below must extend)
	"""
	primitives = layout_bus(step, base_y)
	bus_width = step.width * 2
	elec_width = 2
	padding = 3 - (bus_width + elec_width) % 3
	process_base_x = bus_width + elec_width + padding
	assert process_base_x % 3 == 0
