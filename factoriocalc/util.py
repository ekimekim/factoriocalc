
from collections import namedtuple
from fractions import Fraction

Point = namedtuple('Point', ['x', 'y'])


class Layout(object):
	"""
	A Layout is a recursive structure detailing both direct entities
	(a game object with an x and y coord) and sub-layouts.
	Positions of both entities and sub-layouts are relative to the layout's position.
	"""
	def __init__(self, name, *to_place):
		"""Name is a friendly string, mainly for debugging.
		to_place is an optional list of initial (x, y, entity or sublayout) values.
		"""
		self.name = name
		self.sublayouts = [] # list of (position, sub-layout)
		self.entities = [] # list of (position, entitiy)
		for x, y, child in to_place:
			self.place(x, y, child)

	def place(self, x, y, child):
		"""Child may be entity or sub-layout"""
		pos = Point(x, y)
		if isinstance(child, Layout):
			self.sublayouts.append((pos, child))
		else:
			self.entities.append((pos, child))

	def flatten(self):
		"""Flatten a layout to a list of (position, entity)"""
		entities = list(self.entities)
		for pos, sublayout in self.sublayouts:
			for subpos, entity in sublayout.flatten():
				entities.append((Point(pos.x + subpos.x, pos.y + subpos.y), entity))
		return entities

	def total_entities(self):
		"""For debugging, total entities in this and all sub-layouts"""
		return len(self.entities) + sum(sublayout.total_entities() for pos, sublayout in self.sublayouts)

	def __str__(self):
		"""Produces a long-form description suitable for debugging"""
		return "{}: {}/{} entities{}{}".format(
			self.name,
			len(self.entities),
			self.total_entities(),
			''.join(
				"\n" + "\n".join("  {}".format(line) for line in str(sublayout).split('\n'))
				for pos, sublayout in self.sublayouts
			),
			''.join(
				"\n  {}".format(entity)
				for pos, entity in self.entities
			),
		)


def is_liquid(item):
	LIQUIDS = [
		'petroleum', 'light oil', 'heavy oil', 'sulfuric acid', 'lubricant', 'crude oil', 'water',
		'oil products', 'light oil cracking', 'heavy oil cracking',
	]
	return item in LIQUIDS

def line_limit(item, belt_type):
	if is_liquid(item):
		# 17/tick for pipe lengths up to 166 long. This is a conservative
		# limit that just means I don't need to worry about it.
		return Fraction(17*60)
	if belt_type == 'blue':
		return Fraction(45)
	if belt_type == 'red':
		return Fraction(30)
	if belt_type == 'yellow':
		return Fraction(15)
	raise ValueError("Bad belt type: {!r}".format(belt_type))

UP, RIGHT, DOWN, LEFT = range(4)
