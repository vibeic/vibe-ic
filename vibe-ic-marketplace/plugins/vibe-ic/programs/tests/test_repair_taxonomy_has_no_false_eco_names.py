#!/usr/bin/env python3
"""Keep RTL/post-route repair names separate from physical ECO terminology."""
from __future__ import annotations

import re
from pathlib import Path

from _plugin_tree import plugin_root


PLUGIN = plugin_root()
THIS_FILE = Path(__file__).resolve()

TEXT_SUFFIXES = {
    ".json", ".js", ".md", ".mjs", ".py", ".tcl", ".yaml", ".yml",
}

# Exact interfaces and artefacts formerly used by the two non-ECO mechanisms.
# Generic ECO is intentionally not forbidden: Design-for-ECO, spare-cell,
# metal-only and released-netlist change-order surfaces are genuine ECOs.
FORBIDDEN_RUNTIME_TOKENS = (
    "--max-eco",
    "max_eco",
    "eco_loop_iter",
    "eco_loop_remediation",
    "FAIL_ECO_INERT",
    "ECO_LOOP",
    "eco_loop_audit.py",
    "eco_status_gen.py",
    "eco_trigger_decision.py",
    "phase2.eco_loop",
    "phase3/stage3/eco",
    "eco_log.json",
    "no_eco_needed.flag",
    "no_eco_summary.json",
    "eco_trigger_decision.json",
    "eco_timing_repair.tcl",
    "eco_repair.log",
    "eco_routed.def",
    "sta_mcorner_ocv_posteco.rpt",
    "_build_eco_repair_tcl",
    "_run_eco_repair",
    "_measure_posteco_mcorner_ocv",
    "timing_eco_needed",
)

FORBIDDEN_BASENAMES = {
    "eco_loop_audit.py",
    "eco_status_gen.py",
    "eco_trigger_decision.py",
    "test_device_program_eco_guard.py",
    "test_eco_loop_audit.py",
    "test_eco_status_gen.py",
}


def _shipped_text_files():
    for path in PLUGIN.rglob("*"):
        if path == THIS_FILE or not path.is_file():
            continue
        if path.suffix.lower() in TEXT_SUFFIXES:
            yield path


def test_non_eco_runtime_tokens_do_not_return():
    findings = []
    for path in _shipped_text_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in FORBIDDEN_RUNTIME_TOKENS:
            if token in text:
                findings.append(f"{path.relative_to(PLUGIN)}: {token}")
        if re.search(r"\beco_needed\b", text):
            findings.append(f"{path.relative_to(PLUGIN)}: eco_needed")
    assert not findings, (
        "non-ECO repair interfaces/artifacts returned:\n"
        + "\n".join(findings)
    )


def test_non_eco_files_keep_their_canonical_names():
    found = sorted(
        str(path.relative_to(PLUGIN))
        for path in PLUGIN.rglob("*")
        if path.is_file() and path.name in FORBIDDEN_BASENAMES
    )
    assert not found, "misleading non-ECO filenames returned:\n" + "\n".join(found)


def test_legacy_eco_directory_is_migration_input_only():
    source = (PLUGIN / "programs" / "migrate_to_canonical_taxonomy.py").read_text(
        encoding="utf-8"
    )
    assert '"eco":                "phase3/stage3/postroute_timing_repair"' in source
    assert "Migration-only source alias" in source
