

import base64
import json
import zlib

from .primitives import E


FORMAT_VERSION = '0'
MAP_VERSION = 0x1000330000


# Size of non-1x1 entities. Needed as blueprints specify location by center point.
# Each entry is (width, height), as per their layout with orientation up/down.
entity_sizes = {
	E.pump: (1, 2),
	E.assembler: (3, 3),
	E.furnace: (3, 3),
}


def encode(entities, label="Generated", icons=[E.assembler]):
	"""Encode a list of (pos, entity) into a blueprint string.
	Optional args are to set blueprint label and icons.
	"""
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
				encode_entity(i + 1, pos, entity)
				for i, (pos, entity) in enumerate(entities)
			],
		}
	}
	return FORMAT_VERSION + base64.b64encode(zlib.compress(json.dumps(blueprint)))


def encode_entity(number, pos, entity):
	width, height = entity_sizes.get(entity.name, (1, 1))
	if entity.orientation is not None and entity.orientation % 2 == 1:
		# Rotate entities if left or right
		height, width = width, height
	ret = {
		"entity_number": number,
		"name": entity.name,
		"position": {
			"x": pos.x + width / 2.,
			"y": pos.y + height / 2.,
		},
	}
	if entity.orientation is not None:
		# TODO i don't think my orientations map correctly to theirs
		ret["direction"] = entity.orientation
	ret.update(entity.attrs)
	return ret
