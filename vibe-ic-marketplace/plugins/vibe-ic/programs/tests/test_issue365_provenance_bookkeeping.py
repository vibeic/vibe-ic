#!/usr/bin/env python3
"""#365 — provenance bookkeeping must not assert what it never measured.

Two defects, both in the ledger that the anti-fabrication rules lean on:

1. `version` carried the EDA container's entrypoint banner ("[INFO] Final
   PATH variable: ...") instead of the tool's version line, because the
   probe took stdout line 0 and the harness speaks first.

2. Back-filled entries wrote `duration_ms: 0`. Those entries are written
   for artifacts found ON DISK — the runner never observed the invocation
   that produced them. `0` is a VALUE and reads as "took no time": a
   measurement claim with no measurement behind it.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import provenance_logger as PL  # noqa: E402


def test_365_entrypoint_banner_is_not_recorded_as_the_version():
    """THE defect: the container prints its banner before the tool speaks."""
    got = PL._capture_version(
        r"printf '[INFO] Final PATH variable: /a:/b\nYosys 0.67+26 (sha1 x)\n'")
    assert got == "Yosys 0.67+26 (sha1 x)"
    assert "PATH variable" not in got


def test_365_plain_version_output_is_unchanged():
    """NO-LEAK: a tool that prints no banner is untouched."""
    assert PL._capture_version(r"printf 'Yosys 0.67+26\n'") == "Yosys 0.67+26"


def test_365_banner_only_output_is_recorded_verbatim_not_dropped():
    """Degrade loudly: if the banner is ALL there is, record it so a reader
    sees the anomaly. Returning empty would hide it."""
    got = PL._capture_version(r"printf '[INFO] only banner\n'")
    assert got == "[INFO] only banner"


def test_365_banner_filter_is_grammar_not_a_tool_or_container_name():
    """Tool-AGNOSTIC: keyed on the bracketed-level banner GRAMMAR, so any
    harness that speaks first is handled, and no tool name is hardcoded."""
    import ast
    tree = ast.parse((_PROGRAMS / "provenance_logger.py").read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_capture_version")
    # Scan the CODE only. The docstring names `yosys --version` as an
    # illustrative example, which is documentation, not behaviour — an
    # earlier version of this test flagged it and was wrong.
    body = [n for n in fn.body
            if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                    and isinstance(n.value.value, str))]
    code = "\n".join(ast.dump(n) for n in body).lower()
    for token in ("yosys", "openroad", "klayout", "magic", "netgen",
                  "vibeic", "iic-osic", "headless", "final path"):
        assert token not in code, f"{token!r} drives the probe's behaviour"


def test_365_backfilled_entries_do_not_claim_a_measured_duration():
    """A back-filled entry must say `null` (not measured), never `0`."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    assert '"duration_ms": 0,' not in src, (
        "a back-filled provenance entry still asserts duration_ms: 0")
    n_null = src.count('"duration_ms": None,')
    n_recon = src.count('"reconstructed": True,')
    assert n_null >= 4 and n_recon >= n_null, (
        f"duration_ms=None sites={n_null}, reconstructed sites={n_recon}")


def test_365_backfilled_entries_are_marked_as_reconstructed():
    """The entry must DISCLOSE that it was reconstructed, so a reader can
    tell an observed invocation from an inferred one."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    for m in re.finditer(r'"duration_ms": None,', src):
        window = src[m.end():m.end() + 200]
        assert '"reconstructed": True' in window, (
            "a duration_ms=None entry without a reconstructed marker")


def test_365_exit_code_is_kept_because_a_consumer_reads_it():
    """Producer/consumer discipline: `provenance_check` reads `exit_code`,
    so the field stays — and the hashed artifact on disk IS evidence the
    tool produced it. Only the unmeasured DURATION was removed."""
    consumer = (_PROGRAMS / "provenance_check.py").read_text()
    assert 'e.get("exit_code"' in consumer
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    assert src.count('"exit_code": 0,') >= 4
