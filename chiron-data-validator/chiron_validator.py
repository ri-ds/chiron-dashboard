#!/usr/bin/env python3
"""Entry point: `python chiron_validator.py [validate] [options]`.

See `python chiron_validator.py --help` for full usage, and README.md for
the auth flow and known limitations. All actual logic lives in the chironval
package alongside this file.
"""

import sys

from chironval.cli import main

if __name__ == "__main__":
    sys.exit(main())
