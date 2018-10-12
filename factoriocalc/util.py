
from collections import namedtuple
from fractions import Fraction

Point = namedtuple('Point', ['x', 'y'])

def is_liquid(item):
	LIQUIDS = [
		'petroleum', 'light oil', 'heavy oil', 'sulfuric acid', 'lubricant', 'crude oil', 'water',
		'oil products', 'light oil cracking', 'heavy oil cracking',
	]
	return item in LIQUIDS

def line_limit(item):
	if is_liquid(item):
		# 17/tick for pipe lengths up to 166 long. This is a conservative
		# limit that just means I don't need to worry about it.
		return Fraction(17*60)
	return Fraction(40) # full blue belt

