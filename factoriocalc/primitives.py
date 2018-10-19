# -encoding: utf-8-


from collections import namedtuple

from .util import Layout, Point, UP, RIGHT, DOWN, LEFT


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
	'orientation', # 0-3, 0 is 'up', 1 is 'right', etc.
	'attrs', # arbitrary extra attributes {attr: value}, should match Entity keys in blueprint format
])

def entity(name, orientation=None, **attrs):
	return Entity(name, orientation, attrs)


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
	furnace = 'electric-furnace'

	# checked
	speed_module = 'speed-module-3'

E = _Entities()


belt_to_ground = lambda o: entity(E.underground_belt, o, type='input')
belt_from_ground = lambda o: entity(E.underground_belt, o, type='output')


# Primitives, which are Layouts or Entities.


# A bus pipe with pump, plus underground pipe going under the working area
underpass_pipe = Layout('underpass pipe',
	(0, 0, entity(E.pump, DOWN)),
	(0, 2, entity(E.underground_pipe, UP)),
	(0, 9, entity(E.underground_pipe, DOWN)),
)

# A bus underground belt going under the working area
underpass_belt = Layout('underpass belt',
	(0, 0, belt_to_ground(DOWN)),
	(0, 9, belt_from_ground(DOWN)),
)


# A bus underground pipe for going under a roboport row
roboport_underpass_pipe = Layout('roboport underpass pipe',
	(0, 0, entity(E.underground_pipe, UP)),
	(0, 6, entity(E.underground_pipe, DOWN)),
)


# A bus underground belt for going under a roboport row
roboport_underpass_belt = Layout('roboport underpass belt',
	(0, 0, belt_to_ground(DOWN)),
	(0, 6, belt_from_ground(DOWN)),
)


# Run a length of belt in the specified direction for specified length.
def belt(orientation, length):
	delta = orientation_to_vector(orientation)
	return Layout("belt", *[
		(i * delta.x, i * delta.y, entity(E.belt, orientation))
		for i in range(length)
	])


# As belt(), but for pipes
def pipe(orientation, length):
	delta = orientation_to_vector(orientation)
	return Layout("pipe", *[
		(i * delta.x, i * delta.y, entity(E.pipe))
		for i in range(length)
	])


# An underground belt "coming up for air", ie. an output then another input
# in the same direction immediately.
def belt_surface(orientation):
	delta = orientation_to_vector(orientation)
	return Layout('belt surface',
		(0, 0, belt_from_ground(orientation)),
		(delta.x, delta.y, belt_to_ground(orientation)),
	)


# As belt_surface but for pipes.
def pipe_surface(orientation):
	delta = orientation_to_vector(orientation)
	return Layout('pipe surface',
		(0, 0, entity(E.underground_pipe, orientation)),
		(delta.x, delta.y, entity(E.underground_pipe, (orientation + 2) % 4)),
	)


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
	return Layout('belt offramp',
		(0, 0, belt(DOWN, y_slot)),
		(0, y_slot, entity(E.splitter, DOWN, output_priority='right')),
		(0, y_slot + 1, entity(E.belt, DOWN)),
		(1, y_slot + 1, belt_to_ground(DOWN)),
		(0, y_slot + 2, entity(E.belt, RIGHT)),
		(1, y_slot + 2, belt_to_ground(RIGHT)),
		(1, y_slot + 3, belt_from_ground(DOWN)),
		(0, y_slot + 4, entity(E.belt, DOWN)),
		(1, y_slot + 4, entity(E.belt, LEFT)),
		(0, y_slot + 5, belt(DOWN, 5 - y_slot)),
	)


# As belt_offramp, but belt does not continue. Does not go below y_slot.
#  v
#  ...
#  v
#  >⊃   y_slot
def belt_offramp_all(y_slot):
	return Layout('belt offramp all',
		(0, 0, belt(DOWN, y_slot + 2)),
		(0, y_slot + 2, entity(E.belt, RIGHT)),
		(1, y_slot + 2, belt_to_ground(RIGHT)),
	)


# Take liquid off or put it on a bus pipe that continues.
#  =
#  ...
#  =
#  =⊃   y_slot
#  =
#  ...
#  =
def pipe_ramp(y_slot):
	return Layout('pipe ramp',
		(0, 0, pipe(DOWN, 10)),
		(1, y_slot + 2, entity(E.underground_pipe, LEFT)),
	)


# As belt_offramp_all but for pipes
#  =
#  ...
#  =
#  =⊃   y_slot
def pipe_offramp_all(y_slot):
	return Layout('pipe offramp all',
		(0, 0, pipe(DOWN, y_slot + 3)),
		(1, y_slot + 2, entity(E.underground_pipe, LEFT)),
	)


# Move output from an underground belt to the right of (1, 0)
# onto a new line going down of given height
#  v⊃
#  v
#  ...
#  v
def belt_onramp_all(height):
	return Layout('belt onramp all',
		(0, 0, belt(DOWN, height + 1)),
		(1, 0, belt_from_ground(LEFT)),
	)


# As belt_onramp_all but for pipes
#  =⊃
#  =
#  ...
#  =
def pipe_onramp_all(height):
	return Layout('pipe onramp all',
		(0, 0, pipe(DOWN, height + 1)),
		(1, 0, entity(E.underground_pipe, LEFT)),
	)


# Takes an incoming belt line from the bus and sends it to the left at y slot 1
#  v
#  v
#  v
#  <
belt_to_left = Layout('belt to left',
	(0, 0, belt(DOWN, 3)),
	(0, 3, entity(E.belt, LEFT)),
)


# As belt_to_left but for pipes
#  =
#  =
#  =
#  =
pipe_to_left = pipe(DOWN, 4)


# Takes a belt from the left at bottom y slot and sends it down
#  v
#  v
belt_from_left = belt(DOWN, 2)


# As belt_from_left but for pipes
#  =
#  =
pipe_from_left = pipe(DOWN, 2)


# Join two belts, with the right incoming on y_slot 0.
# Note the balancing of sides in order to ensure full throughput is gained.
# Note we always assume a belt's available throughput is greater on the right side
# ie. we always consume left-first.
#  v
#  v
#  v
#  vv  <- right in
#  Ss
#  v<
#  v
#  v
#  v
#  v
compact_belts = Layout('compact belts',
	(0, 0, belt(DOWN, 4)),
	(1, 3, entity(E.belt, DOWN)),
	(0, 4, entity(E.splitter, DOWN, input_priority='right', output_priority='right')),
	(0, 5, belt(DOWN, 5)),
	(1, 5, entity(E.belt, LEFT)),
)


# As belt_compact, but assume left output can't take everything and overflow
# to a right output on y_slot 6.
# The same notes about balancing apply.
#  v
#  v
#  v
#  vv  <- right in
#  vv
#  vv
#  Ss
#  vSs
#  v<X -> outputs into X
#  v
compact_belts_with_overflow = Layout('compact belts with overflow',
	(0, 0, belt(DOWN, 6)),
	(1, 3, belt(DOWN, 3)),
	(0, 6, entity(E.splitter, DOWN, input_priority='right', output_priority='right')),
	(0, 7, belt(DOWN, 3)),
	(1, 7, entity(E.splitter, DOWN, output_priority='right')),
	(1, 8, entity(E.belt, LEFT)),
)


# Join two pipes, with the right incoming on y_slot 1
#  =
#  =
#  =
#  ==  <- right in
#  =
#  =
#  =
#  =
#  =
#  =
compact_pipe = Layout('compact pipe',
	(0, 0, pipe(DOWN, 10)),
	(1, 3, entity(E.pipe)),
)


# Single-entity primitives, used directly for simple or fiddly bits in layouter
medium_pole = entity(E.medium_pole)
big_pole = entity(E.big_pole)
beacon = entity(E.beacon, items={E.speed_module: 2})
roboport = entity(E.roboport)
