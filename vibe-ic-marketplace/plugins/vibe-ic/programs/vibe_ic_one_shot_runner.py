#!/usr/bin/env python3
"""Public all entry for the step-table runner."""
from __future__ import annotations

import sys


def main(argv=None):
    from flow_engine_frontend import phase_main
    return phase_main(argv, scope="all")


if __name__ == "__main__":
    sys.exit(main())
