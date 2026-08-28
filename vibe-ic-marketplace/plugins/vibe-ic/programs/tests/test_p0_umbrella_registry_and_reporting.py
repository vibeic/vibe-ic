"""P0 structural-RTL umbrella: registry integrity + report presence.

Three defects from the 63-step x 8-dimension flow-gate audit, all on step P0:

  * dim 2 — `skill_compliance_triangle_check` was registered in
    `_STRUCTURAL_RTL_GATES` but no `programs/skill_compliance_triangle_check.py`
    was ever authored. The dispatch loop's `if not prog.exists(): continue`
    dropped it with no fail, no skip, no waiver and no report line, while the
    umbrella kept advertising `len(_STRUCTURAL_RTL_GATES)` checkers. MEASURED
    on the reference run (spm x ihp-sg13g2, plugin 1.6.71-pr427):
    `reports/audit/flow_compliance_check.log` line 8 reads "P0 umbrella, 241
    checkers" and `grep -c skill_compliance_triangle` over that log returns 0.

  * dim 3 / dim 8 — when every gate PASSes with zero skips and zero waivers,
    the umbrella `StepResult` was never constructed, so P0 vanished from the
    human report, from the JSON `steps` array and from `counts`. The single
    best outcome was the only one with no audit record, and
    `--phase 2 --strict-structural` (verdict scope = `[r for r in results if
    r.id == "P0"]`) then decided PASS over an empty scope.

  * dim 5 — the flow yaml's own P0 name/comment and
    `benchmark_verify_report.STEP_METHOD["P0"]` hardcoded "77 gates", a figure
    roughly 3x below the live registry.

The tests below assert observable properties (what the report contains, which
gates actually dispatch), not source substrings, so they stay valid under any
correct alternative fix — e.g. authoring the missing checker instead of
retiring its registry entry would satisfy the dispatch test just as well.
"""
from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

import pytest
import yaml

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN_ROOT / "programs"
FLOW_YAML = PLUGIN_ROOT / "flow" / "phase1_phase2_phase3.yaml"

sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _p0_umbrella_probe_flow as _probe  # noqa: E402
import benchmark_verify_report as _bvr  # noqa: E402
import flow_compliance_check as _flow
import _spawn_stub  # noqa: E402


def _project_with_rtl(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    (proj / "rtl").mkdir(parents=True)
    (proj / "rtl" / "top.v").write_text(
        "module top(input a, output b); assign b = a; endmodule\n")
    return proj


def _stub_subprocess(monkeypatch, dispatched: list, rc: int = 0):
    """Record every gate the umbrella actually spawns; return `rc` for each.

    Anchored on `subprocess.Popen` via `_spawn_stub`, NOT on
    `_flow.subprocess.run`. The old form bound this to whichever helper the
    umbrella called that day: when the P0 launch moved to
    `_watchdog.run_host_supervised`, the gates still ran and this stub went
    blind, reddening both tests below with no change in the behaviour they
    assert. See `_spawn_stub` for the mechanism and
    `test_matrix_d1_wiring.py` for the falsification legs.
    """
    _spawn_stub.stub_spawn(monkeypatch, lambda _stem: (rc, ""), dispatched)


# ---------------------------------------------------------------------------
# dim 2 — every advertised checker really dispatches (or is named as skipped)
# ---------------------------------------------------------------------------
def test_every_registered_structural_gate_dispatches_or_is_named(
        tmp_path, monkeypatch):
    """No registry entry may vanish between the advertised count and the run.

    The umbrella's own step name promises `len(_STRUCTURAL_RTL_GATES)`
    checkers. Each registered gate must therefore either be spawned, or be
    named in the skip list. Silently dropping one — which is what a registry
    entry with no backing program used to do — makes that promise false.
    """
    monkeypatch.setenv("VIBE_IC_COMPLIANCE_WORKERS", "1")
    proj = _project_with_rtl(tmp_path)
    dispatched: list[str] = []
    _stub_subprocess(monkeypatch, dispatched)

    passed, fails, skips, waivers = _flow._run_structural_rtl_gates(proj)

    registered = set(_flow._STRUCTURAL_RTL_GATES)
    named_in_skips = {s.split()[0] for s in skips}
    unaccounted = registered - set(dispatched) - named_in_skips
    assert not unaccounted, (
        "registered structural gates that neither dispatched nor were named "
        f"as skipped: {sorted(unaccounted)}")
    assert passed is True and fails == [] and waivers == []


def test_missing_backing_program_is_disclosed_not_silently_dropped(
        tmp_path, monkeypatch):
    """A registry entry whose program is absent must SAY so, by name.

    Synthetic fixture (the shipped registry has no such entry any more): a
    phantom gate name is injected into the registry, so the missing-program
    branch is exercised for real rather than assumed.
    """
    monkeypatch.setenv("VIBE_IC_COMPLIANCE_WORKERS", "1")
    proj = _project_with_rtl(tmp_path)
    phantom = "zzz_never_authored_gate_check"
    assert not (PROGRAMS / f"{phantom}.py").exists()
    monkeypatch.setattr(
        _flow, "_STRUCTURAL_RTL_GATES",
        tuple(_flow._STRUCTURAL_RTL_GATES) + (phantom,))
    dispatched: list[str] = []
    _stub_subprocess(monkeypatch, dispatched)

    passed, fails, skips, waivers = _flow._run_structural_rtl_gates(proj)

    assert phantom not in dispatched, "phantom gate cannot have a program"
    assert any(s.startswith(phantom) for s in skips), (
        f"missing-program gate {phantom} left no record; skips={skips}")
    # Direction 1: disclosure is not a new failure mode — a missing program
    # is reported, never converted into an umbrella FAIL.
    assert passed is True and fails == []


# ---------------------------------------------------------------------------
# dim 3 / dim 8 — P0 is present in the report in EVERY outcome, including the
# all-clean one
# ---------------------------------------------------------------------------
def _run_main(tmp_path, monkeypatch, records, extra_args=(),
              dispatched=True, seed_dependency_chain=True):
    """Drive main() with the gate runner replaced by a fixed set of RECORDS.

    #497 step 3 — `reasons` is rendered FROM the records, so a stub that states
    an outcome only in prose states it to nobody. This stub publishes the
    records and derives its own 4-tuple from them exactly as the real umbrella
    does, which is what makes the assertions below assertions about the shipped
    renderer rather than about a fixture's idea of it.

    `dispatched=False` is the no-RTL case: the umbrella considered no gate at
    all and returns `None` as its tri-state.

    THE FLOW IS THE FIXTURE'S, and its P0 is the shipped P0 verbatim — see
    `_p0_umbrella_probe_flow`. On the shipped 63-step flow a `tmp_path` project
    leaves P0's declared ancestry (`1` -> `D1`) MISSING, and the ordering rule
    rewrites the umbrella's own word before it can be read. Here that ancestry
    is present and SATISFIED, so the rule runs at full strength, finds nothing,
    and what the report states about P0 is what the umbrella stated.
    `seed_dependency_chain=False` withholds the seed — the negative control
    that proves this fixture is what clears the void.
    """
    proj = _project_with_rtl(tmp_path)
    fails, skips, waivers = _flow._p0_buckets_from_records(records)
    executed = (len(fails) == 0) if dispatched else None
    if not dispatched:
        skips = [_flow._P0_NO_RTL_NOTE]

    def _stub(_project, **kw):
        out = kw.get("records_out")
        if out is not None:
            out.extend(records)
        return (executed, fails, skips, waivers)

    monkeypatch.setattr(_flow, "_run_structural_rtl_gates", _stub)
    flow_def = tmp_path / "p0_probe_flow.yaml"
    _probe.write_flow(flow_def)
    if seed_dependency_chain:
        _probe.write_seed(proj)
    out = tmp_path / "report.json"
    rc = _flow.main([str(proj), "--json", str(out),
                     "--flow-def", str(flow_def), *extra_args])
    return rc, json.loads(out.read_text())


def _fail(name, msg):
    return _flow._p0_gate_record(name, "FAIL", msg, {"exit_code": 1})


def _pass(name):
    """A gate that RAN and came back clean.

    A "clean sweep" fixture has to publish these. Building it from an empty
    records list instead makes `executed` true by `len([]) == 0` — a clean
    sweep of NOTHING — and the assertions below then pin the umbrella's word
    for a population of zero, which is the case this file's own subject says
    must never be a PASS."""
    return _flow._p0_gate_record(name, "PASS", "", {"exit_code": 0})


def _p0(report):
    hits = [s for s in report["steps"] if s["id"] == "P0"]
    return hits[0] if hits else None


# --- the fixture itself, in both directions --------------------------------
# Everything below reads P0's own verdict out of a run whose dependency chain
# the fixture satisfies. If that satisfaction ever stops being real, every one
# of those assertions changes meaning without changing text, so it is asserted
# here rather than assumed — and asserted with the control that proves the
# fixture is what does it.
def test_the_probe_flow_really_satisfies_p0s_dependency_chain(
        tmp_path, monkeypatch, capsys):
    """PREMISE. P0 declares ancestors, they are carried, and they all PASS."""
    assert _probe.stand_in_ids(), (
        "the shipped P0 declares no blocks_on ancestry, so this fixture guards "
        "nothing and every 'must still say PASS' assertion below is untested")
    rc, report = _run_main(tmp_path, monkeypatch, [_pass("gate_ok")],
                           ("--lenient",))
    capsys.readouterr()
    by_id = {str(s["id"]): s for s in report["steps"]}
    for sid in _probe.stand_in_ids():
        assert str(sid) in by_id, f"stand-in {sid} is not in the report"
        assert by_id[str(sid)]["status"] == "PASS", (
            f"stand-in {sid} is {by_id[str(sid)]['status']!r}, so P0's "
            f"dependency is excused or absent rather than SATISFIED")
    assert report["ordering_violations"] == [], report["ordering_violations"]
    assert not [r for r in by_id["P0"]["reasons"] if "PASS voided" in r]
    assert rc == 0


def test_NEGATIVE_CONTROL_withholding_the_seed_brings_the_void_back(
        tmp_path, monkeypatch, capsys):
    """...and the fixture is what clears it, not luck.

    Same flow, same records, same everything — minus the one file the stand-in
    gates look for. The ancestors go MISSING, the ordering rule fires, and the
    umbrella's PASS is rewritten. This is the state origin/main measured for
    every test in this file, and it must stay reachable: if it stops
    reproducing, the fixture above has gone inert and is passing for a reason
    it does not state.
    """
    rc, report = _run_main(tmp_path, monkeypatch, [_pass("gate_ok")],
                           ("--lenient",), seed_dependency_chain=False)
    capsys.readouterr()
    p0 = _p0(report)
    assert p0 is not None and p0["status"] == "PASS_VOIDED_BY_DEPENDENCY", (
        f"the ordering rule no longer voids a P0 PASS over a MISSING "
        f"dependency; status={p0 and p0['status']!r}")
    assert any("PASS voided" in r for r in p0["reasons"]), p0["reasons"]
    assert report["ordering_violations"], (
        "no ordering violation over an unsatisfied chain")


def test_all_gates_clean_still_emits_a_P0_step(tmp_path, monkeypatch, capsys):
    """Clean sweep: P0 must appear as an explicit PASS, not disappear.

    The sweep is stated with a gate that ANSWERED. It used to be stated with
    an empty records list, which is not a clean sweep — it is a sweep of zero
    gates whose `len(fails) == 0` is vacuously true — and this assertion was
    therefore a second pin of the vacuous PASS, one level up from the truth
    table. The claim under test is unchanged: an all-clean structural run
    still renders P0 as an explicit PASS in the JSON and in the listing.
    """
    rc, report = _run_main(tmp_path, monkeypatch, [_pass("gate_ok")],
                           ("--lenient",))
    p0 = _p0(report)
    assert p0 is not None, (
        "P0 missing from the JSON steps array on an all-clean structural run")
    assert p0["status"] == "PASS"
    assert p0["reasons"], "an all-clean P0 must still say what it verified"
    # P0 is IN the PASS numerator, not merely absent from the failures. Stated
    # as the exact total (P0 + the fixture's stand-ins) rather than `>= 1`,
    # which the stand-ins alone would satisfy: every tier that is not a full
    # PASS — `PASS_VOIDED_BY_DEPENDENCY`, `VACUOUS_PASS`, `INCOMPLETE` — sits
    # outside this count, so this is the assertion that catches P0 being
    # demoted into one of them while still rendering as a green-looking row.
    assert report["counts"]["PASS"] == len(_probe.stand_in_ids()) + 1, (
        f"P0 is not counted as a PASS; counts={report['counts']}")
    assert "Step P0" in capsys.readouterr().out, (
        "P0 missing from the human-readable per-step listing")


def test_strict_structural_verdict_is_not_decided_over_an_empty_scope(
        tmp_path, monkeypatch):
    """`--phase 2 --strict-structural` scopes its verdict to P0 alone.

    With P0 absent that scope is empty and the tool reports PASS having
    examined nothing. The umbrella result must be in the report for the
    verdict to mean anything.
    """
    rc, report = _run_main(tmp_path, monkeypatch, [],
                           ("--phase", "2", "--strict-structural"))
    assert _p0(report) is not None, (
        "strict-structural verdict computed with no P0 result in scope")
    assert rc == 0


# --- direction 1: the outcomes that already worked must not change ---------
# #497 step 3 — these are now GOLDEN-TEXT assertions on the operator-facing
# rendering, driven from records. Every reason line is stated in full, so a
# change to the wording, the ordering or the shape selection is a test failure
# rather than something a reader has to notice.
def test_failing_umbrella_still_reports_FAIL_with_its_gate_lines(
        tmp_path, monkeypatch):
    """Form 2: >= 2 failures -> a `Failed gates (N):` header + indented dashes."""
    rc, report = _run_main(
        tmp_path, monkeypatch,
        [_fail("gate_a", "boom"), _fail("gate_b", "bang")], ("--strict",))
    p0 = _p0(report)
    assert p0 is not None and p0["status"] == "FAIL"
    assert p0["reasons"] == ["Failed gates (2):",
                             "  - gate_a — boom",
                             "  - gate_b — bang"]
    assert rc != 0


def test_single_fail_reason_shape_unchanged(tmp_path, monkeypatch):
    """Form 1: exactly one failure -> a single `FAIL: <gate> — <msg>` line."""
    rc, report = _run_main(tmp_path, monkeypatch, [_fail("gate_a", "boom")],
                           ("--strict",))
    p0 = _p0(report)
    assert p0 is not None and p0["status"] == "FAIL"
    assert p0["reasons"] == ["FAIL: gate_a — boom"]


def test_no_rtl_umbrella_still_reports_SKIPPED_CONDITION(
        tmp_path, monkeypatch):
    """#447: 0/N checkers executed is not a PASS — must stay a skip.

    #497 step 3 — this line is the umbrella's note about ITSELF: it names no
    gate, and it is now emitted from the umbrella's tri-state rather than out
    of the per-gate skip bucket. Its rendering, prefix included, is unchanged.
    """
    rc, report = _run_main(tmp_path, monkeypatch, [], ("--lenient",),
                           dispatched=False)
    p0 = _p0(report)
    assert p0 is not None and p0["status"] == "SKIPPED-CONDITION"
    assert p0["reasons"] == [f"SKIP: {_flow._P0_NO_RTL_NOTE}"]
    assert p0["gate_records"] == [], (
        "no gate was considered, so there is no gate record — and the line "
        "above is not one")
    assert not any(g in p0["reasons"][0] for g in _flow._STRUCTURAL_RTL_GATES)


def test_skips_and_waivers_are_still_listed_verbatim(tmp_path, monkeypatch):
    """The SKIP and WAIVED-DEFERRED shapes, rendered from their records.

    The waiver is asserted IN ITS OWN UNIT. `counts` is a tally of STEPS and
    `gate_w` is a structural SUB-GATE inside the one step P0, so it contributes
    0 there — #924/#930 removed the `counts["WAIVED"] += len(structural_waivers)`
    addend precisely because a sub-gate that excused a step off a 63-step
    denominator made the published ratio RISE with the number of things waived.
    Both numbers are stated: 0 waived steps, and the sub-gate published verbatim
    in the channel that carries it. Asserting only the first would be satisfied
    by dropping the waiver on the floor.
    """
    waiver = {"gate": "gate_w", "ticket": "T-1", "first_line": "why",
              "review_required": True}
    rc, report = _run_main(
        tmp_path, monkeypatch,
        [_flow._p0_gate_record("gate_s", "SKIP", "class N/A",
                               {"skip_kind": "class-not-applicable"}),
         _flow._p0_waiver_record(waiver)],
        ("--lenient",))
    p0 = _p0(report)
    assert p0 is not None and p0["status"] == "PASS"
    assert p0["reasons"] == [
        "SKIP: gate_s (SKIP: class N/A)",
        "WAIVED-DEFERRED: gate_w — thin-input (ticket=T-1, "
        "review_required=true): why",
    ]
    assert report["counts"]["WAIVED"] == 0, (
        "a structural SUB-GATE waiver was counted as a waived STEP; that is "
        f"the #924 unit error. counts={report['counts']}")
    assert [w["gate"] for w in report["thin_input_waivers"]] == ["gate_w"], (
        "the sub-gate waiver left the step tally and landed nowhere")


# ---------------------------------------------------------------------------
# dim 5 — P0's static documentation may not state a gate count that the live
# registry contradicts
# ---------------------------------------------------------------------------
# "77 gates", "77 chip-AGNOSTIC structural gates", "77 structural-RTL
# chip-agnostic checkers" all match; version strings like "v1.6.15" and bare
# numbers not describing gates do not.
_COUNT_RE = re.compile(
    r"(?<![.\d])(\d+)\s+(?:[\w-]+\s+){0,3}?(?:gates|checkers|checks)\b",
    re.IGNORECASE)


def _p0_doc_blocks() -> dict[str, str]:
    """P0's static prose: the yaml comment block, the yaml step, the report
    method string."""
    lines = FLOW_YAML.read_text().splitlines()
    start = next(i for i, ln in enumerate(lines) if "── P0 " in ln)
    end = next(i for i in range(start, len(lines))
               if lines[i].strip() == "" and i > start)
    steps = yaml.safe_load(FLOW_YAML.read_text())["steps"]
    p0_step = next(s for s in steps if s.get("id") == "P0")
    return {
        f"{FLOW_YAML.name} P0 block": "\n".join(lines[start:end]),
        f"{FLOW_YAML.name} P0 step": json.dumps(p0_step, ensure_ascii=False),
        "benchmark_verify_report.STEP_METHOD['P0']":
            " ".join(_bvr.STEP_METHOD["P0"]),
    }


def test_p0_documentation_exists_and_describes_the_structural_umbrella():
    """Presence guard: the count check below must not pass vacuously."""
    blocks = _p0_doc_blocks()
    assert len(blocks) == 3
    for where, text in blocks.items():
        assert "structural" in text.lower(), f"{where} no longer describes P0"


def test_p0_documentation_states_no_stale_gate_count():
    """Any gate count P0's documentation states must be the live count.

    Either fix satisfies this: drop the hardcoded number, or keep one that is
    correct. What may not survive is a number that contradicts the registry.
    """
    live = len(_flow._STRUCTURAL_RTL_GATES)
    stale = []
    for where, text in _p0_doc_blocks().items():
        for m in _COUNT_RE.finditer(text):
            if int(m.group(1)) != live:
                stale.append(f"{where}: {m.group(0)!r} (live count is {live})")
    assert not stale, "stale gate counts in P0's documentation: " + "; ".join(
        stale)


def test_registry_and_shipped_programs_agree():
    """Every registered structural gate names a program that exists.

    Deliberate policy, stated so a future reader does not mistake it for an
    accident: the umbrella's advertised checker count IS the registry length,
    so the package must ship every checker it registers. A checker that cannot
    be shipped is removed from the registry (and tracked as open work), not
    left in it to skip for ever. The runtime named-skip added alongside this
    test is the safety net for the window in between, not a licence to keep
    phantom entries.

    Static twin of the dispatch test above; catches a phantom entry without
    running 240 subprocesses.
    """
    missing = [g for g in _flow._STRUCTURAL_RTL_GATES
               if not (PROGRAMS / f"{g}.py").exists()]
    assert not missing, (
        "registered in _STRUCTURAL_RTL_GATES but not shipped: "
        f"{missing} — the umbrella advertises "
        f"{len(_flow._STRUCTURAL_RTL_GATES)} checkers")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
