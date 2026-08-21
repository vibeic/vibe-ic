#!/usr/bin/env python3
"""Tests for _phase1_sentinel.py — shared sentinel module"""
from __future__ import annotations
import sys
from pathlib import Path
import pytest

def test_import():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    import _phase1_sentinel
    assert hasattr(_phase1_sentinel, "is_no_protocol_sentinel_active_in_dir")
    assert hasattr(_phase1_sentinel, "is_no_protocol_sentinel_active_in_docs")
