#!/usr/bin/env python3
"""Tests for readme_submodule_extractor.py — README file-list submodule
extractor (#36 Bug 5, strategy-C).

Pins the structural floor: snake_case `name.v - role` markdown lines become
L9 submodule entries, while single-word generic names (no underscore) and
the dev-kit boilerplate deny-list are rejected. First-occurrence wins on
duplicates; empty / None input returns [].
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import readme_submodule_extractor as mod  # noqa: E402


# ----------------------------------------------------------------------
# PASS — a real README file-list yields submodule (name, role) entries.
# ----------------------------------------------------------------------
def test_pass_extracts_filelist_submodules():
    readme = (
        "# Files\n"
        "- `sha1_core.v` - The core itself\n"
        "- `sha1_w_mem.v` - The W message block memory\n"
        "- sha256_core.v : SHA-256 core\n"
    )
    res = mod.extract_submodules_from_readme_filelist(readme)
    names = [r["name"] for r in res]
    assert names == ["sha1_core", "sha1_w_mem", "sha256_core"]
    first = res[0]
    assert first["role"] == "The core itself"
    assert first["matched_filename"] == "sha1_core.v"
    assert first["evidence_line"] == 2  # 1-based line number


# ----------------------------------------------------------------------
# The defects guarded: generic single-word names and deny-list boilerplate.
# ----------------------------------------------------------------------
def test_rejects_single_word_generic_filename():
    # `core.v` / `top.v` have no underscore -> below the structural floor.
    readme = (
        "- core.v - generic\n"
        "- top.v - generic\n"
        "- chip.v - generic\n"
    )
    assert mod.extract_submodules_from_readme_filelist(readme) == []


def test_rejects_denylisted_boilerplate_names():
    # tb_top / test_bench etc. are vendor/tool example names, not submodules.
    readme = (
        "- tb_top.v - testbench example\n"
        "- test_bench.v - example bench\n"
        "- my_module.v - placeholder\n"
    )
    assert mod.extract_submodules_from_readme_filelist(readme) == []


def test_first_occurrence_wins_on_duplicate():
    readme = (
        "- aes_core.v - first description\n"
        "- aes_core.v - second description (ignored)\n"
    )
    res = mod.extract_submodules_from_readme_filelist(readme)
    assert len(res) == 1
    assert res[0]["role"] == "first description"


def test_line_with_no_separator_or_role_is_skipped():
    # A filename with no separator / role text must not be harvested.
    readme = "aes_core.v\nsha256_core.v -   \n"
    assert mod.extract_submodules_from_readme_filelist(readme) == []


# ----------------------------------------------------------------------
# Empty / None input -> [] (no crash, no fabrication).
# ----------------------------------------------------------------------
def test_empty_string_returns_empty_list():
    assert mod.extract_submodules_from_readme_filelist("") == []


def test_none_returns_empty_list():
    assert mod.extract_submodules_from_readme_filelist(None) == []
