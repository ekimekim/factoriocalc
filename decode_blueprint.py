
import sys
import zlib
import json

def main(input=None):
	if input is None:
		input = sys.stdin.read()
	version, input = input[0], input[1:]
	assert version == '0', "Unknown version: {}".format(version)
	input = input.decode('base64')
	input = zlib.decompress(input)
	input = json.loads(input)
	print json.dumps(input, indent=4)


if __name__ == '__main__':
	main(*sys.argv[1:])
