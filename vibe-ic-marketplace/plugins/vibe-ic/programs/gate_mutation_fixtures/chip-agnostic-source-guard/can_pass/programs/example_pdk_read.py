#!/usr/bin/env python3
"""A program that names its PDK by variable, never by vendor token."""
from __future__ import annotations

import os


def pdk_name() -> str:
    """The PDK is whatever the environment selected — this tree names none."""
    return os.environ.get("PDK", "open-pdk")
