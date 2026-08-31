#!/usr/bin/env python3
"""A corpus document citing a PLUGIN document is not citing a missing proof.

MEASURED on the stamp full-tier run of 2026-08-31. One of the fourteen NEW
dangling citations is

    spm/v1.10.18_sky130A/reports/audit/phase1/expert_parse_track_pack/
    lessons.md :: agents/ic-expert-agent.md

and the citing sentence is

    Rendered deterministically from the general-pattern `### Skill:` sections
    of `agents/ic-expert-agent.md`.

The file EXISTS — `vibe-ic-marketplace/plugins/vibe-ic/agents/ic-expert-agent.md`
in this repository, 434 KB of it — and the same document spells the full path
out at line 2072. The citation is written relative to the PLUGIN ROOT, which is
how every other reference to a plugin asset in this tree is written.

`_resolves_outside_the_scan_root` is the channel for exactly this: "the
artefact EXISTS; it just lives above this gate's root, so ... the document is
correct and this gate is simply not the one that judges it." Its base list is
`root.parent` plus the REPOSITORY root, named structurally from this program's
own location — deliberately, because inferring it from where the corpus sits
broke when the corpus moved out (measured at c5d7f2d00: the disclosed OUT OF
SCOPE count fell 7 -> 2).

The plugin root was simply missing from that list. It is nameable by exactly
the same structural argument, and more cheaply: this program ships inside
`<plugin>/programs/`, so the plugin root is its own grandparent — no inference,
no ancestor walk, and true wherever the corpus is.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
GATE = PROGRAMS / "evidence_citation_resolves_check.py"

spec = importlib.util.spec_from_file_location("_evidence_citation_scope", GATE)
assert spec and spec.loader
G = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = G
spec.loader.exec_module(G)

pytestmark = pytest.mark.timeout(0)


def test_a_plugin_root_relative_citation_resolves_outside_the_scan_root(
        tmp_path):
    """THE STAMP RED. The cited file ships; the gate could not see it."""
    assert (PLUGIN / "agents" / "ic-expert-agent.md").is_file(), (
        "the cited plugin document is gone; this test's subject changed")
    assert G._resolves_outside_the_scan_root(
        "agents/ic-expert-agent.md", tmp_path) is True


def test_a_plugin_relative_path_that_does_not_exist_is_still_dangling(
        tmp_path):
    """THE NEGATIVE CONTROL. Widening a resolution base is the RETIRING
    direction — it makes findings go away — so it must retire only citations
    that name a file which is really there."""
    assert G._resolves_outside_the_scan_root(
        "agents/no-such-agent-file.md", tmp_path) is False


def test_an_absolute_path_is_unaffected_by_the_new_base(tmp_path):
    """Absolute paths are non-portable and were never resolvable here; the
    extra base must not become a way for one to resolve."""
    target = PLUGIN / "agents" / "ic-expert-agent.md"
    assert G._resolves_outside_the_scan_root(str(target), tmp_path) is False
