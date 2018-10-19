# -encoding: utf-8-

import functools

from .primitives import E

# art formatters

def boxed(c, n=3):
	"""Creates a NxN box (default 3) with char c as fill"""
	i = n - 2 # interior size
	c = list(c)
	return (
		    [["┌"] + i*["─"] + ["┐"]]
		+ i*[["│"] + i*  c   + ["│"]]
		+   [["└"] + i*["─"] + ["┘"]]
	)

def forecolor(content, color=8, bold=False):
	if not isinstance(content, basestring):
		return [forecolor(part, color, bold)
		        for part in content]
	color = str(30 + color)
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

def splitter(obj):
	s = {
		'left': 'Ss',
		'right': 'sS',
	}.get(obj.attrs['output_priority'], 'ss')
	if obj.orientation % 2 == 0:
		s = [list(s)]
	else:
		s = [[c] for c in s]
	if obj.orientation / 2 > 0:
		s = s[::-1]
	return blue(s)

class ArtEncoder(object):
	"""Encodes a blueprint in a (lossy!) graphical representation in "ascii art"
	(though not guarenteed to be 100% ascii). The intent is to aid in debugging
	and exploration of designs."""
	EMPTY = ' '

	ART = {
		E.inserter: green([['i']]),
		E.assembler: yellow(boxed("A")),
		E.furnace: blue(boxed("F")),
		E.belt: lambda obj: blue([[
			{
				0: '^',
				1: '>',
				2: 'v',
				3: '<',
			}[obj.orientation]
		]]),
		E.underground_belt: lambda obj: blue([[
			{
				0: '∪',
				1: '⊂',
				2: '∩',
				3: '⊃',
			}[(obj.orientation + (2 if obj.attrs['type'] == 'input' else 0)) % 4]
		]]),
		E.splitter: splitter,
		E.medium_pole: [['o']],
		E.big_pole: [['\\', '/'], ['/', '\\']],
		E.beacon: boxed('B'),
		E.roboport: boxed('R', n=4),
		E.pipe: green([['=']]),
		E.underground_pipe: lambda obj: green([[
			{
				0: '∪',
				1: '⊂',
				2: '∩',
				3: '⊃',
			}[obj.orientation]
		]]),
		E.pump: lambda obj: green({ # large P denotes output end
			0: [['P'], ['p']],
			1: [['p', 'P']],
			2: [['p'], ['P']],
			3: [['P', 'p']],
		}[obj.orientation]),
	}

	def __init__(self, error_on_conflict=True):
		self.error_on_conflict = error_on_conflict

	def encode(self, blueprint):
		"""As with all blueprint encoders, the incoming blueprint should be
		a list of (Point, Entity)."""
		# biggest entities are 5x5
		width = max(pos.x for pos, obj in blueprint) + 5
		height = max(pos.y for pos, obj in blueprint) + 5
		grid = [[self.EMPTY] * width for _ in range(height)]

		for pos, obj in blueprint:
			if pos.x < 0 or pos.y < 0:
				raise ValueError("Blueprint has entity with out of bounds position: {}".format(obj))
			art = self.ART.get(obj.name, bold([['?']]))
			if callable(art):
				art = art(obj)
			self.blit(grid, pos, art)

		return '\n'.join([''.join(row) for row in grid])

	def blit(self, grid, pos, art):
		for dy, row in enumerate(art):
			for dx, char in enumerate(row):
				this_x, this_y = pos.x + dx, pos.y + dy
				if grid[this_y][this_x] != self.EMPTY:
					if self.error_on_conflict:
						raise ValueError("Blueprint has overlapping objects at ({}, {}): Tried to overwrite {} with {}".format(
							this_x, this_y, grid[this_y][this_x], char
						))
					char = red('!', bold=True)
				grid[this_y][this_x] = char
