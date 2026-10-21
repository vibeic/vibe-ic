#!/usr/bin/env python3
"""Tests for internal_vs_external_timing_check.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "internal_vs_external_timing_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_with_waveform(tmp_path):
    # v0.2.55: an L8 with NO protocol/symbol timing content (empty waveforms,
    # no rx_*/tx_* group keys) is N/A for the RX/TX-split rule — a non-protocol
    # IC (e.g. a pure-digital arithmetic primitive) has nothing to split. The
    # gate VACUOUS_PASSes (rc=0) instead of FAILing. A genuinely half-duplex L8
    # that carries only the host-side half is still caught (see the rx_*/tx_*
    # fixtures in test_internal_vs_external_timing_check.py).
    wf = tmp_path / "L8_TIMING_WAVEFORM.json"
    wf.write_text(json.dumps({"waveforms": []}))
    r = _run([str(wf)])
    assert r.returncode == 0
    # THE TIER, and it is NOT re-pinned: this branch was a VACUOUS_PASS before
    # R-0915-124/125 and still is. `flow_compliance_check._stdout_signals_vacuous`
    # believes the disclosure only where the token BEGINS a line, and a clause
    # invoking this gate without `--json` has stdout as its only channel, so the
    # position is load-bearing and not cosmetic.
    assert r.stdout.lstrip().startswith("VACUOUS_PASS"), r.stdout
    # THE CLASS, which is what changed. This fixture stages NO L2 and an L8 empty
    # of protocol content, so it is the ENUMERATING escape -- the gate infers the
    # absence rather than reading a declaration -- and R-0915-124/125 require it be
    # named by structure WITH the enumeration behind it.
    assert "NOT_APPLICABLE_BY_STRUCTURE" in r.stdout
    # AND THE EVIDENCE, not merely the token: a class with nothing behind it is
    # the thing that guard refuses, so assert the enumeration the line carries.
    #
    # AMENDED, NOT WEAKENED (icspm5-s2 pre-landing review, 2026-09-23). This
    # asserted "enumerated 3" over a fixture that stages exactly ONE canonical
    # container (`waveforms`). The count came from `len(_CANONICAL)` -- the
    # NAMES of three containers, two of which are not in the document -- and a
    # container that is absent was never examined. The review named that as the
    # reason a bad enumeration could be laundered into a decided state, so the
    # scan now counts what it walked. The assertion is STRONGER here, not
    # weaker: it pins the count to the fixture's own content.
    assert "enumerated 1" in r.stdout and "found 0" in r.stdout, r.stdout


def _project_with_timing(tmp_path: Path, l1: dict, l2: dict) -> tuple[Path, Path]:
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps(l1))
    (gd / "L2_FRS.json").write_text(json.dumps(l2))
    (gd / "L5_ADI_SPEC.json").write_text(
        json.dumps({"no_analog": True, "analog_blocks": []}))
    wf = gd / "L8_TIMING_WAVEFORM.json"
    # Ordinary external I/O timing is populated, so the older structural-
    # absence escape cannot decide this case.
    wf.write_text(json.dumps({
        "timing_windows": [{"name": "input_setup", "max_ns": 2.0}],
        "timing_constants": [{"name": "output_delay", "value": 20,
                              "unit": "ns"}],
        "waveforms": [],
    }))
    return tmp_path, wf


def test_registry_proven_non_half_duplex_is_not_applicable(tmp_path):
    project, wf = _project_with_timing(
        tmp_path,
        {"description": "AES block cipher encryption and decryption",
         "features": ["128-bit key schedule", "S-box rounds"]},
        {"protocol_overview": None},
    )
    report = project / "gate.json"
    r = _run([str(wf), "--json", str(report)])
    doc = json.loads(report.read_text())
    assert r.returncode == 0, (r.stdout, r.stderr, doc)
    assert doc["verdict"] == "VACUOUS_PASS", doc
    assert doc["reason_class"] == "DESIGN_DECLARED_NA", doc
    assert doc["applicability_evidence"] == {
        "ic_class": "crypto_accelerator",
        "verification_track": "generic_full_stack",
        "half_duplex_bus": False,
        "registry_matched": True,
        "decisive_evidence": (
            "no analog + crypto-accelerator structural signature "
            "(algorithm_family deny-guard + >=2 features, #542)"),
    }


def test_unregistered_class_never_opens_registry_escape(tmp_path, monkeypatch):
    import internal_vs_external_timing_check as gate
    import ic_class_profile

    project, wf = _project_with_timing(
        tmp_path, {"description": "opaque digital device"},
        {"protocol_overview": None},
    )
    monkeypatch.setattr(
        ic_class_profile, "detect_ic_class",
        lambda _project: {"ic_class": "future_unregistered_class"})
    monkeypatch.setattr(
        ic_class_profile, "class_verification_flags",
        lambda _class: {"registry_matched": False,
                        "half_duplex_bus": False})
    assert gate._registry_non_half_duplex(str(wf), wf) is None


def test_explicit_half_duplex_true_overrides_non_half_duplex_class(tmp_path):
    project, wf = _project_with_timing(
        tmp_path,
        {"description": "AES block cipher encryption and decryption",
         "features": ["128-bit key schedule", "S-box rounds"]},
        {"protocol_overview": {"half_duplex": True}},
    )
    report = project / "gate.json"
    r = _run([str(wf), "--json", str(report)])
    doc = json.loads(report.read_text())
    assert r.returncode != 0, (r.stdout, r.stderr, doc)
    assert doc["verdict"] != "VACUOUS_PASS", doc
