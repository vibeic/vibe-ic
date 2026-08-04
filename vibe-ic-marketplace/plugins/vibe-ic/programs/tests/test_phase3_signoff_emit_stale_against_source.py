"""Regression — the phase-3 sign-off emitters must re-run when their output
predates the routed DEF / extracted SPEF it is COMPUTED FROM.

Defect (measured on a real re-run): `step_canonicalize_artefacts` gated ~14
sign-off emitters on their output's EXISTENCE alone, e.g.

    if primary_def.is_file() and not dyn_ir_json.is_file():
    if (not _mcf_json.is_file() and _mcf_spef and ...):
    if not power_rpt.is_file() and primary_def.is_file():

Every one of those outputs is DERIVED from the routed DEF (and, for the
parasitic-fed ones, the extracted SPEF). On a re-run in which place-and-route
legitimately re-ran and rewrote its DEF, an existence-only gate reuses the
PREVIOUS round's artefact and the step publishes a superseded layout's numbers
as the current round's, with nothing in the run disclosing it.

Two instances measured on one run directory:

  * `reports/phase3/si_mcf_sta.json` written 18:02:53 recorded
    `coupling_pairs: 1255`; the SPEF at the path it names was re-extracted at
    00:55:18 (6 h 53 m later) and holds 1183 coupling caps. Emitter and
    checker call the SAME `count_coupling_caps` on the SAME path and disagree,
    because the file changed under a cached output. The Step-27 gate then
    FAILED — it re-derived the expected Cc*MCF fold from the CURRENT SPEF and
    proved it against a bounded SPEF folded from the PREVIOUS one, reporting
    358 nets as under/over-applied MCF. Re-running the emitter against the
    current SPEF returned the gate to PASS with 0 errors.

  * `reports/phase3/power.json` written 18:02 carries `"verdict": "PASS"` for a
    netlist replaced at 00:54 — a stale PASS, which is worse than a stale FAIL
    because nothing downstream questions it.

This is the same mechanism as the Step-34 metal-fill staleness (filed
separately); that call site is deliberately NOT touched here so the two
changes do not collide.

NEG cases below are load-bearing: the guard must not degenerate into "always
re-run", which would defeat the caching it refines and mask the real defect.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as p3  # noqa: E402


def _touch(path: Path, mtime: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    os.utime(path, (mtime, mtime))
    return path


# --------------------------------------------------------------------------
# The BEHAVIOURAL delta, stated against the pre-fix gate expression verbatim.
# This is the test that proves behaviour changed rather than merely that a new
# symbol exists: it fails against the byte-identical pre-fix file because the
# pre-fix expression answers "reuse" on the measured case.
# --------------------------------------------------------------------------
def test_pre_fix_existence_gate_would_have_reused_the_stale_artefact(tmp_path):
    """The measured case: output 6h53m OLDER than the source it derives from."""
    routed_def = _touch(tmp_path / "pnr" / "top.def", 1_000_000.0)
    stale_json = _touch(tmp_path / "reports" / "si_mcf_sta.json", 975_180.0)

    # The pre-fix gate, verbatim. False => "do not emit" => reuse the stale file.
    pre_fix_says_emit = not stale_json.is_file()
    assert pre_fix_says_emit is False, (
        "pre-fix gate is existence-only, so it must answer 'reuse' here"
    )

    # The post-fix guard must answer "re-emit" on exactly that input.
    assert p3._signoff_emit_needed(stale_json, routed_def) is True

    assert pre_fix_says_emit != p3._signoff_emit_needed(stale_json, routed_def)


# --------------------------------------------------------------------------
# POSITIVE — must re-emit
# --------------------------------------------------------------------------
def test_absent_output_still_emits(tmp_path):
    """Unchanged from pre-fix behaviour: an absent artefact is produced."""
    routed_def = _touch(tmp_path / "top.def", 1_000_000.0)
    missing = tmp_path / "reports" / "dynamic_ir.json"
    assert not missing.exists()
    assert p3._signoff_emit_needed(missing, routed_def) is True


def test_stale_against_any_one_of_several_sources(tmp_path):
    """A SPEF-fed emitter is stale if EITHER the DEF or the SPEF is newer."""
    out = _touch(tmp_path / "si_mcf_sta.json", 1_000_000.0)
    old_def = _touch(tmp_path / "top.def", 900_000.0)
    new_spef = _touch(tmp_path / "top.spef", 1_000_001.0)
    assert p3._signoff_emit_needed(out, old_def, new_spef) is True


def test_unprovable_freshness_re_emits(tmp_path, monkeypatch):
    """A stat that raises must RE-RUN, never publish an unverifiable artefact."""
    out = _touch(tmp_path / "power.json", 1_000_000.0)
    src = _touch(tmp_path / "top.def", 900_000.0)

    real_stat = Path.stat

    def boom(self, *a, **kw):
        if self.name == "top.def":
            raise OSError("stat unavailable")
        return real_stat(self, *a, **kw)

    monkeypatch.setattr(Path, "stat", boom)
    assert p3._signoff_emit_needed(out, src) is True


# --------------------------------------------------------------------------
# NEGATIVE / REVERSE — must STILL reuse. If any of these flips, the guard has
# degenerated into "always re-run" and the caching it refines is gone.
# --------------------------------------------------------------------------
def test_fresh_output_is_reused(tmp_path):
    """REVERSE CASE: output NEWER than its source is still cached."""
    src = _touch(tmp_path / "top.def", 1_000_000.0)
    fresh = _touch(tmp_path / "power.json", 1_000_050.0)
    assert p3._signoff_emit_needed(fresh, src) is False


def test_equal_mtime_is_not_stale(tmp_path):
    """A same-second write is normal within-one-run ordering, not staleness."""
    src = _touch(tmp_path / "top.def", 1_000_000.0)
    same = _touch(tmp_path / "erc.rpt", 1_000_000.0)
    assert p3._signoff_emit_needed(same, src) is False


def test_absent_source_does_not_force_re_emit(tmp_path):
    """Nothing to be stale against => the existing artefact stands."""
    out = _touch(tmp_path / "thermal_screen.json", 1_000_000.0)
    assert p3._signoff_emit_needed(out, tmp_path / "never_written.def") is False


def test_no_sources_reduces_to_the_existence_gate(tmp_path):
    """With no declared source the guard must behave exactly like pre-fix."""
    out = _touch(tmp_path / "dfm_screen.json", 1_000_000.0)
    assert p3._signoff_emit_needed(out) is False
    assert p3._signoff_emit_needed(tmp_path / "gone.json") is True


def test_all_sources_older_is_reused(tmp_path):
    """Multi-source reuse: every source older => cached."""
    out = _touch(tmp_path / "si_mcf_sta.json", 1_000_000.0)
    d = _touch(tmp_path / "top.def", 999_000.0)
    s = _touch(tmp_path / "top.spef", 998_000.0)
    assert p3._signoff_emit_needed(out, d, s) is False


# --------------------------------------------------------------------------
# The class must stay closed: no DEF-derived sign-off emitter may go back to
# an existence-only gate.
# --------------------------------------------------------------------------
GUARDED_OUTPUTS = [
    "ir_rpt", "em_rpt", "antenna_rpt", "si_rpt", "erc_rpt", "lec_post_json",
    "metal_density_json", "aging_sta_json", "dyn_ir_json", "thermal_json",
    "dfm_json", "perc_rpt", "sdf_out", "power_rpt", "_mcf_json",
]


def _canonicalize_body() -> str:
    """Source of `step_canonicalize_artefacts` ONLY.

    Scoped deliberately. The same `not <x>.is_file()` spelling appears inside
    the emitter IMPLEMENTATIONS (`_emit_power_report`, the SDF emitter) as a
    legitimate "did the tool actually produce output" post-check. Those are a
    different question from the GATE that decides whether to invoke the
    emitter at all, and this test must not conflate them — nor may it be
    widened until it stops finding anything.
    """
    import ast
    src = (PROG / "phase3_one_shot_runner.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (isinstance(node, ast.FunctionDef)
                and node.name == "step_canonicalize_artefacts"):
            lines = src.splitlines()[node.lineno - 1:node.end_lineno]
            return "\n".join(lines)
    raise AssertionError("step_canonicalize_artefacts not found")


@pytest.mark.parametrize("name", GUARDED_OUTPUTS)
def test_signoff_emitter_gate_is_freshness_aware(name):
    body = _canonicalize_body()
    for pat in (f"not {name}.is_file()", f"not ({name}.is_file()"):
        assert pat not in body, (
            f"{name} is gated on existence alone again — a re-run that rewrites "
            f"the routed DEF will republish the previous round's artefact. Use "
            f"_signoff_emit_needed({name}, <source it derives from>)."
        )
    assert f"_signoff_emit_needed({name}" in body, (
        f"{name} must be gated by _signoff_emit_needed against the source it "
        f"is computed from"
    )


def test_scan_scope_actually_contains_the_gates():
    """The scoped scan must not be vacuous — if `step_canonicalize_artefacts`
    stops containing these gates the parametrized test above would pass by
    finding nothing, so anchor it."""
    body = _canonicalize_body()
    assert body.count("_signoff_emit_needed(") >= len(GUARDED_OUTPUTS)
    assert "primary_def" in body and "spef_out" in body


def test_emitter_internal_output_checks_are_left_alone():
    """REVERSE CASE for the scan: the post-emit 'did the tool write anything'
    checks inside the emitter implementations must SURVIVE. If this flips, the
    fix has over-reached out of its scope."""
    src = (PROG / "phase3_one_shot_runner.py").read_text()
    body = _canonicalize_body()
    for pat in ("not power_rpt.is_file() or power_rpt.stat().st_size",
                "not sdf_out.is_file() or sdf_out.stat().st_size"):
        assert pat in src, f"post-emit output check was wrongly removed: {pat}"
        assert pat not in body, f"{pat} unexpectedly inside the gate scope"
