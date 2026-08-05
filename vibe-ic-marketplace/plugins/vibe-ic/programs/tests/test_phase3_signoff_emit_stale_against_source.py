"""Regression — the phase-3 sign-off emitters must re-run when their output
predates the routed DEF / extracted SPEF it is COMPUTED FROM.

Defect (measured on a real re-run): `step_canonicalize_artefacts` gated the
sign-off emitters on their output's EXISTENCE alone, e.g.

    if primary_def.is_file() and not dyn_ir_json.is_file():
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

The first tranche of this class (extraction + STA, then IR/EM/antenna/SI/MCF)
landed already and is guarded by `_signoff_regen`. This file closes the
REMAINDER against the SAME predicate rather than a second one: a flow with two
freshness predicates that answer differently is the defect one level up.
`_signoff_regen` was WIDENED to a variadic source list for that, because a
crosstalk report is derived from the SPEF as well as from the DEF.

NEG cases below are load-bearing: the guard must not degenerate into "always
re-run", which would defeat the caching it refines and mask the real defect.

Scope note — `metal_density_json` is deliberately NOT in the guarded set.
`_emit_metal_density_report` resolves the FRESHER of {canonical alias,
streamed pnr source} itself, so this call site has no single input path it
could honestly date the report against; a guard dated against a file the
emitter does not read is a worse claim than no guard. That report's currency
is owned on the read side, by `_freshest_gds` inside the emitter.
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
# `_signoff_regen` ALREADY EXISTS on the base this change is built on, so a
# test that merely calls it would pass on the unfixed tree. These tests state
# the delta as a DISAGREEMENT between the pre-fix expression and the predicate
# now in the guard, on inputs the pre-fix expression answers wrongly.
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
    """A SPEF-fed emitter is stale if EITHER the DEF or the SPEF is newer.

    This is the case the widening exists for: with the pre-widening
    single-source signature the SPEF could not be declared at all, so a
    re-extraction that left the DEF alone republished the previous
    extraction's crosstalk numbers.
    """
    out = _touch(tmp_path / "si_crosstalk.rpt", 1_000_000.0)
    old_def = _touch(tmp_path / "top.def", 900_000.0)
    new_spef = _touch(tmp_path / "top.spef", 1_000_001.0)
    assert p3._signoff_regen(out, old_def, new_spef) is True
    # ... and symmetrically, when it is the DEF that moved.
    out2 = _touch(tmp_path / "si_crosstalk2.rpt", 1_000_000.0)
    new_def = _touch(tmp_path / "top2.def", 1_000_001.0)
    old_spef = _touch(tmp_path / "top2.spef", 900_000.0)
    assert p3._signoff_regen(out2, new_def, old_spef) is True


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
    """Nothing to be stale against => the existing artefact stands.

    This is the pre-widening `_signoff_regen` contract ("no layout -> leave an
    existing artefact alone") and the widening must not have moved it.
    """
    out = _touch(tmp_path / "thermal_screen.json", 1_000_000.0)
    assert p3._signoff_regen(out, tmp_path / "never_written.def") is False


def test_absent_source_is_skipped_not_short_circuited(tmp_path):
    """A missing source must not hide a LATER source that IS newer.

    The single-source predicate answered `return False` the moment a source was
    absent. Widened, that has to become "skip this one and keep looking", or a
    DEF that has not been written yet would mask a re-extracted SPEF.
    """
    out = _touch(tmp_path / "si_crosstalk.rpt", 1_000_000.0)
    absent = tmp_path / "never_written.def"
    newer = _touch(tmp_path / "top.spef", 1_000_500.0)
    assert p3._signoff_regen(out, absent, newer) is True


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
# The WIDENING must be behaviour-preserving for every call site that already
# passes exactly one source. Enumerated, not argued.
# --------------------------------------------------------------------------
_STATES = {"absent": None, "older": 900_000.0,
           "equal": 1_000_000.0, "newer": 1_100_000.0}


def _pre_widening_signoff_regen(artifact: Path, layout: Path) -> bool:
    """`_signoff_regen` EXACTLY as it stood before the widening (v1.9.79)."""
    try:
        if not artifact.is_file():
            return True
        if not layout.is_file():
            return False
        return artifact.stat().st_mtime < layout.stat().st_mtime
    except OSError:
        return True


@pytest.mark.parametrize("art_state", sorted(_STATES))
@pytest.mark.parametrize("lay_state", sorted(_STATES))
def test_single_source_is_identical_to_the_pre_widening_predicate(
        tmp_path, art_state, lay_state):
    """All 16 filesystem-reachable (artifact, layout) states agree.

    Every call site that already existed passes exactly one source, so this is
    the statement that none of them changed answer.
    """
    art = tmp_path / "artifact.rpt"
    lay = tmp_path / "layout.def"
    if _STATES[art_state] is not None:
        _touch(art, 1_000_000.0 if art_state == "equal" else _STATES[art_state])
    if _STATES[lay_state] is not None:
        _touch(lay, _STATES[lay_state])
    assert p3._signoff_regen(art, lay) is _pre_widening_signoff_regen(art, lay)


def test_widening_is_behaviour_preserving_including_unreadable_states(tmp_path):
    """Same claim, extended to the states a real filesystem cannot reach.

    The parametrized test above covers the 16 filesystem-reachable states. The
    ones that decide whether a widening is really a no-op are the OTHER ones:
    `is_file()` answering True while `stat()` raises, `is_file()` itself
    raising. A widening that hoists the artefact's `stat()` ABOVE the source
    loop — the obvious way to write it — changes the answer in exactly one of
    them (artefact unstattable, source absent: the pre-widening body returns
    "reuse", the hoisted one returns "re-run"), and no filesystem test would
    ever show it. So the states are injected.
    """
    import itertools
    import tempfile

    rels = {"older": -100.0, "equal": 0.0, "newer": +100.0}
    errs = [None, ("art", "stat"), ("lay", "stat"),
            ("art", "isfile"), ("lay", "isfile")]
    base_t = 1_000_000.0

    boom: dict[str, str] = {}
    real_stat, real_isfile = Path.stat, Path.is_file

    def patched_stat(self, *a, **kw):
        if boom.get(str(self)) == "stat":
            raise OSError("stat unavailable")
        return real_stat(self, *a, **kw)

    def patched_isfile(self, *a, **kw):
        if boom.get(str(self)) == "isfile":
            raise OSError("is_file unavailable")
        return real_isfile(self, *a, **kw)

    states = 0
    divergences = []
    Path.stat, Path.is_file = patched_stat, patched_isfile
    try:
        for a_st, l_st, err in itertools.product(
                ("absent", "present"), ("absent", "present"), errs):
            both = a_st == "present" and l_st == "present"
            for rel_name, rel in (rels.items() if both else [("n/a", 0.0)]):
                with tempfile.TemporaryDirectory() as td:
                    boom.clear()
                    art = Path(td) / "artifact.json"
                    lay = Path(td) / "layout.def"
                    if a_st == "present":
                        art.write_text("x")
                        os.utime(art, (base_t, base_t))
                    if l_st == "present":
                        lay.write_text("x")
                        os.utime(lay, (base_t + rel, base_t + rel))
                    if err:
                        who, kind = err
                        boom[str(art if who == "art" else lay)] = kind

                    def call(fn):
                        try:
                            return fn(art, lay)
                        except Exception as exc:      # noqa: BLE001
                            return f"EXC:{type(exc).__name__}"

                    states += 1
                    was = call(_pre_widening_signoff_regen)
                    now = call(p3._signoff_regen)
                    if was != now:
                        divergences.append(
                            (a_st, l_st, rel_name, err, was, now))
    finally:
        Path.stat, Path.is_file = real_stat, real_isfile

    assert states == 30, f"state enumeration changed shape: {states}"
    assert divergences == [], (
        "widening _signoff_regen to varargs changed single-source behaviour, "
        f"so the pre-existing call sites moved: {divergences}"
    )


# --------------------------------------------------------------------------
# The class must stay closed: no DEF-derived sign-off emitter may go back to
# an existence-only gate.
# --------------------------------------------------------------------------
GUARDED_OUTPUTS = [
    "ir_rpt", "em_rpt", "antenna_rpt", "si_rpt", "erc_rpt", "lec_post_json",
    "aging_sta_json", "dyn_ir_json", "thermal_json",
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


# --------------------------------------------------------------------------
# BEHAVIOURAL control on the CALL SITES. The substring scan above proves only
# that a NAME appears in the source; it cannot tell a converted guard from one
# that merely mentions the helper in a comment. These two EXTRACT each gate's
# real condition expression from the AST and EVALUATE it against a synthetic
# run directory, so what is asserted is what the guard DOES.
# --------------------------------------------------------------------------
def _gate_condition_src(name: str) -> str:
    """The `if` condition, as source, that decides whether `name` is emitted."""
    import ast
    src = (PROG / "phase3_one_shot_runner.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == "step_canonicalize_artefacts")
    hits = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
        if name in names:
            hits.append((node.lineno, ast.unparse(node.test)))
    assert hits, f"no gate mentioning {name} inside step_canonicalize_artefacts"
    # The EMIT gate is the first `if` in source order that mentions the name;
    # anything later is a post-emit "did the tool write something" check on the
    # SAME name, a different question (see
    # test_emitter_internal_output_checks_are_left_alone).
    hits.sort()
    return hits[0][1]


def _eval_gate(cond: str, tmp: Path, *, stale: bool) -> bool:
    """Evaluate a real gate condition against a synthetic run directory.

    `stale=True`  -> every guarded output predates the routed DEF / SPEF.
    `stale=False` -> every guarded output postdates them (the REVERSE case).
    """
    src_t, out_t = ((1_000_000.0, 900_000.0) if stale
                    else (900_000.0, 1_000_000.0))
    project = tmp / "proj"
    primary_def = _touch(project / "phase3/stage3/pnr/top.def", src_t)
    spef_out = _touch(project / "phase3/stage3/extracted/top.spef", src_t)
    _touch(project / "phase3/stage3/pnr/constraint.sdc", src_t)
    ns = {
        "project": project,
        "primary_def": primary_def,
        "spef_out": spef_out,
        "_mcf_spef": [spef_out],
        "_mcf_newest_spef": spef_out,
        "_signoff_regen": p3._signoff_regen,
        "multi_process": True,
    }
    for n in GUARDED_OUTPUTS:
        ns[n] = _touch(project / "reports" / f"{n}.out", out_t)
    return bool(eval(cond, {"__builtins__": {}}, ns))  # noqa: S307


@pytest.mark.parametrize("name", GUARDED_OUTPUTS)
def test_gate_predicate_re_emits_a_stale_artefact(tmp_path, name):
    """FORWARD, behavioural: the REAL gate expression must answer "emit".

    Fails against the pre-fix file for the right reason — the pre-fix
    predicate, evaluated on an output that predates the routed DEF it derives
    from, answers "reuse".
    """
    cond = _gate_condition_src(name)
    assert _eval_gate(cond, tmp_path, stale=True) is True, (
        f"gate for {name} answers 'reuse' on a STALE output: {cond}"
    )


@pytest.mark.parametrize("name", GUARDED_OUTPUTS)
def test_gate_predicate_still_reuses_a_fresh_artefact(tmp_path, name):
    """REVERSE, behavioural: the REAL gate expression must answer "reuse".

    Anti-degeneration. If a gate were rewritten to "always re-run" this fails
    while the forward test above stays green — so the pair is decisive in both
    directions rather than only counting failures.
    """
    cond = _gate_condition_src(name)
    assert _eval_gate(cond, tmp_path, stale=False) is False, (
        f"gate for {name} re-runs unconditionally on a FRESH output: {cond}"
    )


def test_the_helper_is_the_one_the_runner_already_had():
    """REVERSE CASE for the remedy itself: no SECOND freshness helper.

    The first revision of this change added `_signoff_emit_needed(output,
    *sources)` beside the `_signoff_regen(artifact, layout)` the runner already
    carried. Measured, the two were the same function on every reachable
    single-source state — so what shipped would have been one freshness rule
    stated twice, free to drift. If a differently-named twin reappears, that
    drift is back.
    """
    src = (PROG / "phase3_one_shot_runner.py").read_text()
    assert "def _signoff_regen(" in src
    assert "def _signoff_emit_needed(" not in src, (
        "a second freshness helper was reintroduced; widen _signoff_regen "
        "instead so there is exactly one rule"
    )


def test_si_report_is_dated_against_the_spef_it_is_made_of():
    """Step 27 reads the SPEF's coupling caps, so the SPEF is a SOURCE.

    Dating it against the DEF alone leaves the exact escape measured on
    `si_mcf_sta.json`: a re-extraction supersedes the report without touching
    the DEF, and the guard sees nothing.
    """
    body = _canonicalize_body()
    assert "_signoff_regen(si_rpt, primary_def, spef_out)" in body, (
        "si_crosstalk.rpt must be dated against the extracted SPEF as well as "
        "the routed DEF — it is computed from the SPEF's coupling caps"
    )


def test_metal_density_exclusion_is_recorded_not_forgotten():
    """The one deliberate omission must be visible as a decision.

    `metal_density_json` is the only remaining existence-only gate in this
    block. If that is ever silently changed — in either direction — the
    reasoning must be updated with it, so pin both the state and its note.
    """
    body = _canonicalize_body()
    assert "not metal_density_json.is_file()" in body
    assert "_signoff_regen(metal_density_json" not in body
    assert "DELIBERATELY NOT `_signoff_regen`-gated" in body, (
        "the exclusion lost its rationale; a reader cannot tell an omission "
        "from an oversight"
    )


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
