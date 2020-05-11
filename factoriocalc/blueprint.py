

import base64
import json
import zlib

from .primitives import E, Entity
from .util import UP, RIGHT, DOWN, LEFT, Point


FORMAT_VERSION = '0'
MAP_VERSION = 0x1000330000


# Size of non-1x1 entities. Needed as blueprints specify location by center point.
# Each entry is (width, height), as per their layout with orientation up/down.
x2 = (2, 2)
x3 = (3, 3)
x4 = (4, 4)
x5 = (5, 5)
entity_sizes = {
	E.pump: (1, 2),
	E.big_pole: x2,
	E.beacon: x3,
	E.radar: x3,
	E.assembler: x3,
	E.chemical_plant: x3,
	E.splitter: (2, 1),
	E.roboport: x4,
	E.furnace: x3,
	E.refinery: x5,
}


def encode(entities, label="Generated", icons=[E.assembler]):
	"""Encode a list of (pos, entity) into a blueprint string.
	Optional args are to set blueprint label and icons.
	"""
	# Non-centered blueprints seem to cause weird issues.
	# We work out the full width and height, then pick a center point
	# and re-cast everything to that.
	width = max([
		pos.x + entity_sizes.get(entity.name, (1, 1))[0]
		for pos, entity in entities
	])
	height = max([
		pos.y + entity_sizes.get(entity.name, (1, 1))[1]
		for pos, entity in entities
	])
	center = Point(width / 2 + .5, height / 2 + .5)
	blueprint = {
		"blueprint": {
			"item": "blueprint",
			"label": label,
			"version": MAP_VERSION,
			"icons": [
				{
					"index": i + 1,
					"signal": {
						"type": "item", # future work: more icon types
						"name": item,
					},
				} for i, item in enumerate(icons)
			],
			"entities": [
				encode_entity(i + 1, pos, entity, center)
				for i, (pos, entity) in enumerate(entities)
			],
		}
	}
	return encode_json(blueprint)


def encode_json(data):
	return FORMAT_VERSION + base64.b64encode(zlib.compress(json.dumps(data)))


def decode_json(data):
	if data[0] != FORMAT_VERSION:
		raise ValueError("Unknown format version: {}".format(data[0]))
	return json.loads(zlib.decompress(base64.b64decode(data[1:])))


def encode_entity(number, pos, entity, center):
	width, height = entity_sizes.get(entity.name, (1, 1))
	if entity.orientation is not None and entity.orientation % 2 == 1:
		# Rotate entities if left or right
		height, width = width, height
	ret = {
		"entity_number": number,
		"name": entity.name,
		"position": {
			"x": pos.x + width / 2. - center.x,
			"y": pos.y + height / 2. - center.y,
		},
	}
	if entity.orientation is not None and entity.orientation != UP:
		# In their blueprints, up-oriented things have direction omitted.
		# I suspect this would work either way but shorter blueprints is always nice.
		# Their orientations map the same as ours but doubled, ie. 0, 2, 4, 6.
		# Bottom bit is ignored.
		ret["direction"] = 2 * entity.orientation
	ret.update(entity.attrs)
	return ret


def lossy_decode_entity(entity):
	"""Convert blueprint entity to (position, Entity)"""
	width, height = entity_sizes.get(entity['name'], (1, 1))
	orientation = entity.get('direction', 0) / 2
	if orientation % 2 == 1:
		# Rotate entities if left or right
		height, width = width, height
	attrs = {k: v for k, v in entity.items() if k not in ('entity_number', 'name', 'position', 'direction')}
	pos = entity['position']
	return Point(
		pos['x'] - width / 2.,
		pos['y'] - height / 2.,
	), Entity(
		entity['name'],
		orientation,
		attrs,
	)


def lossy_decode(data):
	"""Convert a blueprint to a list of (position, entity). Note that many properties get dropped!"""
	data = decode_json(data)
	entities = map(lossy_decode_entity, data['blueprint']['entities'])
	if not entities:
		return []
	top_left = Point(
		min(pos.x for pos, entity in entities),
		min(pos.y for pos, entity in entities),
	)
	return [
		(
			Point(int(pos.x - top_left.x), int(pos.y - top_left.y)),
			entity,
		)
		for pos, entity in entities
	]


if __name__ == '__main__':
	# For testing of arbitrary blueprints
	import sys
	print encode_json(json.load(sys.stdin))
