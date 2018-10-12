

from collections import namedtuple

from .util import Point


UP, RIGHT, DOWN, LEFT = range(4)


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
	medium_pole = 'medium electric power pole'
	beacon = 'beacon'
	inserter = 'stack inserter'
	assembler = 'assembly-machine-3'
	splitter = 'express belt splitter'

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


# Single-entity primitives
medium_pole = [entity(0, 0, E.medium_pole)]
beacon = [entity(0, 0, E.beacon, items={E.speed_module: 2})]
