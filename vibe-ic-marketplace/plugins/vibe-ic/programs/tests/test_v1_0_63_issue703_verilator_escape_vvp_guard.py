"""ORGANIC #703 — Verilator SV-escape simulation result DISCARDED because the
caller re-ran `vvp` on a `.vvp` the verilator frontend never produces.

ROOT CAUSE: a SV reference/full-stack/oracle TB compile falls through
iverilog→sv2v and is recovered by the #657 verilator SV-escape (with the #668
-DSYNTHESIS retry). The escape returns rc=0 with the completion transcript in
STDOUT and `tb_frontend='verilator_sva'`, and it produces a NATIVE BINARY (NO
.vvp) — it already RAN the sim inside the escape. But the caller then
UNCONDITIONALLY ran `vvp <name>.vvp` → "Unable to open input file" rc=255 →
discarded the successful sim stdout and mislabelled the step a runtime FAIL.

Sites (all UNGUARDED before): `_run_oracle_tb` (oracle, ORACLE_TB_DONE),
`_reference_tb_generic_full_stack` (full-stack, FULL_STACK_TB_DONE),
`step_reference_tb` (protocol ref-TB, PROTOCOL_REFERENCE_TB_PASS).

FIX: a shared helper `_sim_run_or_reuse` GUARDS on the frontend:
  * tb_frontend == 'verilator_sva'  → REUSE the escape's captured (rc, out, err);
    do NOT run vvp. The caller still checks the COMPLETION MARKER in that stdout.
  * any other frontend (iverilog_g2012 / iverilog_sv2v) → run `vvp <name>.vvp`
    exactly as before.

POSITIVE: verilator_sva + FULL_STACK_TB_DONE in the captured stdout → reused,
PASS-eligible, WITHOUT running vvp.
§4.05 NO-LEAK: the iverilog/sv2v `.vvp` path STILL runs vvp; a verilator escape
that did NOT reach the completion marker still FAILs (no fake PASS — the marker
is checked in the escape stdout); a real vvp runtime failure on the iverilog
path still FAILs.

chip-AGNOSTIC: keyed only on the frontend tag + the standard vvp invocation; no
chip/vendor literal.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import design_one_shot_runner as R  # noqa: E402

# The real escape transcript shape — the verilator native binary ran to
# completion and printed the full-stack completion marker.
FULL_STACK_ESCAPE_OUT = (
    "INFO: full-stack scenario 0 driven\n"
    "FULL_STACK_TB_DONE\n"
    "[verilator SVA escape: sv2v could not lower property]\n")

#: The simulation bound handed to `_sim_run_or_reuse` below.
#:
#: `_patch_run` replaces `R._run` in every one of these tests, so nothing is
#: executed and the measured worst case at those call sites is appending to a
#: list. The values used to be 120 and 300, both above
#: `ci_harness_timeout_ceiling_check`'s per-call ceiling (harness bound // 3 =
#: 60 s), which put five entries on that gate's advisory list of bounds it
#: cannot resolve — a list that can only be cleared here, not there.
_T_PATCHED = 60


def _patch_run(monkeypatch):
    """Patch R._run to RECORD every invocation and never actually exec vvp.
    Returns the calls list."""
    calls = []

    def _fake_run(cmd, cwd=None, timeout=None, **kw):
        calls.append(list(cmd))
        # Simulate the historical vvp-on-missing-file failure.
        if cmd and cmd[0] == "vvp":
            return (255, "", f"{cmd[1]}: Unable to open input file.")
        return (0, "", "")

    monkeypatch.setattr(R, "_run", _fake_run)
    return calls


# ── POSITIVE: verilator escape reused, no vvp ────────────────────────────────
def test_verilator_sva_reuses_stdout_without_vvp(tmp_path, monkeypatch):
    calls = _patch_run(monkeypatch)
    rc, out, err = R._sim_run_or_reuse(
        "verilator_sva", tmp_path / "full_stack.vvp",
        compile_rc=0, compile_out=FULL_STACK_ESCAPE_OUT, compile_err="",
        run_dir=tmp_path, timeout=_T_PATCHED)
    # The escape result is reused verbatim — and vvp was NEVER invoked.
    assert rc == 0
    assert "FULL_STACK_TB_DONE" in out
    assert not any(c and c[0] == "vvp" for c in calls), \
        f"vvp must NOT run for verilator_sva, got calls={calls}"


def test_verilator_sva_marker_check_in_caller_still_gates_pass(monkeypatch,
                                                               tmp_path):
    # The completion-marker check happens in the CALLER on the reused stdout,
    # so the contract is: reused stdout carries the marker => PASS-eligible.
    _patch_run(monkeypatch)
    rc, out, _ = R._sim_run_or_reuse(
        "verilator_sva", tmp_path / "full_stack.vvp",
        0, FULL_STACK_ESCAPE_OUT, "", tmp_path, _T_PATCHED)
    # caller's gate:  rc == 0 and "FULL_STACK_TB_DONE" in out
    assert (rc == 0 and "FULL_STACK_TB_DONE" in out)


# ── §4.05 NO-LEAK: iverilog/sv2v path still runs vvp ─────────────────────────
def test_iverilog_path_still_runs_vvp(tmp_path, monkeypatch):
    calls = _patch_run(monkeypatch)
    vvp_path = tmp_path / "oracle.vvp"
    R._sim_run_or_reuse("iverilog_g2012", vvp_path,
                        compile_rc=0, compile_out="", compile_err="",
                        run_dir=tmp_path, timeout=_T_PATCHED)
    assert any(c and c[0] == "vvp" and c[1] == str(vvp_path) for c in calls), \
        f"iverilog path MUST run vvp, got calls={calls}"


def test_iverilog_sv2v_path_still_runs_vvp(tmp_path, monkeypatch):
    calls = _patch_run(monkeypatch)
    vvp_path = tmp_path / "full_stack.vvp"
    R._sim_run_or_reuse("iverilog_sv2v", vvp_path,
                        0, "", "", tmp_path, _T_PATCHED)
    assert any(c and c[0] == "vvp" for c in calls)


# ── §4.05 NO-LEAK: verilator escape WITHOUT the marker still FAILs ───────────
def test_verilator_sva_without_marker_does_not_fake_pass(tmp_path,
                                                         monkeypatch):
    _patch_run(monkeypatch)
    # The escape compiled+ran but the marker is ABSENT (genuine functional miss
    # or premature termination). The helper reuses the stdout faithfully — so
    # the caller's marker check fails and the step FAILs (no fabricated PASS).
    no_marker_out = "INFO: scenario 0 driven\n(simulation aborted)\n"
    rc, out, err = R._sim_run_or_reuse(
        "verilator_sva", tmp_path / "full_stack.vvp",
        compile_rc=0, compile_out=no_marker_out, compile_err="",
        run_dir=tmp_path, timeout=_T_PATCHED)
    # caller's gate:  rc == 0 and "FULL_STACK_TB_DONE" in out  → False here.
    assert "FULL_STACK_TB_DONE" not in out
    assert not (rc == 0 and "FULL_STACK_TB_DONE" in out)


def test_verilator_sva_nonzero_escape_rc_propagates(tmp_path, monkeypatch):
    # Even a verilator escape that itself returned non-zero is reused honestly
    # (the helper never masks an escape failure as success).
    _patch_run(monkeypatch)
    rc, out, err = R._sim_run_or_reuse(
        "verilator_sva", tmp_path / "x.vvp",
        compile_rc=3, compile_out="", compile_err="elab error", run_dir=tmp_path)
    assert rc == 3
    assert err == "elab error"


# ── §4.05 NO-LEAK: real vvp runtime failure on iverilog path still FAILs ─────
def test_real_vvp_failure_on_iverilog_path_still_fails(tmp_path, monkeypatch):
    _patch_run(monkeypatch)  # the fake makes vvp return 255
    rc, out, err = R._sim_run_or_reuse(
        "iverilog_g2012", tmp_path / "missing.vvp",
        compile_rc=0, compile_out="", compile_err="", run_dir=tmp_path)
    assert rc == 255
    assert "Unable to open input file" in err


# ── the three real sites all route through the shared helper ─────────────────
def test_all_three_sites_use_shared_helper():
    import inspect
    src = inspect.getsource(R)
    # The shared helper exists and the three vvp re-run sites delegate to it.
    assert "def _sim_run_or_reuse(" in src
    # Exactly three CALL-sites (oracle / full-stack / protocol ref-TB). Count
    # the call form `= _sim_run_or_reuse(tb_frontend` so the helper's own
    # `def _sim_run_or_reuse(tb_frontend` signature line is not counted.
    assert src.count("= _sim_run_or_reuse(tb_frontend") == 3, \
        "all three vvp re-run sites must route through the shared guard"


def test_helper_guard_keyed_on_verilator_sva():
    import inspect
    helper_src = inspect.getsource(R._sim_run_or_reuse)
    assert 'tb_frontend == "verilator_sva"' in helper_src
    assert 'vvp' in helper_src  # the iverilog path still runs vvp
