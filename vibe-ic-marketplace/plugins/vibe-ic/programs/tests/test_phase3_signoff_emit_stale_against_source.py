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

import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))




# --------------------------------------------------------------------------
# The BEHAVIOURAL delta, stated against the pre-fix gate expression verbatim.
# This is the test that proves behaviour changed rather than merely that a new
# symbol exists: it fails against the byte-identical pre-fix file because the
# pre-fix expression answers "reuse" on the measured case.
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# POSITIVE — must re-emit
# --------------------------------------------------------------------------






# --------------------------------------------------------------------------
# NEGATIVE / REVERSE — must STILL reuse. If any of these flips, the guard has
# degenerated into "always re-run" and the caching it refines is gone.
# --------------------------------------------------------------------------










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
