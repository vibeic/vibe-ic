#!/usr/bin/env python3
"""Regression tests for issue #687 — the via-analyzer must read the tech LEF
through the container-aware reader, not a host-only Path.read_text().

Root cause (caravel round-6, public tree v1.0.47): step_pnr did
`tlef_text = Path(pdk.tech_lef).read_text(errors="ignore")` on the HOST, but
`pdk.tech_lef` is a CONTAINER-side path (PDKS_IN_CONTAINER=/foss/pdks); the
iic-osic-tools PDK exists only inside docker (`ls /foss` on host → No such
file). The host read threw FileNotFoundError, was swallowed by the bare
except, and the single-cut-via routing restriction was silently dropped on
the exact PDK class it was written for (multi-cut-only upper vias → DRT-0234
detailed_route abort).

Fix: use `_v1_6_604_read_text_or_container_cat(str(pdk.tech_lef), container)`
— the same host→container-cat fallback every other techlef/liberty consumer
uses — and raise FileNotFoundError only when BOTH fail.

§4.05 negative (no false alert): a benign all-single-cut techlef (sky130-
style) must still produce NO routing restriction — covered by
test_negative_single_cut_pdk_emits_no_restriction.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "phase3_one_shot_runner.py"
sys.path.insert(0, str(PROG.parent))
import phase3_one_shot_runner as r  # noqa: E402
import _pdk_via_analyzer as via  # noqa: E402


# A multi-cut-only upper via PDK fragment: single-cut VIA1..VIA4 but VIA5 is
# multi-cut only (the DRT-0234 case → routing must be restricted to M1..M5).
_MULTICUT_TLEF = """
VIA VIA12 DEFAULT
  LAYER met1 ;
    RECT 0 0 1 1 ;
  LAYER via1 ;
    RECT 0 0 1 1 ;
  LAYER met2 ;
    RECT 0 0 1 1 ;
END VIA12
VIA VIA56 DEFAULT
  LAYER met5 ;
    RECT 0 0 1 1 ;
  LAYER via5 ;
    RECT 0 0 1 1 ;
    RECT 2 2 3 3 ;
  LAYER met6 ;
    RECT 0 0 1 1 ;
END VIA56
LAYER met1
  TYPE ROUTING ;
END met1
LAYER met6
  TYPE ROUTING ;
END met6
"""

# A benign all-single-cut techlef (sky130-style): VIA1..VIA4 each have a
# single-cut variant, so every routing layer is reachable — no restriction.
_SINGLE_CUT_TLEF = """
VIA VIA12 DEFAULT
  LAYER met1 ;
  LAYER via1 ;
    RECT 0 0 1 1 ;
  LAYER met2 ;
END VIA12
VIA VIA23 DEFAULT
  LAYER met2 ;
  LAYER via2 ;
    RECT 0 0 1 1 ;
  LAYER met3 ;
END VIA23
VIA VIA34 DEFAULT
  LAYER met3 ;
  LAYER via3 ;
    RECT 0 0 1 1 ;
  LAYER met4 ;
END VIA34
VIA VIA45 DEFAULT
  LAYER met4 ;
  LAYER via4 ;
    RECT 0 0 1 1 ;
  LAYER met5 ;
END VIA45
"""


# ── the container-cat reader is what the analyzer now uses ─────────────
def test_container_cat_fallback_reads_container_only_techlef(monkeypatch):
    """Simulate a /foss/pdks container-only path: the host read fails, but a
    stubbed `docker exec cat` returns the techlef. The reader the via-
    analyzer now calls must return that content (the old host-only read
    would have returned nothing → analyzer silently skipped)."""
    container_path = "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/techlef/x.tlef"

    class _CP:
        returncode = 0
        stdout = _MULTICUT_TLEF

    def _fake_run(cmd, *a, **k):
        # Must be invoked as `docker exec <container> cat <path>`.
        assert cmd[:3] == ["docker", "exec", "vibeic-test"]
        assert cmd[3] == "cat"
        assert cmd[4] == container_path
        return _CP()

    monkeypatch.setattr(r.subprocess, "run", _fake_run)
    text = r._v1_6_604_read_text_or_container_cat(container_path, "vibeic-test")
    assert text == _MULTICUT_TLEF
    # And the analyzer over that text produces a restriction bound: only
    # VIA12 is single-cut, VIA56 (the upper via) is multi-cut-only, so the
    # safe routing range is M1..M2 (route stops below the uncovered VIA5).
    bound = via.routing_layer_upper_bound(text)
    assert bound == 2
    # The DRT-0234 restriction is now derivable — pre-fix the analyzer never
    # even saw this text (host read of the /foss path returned nothing).


def test_container_cat_returns_none_when_no_container(monkeypatch):
    # Host read of a non-existent path + no container → None (analyzer then
    # raises FileNotFoundError, an HONEST skip, not a silent swallow that
    # masks a real container-only PDK).
    monkeypatch.setattr(r.subprocess, "run",
                        lambda *a, **k: pytest.fail("should not exec"))
    assert r._v1_6_604_read_text_or_container_cat(
        "/foss/pdks/does/not/exist.tlef", "") is None


# ── the inline source actually uses the container-aware reader ─────────
def test_step_pnr_via_analyzer_uses_container_reader():
    """Guard against a regression back to the host-only read: the via-
    analyzer block must call _v1_6_604_read_text_or_container_cat on
    pdk.tech_lef and must NOT do a bare Path(pdk.tech_lef).read_text()."""
    src = PROG.read_text()
    # locate the via-analyzer import as an anchor for the block.
    anchor = src.index("from _pdk_via_analyzer import routing_layer_upper_bound")
    block = src[anchor:anchor + 800]
    assert "_v1_6_604_read_text_or_container_cat(" in block
    assert "str(pdk.tech_lef), container" in block
    assert "Path(pdk.tech_lef).read_text(" not in block


# ── §4.05 NEGATIVE — benign single-cut PDK emits NO restriction ────────
def test_negative_single_cut_pdk_emits_no_restriction():
    """A normal all-single-cut techlef must NOT trigger a routing
    restriction (no false alert). Every metal transition is single-cut-
    covered, so the bound is None — the consumer emits set_routing_layers
    only when the bound is not None, so a benign PDK keeps full routing."""
    upper = via.routing_layer_upper_bound(_SINGLE_CUT_TLEF)
    # GAP#1 corrected semantics: fully-covered → None (no restriction).
    assert upper is None
