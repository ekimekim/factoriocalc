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
	'connections', # list of (port, color, rel_x, rel_y, target_port) of other entities connected by circuit wire.
	               # port is generally 1, and refers to which connection point on this entity is used.
	               # target_port is the same but for the target.
	               # color is red or green. Both sides must link to each other.
	               # You can use circuit() as a helper function for this.
	'attrs', # arbitrary extra attributes {attr: value}, should match Entity keys in blueprint format
])

def entity(name, orientation=None, connections=[], **attrs):
	return Entity(name, orientation, connections, attrs)


def circuit(rel_x, rel_y, color='green', port=1, target_port=1):
	"""helper method for setting Entity connections, eg. Entity(E.chest, connections=[circuit(0, 1)])"""
	return port, color, rel_x, rel_y, target_port


# A mapping from easy internal names to official names
class _Entities(object):
	# guessed
	yellow_underground_belt = 'underground-belt'

	# checked
	red_science = 'automation-science-pack'
	green_science = 'logistic-science-pack'
	black_science = 'military-science-pack'
	blue_science = 'chemical-science-pack'
	purple_science = 'production-science-pack'
	yellow_science = 'utility-science-pack'
	white_science = 'space-science-pack'
	electric_engine = 'electric-engine-unit'
	blue_circuit = 'processing-unit'
	yellow_belt = 'transport-belt'
	robot_frame = 'flying-robot-frame'
	ammo = 'firearm-magazine'
	piercing_ammo = 'piercing-rounds-magazine'
	plastic = 'plastic-bar'
	engine = 'engine-unit'
	solid_fuel = 'solid-fuel-from-light-oil'
	radar = 'radar'
	wall = 'stone-wall'
	underground_pipe = 'pipe-to-ground'
	pipe = 'pipe'
	pump = 'pump'
	belt = 'express-transport-belt'
	blue_belt = 'express-transport-belt'
	red_belt = 'fast-transport-belt'
	yellow_belt = 'transport-belt'
	underground_belt = 'express-underground-belt'
	blue_underground_belt = underground_belt
	red_underground_belt = 'fast-underground-belt'
	yellow_underground_belt = 'underground-belt'
	medium_pole = 'medium-electric-pole'
	big_pole = 'big-electric-pole'
	beacon = 'beacon'
	ins = 'stack-inserter'
	long_inserter = 'long-handed-inserter'
	chest = 'steel-chest'
	assembler = 'assembling-machine-3'
	lab = 'lab'
	splitter = 'express-splitter'
	red_splitter = 'fast-splitter'
	yellow_splitter = 'splitter'
	roboport = 'roboport'
	furnace = 'electric-furnace'
	chemical_plant = 'chemical-plant'
	speed_1 = 'speed-module'
	speed_3 = 'speed-module-3'
	prod_1 = 'productivity-module'
	prod_3 = 'productivity-module-3'
	gear = 'iron-gear-wheel'
	refinery = 'oil-refinery'
	copper_wire = 'copper-cable'
	green_circuit = 'electronic-circuit'
	red_circuit = 'advanced-circuit'
	rocket_silo = 'rocket-silo',
	# not entities but still a recipe name
	oil_products = 'advanced-oil-processing'

	def __getitem__(self, key):
		return getattr(self, key.replace(' ', '_'), key.replace(' ', '-'))

E = _Entities()


def _underground_belt(orientation, io, color):
	e = {
		'blue': E.underground_belt,
		'red': E.red_underground_belt,
		'yellow': E.yellow_underground_belt,
	}[color]
	return entity(e, orientation, type=io)
belt_to_ground = lambda o, type='blue': _underground_belt(o, 'input', type)
belt_from_ground = lambda o, type='blue': _underground_belt(o, 'output', type)


# Primitives, which are Layouts or Entities.


# A bus pipe with pump, plus underground pipe going under the working area
underpass_pipe = Layout('underpass pipe',
	(0, 0, entity(E.pump, DOWN)),
	(0, 2, entity(E.underground_pipe, UP)),
	(0, 9, entity(E.underground_pipe, DOWN)),
)

# A bus pipe without a pump, which may not fit in some special cases
underpass_pipe_no_pump = Layout('underpass pipe no pump',
	(0, 0, entity(E.underground_pipe, UP)),
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
def belt(orientation, length=1, type='blue'):
	delta = orientation_to_vector(orientation)
	e = {
		'blue': E.belt,
		'red': E.red_belt,
		'yellow': E.yellow_belt,
	}[type]
	return Layout("belt", *[
		(i * delta.x, i * delta.y, entity(e, orientation))
		for i in range(length)
	])


def splitter(orientation, type='blue', **attrs):
	e = {
		'blue': E.splitter,
		'red': E.red_splitter,
		'yellow': E.yellow_splitter,
	}[type]
	return entity(e, orientation, **attrs)


# As belt(), but for pipes
def pipe(orientation, length=1):
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
def belt_offramp(y_slot, type='blue'):
	return Layout('belt offramp',
		(0, 0, belt(DOWN, y_slot, type=type)),
		(0, y_slot, splitter(DOWN, output_priority='right', type=type)),
		(0, y_slot + 1, belt(DOWN, type=type)),
		(1, y_slot + 1, belt_to_ground(DOWN)),
		(0, y_slot + 2, belt(RIGHT, type=type)),
		(1, y_slot + 2, belt_to_ground(RIGHT)),
		(1, y_slot + 3, belt_from_ground(DOWN)),
		(0, y_slot + 4, belt(DOWN, type=type)),
		(1, y_slot + 4, belt(LEFT, type=type)),
		(0, y_slot + 5, belt(DOWN, 5 - y_slot, type=type)),
	)


# As belt_offramp, but belt does not continue. Does not go below y_slot.
#  v
#  ...
#  v
#  >⊃   y_slot
def belt_offramp_all(y_slot, type='blue'):
	return Layout('belt offramp all',
		(0, 0, belt(DOWN, y_slot + 2, type=type)),
		(0, y_slot + 2, belt(RIGHT, type=type)),
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
def belt_onramp_all(height, type='blue'):
	return Layout('belt onramp all',
		(0, 0, belt(DOWN, height + 1, type=type)),
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


# Takes an incoming belt line from the bus and sends it to the left at y slot 1,
# making sure it's right-packed. This strays outside our bounds a bit, but works
# for now.
#  v
# Ss
# >v
#  <
def belt_to_left(type='blue'):
	return Layout('belt to left',
		(0, 0, belt(DOWN, type=type)),
		(-1, 1, splitter(DOWN, output_priority='right', type=type)),
		(-1, 2, belt(RIGHT, type=type)),
		(0, 2, belt(DOWN, type=type)),
		(0, 3, belt(LEFT, type=type)),
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
belt_from_left = lambda type='blue': belt(DOWN, 2, type=type)


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
def compact_belts(type='blue'):
	return Layout('compact belts',
		(0, 0, belt(DOWN, 4, type=type)),
		(1, 3, belt(DOWN, type=type)),
		(0, 4, splitter(DOWN, input_priority='right', output_priority='right', type=type)),
		(0, 5, belt(DOWN, 5, type=type)),
		(1, 5, belt(LEFT, type=type)),
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
def compact_belts_with_overflow(type='blue'):
	return Layout('compact belts with overflow',
		(0, 0, belt(DOWN, 6, type=type)),
		(1, 3, belt(DOWN, 3, type=type)),
		(0, 6, splitter(DOWN, input_priority='right', output_priority='right', type=type)),
		(0, 7, belt(DOWN, 3, type=type)),
		(1, 7, splitter(DOWN, output_priority='right', type=type)),
		(1, 8, belt(LEFT, type=type)),
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
beacon = lambda module: entity(E.beacon, items={E[module]: 2})
roboport = entity(E.roboport)
radar = entity(E.radar)
