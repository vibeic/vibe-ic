#!/usr/bin/env python3
"""vibe-ic#1705 — a ratchet cannot compare against a baseline it never read.

All four programs below derive their verdict from ``current - baseline``.  The
load-bearing distinction is therefore between an explicitly measured empty
set and no measurement at all:

* absent / unreadable / truncated baseline -> rc 2, NOT CHECKED, path named;
* an explicitly valid empty baseline -> a first offender is NEW and rc 1.

The four sites, in the order the issue probed them, and what each did when the
baseline was moved aside on `main` ee849c19e (re-measured at v1.10.75):

    flow_gate_enforcement_audit.py           FABRICATED 116 findings, rc 1
    checker_execution_wiring_audit.py        FABRICATED  31 findings, rc 1
    silent_decline_audit.py                  PASSED SILENTLY over 15,   rc 0
    tracked_symlink_target_present_check.py  INCONCLUSIVE in this tree —
        its corpus moved to its own repository at v1.10.56, so the run reaches
        NO_CORPUS before any verdict. Given the corpus it did not have (built
        here as a synthetic git repo), it FABRICATES too: rc 0 with the
        register, rc 1 and "1 NEW committed pointer(s)" with it absent.

The pairs exercise the programs through their CLIs on small synthetic trees.
That keeps the control behavioural: before the fix the first half returns rc 1
(or, for `silent_decline_audit`, rc 0) and misattributes the pre-existing
offender, while the second half already proves the ratchet must keep its teeth.
An over-correction that simply refuses everything fails that second half.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


PROGRAMS = Path(__file__).resolve().parent.parent
FLOW_AUDIT = PROGRAMS / "flow_gate_enforcement_audit.py"
WIRING_AUDIT = PROGRAMS / "checker_execution_wiring_audit.py"


def _baseline(path: Path, state: str) -> Path:
    if state == "unreadable":
        # A directory exists but cannot be read as the baseline artefact.  This
        # is deterministic under every test uid, unlike chmod-based fixtures.
        path.mkdir()
    elif state == "truncated":
        path.write_text('{"known": [', encoding="utf-8")
    elif state == "invalid_utf8":
        path.write_bytes(b'{"known": ["sample_check.py\xff"]}')
    elif state == "invalid_schema":
        path.write_text('{"known": [null]}', encoding="utf-8")
    else:
        assert state == "absent"
        assert not path.exists()
    return path




def _wiring_tree(root: Path) -> None:
    plugin = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    for rel in ("programs/tests", "flow", "skills", "agents", "commands",
                "tests"):
        (plugin / rel).mkdir(parents=True, exist_ok=True)
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / "tools").mkdir()
    (plugin / "programs" / "sample_check.py").write_text(
        "def main():\n    return 0\n", encoding="utf-8")
    (plugin / "programs" / "tests" / "test_sample_check.py").write_text(
        "import sample_check\n", encoding="utf-8")


def _run(*argv: str) -> subprocess.CompletedProcess[str]:
    # These are synthetic CLI fixtures.  A landing/corpus runner legitimately
    # exports the live-corpus pointer for the surrounding suite, but letting
    # that pointer override this test's explicit ``--root``/``--subdir`` makes
    # the child inspect the real corpus instead of the repository built above.
    # Keep the parent binding intact and remove it only from this child.
    env = os.environ.copy()
    env.pop("VIBE_IC_BENCHMARK_DATA", None)
    env.pop("GATEKEEPER_BENCHMARK_DATA_SHA", None)
    return subprocess.run(
        [sys.executable, *argv], capture_output=True, text=True, check=False,
        env=env)








@pytest.mark.parametrize(
    "state", ("absent", "unreadable", "truncated", "invalid_utf8",
              "invalid_schema"))
def test_checker_wiring_audit_refuses_a_baseline_it_cannot_read(
        tmp_path: Path, state: str) -> None:
    _wiring_tree(tmp_path)
    baseline = _baseline(tmp_path / "wiring-baseline.json", state)

    got = _run(str(WIRING_AUDIT), "--repo-root", str(tmp_path),
               "--baseline", str(baseline))
    transcript = got.stdout + got.stderr

    assert got.returncode == 2, transcript
    assert "NOT CHECKED" in transcript, transcript
    assert str(baseline) in transcript, transcript
    assert "[PASS]" not in transcript and "[FAIL]" not in transcript, transcript


def test_checker_wiring_audit_keeps_an_explicit_empty_measurement_blocking(
        tmp_path: Path) -> None:
    _wiring_tree(tmp_path)
    baseline = tmp_path / "wiring-baseline.json"
    baseline.write_text(json.dumps({"known": []}), encoding="utf-8")

    got = _run(str(WIRING_AUDIT), "--repo-root", str(tmp_path),
               "--baseline", str(baseline))
    transcript = got.stdout + got.stderr

    assert got.returncode == 1, transcript
    assert "[FAIL]" in transcript and "sample_check.py" in transcript, transcript
    assert "NOT CHECKED" not in transcript, transcript


def test_checker_wiring_audit_does_not_overwrite_a_truncated_measurement(
        tmp_path: Path) -> None:
    _wiring_tree(tmp_path)
    baseline = tmp_path / "wiring-baseline.json"
    truncated = '{"known": ['
    baseline.write_text(truncated, encoding="utf-8")

    got = _run(str(WIRING_AUDIT), "--repo-root", str(tmp_path),
               "--baseline", str(baseline), "--write-baseline")
    transcript = got.stdout + got.stderr

    assert got.returncode == 2, transcript
    assert "NOT CHECKED" in transcript and str(baseline) in transcript, transcript
    assert baseline.read_text(encoding="utf-8") == truncated


# ───────────────────────────────────────────────────────────────────────────
# silent_decline_audit — the OTHER direction of the same defect.
#
# The two audits above FABRICATE: with nothing to subtract they report the
# whole inherited population as regressions. This one did the reverse. Its
# comparison was gated behind `--ratchet`, so the DEFAULT invocation printed
# every finding it had just measured and returned 0 without opening the
# baseline at all — and returned the same 0 with the baseline present. rc 0
# therefore meant both "compared, and at or below the record" and "never
# compared", which is a pass over a comparison that never happened.
#
# Probed on main ee849c19e (and reproduced at v1.10.75): 15 live findings,
# rc 0 with the baseline in place, rc 0 with it moved aside.
# ───────────────────────────────────────────────────────────────────────────

SILENT_AUDIT = PROGRAMS / "silent_decline_audit.py"

# One remedy-semantic call whose decline path records nothing. `loosen` is in
# the audit's own remedy vocabulary and the `if ... is not None:` has no else,
# which is the exact shape #313 §6 defines.
_ONE_SILENT_DECLINE = """\
def loosen_die(x):
    return None


def run(x):
    lf = loosen_die(x)
    if lf is not None:
        apply_it(lf)
"""
















# ───────────────────────────────────────────────────────────────────────────
# tracked_symlink_target_present_check — the site #1705 could only record as
# INCONCLUSIVE.
#
# Its register is read before the population, and an UNREADABLE one already
# refused with the words "a missing register is not an empty one". An ABSENT
# one skipped that branch entirely and left `recorded` at `[]` — the value
# that means measured-and-empty — so `hard - recorded` reported every
# inherited pointer as NEW.
#
# The published corpus left this repository at v1.10.56, so a run here reaches
# NO_CORPUS before ever computing a verdict, which is why the issue's probe saw
# rc 2 with and without the register and could not tell. These tests build the
# corpus the probe did not have, and the fabrication is immediate.
# ───────────────────────────────────────────────────────────────────────────

SYMLINK_CHECK = PROGRAMS / "tracked_symlink_target_present_check.py"
