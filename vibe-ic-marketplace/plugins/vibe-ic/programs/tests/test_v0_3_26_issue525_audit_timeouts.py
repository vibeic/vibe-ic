"""v0.3.26 — ORGANIC #525: hardcoded 300s timeouts false-FAILed large SoCs.

A 155k-filler project's flow_compliance legitimately needs ~8-9 min; the
fixed 300s caps killed it mid-run and surfaced the kill as a plain FAIL with
empty detail (and phase23_completion_self_audit_check CRASHED outright on
TimeoutExpired). The fix:
  * ONE shared size-adaptive resolver in _path_layout (audit_timeout_s:
    900s base, +4s/MiB over 128MiB, cap 3600s, env VIBE_IC_AUDIT_TIMEOUT_S)
    consumed by final_report_generate (#469 site), phase2 step_final_audit,
    phase23_completion_self_audit_check and emit_final_summary's outer cap;
  * a per-gate budget (gate_timeout_s: 900s default, env
    VIBE_IC_GATE_TIMEOUT_S) for flow_compliance program_exit_zero gates
    (field evidence: reset_dependency_check ~6 min on a 7.5MB netlist);
  * TIMEOUT ≠ verdict: every timeout path now NAMES itself (AUDIT_TIMEOUT /
    "NOT a verdict") instead of masquerading as a substantive FAIL;
  * perf: _evidence_integrity_scan reads only the 8KiB head (was: whole
    multi-hundred-MB artifact then slice);
  * discovery-glob hygiene (field round-4 adjacent finding): stale reports
    under backup/hidden dirs no longer pollute eda_report_audit discovery.

NEGATIVE no-leak: a REAL audit FAIL (Overall: FAIL) still FAILs plainly.

chip-AGNOSTIC: synthetic projects/fixtures only.
"""
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import _path_layout as _pl  # noqa: E402
import design_one_shot_runner as P2  # noqa: E402
import eda_report_audit as ERA  # noqa: E402


# ── shared resolvers ────────────────────────────────────────────────────────

def test_audit_timeout_small_tree_default(tmp_path, monkeypatch):
    monkeypatch.delenv(_pl.AUDIT_TIMEOUT_ENV, raising=False)
    assert _pl.audit_timeout_s(tmp_path) == _pl.AUDIT_TIMEOUT_DEFAULT_S == 900


def test_audit_timeout_env_override_and_cap(tmp_path, monkeypatch):
    monkeypatch.setenv(_pl.AUDIT_TIMEOUT_ENV, "1234")
    assert _pl.audit_timeout_s(tmp_path) == 1234
    monkeypatch.setenv(_pl.AUDIT_TIMEOUT_ENV, "999999")
    assert _pl.audit_timeout_s(tmp_path) == _pl.AUDIT_TIMEOUT_CAP_S == 3600


def test_audit_timeout_size_adaptive_and_capped(tmp_path, monkeypatch):
    monkeypatch.delenv(_pl.AUDIT_TIMEOUT_ENV, raising=False)
    big = _pl.AUDIT_SIZE_ADAPT_THRESHOLD_BYTES + 256 * 1024 * 1024
    got = _pl.audit_timeout_s(tmp_path, size_fn=lambda *a, **k: big)
    assert got == 900 + 256 * _pl.AUDIT_SIZE_ADAPT_S_PER_MIB
    got = _pl.audit_timeout_s(tmp_path, size_fn=lambda *a, **k: 1 << 50)
    assert got == _pl.AUDIT_TIMEOUT_CAP_S


def test_gate_timeout_default_env_cap(monkeypatch):
    monkeypatch.delenv(_pl.GATE_TIMEOUT_ENV, raising=False)
    assert _pl.gate_timeout_s() == _pl.GATE_TIMEOUT_DEFAULT_S == 900
    monkeypatch.setenv(_pl.GATE_TIMEOUT_ENV, "120")
    assert _pl.gate_timeout_s() == 120
    monkeypatch.setenv(_pl.GATE_TIMEOUT_ENV, "999999")
    assert _pl.gate_timeout_s() == _pl.AUDIT_TIMEOUT_CAP_S


# ── phase2 step_final_audit: TIMEOUT is named, not a bare FAIL ─────────────


# ── flow_compliance per-gate cap: named timeout + env budget ───────────────

#: A `run_host_supervised` reporting that the gate's process tree made no
#: forward progress. The shipped type from the shipped module, not a duck.


# ── phase23 self-audit: no crash, named AUDIT_TIMEOUT overall ──────────────


# ── emit_final_summary outer cap no longer defeats the inner budget ────────

def test_outer_summary_budget_exceeds_inner(tmp_path):
    # the old fixed 240s outer cap was SMALLER than #469's 900s inner
    # budget; the default must now be inner + margin.
    inner = _pl.audit_timeout_s(tmp_path)
    assert inner + _pl.OUTER_TIMEOUT_MARGIN_S > 240
    assert _pl.OUTER_TIMEOUT_MARGIN_S > 0


# ── evidence-scan head-read keeps correctness ──────────────────────────────


# ── discovery-glob hygiene (#525 round-4 adjacent finding) ─────────────────

def test_discover_skips_backup_and_hidden_dirs(tmp_path):
    live = tmp_path / "reports" / "phase3"
    live.mkdir(parents=True)
    (live / "antenna.rpt").write_text("live antenna report, 0 violations")
    stale1 = tmp_path / "_stale_bak"
    stale1.mkdir()
    (stale1 / "antenna.rpt").write_text("STALE: 56 violations")
    stale2 = tmp_path / "phase3" / "backup"
    stale2.mkdir(parents=True)
    (stale2 / "old_lvs.rpt").write_text("STALE lvs")
    hidden = tmp_path / ".snapshots"
    hidden.mkdir()
    (hidden / "antenna.rpt").write_text("STALE hidden")
    found = ERA._discover(tmp_path, ["*antenna*.rpt", "*lvs*.rpt"])
    rels = sorted(str(p.relative_to(tmp_path)) for p in found)
    assert rels == ["reports/phase3/antenna.rpt"], rels


def test_discover_negative_normal_nested_dirs_kept(tmp_path):
    # NEGATIVE: boundary-aware tokens — "golden"/"bakery" are NOT backups.
    d1 = tmp_path / "phase3" / "golden_runs"
    d1.mkdir(parents=True)
    (d1 / "antenna.rpt").write_text("legit")
    d2 = tmp_path / "bakery"
    d2.mkdir()
    (d2 / "lvs.rpt").write_text("legit")
    found = ERA._discover(tmp_path, ["*antenna*.rpt", "*lvs*.rpt"])
    assert len(found) == 2


# ── adversarial-review regressions (v0.3.26 pre-push round) ────────────────


def test_run_timeout_partial_stdout_is_str(tmp_path):
    import sys as _sys
    rc, out, err = P2._run(
        [_sys.executable, "-c",
         "import time; print('x'*100000, flush=True); time.sleep(30)"],
        timeout=1)
    assert rc == 124
    assert isinstance(out, str)
