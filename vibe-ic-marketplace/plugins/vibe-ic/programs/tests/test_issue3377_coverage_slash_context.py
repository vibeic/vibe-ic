"""Regression coverage for issue #3377.

Slash separated identifiers become mandatory pin alias coverage only when the
source text presents them as a pin, pad, port, signal, or alias declaration.
Ordinary policy prose must not grow the Phase 1 coverage denominator.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]
PRODUCER = PROGRAMS / "phase1_coverage_report_gen.py"
CONSUMER = PROGRAMS / "phase1_coverage_report_present_check.py"


def _write_project(project: Path, text: str, l1: dict) -> None:
    source = project / "phase1" / "input_doc"
    docs = project / "phase1" / "generated_docs"
    source.mkdir(parents=True)
    docs.mkdir(parents=True)
    (source / "spec.txt").write_text(text)
    (docs / "L1_DATASHEET.json").write_text(json.dumps(l1))


def _l1(*, display_alias: bool, policy_tokens=()) -> dict:
    pin = {
        "name": "GPIO0",
        "aliases": ["SCL"],
        "direction": "input",
        "description": "Serial clock input",
    }
    if display_alias:
        pin["display_label"] = "GPIO0/SCL"
    return {
        "schema_version": 1,
        "ic_name": "neutral_alias_intake",
        "pin_table": [pin],
        "policy_topics": list(policy_tokens),
    }


def _run(program: Path, project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(program), str(project)],
        capture_output=True, text=True,
    )


def _auto_items(project: Path) -> list[dict]:
    payload = json.loads(
        (project / "phase1" / "extraction_patterns.auto.json").read_text())
    return payload["spec.txt"]


def test_normal_entry_keeps_pin_alias_and_ignores_policy_slash(tmp_path):
    project = tmp_path / "project"
    _write_project(
        project,
        "| Pin | Function |\n"
        "| --- | --- |\n"
        "| GPIO0/SCL | Serial clock input |\n\n"
        "The CONFIG/fallback policy is selected by the deployment layer.\n",
        _l1(display_alias=True, policy_tokens=("CONFIG",)),
    )

    produced = _run(PRODUCER, project)
    assert produced.returncode == 0, produced.stdout + produced.stderr
    consumed = _run(CONSUMER, project)
    assert consumed.returncode == 0, consumed.stdout + consumed.stderr

    aliases = {
        item["literal"] for item in _auto_items(project)
        if item["label"] == "auto-discovered (pin_alias)"
    }
    assert "GPIO0/SCL" in aliases
    assert "CONFIG/fallback" not in aliases


def test_slash_identifier_shape_without_pin_context_is_not_an_alias(tmp_path):
    project = tmp_path / "project"
    _write_project(
        project,
        "Signal processing selects MODE/default as a policy choice. "
        "SOURCE/derived is a precedence rule.\n",
        _l1(display_alias=True, policy_tokens=("MODE", "SOURCE")),
    )

    produced = _run(PRODUCER, project)
    assert produced.returncode == 0, produced.stdout + produced.stderr
    aliases = {
        item["literal"] for item in _auto_items(project)
        if item["label"] == "auto-discovered (pin_alias)"
    }
    assert aliases == set()


def test_explicit_signal_alias_declaration_remains_discoverable(tmp_path):
    project = tmp_path / "project"
    _write_project(
        project,
        "Signal naming aliases: GPIO0/SCL\n",
        _l1(display_alias=True),
    )

    produced = _run(PRODUCER, project)
    assert produced.returncode == 0, produced.stdout + produced.stderr
    aliases = {
        item["literal"] for item in _auto_items(project)
        if item["label"] == "auto-discovered (pin_alias)"
    }
    assert aliases == {"GPIO0/SCL"}


def test_missing_true_pin_alias_remains_a_coverage_failure(tmp_path):
    project = tmp_path / "project"
    _write_project(
        project,
        "| Pin | Function |\n"
        "| --- | --- |\n"
        "| GPIO0/SCL | Serial clock input |\n",
        _l1(display_alias=False),
    )

    produced = _run(PRODUCER, project)
    assert produced.returncode == 0, produced.stdout + produced.stderr
    consumed = _run(CONSUMER, project)
    assert consumed.returncode == 1, consumed.stdout + consumed.stderr
    report = json.loads(
        (project / "reports" / "phase1" /
         "extraction_coverage_report.json").read_text())
    missing = report["per_doc"][0]["missing_literals"]
    assert {
        "literal": "GPIO0/SCL",
        "label": "auto-discovered (pin_alias)",
    } in missing
