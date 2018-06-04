from setuptools import setup, find_packages

setup(
	name='factoriocalc',
	version='0.0.1',
	author='Mike Lang',
	author_email='mikelang3000@gmail.com',
	description='Calculator and generator for factorio factories',
	packages=find_packages(),
	install_requires=[
		"argh",
	],
)
