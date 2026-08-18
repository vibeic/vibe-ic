#!/usr/bin/env python3
"""A runner whose default workspace is resolved, never baked in."""
from __future__ import annotations

import os
from pathlib import Path


def designs_root() -> Path:
    """Anchor on the caller's environment, so a clean install stays clean."""
    env = os.environ.get("VIBEIC_DESIGNS_ROOT")
    return Path(env) if env else Path.home() / "vibeic-designs"
