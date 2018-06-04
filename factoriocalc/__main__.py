import logging
from factoriocalc.main import main

import argh

logging.basicConfig(level=logging.DEBUG)
argh.dispatch_command(main)
