#!/usr/bin/env python3
"""Tests for GitHub issue #469 — field-agent residual of #461.

#461 made the single-snapshot consistency logic in
`programs/final_report_generate.py` correct, but on large run dirs
(observed ~256 MB, standalone `flow_compliance_check.py` >200 s, rc=124)
the internal-audit subprocess's hard-coded 180 s timeout fired and the
report degraded to `Overall: UNKNOWN` with counts 0/0 — indistinguishable
from a never-audited project.

The fix (this version):

  (1) the `_run_audit` timeout is configurable — CLI `--audit-timeout`,
      env `VIBE_IC_AUDIT_TIMEOUT_S`, else a raised size-adaptive default
      (`AUDIT_TIMEOUT_DEFAULT_S`, +headroom over a size threshold);

  (2) when the timeout DOES fire the verdict reads the NAMED
      `AUDIT_TIMEOUT` (never `UNKNOWN`), and the previous summary's
      snapshot marker is preserved so a reader can tell 審不完 (timed
      out) from 沒審 (never audited).

Acceptance (verbatim from the issue): a run dir whose audit exceeds the
(test-shrunk) timeout regenerates a summary whose verdict is the named
AUDIT_TIMEOUT, not UNKNOWN; small run dirs keep real Overall verdicts.

Each fixed-path test is paired with a regression guard for the prior
correct behavior. Conventions follow
programs/tests/test_v0_2_95_issue461_final_summary.py (sys.path.insert
import pattern + subprocess/in-process CLI invocation).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import final_report_generate as g  # noqa: E402
import _path_layout as _pl  # noqa: E402

PROG = PROGRAMS / "final_report_generate.py"


def _summary_text(project: Path) -> str:
    return (project / "reports" / "final_summary.md").read_text()


def _write_slow_compliance_stub(tmp_path: Path, sleep_s: float = 30.0) -> Path:
    """A stub that mimics flow_compliance_check.py but sleeps longer than
    any test-shrunk timeout, so the subprocess deterministically times
    out (no dependence on a real 256 MB run dir / wall-clock luck)."""
    stub = tmp_path / "slow_compliance_stub.py"
    stub.write_text(textwrap.dedent(f"""\
        import time, sys
        time.sleep({sleep_s})
        print("Overall: PASS")
        sys.exit(0)
    """))
    return stub


def _write_fast_compliance_stub(tmp_path: Path, overall: str = "PASS") -> Path:
    """A stub that returns immediately with a real Overall verdict — the
    small-run-dir baseline."""
    stub = tmp_path / "fast_compliance_stub.py"
    stub.write_text(textwrap.dedent(f"""\
        import sys
        print("Overall: {overall}")
        print("Steps: 1/1")
        sys.exit(0)
    """))
    return stub


# ────────────────────────────────────────────────────────────────────
# Acceptance — timeout regenerates a summary whose verdict is the NAMED
# AUDIT_TIMEOUT, never UNKNOWN.
# ────────────────────────────────────────────────────────────────────

def test_run_audit_timeout_yields_named_verdict(tmp_path, monkeypatch):
    """FIXED PATH (unit): when the compliance subprocess exceeds the
    timeout, `_run_audit` returns the NAMED AUDIT_TIMEOUT verdict, not
    UNKNOWN. We point the tool at a sleeping stub and shrink the timeout
    so the timeout deterministically fires."""
    stub = _write_slow_compliance_stub(tmp_path)
    monkeypatch.setattr(g, "COMPLIANCE_TOOL", stub)
    text, overall = g._run_audit(tmp_path, timeout_s=1)
    assert overall == g.AUDIT_TIMEOUT_VERDICT == "AUDIT_TIMEOUT"
    assert overall != "UNKNOWN"
    # The audit text itself parses to AUDIT_TIMEOUT (the Overall: line).
    assert "Overall: AUDIT_TIMEOUT" in text


def test_end_to_end_summary_verdict_is_audit_timeout_not_unknown(
        tmp_path, monkeypatch):
    """ACCEPTANCE end-to-end: regenerating the summary when the audit
    exceeds the (test-shrunk) timeout writes `Overall: AUDIT_TIMEOUT`
    into the report — NOT `Overall: UNKNOWN`."""
    stub = _write_slow_compliance_stub(tmp_path)
    monkeypatch.setattr(g, "COMPLIANCE_TOOL", stub)
    rc = g.main([str(tmp_path), "--audit-timeout", "1"])
    assert rc == 0
    text = _summary_text(tmp_path)
    assert "**`Overall: AUDIT_TIMEOUT`**" in text
    assert "**`Overall: UNKNOWN`**" not in text
    # The reader-facing distinction 審不完 vs 沒審 is surfaced explicitly.
    assert "審不完" in text and "沒審" in text


def test_env_var_shrinks_timeout_and_fires(tmp_path, monkeypatch):
    """FIXED PATH: VIBE_IC_AUDIT_TIMEOUT_S is honored. A 1 s env budget
    against a 30 s stub times out → AUDIT_TIMEOUT verdict."""
    stub = _write_slow_compliance_stub(tmp_path)
    monkeypatch.setattr(g, "COMPLIANCE_TOOL", stub)
    monkeypatch.setenv(g.AUDIT_TIMEOUT_ENV, "1")
    text, overall = g._run_audit(tmp_path)  # no explicit override
    assert overall == "AUDIT_TIMEOUT"


# ────────────────────────────────────────────────────────────────────
# Preserve the previous snapshot — 審不完 (timed out) vs 沒審 (never)
# ────────────────────────────────────────────────────────────────────

def test_timeout_preserves_previous_snapshot_marker(tmp_path, monkeypatch):
    """FIXED PATH: when a prior clean summary exists, a subsequent
    AUDIT_TIMEOUT report carries the PRIOR snapshot marker so a reader
    can see the last point at which the design audited cleanly. This is
    the 審不完-vs-沒審 distinction the issue requires."""
    # 1) First, a clean run via a fast stub writes a real marker.
    fast = _write_fast_compliance_stub(tmp_path, overall="PASS")
    monkeypatch.setattr(g, "COMPLIANCE_TOOL", fast)
    assert g.main([str(tmp_path)]) == 0
    first = _summary_text(tmp_path)
    import re
    m_prev = re.search(
        r"snapshot \S+ · audit-digest sha256:[0-9a-f]+ · overall \S+", first)
    assert m_prev, "first run did not stamp a snapshot marker"
    prev_marker = m_prev.group(0)

    # 2) Now the audit times out (large-design simulation). The new
    # report must (a) read AUDIT_TIMEOUT and (b) preserve prev_marker.
    slow = _write_slow_compliance_stub(tmp_path)
    monkeypatch.setattr(g, "COMPLIANCE_TOOL", slow)
    assert g.main([str(tmp_path), "--audit-timeout", "1"]) == 0
    second = _summary_text(tmp_path)
    assert "**`Overall: AUDIT_TIMEOUT`**" in second
    assert f"Last clean snapshot: `{prev_marker}`" in second


def test_timeout_with_no_prior_snapshot_says_so(tmp_path, monkeypatch):
    """REGRESSION/edge: a first-ever run that times out (no prior
    summary) must say 'No prior clean snapshot is available' rather than
    fabricate one — but still read AUDIT_TIMEOUT, never UNKNOWN."""
    slow = _write_slow_compliance_stub(tmp_path)
    monkeypatch.setattr(g, "COMPLIANCE_TOOL", slow)
    assert g.main([str(tmp_path), "--audit-timeout", "1"]) == 0
    text = _summary_text(tmp_path)
    assert "**`Overall: AUDIT_TIMEOUT`**" in text
    assert "No prior clean snapshot is available" in text


def test_prewrite_does_not_clobber_preserved_marker(tmp_path, monkeypatch):
    """GUARD: the #461 attestation pre-pass overwrites the canonical
    summary BEFORE the audit. The preserved-marker capture must happen
    before that pre-pass, otherwise the timeout report would lose the
    prior marker. This pins that the marker survives the pre-pass."""
    fast = _write_fast_compliance_stub(tmp_path, overall="PASS")
    monkeypatch.setattr(g, "COMPLIANCE_TOOL", fast)
    g.main([str(tmp_path)])
    import re
    prev = re.search(
        r"snapshot \S+ · audit-digest sha256:[0-9a-f]+ · overall \S+",
        _summary_text(tmp_path)).group(0)
    # Capture helper used by main() must still see it on disk pre-pass.
    captured = g._previous_snapshot_marker(tmp_path)
    assert captured == prev
    # After a timeout regen, the captured marker is what appears.
    slow = _write_slow_compliance_stub(tmp_path)
    monkeypatch.setattr(g, "COMPLIANCE_TOOL", slow)
    g.main([str(tmp_path), "--audit-timeout", "1"])
    assert f"Last clean snapshot: `{prev}`" in _summary_text(tmp_path)


# ────────────────────────────────────────────────────────────────────
# Configurable timeout — precedence CLI > env > size-adaptive default
# ────────────────────────────────────────────────────────────────────

def test_resolve_timeout_default_raised_from_180(tmp_path, monkeypatch):
    """FIXED PATH: the default is the raised AUDIT_TIMEOUT_DEFAULT_S
    (900 s here), NOT the old hard-coded 180 s, on a small run dir."""
    monkeypatch.delenv(g.AUDIT_TIMEOUT_ENV, raising=False)
    assert g.AUDIT_TIMEOUT_DEFAULT_S == 900
    assert g.AUDIT_TIMEOUT_DEFAULT_S > 180
    resolved = g._resolve_audit_timeout(tmp_path, None)
    # Small/empty dir → no size adaptation → exactly the default.
    assert resolved == g.AUDIT_TIMEOUT_DEFAULT_S


def test_resolve_timeout_explicit_beats_env(tmp_path, monkeypatch):
    """FIXED PATH: an explicit CLI value wins over the env var, which in
    turn wins over the default."""
    monkeypatch.setenv(g.AUDIT_TIMEOUT_ENV, "300")
    assert g._resolve_audit_timeout(tmp_path, 42) == 42      # explicit
    assert g._resolve_audit_timeout(tmp_path, None) == 300   # env


def test_resolve_timeout_rejects_nonpositive(tmp_path, monkeypatch):
    """REGRESSION GUARD: a ≤0 explicit/env value is ignored and the next
    source is used (never a 0 s timeout that would always fire)."""
    monkeypatch.delenv(g.AUDIT_TIMEOUT_ENV, raising=False)
    assert g._resolve_audit_timeout(tmp_path, 0) == g.AUDIT_TIMEOUT_DEFAULT_S
    assert g._resolve_audit_timeout(tmp_path, -5) == g.AUDIT_TIMEOUT_DEFAULT_S
    monkeypatch.setenv(g.AUDIT_TIMEOUT_ENV, "0")
    assert g._resolve_audit_timeout(tmp_path, None) == g.AUDIT_TIMEOUT_DEFAULT_S
    monkeypatch.setenv(g.AUDIT_TIMEOUT_ENV, "not-an-int")
    assert g._resolve_audit_timeout(tmp_path, None) == g.AUDIT_TIMEOUT_DEFAULT_S


def test_resolve_timeout_size_adaptive(tmp_path, monkeypatch):
    """FIXED PATH: the computed default scales up with run-dir size past
    the threshold (the ~256 MB observation in the issue), without
    touching flow_compliance semantics. We monkeypatch the measured size
    so the test is fast and deterministic."""
    monkeypatch.delenv(g.AUDIT_TIMEOUT_ENV, raising=False)
    big = g.AUDIT_SIZE_ADAPT_THRESHOLD_BYTES + 256 * 1024 * 1024  # +256 MiB
    monkeypatch.setattr(g, "_dir_size_bytes", lambda *a, **k: big)
    resolved = g._resolve_audit_timeout(tmp_path, None)
    expected = (g.AUDIT_TIMEOUT_DEFAULT_S
                + 256 * g.AUDIT_SIZE_ADAPT_S_PER_MIB)
    assert resolved == min(expected, g.AUDIT_TIMEOUT_CAP_S)
    assert resolved > g.AUDIT_TIMEOUT_DEFAULT_S


def test_resolve_timeout_capped(tmp_path, monkeypatch):
    """REGRESSION GUARD: even an enormous run dir / huge env value never
    exceeds the cap (no unbounded hang)."""
    monkeypatch.setattr(g, "_dir_size_bytes", lambda *a, **k: 1 << 50)
    assert g._resolve_audit_timeout(tmp_path, None) == g.AUDIT_TIMEOUT_CAP_S
    monkeypatch.delenv(g.AUDIT_TIMEOUT_ENV, raising=False)
    assert g._resolve_audit_timeout(tmp_path, 10 ** 9) == g.AUDIT_TIMEOUT_CAP_S


# ────────────────────────────────────────────────────────────────────
# REGRESSION GUARDS — small run dirs keep REAL Overall verdicts; the
# never-audited path stays UNKNOWN (and is distinct from timeout).
# ────────────────────────────────────────────────────────────────────

def test_small_run_dir_keeps_real_overall(tmp_path, monkeypatch):
    """ACCEPTANCE regression: a small run dir whose audit finishes well
    within the timeout keeps its REAL Overall verdict (PASS here) — the
    timeout machinery must not infect the happy path."""
    fast = _write_fast_compliance_stub(tmp_path, overall="PASS")
    monkeypatch.setattr(g, "COMPLIANCE_TOOL", fast)
    text, overall = g._run_audit(tmp_path, timeout_s=g.AUDIT_TIMEOUT_DEFAULT_S)
    assert overall == "PASS"
    rc = g.main([str(tmp_path)])
    assert rc == 0
    summary = _summary_text(tmp_path)
    assert "**`Overall: PASS`**" in summary
    assert "AUDIT_TIMEOUT" not in summary.split("## Verdict", 1)[1].split("##", 1)[0]


def test_real_compliance_tool_small_dir_not_timeout_not_unknown(tmp_path):
    """REGRESSION (no stub): running the REAL flow_compliance_check.py on
    a tiny empty dir produces a concrete Overall (FAIL on an empty dir),
    never AUDIT_TIMEOUT and never UNKNOWN, under the generous default."""
    rc = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path)],
        capture_output=True, text=True).returncode
    assert rc == 0
    text = _summary_text(tmp_path)
    assert "**`Overall: AUDIT_TIMEOUT`**" not in text
    assert "**`Overall: UNKNOWN`**" not in text


def test_no_audit_path_stays_unknown_not_timeout(tmp_path):
    """REGRESSION GUARD: --no-audit (沒審 — audit never run) must stay
    UNKNOWN, NOT AUDIT_TIMEOUT. The two reasons-for-no-snapshot are kept
    distinct (the whole point of the named verdict)."""
    rc = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--no-audit"],
        capture_output=True, text=True).returncode
    assert rc == 0
    text = _summary_text(tmp_path)
    assert "**`Overall: UNKNOWN`**" in text
    assert "**`Overall: AUDIT_TIMEOUT`**" not in text
    assert g.AUDIT_NOT_RUN_VERDICT == "UNKNOWN"
    assert g.AUDIT_TIMEOUT_VERDICT != g.AUDIT_NOT_RUN_VERDICT


def test_missing_compliance_tool_is_unknown_not_timeout(tmp_path, monkeypatch):
    """REGRESSION GUARD: a missing compliance tool (沒審) degrades to
    UNKNOWN, never AUDIT_TIMEOUT."""
    monkeypatch.setattr(g, "COMPLIANCE_TOOL", tmp_path / "does_not_exist.py")
    text, overall = g._run_audit(tmp_path)
    assert overall == "UNKNOWN"
    assert overall != "AUDIT_TIMEOUT"


def test_non_timeout_exception_is_unknown(tmp_path, monkeypatch):
    """REGRESSION GUARD: a non-timeout subprocess failure still degrades
    to UNKNOWN (only a genuine STALL maps to AUDIT_TIMEOUT).

    THE SEAM THE CODE ACTUALLY LAUNCHES THROUGH moved (#1444-class fix):
    `_run_audit` no longer calls `subprocess.run` at all — it calls
    `_watchdog.run_host_supervised`, so faking `g.subprocess.run` intercepts
    nothing and the REAL supervisor ran the stub for real, returning its
    actual PASS instead of exercising this exception path at all (measured:
    this test silently went green on 'PASS' rather than red on a wrong
    verdict, which is its own lesson about faking below the real seam)."""
    def _boom(*a, **k):
        raise RuntimeError("subprocess blew up")
    monkeypatch.setattr(g._wd, "run_host_supervised", _boom)
    # COMPLIANCE_TOOL must exist to reach the subprocess call.
    stub = _write_fast_compliance_stub(tmp_path)
    monkeypatch.setattr(g, "COMPLIANCE_TOOL", stub)
    text, overall = g._run_audit(tmp_path)
    assert overall == "UNKNOWN"
    assert "AUDIT_TIMEOUT" not in overall


# ────────────────────────────────────────────────────────────────────
# Cross-cutting: chip-agnostic output + canonical sections intact even
# on the AUDIT_TIMEOUT path.
# ────────────────────────────────────────────────────────────────────

def test_timeout_report_still_chip_agnostic_and_complete(tmp_path, monkeypatch):
    """REGRESSION GUARD: the AUDIT_TIMEOUT report must still be
    chip-agnostic and render every canonical section (the timeout note
    must not break the document)."""
    slow = _write_slow_compliance_stub(tmp_path)
    monkeypatch.setattr(g, "COMPLIANCE_TOOL", slow)
    g.main([str(tmp_path), "--audit-timeout", "1"])
    text = _summary_text(tmp_path)
    for sec in ("## Verdict", "## Stage breakdown",
                "## SHA-256 Attestation", "## Self-attestation",
                "## Chip-specific addendum"):
        assert sec in text, f"missing section {sec}"
    forbidden = ["EXAMPLE_CHIP", "Apple", "Lightning", "byte[6]", "0xF2",
                 "bandgap", "tsmc", "sky130"]
    leaked = [w for w in forbidden if w in text]
    assert not leaked, f"chip-specific terms leaked: {leaked}"
