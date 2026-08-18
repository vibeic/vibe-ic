#!/usr/bin/env python3
"""A program that runs a simulation and leaves its dump outside the bundle."""
from __future__ import annotations

from pathlib import Path


def dump_path(workdir: Path) -> Path:
    """Waveforms belong in a work directory, never inside the plugin tree."""
    return workdir / "sim.vcd"
