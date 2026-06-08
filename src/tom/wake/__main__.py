"""``python -m tom.wake`` — run the wake relay."""

from __future__ import annotations

import sys

from tom.wake.cli import main

if __name__ == "__main__":
    sys.exit(main())
