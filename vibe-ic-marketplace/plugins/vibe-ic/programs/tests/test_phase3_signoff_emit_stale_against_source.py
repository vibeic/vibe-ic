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
    assert p3._signoff_regen(stale_json, routed_def) is True

    assert pre_fix_says_emit != p3._signoff_regen(stale_json, routed_def)


# --------------------------------------------------------------------------
# POSITIVE — must re-emit
# --------------------------------------------------------------------------
def test_absent_output_still_emits(tmp_path):
    """Unchanged from pre-fix behaviour: an absent artefact is produced."""
    routed_def = _touch(tmp_path / "top.def", 1_000_000.0)
    missing = tmp_path / "reports" / "dynamic_ir.json"
    assert not missing.exists()
    assert p3._signoff_regen(missing, routed_def) is True


def test_stale_against_any_one_of_several_sources(tmp_path):
    """A SPEF-fed emitter is stale if EITHER the DEF or the SPEF is newer."""
    out = _touch(tmp_path / "si_mcf_sta.json", 1_000_000.0)
    old_def = _touch(tmp_path / "top.def", 900_000.0)
    new_spef = _touch(tmp_path / "top.spef", 1_000_001.0)
    assert p3._signoff_regen(out, old_def, new_spef) is True


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
    assert p3._signoff_regen(out, src) is True


# --------------------------------------------------------------------------
# NEGATIVE / REVERSE — must STILL reuse. If any of these flips, the guard has
# degenerated into "always re-run" and the caching it refines is gone.
# --------------------------------------------------------------------------
def test_fresh_output_is_reused(tmp_path):
    """REVERSE CASE: output NEWER than its source is still cached."""
    src = _touch(tmp_path / "top.def", 1_000_000.0)
    fresh = _touch(tmp_path / "power.json", 1_000_050.0)
    assert p3._signoff_regen(fresh, src) is False


def test_equal_mtime_is_not_stale(tmp_path):
    """A same-second write is normal within-one-run ordering, not staleness."""
    src = _touch(tmp_path / "top.def", 1_000_000.0)
    same = _touch(tmp_path / "erc.rpt", 1_000_000.0)
    assert p3._signoff_regen(same, src) is False


def test_absent_source_does_not_force_re_emit(tmp_path):
    """Nothing to be stale against => the existing artefact stands."""
    out = _touch(tmp_path / "thermal_screen.json", 1_000_000.0)
    assert p3._signoff_regen(out, tmp_path / "never_written.def") is False


def test_no_sources_reduces_to_the_existence_gate(tmp_path):
    """With no declared source the guard must behave exactly like pre-fix."""
    out = _touch(tmp_path / "dfm_screen.json", 1_000_000.0)
    assert p3._signoff_regen(out) is False
    assert p3._signoff_regen(tmp_path / "gone.json") is True


def test_all_sources_older_is_reused(tmp_path):
    """Multi-source reuse: every source older => cached."""
    out = _touch(tmp_path / "si_mcf_sta.json", 1_000_000.0)
    d = _touch(tmp_path / "top.def", 999_000.0)
    s = _touch(tmp_path / "top.spef", 998_000.0)
    assert p3._signoff_regen(out, d, s) is False


# --------------------------------------------------------------------------
# The class must stay closed: no DEF-derived sign-off emitter may go back to
# an existence-only gate.
# --------------------------------------------------------------------------
GUARDED_OUTPUTS = [
    "ir_rpt", "em_rpt", "antenna_rpt", "si_rpt", "erc_rpt", "lec_post_json",
    "aging_sta_json", "dyn_ir_json", "thermal_json",
    "dfm_json", "perc_rpt", "sdf_out", "power_rpt", "_mcf_json",
]

# `metal_density_json` is NOT in that list, and the omission is the point.
#
# The check below is a SOURCE GREP: it requires the literal
# `_signoff_regen(<name>` to appear in `step_canonicalize_artefacts`. For every
# other output that is the right shape — each derives from ONE input path the
# call site can name and date against.
#
# Metal density cannot. `_emit_metal_density_report` resolves the FRESHER of
# {canonical stage-4 alias, streamed pnr GDS} itself, because Step 37 rewrites
# the alias LATER in this same pass. There is no single input path the call
# site could honestly date against, and `_signoff_regen` dated against the
# wrong input is a worse claim than no guard — the runner's own comment says
# exactly this, and ends: "if the SKIP-on-existence needs closing too, it must
# be closed there, against the path that emitter actually chose."
#
# It has been closed there. So requiring the helper's NAME at this call site
# would now fail a correct implementation — the test would be pinning the
# IMPLEMENTATION rather than the property. The property is checked
# behaviourally instead, in `test_metal_density_is_re_emitted_when_it_predates
# _the_gds_it_describes` below: a report older than the GDS it names is
# re-emitted, and one newer than it is left alone. That test passes against any
# correct implementation, including one that never calls `_signoff_regen`.


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
            f"_signoff_regen({name}, <source it derives from>)."
        )
    assert f"_signoff_regen({name}" in body, (
        f"{name} must be gated by _signoff_regen against the source it "
        f"is computed from"
    )


def test_scan_scope_actually_contains_the_gates():
    """The scoped scan must not be vacuous — if `step_canonicalize_artefacts`
    stops containing these gates the parametrized test above would pass by
    finding nothing, so anchor it."""
    body = _canonicalize_body()
    assert body.count("_signoff_regen(") >= len(GUARDED_OUTPUTS)
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


# --------------------------------------------------------------------------
# metal_density: the PROPERTY, checked behaviourally rather than by grepping
# for a helper name at a call site that cannot honestly use it.
# --------------------------------------------------------------------------
def _density_emitter():
    import importlib.util as _iu, sys as _sys
    p = PROG / "phase3_one_shot_runner.py"
    spec = _iu.spec_from_file_location("_p3_density", p)
    mod = _iu.module_from_spec(spec)
    _sys.modules["_p3_density"] = mod
    spec.loader.exec_module(mod)
    return mod


def _layout(tmp_path, *, report_older_than_gds: bool):
    """A project whose metal_density.json is older or newer than its GDS."""
    import os
    proj = tmp_path / "proj"
    gdsd = proj / "phase3" / "stage4" / "gds"
    rpt = proj / "reports" / "phase3"
    for d in (gdsd, rpt, proj / "phase3" / "stage3" / "pnr"):
        d.mkdir(parents=True, exist_ok=True)
    gds = gdsd / "top.gds"
    gds.write_bytes(b"\x00\x06\x00\x02\x00\x07")
    out = rpt / "metal_density.json"
    out.write_text('{"layers": {"met1": 0.11}}')
    t = gds.stat().st_mtime
    os.utime(out, (t - 500, t - 500) if report_older_than_gds else (t + 500, t + 500))
    return proj, gds, out


def test_metal_density_is_re_emitted_when_it_predates_the_gds_it_describes(tmp_path):
    """THE PROPERTY. A density report older than the layout it names describes a
    design that no longer exists, and nothing in the artefact says so. The
    emitter must not treat it as current."""
    p3 = _density_emitter()
    proj, gds, out = _layout(tmp_path, report_older_than_gds=True)
    notes = []
    # No container/PDK here, so emission cannot complete — but it must get PAST
    # the currency decision, which is what this pins. A skip on currency returns
    # before any note is added; a skip on tooling says so.
    p3._emit_metal_density_report(proj, "top", _FakePdk(), "nonexistent", out, notes)
    assert notes, (
        "the emitter returned without a word — it treated a report older than "
        "the GDS it names as current")
    assert any("predates" in n or "layermap" in n or "skipped" in n for n in notes), notes


def test_metal_density_that_postdates_its_gds_is_left_alone(tmp_path):
    """REVERSE CASE, and the one that matters: an emitter that re-ran every time
    would satisfy the test above and be worse than the defect — it would re-run
    KLayout on every canonicalize pass. A current report must be left alone."""
    p3 = _density_emitter()
    proj, gds, out = _layout(tmp_path, report_older_than_gds=False)
    notes = []
    rv = p3._emit_metal_density_report(proj, "top", _FakePdk(), "nonexistent", out, notes)
    assert rv is False and notes == [], (
        f"a report NEWER than its GDS must be left alone silently; got {notes}")


class _FakePdk:
    name = "testpdk"
    lefdef_layermap = None
