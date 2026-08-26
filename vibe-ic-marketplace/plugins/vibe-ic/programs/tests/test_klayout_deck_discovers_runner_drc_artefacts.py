#!/usr/bin/env python3
"""klayout_deck_mode_check must see the DRC the phase3 runner actually writes.

MEASURED, on the completed sky130A run ``run-spm-publish`` (23 GB, DRC 0
violations from the PDK sign-off deck, LVS MATCH):

    $ python3 klayout_deck_mode_check.py <run>
    === klayout_deck_mode_check (run) ===
      [skipped] no KLayout DRC artefacts found          rc 2

and, over that entire run root, ``find`` returns ZERO files named
``manifest.json``, ``*.lyrdb``, ``drc_*.log`` or ``klayout_*.json``, and zero
``reports/drc_*.json``. Those five shapes are what the gate globbed, and they
are the ``eda_drc_klayout`` MCP tool's names. What the run DOES hold is the
phase3 runner's own physical-verification evidence:

    reports/phase3/drc_signoff.rpt   KLayout report-database,
                                     <generator>drc: script='…/sky130A.lydrc'
    reports/phase3/drc_signoff.json  producer klayout, is_signoff_deck true
    reports/phase3/drc_router.{json,rpt}, phase3/stage3/pnr/routed.drc.rpt

So the gate answered "no KLayout DRC artefacts" about a run whose KLayout DRC
had already passed on the foundry deck — and would have answered exactly the
same about a run whose KLayout DRC had fallen back to the structural-only deck
the gate exists to catch, because that fallback recorded under a runner name is
equally invisible to those five globs. The consequence is not a missing PASS:
it is a gate that cannot say no.

Both directions are pinned below. ``test_runner_signoff_drc_is_discovered``
fails on the unfixed program with rc 2 (it finds nothing). ``…_still_fails``
and ``…_advisory_under_runner_name_still_fails`` fail on the unfixed program
with rc 2 as well — the structural-only fallback recorded under the runner's
name goes unnoticed — which is the half that matters.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "klayout_deck_mode_check.py"

SIGNOFF_DECK = "/foss/pdks/sky130A/libs.tech/klayout/drc/sky130A.lydrc"


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project),
         "--json", str(project / "out.json")],
        capture_output=True, text=True)


def _report(project: Path) -> dict:
    return json.loads((project / "out.json").read_text())


def _runner_signoff_rpt(project: Path, body: str = "") -> Path:
    """The phase3 runner's KLayout report-database, verbatim in shape."""
    p = project / "reports" / "phase3" / "drc_signoff.rpt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<report-database>\n"
        " <description>SKY130 DRC runset</description>\n"
        f" <generator>drc: script='{SIGNOFF_DECK}'</generator>\n"
        " <top-cell>spm</top-cell>\n"
        f"{body}"
        "</report-database>\n")
    return p


def _runner_signoff_json(project: Path, **over) -> Path:
    p = project / "reports" / "phase3" / "drc_signoff.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "program": "eda_report_audit:drc",
        "passed": True,
        "summary": {
            "real_violation_total": 0,
            "producers": [{
                "producer": "klayout",
                "deck": SIGNOFF_DECK,
                "top_cell": "spm",
                "is_signoff_deck": True,
            }],
        },
    }
    body.update(over)
    p.write_text(json.dumps(body, indent=1))
    return p


def test_runner_signoff_drc_is_discovered(tmp_path):
    """A clean sign-off DRC under the RUNNER's names is seen, not skipped."""
    _runner_signoff_rpt(tmp_path)
    _runner_signoff_json(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    rpt = _report(tmp_path)
    found = rpt["summary"]["drc_artefacts_found"]
    assert "reports/phase3/drc_signoff.rpt" in found
    assert "reports/phase3/drc_signoff.json" in found
    # The PASS is evidence-backed: it names the deck that ran.
    attested = rpt["summary"]["deck_attested"]
    assert attested, rpt["summary"]
    assert any(SIGNOFF_DECK in a["deck"] for a in attested), attested
    assert "sky130A.lydrc" in r.stdout


def test_structural_only_under_runner_name_still_fails(tmp_path):
    """THE HALF THAT MATTERS — the fallback recorded by the runner is caught.

    Same file name as the passing case above, same directory. Only the
    recorded deck mode differs, and the gate must still refuse.
    """
    _runner_signoff_json(
        tmp_path,
        summary={"producers": [{"producer": "klayout",
                                "deck_mode": "structural_only"}]})
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    rpt = _report(tmp_path)
    assert any(f["rule"] == "KLAYOUT_STRUCTURAL_DRC_NEEDS_WAIVER"
               for f in rpt["findings"]), rpt["findings"]
    assert rpt["summary"]["structural_evidence"] == [
        "reports/phase3/drc_signoff.json"]


def test_structural_advisory_under_runner_name_still_fails(tmp_path):
    """The 0-enforceable-rules advisory in a runner-named report is caught."""
    p = tmp_path / "reports" / "phase3" / "drc_signoff.rpt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "Auto-deck synthesis from tech LEF produced 0 enforceable rules.\n"
        "Ran KLayout in structural-only mode.\n")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr


def test_structural_only_under_runner_name_waiver_still_honoured(tmp_path):
    """The widened discovery did not widen the failure: K01 still closes it."""
    _runner_signoff_json(
        tmp_path,
        summary={"producers": [{"producer": "klayout",
                                "deck_mode": "structural_only"}]})
    (tmp_path / "waivers.json").write_text(json.dumps({"waivers": [{
        "id": "K01_klayout_structural_only_drc",
        "rationale": "open PDK ships no matching layermap for this macro; "
                     "foundry closure plan tracked at sign-off review",
        "review_required": True,
    }]}))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_nested_routed_drc_rpt_is_discovered(tmp_path):
    """`<stage>/pnr/routed.drc.rpt` — the router's own name — is in scope."""
    p = tmp_path / "phase3" / "stage3" / "pnr" / "routed.drc.rpt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("Ran KLayout in structural-only mode.\n")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr


def test_legacy_mcp_manifest_shape_still_covered(tmp_path):
    """The five globs replaced were a subset — the MCP names still fire."""
    for rel, body in (
        ("phase3/gds/manifest.json",
         json.dumps({"step": "drc", "status": "STRUCTURAL_PASS"})),
        ("logs/drc_klayout.log",
         "Auto-deck synthesis from tech LEF produced 0 enforceable rules.\n"),
        ("reports/drc_manifest.json",
         json.dumps({"deck_mode": "structural_only"})),
        ("pv/drc.lyrdb", "structural-only\n"),
    ):
        proj = tmp_path / rel.replace("/", "_")
        f = proj / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body)
        r = _run(proj)
        assert r.returncode == 1, f"{rel}: {r.stdout}{r.stderr}"


def test_no_drc_artefacts_still_skips(tmp_path):
    """An empty project is still an honest skip, not a pass."""
    assert _run(tmp_path).returncode == 2
