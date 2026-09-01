#!/usr/bin/env python3
"""Typed clock/reset facts must reach L8's release-document consumer field."""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
sys.path.insert(0, str(_PROGRAMS))

import l8_clock_reset_waveform_emit as EMIT  # noqa: E402
import _atomic_artefact as A  # noqa: E402
import phase1_doc_one_shot_runner as RUNNER  # noqa: E402

HELPER = "_post_emit_l8_clock_reset_waveform"
RUNNER_PATH = _PROGRAMS / "phase1_doc_one_shot_runner.py"


def _write(project: Path, *, clock: bool = True, reset: bool = True,
           existing=None) -> None:
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    l8 = {"doc_class": "timing_waveform", "clocks": []}
    if clock:
        l8["clocks"] = [{
            "name": "clk", "period_ns": 24, "freq_mhz": 41.6666666667,
            "pdk_scoped_target": "process_family_a",
            "evidence": {"file": "input/docs/timing.md", "line": 7},
        }]
    if existing is not None:
        l8["clock_and_reset_waveform"] = existing
    l9 = {"doc_class": "integration_spec", "clocks": [
        {"name": "clk", "edge": "posedge"}], "reset_domains": [],
        "ports": []}
    if reset:
        l9["reset_domains"] = [{
            "name": "rst", "polarity": "active_high", "sync": "unknown",
            "extraction_strategy": "typed_reset_fixture",
        }]
        l9["ports"] = [{
            "name": "rst", "description":
            "Synchronous active-high reset; state clears within one cycle."}]
    (docs / "L8_TIMING_WAVEFORM.json").write_text(
        json.dumps(l8), encoding="utf-8")
    (docs / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps(l9), encoding="utf-8")


def _l8(project: Path) -> dict:
    return json.loads((project / EMIT.L8_REL).read_text(encoding="utf-8"))


def test_typed_clock_and_reset_reach_release_doc_field(tmp_path):
    _write(tmp_path)
    assert getattr(RUNNER, HELPER)(tmp_path) == 1
    value = _l8(tmp_path)["clock_and_reset_waveform"]
    assert value["clocks"][0]["period_ns"] == 24
    assert value["clocks"][0]["edge"] == "posedge"
    assert value["resets"][0]["polarity"] == "active_high"
    assert "Synchronous active-high" in value["resets"][0]["port_description"]
    assert value["derived_from"] == [EMIT.L8_REL, EMIT.L9_REL]


@pytest.mark.parametrize("clock,reset", [(False, True), (True, False)])
def test_one_sided_fact_set_is_named_skip_and_writes_nothing(
        tmp_path, capsys, clock, reset):
    _write(tmp_path, clock=clock, reset=reset)
    path = tmp_path / EMIT.L8_REL
    before = path.read_bytes()
    assert getattr(RUNNER, HELPER)(tmp_path) == 0
    assert "L8 clock/reset waveform: SKIPPED" in capsys.readouterr().out
    assert path.read_bytes() == before


def test_protocol_specific_existing_waveform_wins(tmp_path):
    existing = {"ACLK": "rising edge", "ARESETn": "active low"}
    _write(tmp_path, existing=existing)
    assert getattr(RUNNER, HELPER)(tmp_path) == 0
    assert _l8(tmp_path)["clock_and_reset_waveform"] == existing


def test_empty_primary_lists_fall_through_to_typed_aliases(tmp_path):
    _write(tmp_path)
    l8 = _l8(tmp_path)
    l8["clock_domains"] = l8["clocks"]
    l8["clocks"] = []
    (tmp_path / EMIT.L8_REL).write_text(json.dumps(l8), encoding="utf-8")
    l9_path = tmp_path / EMIT.L9_REL
    l9 = json.loads(l9_path.read_text(encoding="utf-8"))
    l9["resets"] = l9["reset_domains"]
    l9["reset_domains"] = []
    l9_path.write_text(json.dumps(l9), encoding="utf-8")

    assert getattr(RUNNER, HELPER)(tmp_path) == 1
    waveform = _l8(tmp_path)["clock_and_reset_waveform"]
    assert waveform["clocks"][0]["period_ns"] == 24
    assert waveform["resets"][0]["polarity"] == "active_high"


def test_unreadable_layer_is_error_not_successful_zero(tmp_path):
    _write(tmp_path)
    (tmp_path / EMIT.L9_REL).write_text("{broken", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unreadable"):
        getattr(RUNNER, HELPER)(tmp_path)
    assert EMIT.main([str(tmp_path)]) == 1


def test_cli_report_appears_only_after_an_atomic_write(tmp_path, monkeypatch):
    """The report writer still runs, and an interrupted first write is absent."""
    existing = {"clock": "rising edge", "reset": "active high"}
    _write(tmp_path, existing=existing)
    complete = tmp_path / "reports" / "complete.json"
    assert EMIT.main([str(tmp_path), "--json", str(complete)]) == 0
    assert json.loads(complete.read_text(encoding="utf-8"))["tool"] == EMIT.TOOL

    def die(*_args, **_kwargs):
        raise OSError("simulated interruption before atomic rename")

    doomed = tmp_path / "reports" / "doomed.json"
    monkeypatch.setattr(A.os, "fsync", die)
    try:
        rc = EMIT.main([str(tmp_path), "--json", str(doomed)])
    except OSError as exc:
        outcome = ("raised", str(exc))
    else:
        outcome = ("returned", rc)
    assert outcome[0] == "raised", outcome
    assert not doomed.exists()
    assert not A.temp_name_for(doomed).exists()


def test_runner_calls_projection_after_protocol_overlay():
    tree = ast.parse(RUNNER_PATH.read_text(encoding="utf-8"))
    main = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    ours = [n.lineno for n in ast.walk(main)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == HELPER]
    overlays = [n.lineno for n in ast.walk(main)
                if isinstance(n, ast.Call)
                and getattr(n.func, "attr", getattr(n.func, "id", None))
                in ("apply_spi_synth", "_apply_spi")]
    coverage = [n.lineno for n in ast.walk(main)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "emit_coverage_report"]
    assert ours, f"{HELPER} is defined but not called by main()"
    assert overlays, "protocol overlay call disappeared; ordering test vacuous"
    assert coverage, "coverage report call disappeared; ordering test vacuous"
    assert min(ours) > max(overlays), (
        "generic projection ran before a protocol-specific waveform producer")
    assert max(ours) < min(coverage), (
        "coverage report ran before the final L8 projection and graded stale "
        "L-document bytes")
