# -encoding: utf-8-


from collections import namedtuple

from .util import Point, UP, RIGHT, DOWN, LEFT


def orientation_to_vector(orientation):
	"""Return a Point with the unit vector for the direction given,
	eg. up is (0, -1).
	"""
	return {
		UP: Point(0, -1),
		RIGHT: Point(1, 0),
		DOWN: Point(0, 1),
		LEFT: Point(-1, 0),
	}[orientation]


Entity = namedtuple('Entity', [
	'name',
	'position', # Point
	'orientation', # 0-3, 0 is 'up', 1 is 'right', etc.
	'attrs', # arbitrary extra attributes {attr: value}, should match Entity keys in blueprint format
])

def entity(x, y, name, orientation=None, **attrs):
	return Entity(name, Point(x, y), orientation, attrs)


# A mapping from easy internal names to official names
class _Entities(object):
	# guessed
	underground_pipe = 'underground pipe'
	pipe = 'pipe'
	pump = 'pump'
	belt = 'express belt'
	underground_belt = 'express underground belt'
	medium_pole = 'medium-electric-pole'
	big_pole = 'big-electric-pole'
	beacon = 'beacon'
	inserter = 'stack-inserter'
	assembler = 'assembly-machine-3'
	splitter = 'express belt splitter'
	roboport = 'roboport'

	# checked
	speed_module = 'speed-module-3'

E = _Entities()


# Primitives, which are lists of Entity.


# A bus pipe with pump, plus underground pipe going under the working area
underpass_pipe = [
	entity(0, 0, E.pump, DOWN),
	entity(0, 2, E.underground_pipe, DOWN),
	entity(0, 9, E.underground_pipe, UP),
]

# A bus underground belt going under the working area
underpass_belt = [
	entity(0, 0, E.underground_belt, DOWN),
	entity(0, 9, E.underground_belt, UP),
]


# A bus underground pipe for going under a roboport row
roboport_underpass_pipe = [
	entity(0, 0, E.underground_pipe, DOWN),
	entity(0, 6, E.underground_pipe, UP),
]


# A bus underground belt for going under a roboport row
roboport_underpass_belt = [
	entity(0, 0, E.underground_belt, DOWN),
	entity(0, 6, E.underground_belt, UP),
]


# Run a length of belt in the specified direction for specified length
def belt(base_x, base_y, orientation, length):
	delta = orientation_to_vector(orientation)
	return [
		entity(base_x + i * delta.x, base_y + i * delta.y, E.belt, orientation)
		for i in range(length)
	]


# An underground belt "coming up for air", ie. an output then another input
# in the same direction immediately.
def belt_surface(orientation):
	delta = orientation_to_vector(orientation)
	return [
		entity(0, 0, E.underground_belt, orientation),
		entity(delta.x, delta.y, E.underground_belt, orientation),
	]


# As belt_surface but for pipes.
def pipe_surface(orientation):
	delta = orientation_to_vector(orientation)
	return [
		entity(0, 0, E.underground_pipe, orientation),
		entity(delta.x, delta.y, E.underground_pipe, orientation),
	]


# Take items off a belt onto given y slot, though the belt continues.
# Expects a belt input from above (0,0), a belt output below (0,9)
# and a underground belt output right of (1, y_slot).
# Should be placed at y=-3 relative to y slots.
# Note the splitter preferences the process, and only the remainder continues.
# Looks like this:
#  v
#  ...
#  v
#  Ss
#  v∪
#  >⊃   y_slot
#   ∩
#  v<
#  v
#  ...
#  v
def belt_offramp(y_slot):
	return (
		belt(0, 0, DOWN, y_slot)
		+ [
			entity(0, y_slot, E.splitter, DOWN, output_priority='right'),
			entity(0, y_slot + 1, E.belt, DOWN),
			entity(1, y_slot + 1, E.underground_belt, DOWN),
			entity(0, y_slot + 2, E.belt, RIGHT),
			entity(1, y_slot + 2, E.underground_belt, RIGHT),
			entity(1, y_slot + 3, E.underground_belt, UP),
			entity(0, y_slot + 4, E.belt, DOWN),
			entity(1, y_slot + 4, E.belt, LEFT),
		] +
		belt(0, y_slot + 5, DOWN, 5 - y_slot)
	)


# As belt_offramp, but belt does not continue. Does not go below y_slot.
#  v
#  ...
#  v
#  >>   y_slot
def belt_offramp_all(y_slot):
	return belt(0, 0, DOWN, y_slot + 2) + belt(0, y_slot + 2, RIGHT, 2)


# Take liquid off or put it on a bus pipe that continues.
#  =
#  ...
#  =
#  ==   y_slot
#  =
#  ...
#  =
def pipe_ramp(y_slot):
	return [entity(0, i, E.pipe) for i in range(10)] + [entity(1, y_slot + 2, E.pipe)]


# Single-entity primitives, used directly for simple or fiddly bits in layouter
medium_pole = [entity(0, 0, E.medium_pole)]
big_pole = [entity(0, 0, E.big_pole)]
beacon = [entity(0, 0, E.beacon, items={E.speed_module: 2})]
roboport = [entity(0, 0, E.roboport)]
