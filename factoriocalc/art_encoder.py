# -encoding: utf-8-

import functools

# art formatters

def boxed(c):
	"""Creates a 3x3 box with char c in the middle"""
	return [
		["┌", "─", "┐"],
		["│",   c, "│"],
		["└", "─", "┘"],
	],

def forecolor(content, color=8, bold=False):
	if not isinstance(color, basestring):
		return [forecolor(part, color, bold)
		        for part in content]
	color = str(color)
	if bold:
		color += ';1'
	return '\x1b[{}m{}\x1b[m'.format(color, content)

black = functools.partial(forecolor, color=0)
red = functools.partial(forecolor, color=1)
green = functools.partial(forecolor, color=2)
yellow = functools.partial(forecolor, color=3)
blue = functools.partial(forecolor, color=4)
purple = functools.partial(forecolor, color=5)
cyan = functools.partial(forecolor, color=6)
white = functools.partial(forecolor, color=7)
bold = functools.partial(forecolor, bold=True)

class ArtEncoder(object):
	"""Encodes a blueprint in a (lossy!) graphical representation in "ascii art"
	(though not guarenteed to be 100% ascii). The intent is to aid in debugging
	and exploration of designs."""
	EMPTY = ' '

	ART = {
		'inserter': green([['i']]),
		'assembler': yellow(boxed("A")),
		'belt': lambda obj: blue([[
			{
				0: '^',
				1: '>',
				2: 'v',
				3: '<',
			}[obj.orientation]
		]]),
		'underground belt': lambda obj: blue([[
			{
				0: '∪',
				1: '⊂',
				2: '∩',
				3: '⊃',
			}[obj.orientation]
		]]),
		'splitter': lambda obj: blue({
			0: [['S', 'S']],
			1: [['S'], ['S']],
		}[obj.orientation % 2]),
		'electric pole': 'o',
	},

	def encode(self, blueprint):
		"""As with all blueprint encoders, the incoming blueprint should be
		a list of GameObjects"""
		width = max(obj.x for obj in blueprint) + 1
		height = max(obj.y for obj in blueprint) + 1
		grid = [[self.EMPTY] * width for _ in range(height)]

		for obj in blueprint:
			art = self.ART.get(obj.name, bold([['?']]))
			if callable(art):
				art = art(obj)
			self.blit(grid, obj.x, obj.y, art)

		return '\n'.join([''.join(row) for row in grid])

	def blit(self, grid, x, y, art):
		for dy, row in enumerate(art):
			for dx, char in enumerate(row):
				this_x, this_y = x + dx, y + dy
				if grid[this_y][this_x] != self.EMPTY:
					raise ValueError("Blueprint has overlapping objects at ({}, {})".format(this_x, this_y))
				grid[this_y][this_x] = char
