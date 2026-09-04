#!/usr/bin/env python3
"""A clock target declared for ANOTHER process is not this process's target.

`_v1_9_65_post_emit_l8_pdk_scoped_clock` re-points L8's primary clock at the
document row that names the process being built. Measured on the pre-fix code,
it does that correctly when the row exists — but when it does NOT exist it
returned False and left in place whatever the prose walker had adopted, which
on a document that declares targets per process is another process's row. A
design with

    | Target clock period — <PDK-A> | 10 ns (100 MHz) |

built on <PDK-B> therefore silently inherited <PDK-A>'s 100 MHz, evidence and
all, and the backend would close timing against a period this design never
asked for on this process.

The correct answer to "what is the clock target for a process this document
never gave one to" is NOT_DETERMINED with a named reason — not somebody else's
number.

Both directions are asserted: the ADOPT direction must still adopt (a fix that
refuses everything is not a fix), and the NO-OPINION direction must stay silent
(a document that does not speak in per-process rows is not ambiguous, and
blanking its prose target would be a regression, not a repair).

chip-AGNOSTIC: open-PDK names, a namespace the flow's registry already carries;
no chip, foundry SKU or design literal.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import phase1_doc_one_shot_runner as p1        # noqa: E402

_BOTH = ("| Target clock period — SKY130   | 10 ns (100 MHz) |\n"
         "| Target clock period — GF180MCU | 20 ns (50 MHz) |\n")
_ONLY_A = "| Target clock period — SKY130 | 10 ns (100 MHz) |\n"
_PROSE = "The core runs at 100 MHz.\n"


def _project(tmp_path: Path, doc: str) -> Path:
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "L1_product_metadata.md").write_text("# L1\n\n" + doc,
                                                 encoding="utf-8")
    gd = p1._pl.generated_docs_dir(tmp_path)
    gd.mkdir(parents=True, exist_ok=True)
    payload = {
        "clock_mhz": 100.0,
        "clock_domains": [{
            "name": "clk", "role": "primary", "freq_mhz": 100.0,
            "period_ns": 10.0,
            "extraction_strategy": "clock_domain_doc_prose_fmax",
            "evidence": {"file": "input/docs/L1_product_metadata.md",
                         "line": 1, "matched_substring": "100 MHz"},
        }],
        "clocks": [{"name": "clk", "freq_mhz": 100.0, "period_ns": 10.0}],
    }
    for layer in ("L8_RTL_CONSTANTS", "L8_TIMING_WAVEFORM"):
        (gd / f"{layer}.json").write_text(json.dumps(payload, indent=2),
                                          encoding="utf-8")
    return tmp_path


def _run(tmp_path: Path, doc: str, pdk: str):
    proj = _project(tmp_path, doc)
    prev = p1._CLI_PDK
    p1._CLI_PDK = pdk
    try:
        changed = p1._v1_9_65_post_emit_l8_pdk_scoped_clock(proj)
    finally:
        p1._CLI_PDK = prev
    gd = p1._pl.generated_docs_dir(proj)
    out = {L: json.loads((gd / f"{L}.json").read_text(encoding="utf-8"))
           for L in ("L8_RTL_CONSTANTS", "L8_TIMING_WAVEFORM")}
    return changed, out


@pytest.mark.parametrize("pdk,want_mhz", [("gf180mcu", 50.0),
                                          ("sky130", 100.0)])
def test_each_pdk_gets_its_own_row(tmp_path, pdk, want_mhz):
    """Same document, two processes, two different answers."""
    _changed, out = _run(tmp_path, _BOTH, pdk)
    for layer, data in out.items():
        dom = data["clock_domains"][0]
        assert dom["freq_mhz"] == want_mhz, layer
        assert dom["period_ns"] == pytest.approx(1000.0 / want_mhz), layer
        assert data["clock_mhz"] == want_mhz, layer
        assert data.get("clock_target_resolution") is None, layer


def test_target_declared_for_another_pdk_is_refused_not_borrowed(tmp_path):
    """The row names SKY130 only; the run is GF180MCU. 100 MHz is not ours."""
    changed, out = _run(tmp_path, _ONLY_A, "gf180mcu")
    assert changed is True
    for layer, data in out.items():
        dom = data["clock_domains"][0]
        assert dom["freq_mhz"] is None, layer
        assert dom["period_ns"] is None, layer
        assert dom["extraction_strategy"] == "clock_target_not_determined"
        assert data["clock_mhz"] is None, layer
        res = data.get("clock_target_resolution")
        assert isinstance(res, dict) and res["status"] == "NOT_DETERMINED"
        assert res["pdk"] == "gf180mcu"
        # The refusal must say what it looked for and what it found instead.
        assert "gf180mcu" in res["reason"]
        assert any("sky130" in r for r in res["rows_found"]), layer
        assert any("L1_product_metadata.md:" in r
                   for r in res["rows_found"]), layer
        # Nothing the design said is discarded.
        alts = dom.get("alternate_frequency_mentions") or []
        assert any(a.get("freq_mhz") == 100.0 for a in alts), layer


def test_document_without_per_pdk_rows_keeps_its_prose_target(tmp_path):
    """No per-process rows at all — nothing to arbitrate, no opinion."""
    changed, out = _run(tmp_path, _PROSE, "gf180mcu")
    assert changed is False
    for layer, data in out.items():
        assert data["clock_domains"][0]["freq_mhz"] == 100.0, layer
        assert data["clock_mhz"] == 100.0, layer
        assert data.get("clock_target_resolution") is None, layer
