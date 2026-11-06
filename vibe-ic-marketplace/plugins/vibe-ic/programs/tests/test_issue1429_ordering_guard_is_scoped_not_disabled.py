"""vibe-ic#1429 — `--phase 2 --strict-structural` red on a step-level MISSING.

THE DEFECT
==========
`--phase 2 --strict-structural` declares step-level FAIL/MISSING INFORMATIONAL.
`flow_compliance_check.main` says so in three separate places:

  * `scoped` — the verdict buckets read the `P0` umbrella plus the analog
    track (#634) and nothing else;
  * the `structural_fail_lines` / `step_artifact_fail_lines` split — "With
    --strict-structural alone they are info-only";
  * the report's own heading, "Step-level gates (informational, not gating
    --strict-structural)".

The step-execution ordering guard was the ONE place that did not. It set
`forced_fail = True` on ANY violation, so a step-level MISSING re-entered the
verdict through a side door, and the report contradicted itself two lines
apart. MEASURED on the fixture below — RTL present, no L-docs, no structural
gate FAIL:

    Overall: FAIL  (strict=True)

    Step-level gates (informational, not gating --strict-structural): 5 step(s)
    ...
    ✗ [1] Spec-to-RTL = PASS marked done while dependency
          [D1] Phase 1 Doc Extraction = MISSING          <- the sole cause

`D1 = MISSING` IS a step-level MISSING. `--strict-step-artifacts` already
exists for the reading in which it should count.

WHY THIS IS NOT A WEAKENED GATE
===============================
The guard is SCOPED, not disabled, and every assertion below that is a control
rather than the fix passes on BOTH trees:

  * the SAME tree, with the SAME two violations, still audits FAIL in default
    strict mode and under `--strict-step-artifacts` (§1);
  * a violation whose DEPENDENCY is inside the verdict scope still forces FAIL
    in structural-only mode, and is still named in the gating list (§2) — the
    two arms of §2 differ in exactly one thing, which end of the edge is in
    scope, so neither can be satisfied by a rule that simply stopped gating;
  * the scoped-out violation is still COMPUTED, still PRINTED and still in the
    JSON `ordering_violations` field (§3) — the disclosure is untouched, only
    the verdict scope moved.

§2 injects its violation set through `flow_step_execution_coverage_check.
analyze`. That is deliberate and it is the only way to reach the case: the
analog gates make the file-driven version unconstructible on purpose —
`analog_a4_corner_sweep_check` FAILs with `A4_NETLIST_ABSENT` when a sweep
declares corners while A3's deck is absent, so "A4 = PASS over A3 = MISSING"
cannot be built out of files. Injecting the guard's INPUT isolates the
consumer under test; `analyze` itself is covered by its own program's tests.

Every fixture here is synthetic: an empty module body, an invented block name,
no design content, no PDK.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
for _p in (str(_PROGRAMS), str(_TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _published_corpus import corpus_root, needs_corpus  # noqa: E402


_D1_NAME = "Phase 1 Doc Extraction (17 skills + dialogue entry → L1-L27)"




def _stub_structural_gates(monkeypatch, mod, *, passing: int = 2):
    """The P0 umbrella reports N registered gates, all PASS, no FAIL.

    `passing` matters: with an EMPTY record list the umbrella reports
    INCOMPLETE (the empty-denominator guard, #599/#901/#947), which is correct
    and is NOT what this file is about. Publishing records that actually
    PASSED is what the fixture's own premise — "a project whose structural-RTL
    gates ALL PASS" — requires.
    """
    records = [mod._p0_gate_record(f"synthetic_gate_{i}", "PASS", "",
                                   {"exit_code": 0})
               for i in range(passing)]

    def _stub(_project, **kwargs):
        out = kwargs.get("records_out")
        if out is not None:
            out.extend(records)
        return (True, [], [], [])

    monkeypatch.setattr(mod, "_run_structural_rtl_gates", _stub)


def _structural_only_project(tmp_path: Path) -> Path:
    """RTL and nothing else — the input class `--strict-structural` exists for.

    Step 1 (Spec-to-RTL) resolves to PASS off `phase2/stage1/rtl/*.sv`; D1
    (Phase 1 Doc Extraction) is MISSING because no `L*.json` was authored. That
    pair is the ordering violation at the centre of #1429, and it is the NORMAL
    shape of a structural-only run, not a corrupt tree.
    """
    project = tmp_path / "proj"
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "core.sv").write_text("module core; endmodule\n")
    return project


def _audit(mod, project: Path, *flags: str, json_out: Path | None = None):
    argv = [str(project), *flags]
    if json_out is not None:
        argv += ["--json", str(json_out)]
    rc = mod.main(argv)
    return rc


# ══ 0. THE DEFECT — this is the only assertion that changes tree to tree ═══



# ══ 1. THE SAME TREE, THE SAME VIOLATIONS, STILL RED WHERE THEY COUNT ══════
#
# Both cases pass on the pre-fix AND the post-fix tree. They are what makes
# §0 a scoping change rather than a deleted guard: the violation set is
# IDENTICAL to §0's — only the requested verdict scope differs.





# ══ 2. AN IN-SCOPE DEPENDENCY STILL GATES — the discriminating control ═════
#
# One difference between the two cases: which step the violated dependency IS.
# A rule that stopped gating altogether fails the first; a rule that kept
# gating unconditionally fails the second. Neither can be satisfied by the
# other's answer.









# ══ 3. SCOPED, NOT SUPPRESSED ══════════════════════════════════════════════







# ══ 4. THE #634 BOUNDARY — the analog track still reaches the verdict ══════



# ══ 5. BACKED BY REAL IN-REPO ARTEFACTS, not only by fixtures ═════════════
#
# `flow-change-acceptance` §4: a change whose tests are ALL fixtures authored
# alongside it cannot distinguish itself from its own absence. The two cases
# below are driven by artefacts that were in the repo before this change — the
# canonical flow definition, and the published compliance reports — through
# `_hostpaths.require_repo`, so neither hardcodes a path.

def test_the_scope_boundary_is_the_real_flows_own_boundary():
    """The scoping rule is only as good as what the FLOW says is in scope.

    Read from `flow/phase1_phase2_phase3.yaml` itself, not from a fixture:
    `P0` and the analog track are the structural-only verdict scope, and the
    step-level steps this issue is about — D1 and the numbered steps — are
    outside it. Goes red if the analog stage word is renamed, if D1 is moved
    onto the analog track, or if `P0` stops being a step id.
    """
    import yaml
    import verdict as tiers
    import _hostpaths

    flow = _hostpaths.require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "flow",
        "phase1_phase2_phase3.yaml")
    steps = yaml.safe_load(flow.read_text())["steps"]
    by_id = {str(st.get("id")): st for st in steps}

    assert "P0" in by_id, "PRECONDITION: the P0 umbrella must exist in the flow"
    analog = [sid for sid, st in by_id.items() if tiers.in_analog_track(st)]
    assert analog, "PRECONDITION: the flow must declare an analog track"

    # In scope for `--phase 2 --strict-structural`.
    in_scope = {"P0", *analog}
    # The dependency at the centre of #1429, and the Phase-2 step-level gates
    # the mode reports as informational.
    for sid in ("D1", "1", "2", "12", "13"):
        assert sid in by_id, f"PRECONDITION: step {sid} must exist in the flow"
        assert sid not in in_scope, (
            f"step {sid} is inside the structural-only verdict scope, so the "
            f"premise of #1429 no longer holds and this fix needs re-deciding")
