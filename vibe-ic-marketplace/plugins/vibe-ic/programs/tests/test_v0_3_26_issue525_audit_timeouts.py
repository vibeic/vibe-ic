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
import _progress_run as _pr  # noqa: E402
import design_one_shot_runner as P2  # noqa: E402
import flow_compliance_check as FCC  # noqa: E402
import phase23_completion_self_audit_check as SA  # noqa: E402
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

def test_final_audit_timeout_named_not_bare_fail(tmp_path, monkeypatch):
    monkeypatch.setattr(
        P2, "_run",
        lambda cmd, cwd=None, timeout=600, env=None:
            (124, "", f"TIMEOUT after {timeout}s: killed"))
    r = P2.step_final_audit(tmp_path, phase=2)
    assert r.status == "FAIL"
    assert "TIMEOUT" in r.detail and "NOT a verdict" in r.detail
    assert _pl.AUDIT_TIMEOUT_ENV in r.detail            # tells how to extend
    assert r.extras.get("finding") == "AUDIT_TIMEOUT"


def test_final_audit_real_fail_still_plain_fail(tmp_path, monkeypatch):
    # NEGATIVE no-leak: a substantive audit FAIL keeps the plain-FAIL shape.
    monkeypatch.setattr(
        P2, "_run",
        lambda cmd, cwd=None, timeout=600, env=None:
            (1, "step 31 FAIL\nOverall: FAIL\n", ""))
    r = P2.step_final_audit(tmp_path, phase=2)
    assert r.status == "FAIL"
    assert "AUDIT_TIMEOUT" not in (r.extras.get("finding") or "")
    assert "Overall: FAIL" in r.detail


def test_final_audit_pass_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(
        P2, "_run",
        lambda cmd, cwd=None, timeout=600, env=None:
            (0, "Overall: PASS\n", ""))
    assert P2.step_final_audit(tmp_path, phase=2).status == "PASS"


# ── flow_compliance per-gate cap: named timeout + env budget ───────────────

#: A `run_host_supervised` reporting that the gate's process tree made no
#: forward progress. The shipped type from the shipped module, not a duck.
def _stalled_result(cmd, **_kw):
    return FCC._watchdog.SupervisedResult(
        FCC._watchdog.RC_STALLED, "", "WATCHDOG_STALLED", "stalled", 61.0)


def test_gate_stall_message_says_not_a_verdict(tmp_path, monkeypatch):
    """THIS BRANCH CHANGED THE SHAPE, and the test follows it rather than being
    relaxed to accept either.

    It used to stub `FCC.subprocess.run` and raise `TimeoutExpired`. The gate
    runner no longer bounds a gate by RUNTIME — a structural gate reading a
    post-PnR netlist or hashing a multi-GB GDS is WORKING, and the old fixed
    budget killed it and recorded the kill as a gate FAIL — so the launch moved
    to `_watchdog.run_host_supervised` and that stub went BLIND: the real gate
    ran, returned 0, and this test asserted `ok is False` against a genuine
    PASS. A stub below the seam the code actually launches through does not
    make a test lenient, it makes it MEASURE SOMETHING ELSE.

    #525's reading is unchanged and is what is asserted: an unevaluated gate
    still FAILs, the reason still says it is NOT a verdict about the design, and
    it still names the env var that extends the allowance. What moved is the
    OBSERVATION behind it — "it has been N seconds", which a correct gate on a
    busy host reaches just as easily, became "this gate's tree did nothing at
    all for N seconds", which only a wedged gate reaches.
    """
    monkeypatch.setattr(FCC._watchdog, "run_host_supervised", _stalled_result)
    ok, msg = FCC._check_program_exit_zero(
        tmp_path, "marketplace_version_sync_check .")
    assert ok is False
    assert "STALLED" in msg and "NOT a verdict" in msg
    assert _pl.GATE_TIMEOUT_ENV in msg
    # AND THE ACCUSING CLOCK SENTENCE IS GONE. Asserted, not assumed: the whole
    # point of the change is that the reason stopped naming a duration.
    assert "TIMED OUT" not in msg, msg


def test_gate_budget_honors_env(tmp_path, monkeypatch):
    """THE HALF THAT MUST NOT MOVE: the operator's declared number still reaches
    the launch. It is now the STALL GRACE rather than a runtime deadline — how
    long the gate may show no progress at all — so it is read off
    `stall_grace_s` instead of `timeout`. The env var, the value and the fact
    that the caller's number is honoured as given are all unchanged.
    """
    seen = {}

    def capture(cmd, **kw):
        seen["stall_grace_s"] = kw.get("stall_grace_s")
        return _stalled_result(cmd, **kw)

    monkeypatch.setenv(_pl.GATE_TIMEOUT_ENV, "77")
    monkeypatch.setattr(FCC._watchdog, "run_host_supervised", capture)
    FCC._check_program_exit_zero(
        tmp_path, "marketplace_version_sync_check .")
    assert seen["stall_grace_s"] == 77


# ── phase23 self-audit: no crash, named AUDIT_TIMEOUT overall ──────────────

def test_phase23_self_audit_timeout_no_crash(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="x", timeout=k.get("timeout"))
    for _launcher in (getattr(SA, "subprocess", None),
                      getattr(SA, "_pr", None)):
        if _launcher is not None:
            monkeypatch.setattr(_launcher, "run", boom)
    rc, out = SA._run_compliance(tmp_path)
    assert rc == 124
    m = SA._OVERALL_RE.search(out)
    assert m and m.group(1).upper() == "AUDIT_TIMEOUT"
    assert "NOT a verdict" in out


# ── emit_final_summary outer cap no longer defeats the inner budget ────────

def test_outer_summary_budget_exceeds_inner(tmp_path):
    # the old fixed 240s outer cap was SMALLER than #469's 900s inner
    # budget; the default must now be inner + margin.
    inner = _pl.audit_timeout_s(tmp_path)
    assert inner + _pl.OUTER_TIMEOUT_MARGIN_S > 240
    assert _pl.OUTER_TIMEOUT_MARGIN_S > 0


# ── evidence-scan head-read keeps correctness ──────────────────────────────

def test_evidence_scan_detects_stub_in_head_of_big_file(tmp_path):
    src = (PROGRAMS / "flow_compliance_check.py").read_text()
    # the whole-file read is gone from the scan
    assert 'read_text(errors="replace")[:8000]' not in src.split(
        "def _evidence_integrity_scan")[1].split("def ")[0]
    assert 'fh.read(8192)' in src


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

def test_final_audit_timeout_through_real_run_with_partial_bytes(
        tmp_path, monkeypatch):
    # HIGH (review): TimeoutExpired.stdout is BYTES even under text=True;
    # the old handler returned them raw and step_final_audit crashed with
    # TypeError at the transcript write BEFORE the named AUDIT_TIMEOUT
    # branch. Go through the REAL _run against a print-then-hang child.
    import sys as _sys
    monkeypatch.setenv(_pl.AUDIT_TIMEOUT_ENV, "1")
    monkeypatch.setattr(
        P2, "_build_final_audit_cmd",
        lambda project, audit, phase=3, skip_analog=False:
            [_sys.executable, "-c",
             "import time,sys; print('partial line'*200, flush=True);"
             " time.sleep(30)"])
    r = P2.step_final_audit(tmp_path, phase=2)
    assert r.status == "FAIL"
    assert r.extras.get("finding") == "AUDIT_TIMEOUT"
    assert "NOT a verdict" in r.detail


def test_run_timeout_partial_stdout_is_str(tmp_path):
    import sys as _sys
    rc, out, err = P2._run(
        [_sys.executable, "-c",
         "import time; print('x'*100000, flush=True); time.sleep(30)"],
        timeout=1)
    assert rc == 124
    assert isinstance(out, str)


def test_phase23_runner_uses_shared_summary_helper():
    # MED (review): the phase23 runner carried a third raw 240s outer cap
    # that defeated the size-adaptive inner budget.
    src = (PROGRAMS / "phase23_one_shot_runner.py").read_text()
    assert "emit_final_summary" in src
    assert "timeout=240" not in src


def test_final_report_constants_are_aliases():
    """LOW (review): constants must alias the _path_layout single source.

    Compared through `g._pl` -- the module object `final_report_generate`
    ITSELF aliased -- not through this file's own `import _path_layout`.

    Those are not always the same object. Under whole-directory collection
    `_path_layout` is imported twice (27 files in this suite reload or pop
    modules from sys.modules), and then every one of these `is` checks compares
    equal-but-distinct constants across two module instances:

        pytest <this file>                                  passed
        pytest programs/tests -k <this test>                 FAILED
            AssertionError: assert 900 is 900

    900 is outside CPython's small-int cache, so identity across two module
    objects is never guaranteed -- the assertion was measuring which import
    graph pytest happened to build, not whether the constants alias.

    The claim itself is unweakened, and is the reason `is` rather than `==` is
    right here: an independent literal in `final_report_generate` compiles to a
    different object than `_path_layout`'s and still fails this.
    """
    import final_report_generate as g
    src = g._pl
    assert g.AUDIT_TIMEOUT_DEFAULT_S is src.AUDIT_TIMEOUT_DEFAULT_S
    assert g.AUDIT_TIMEOUT_CAP_S is src.AUDIT_TIMEOUT_CAP_S
    assert g.AUDIT_TIMEOUT_ENV is src.AUDIT_TIMEOUT_ENV
