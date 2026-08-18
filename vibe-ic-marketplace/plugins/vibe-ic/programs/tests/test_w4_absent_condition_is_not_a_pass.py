"""NOTHING TO CHECK IS A FAILURE, NOT A PASS — the `optional_program_exit_zero`
half.

WHAT WAS WRONG
--------------
`flow_compliance_check._evaluate_gate` evaluated an `optional_program_exit_zero`
clause whose `condition_files_exist` matched no path as

    if not present:
        return True, reasons  # no inputs -> N/A -> pass

No marker, no reason, no record. MEASURED on origin/main (397b3f25f) against an
EMPTY project tree, every one of step 2's nine optional clauses:

    origin/main -> PASS   reasons=[]

The clause did not run, concluded nothing, and was indistinguishable in the
step record from a clause that ran and found nothing. That is the sentence
`tools/ci/_gate_dispatch.sh` spends four hundred lines removing from the
hygiene tier ("I could not look" must not reach a reader as "I looked and it
was clean"), and the flow gate dispatcher had the opposite default.

THE OPPOSITE IDIOM
------------------
OpenROAD-flow-scripts' `util/checkMetadata.py` exits 1 on `len(rules) == 0`
("No rules"), and exits 1 for a rule whose metric is absent from
`metadata.json` ("[ERROR] Value not found for {field}"). Absent input is its
FAILURE case, which is why a stage skipped with `SKIP_DETAILED_ROUTE=1` — which
still produces a GDS and still lets `make finish` succeed — is caught by the
missing `detailedroute__route__drc_errors`.

WHAT THIS FILE PINS
-------------------
A1  an unmet condition with NO `absent_condition_reason` FAILs, and the reason
    NAMES the patterns that matched nothing (the empty corpus).
A2  an unmet condition WITH a declaration passes, and emits the
    `__NA_HINT__` marker carrying the declared reason — the exemption is
    visible, which is the whole difference between an exemption and a hole.
A3  a declaration too short to be checkable buys nothing.
A4  a MET condition still dispatches the program: the fix must not have been
    bought by checking less.
A5  the marker is held out of `non_hint_reasons`, so a declared not-applicable
    can never itself become a reason a step failed, and it is re-emitted on the
    step line so it cannot vanish either.
A6  the shipped flow YAML declares one on EVERY optional clause.
A7  the static gate (`flow_condition_reachability_check`) FAILs a flow YAML
    with an undeclared clause and names it — the declaration is itself gated.
A8  the runtime floor and the static floor are the SAME number, read from each
    module rather than copied here.
A11 the ADVISORY slot carries the same `condition_files_exist` shape and had
    the same silent skip. It is covered too: its own SKILL.md states the
    exposure — "over the 28 published run roots it executes on 1 and is
    silent on 27". An undeclared one FAILs (a wiring defect, which this branch
    already treats as blocking even in the advisory slot); a declared one is
    recorded on the advisory channel.
A10 the record SURVIVES the `all_of` / `any_of` whitelist. That loop forwards
    only the hint prefixes it names and drops the rest silently — its own
    comment says so, and it had already cost #599 and #901 a landed
    disclosure each. MEASURED here before the branch existed: five of step 2's
    nine optional clauses emitted their declared not-applicable and
    `check_step` reported `declared_not_applicable: 0`.
A9  `len(rules) == 0` — the OTHER half of the same sentence. `files_exist: []`
    and `all_of: []` each certified a tree they never looked at; `any_of: []`
    already refused, so the right convention was in the same function. Pinned
    with a negative control against origin/main and with the measured fact
    that the shipped flow declares no empty list, so the ratchet ships with
    no debt.

NEGATIVE CONTROL. A1/A3/A7 are the arms that must FAIL against the pre-fix
code, and A1 is asserted directly against origin/main's own evaluator, loaded
from `git show` at test time, so the discrimination is measured and not
asserted.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
FLOW_YAML = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
sys.path.insert(0, str(PROGRAMS))

import flow_compliance_check as fcc  # noqa: E402
import flow_condition_reachability_check as fcr  # noqa: E402

_T = 120

#: One real clause, verbatim from the shipped flow, so this test cannot pass
#: against a shape the flow does not actually use.
_CLAUSE = {
    "command": ("rtl_bug_report_schema_check . "
                "--json reports/phase2/gates/rtl_bug_schema.json"),
    "condition_files_exist": ["reports/phase2/rtl_bugs.json"],
}


def _gate(spec: dict) -> dict:
    return {"optional_program_exit_zero": spec}


def _declared(reason: str = "x" * 60) -> dict:
    return {**_CLAUSE, "absent_condition_reason": reason}


# ── A1 — an undeclared empty corpus is a FAIL that names the corpus ────────
def test_undeclared_unmet_condition_fails_and_names_the_empty_corpus():
    with tempfile.TemporaryDirectory() as td:
        ok, reasons = fcc._evaluate_gate(Path(td), _gate(dict(_CLAUSE)))
    assert ok is False, "an unmet condition with no declaration must not pass"
    blob = " ".join(reasons)
    assert "reports/phase2/rtl_bugs.json" in blob, (
        "the FAIL must NAME the corpus that was empty, or a reader cannot tell "
        f"which one it was: {reasons}")
    assert "matched 0 path(s)" in blob
    assert "absent_condition_reason" in blob, (
        "the FAIL must say what would buy the tolerance")


# ── A1' — the same call against ORIGIN/MAIN's evaluator, measured ─────────
def _origin_main_fcc():
    """origin/main's `flow_compliance_check`, loaded from git at test time.

    The negative control has to be the code that actually shipped, not a
    hand-written imitation of it: a control that cannot fail proves nothing,
    and one written from memory proves something else.
    """
    repo = PLUGIN
    while repo != repo.parent and not (repo / ".git").exists():
        repo = repo.parent
    rel = ("vibe-ic-marketplace/plugins/vibe-ic/programs/"
           "flow_compliance_check.py")
    r = subprocess.run(["git", "-C", str(repo), "show", f"origin/main:{rel}"],
                       capture_output=True, text=True, timeout=_T)
    if r.returncode != 0 or not r.stdout:
        pytest.skip("origin/main not fetched in this checkout")
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "base_fcc.py"
        src.write_text(r.stdout, encoding="utf-8")
        spec = importlib.util.spec_from_file_location("w4_base_fcc", src)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["w4_base_fcc"] = mod
        spec.loader.exec_module(mod)
        return mod


def test_negative_control_origin_main_passes_the_same_empty_corpus_silently():
    base = _origin_main_fcc()
    with tempfile.TemporaryDirectory() as td:
        ok, reasons = base._evaluate_gate(Path(td), _gate(dict(_CLAUSE)))
    assert ok is True and reasons == [], (
        "the defect this file pins is that origin/main returned a BARE True "
        f"with no record; it returned {(ok, reasons)!r} instead, so the "
        "control no longer discriminates and this test is measuring nothing")


# ── A2 — a declared exemption passes, and is VISIBLE ──────────────────────
def test_declared_unmet_condition_passes_and_says_so():
    why = ("Scoped to a CLAIM file that a clean run legitimately never "
           "writes; the failure mode needs the claim to exist.")
    with tempfile.TemporaryDirectory() as td:
        ok, reasons = fcc._evaluate_gate(Path(td), _gate(_declared(why)))
    assert ok is True
    hints = [r for r in reasons
             if r.startswith(fcc._NOT_APPLICABLE_HINT_PREFIX)]
    assert len(hints) == 1, (
        f"a declared not-applicable must leave exactly one record: {reasons}")
    assert why in hints[0], "the record must carry the DECLARED reason verbatim"
    assert "reports/phase2/rtl_bugs.json" in hints[0]


# ── A3 — a declaration too short to be checkable buys nothing ─────────────
@pytest.mark.parametrize("why", ["", "   ", "N/A", "optional", "x" * 39])
def test_a_placeholder_declaration_buys_nothing(why):
    with tempfile.TemporaryDirectory() as td:
        ok, _ = fcc._evaluate_gate(Path(td), _gate(_declared(why)))
    assert ok is False, (
        f"{why!r} is a label on the hole, not the hole closed; "
        f"the floor is {fcc._MIN_ABSENT_CONDITION_REASON} characters")


def test_a_declaration_at_the_floor_is_accepted():
    why = "y" * fcc._MIN_ABSENT_CONDITION_REASON
    with tempfile.TemporaryDirectory() as td:
        ok, _ = fcc._evaluate_gate(Path(td), _gate(_declared(why)))
    assert ok is True, "the floor must be inclusive, or it is off by one"


# ── A4 — a MET condition still runs the program ──────────────────────────
def test_a_met_condition_still_dispatches_the_program():
    """The fix must not have been bought by checking less.

    With the condition MET the clause dispatches, so the record carries the
    `__RAN_HINT__` denominator marker and NO not-applicable marker — and it
    carries them identically with and without the declaration, because the
    declaration only ever describes the branch where nothing ran.
    """
    for spec in (dict(_CLAUSE), _declared()):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            tgt = project / "reports" / "phase2" / "rtl_bugs.json"
            tgt.parent.mkdir(parents=True)
            tgt.write_text("{}\n", encoding="utf-8")
            _, reasons = fcc._evaluate_gate(project, _gate(spec))
        assert any(r.startswith(fcc._RAN_HINT_PREFIX) for r in reasons), (
            f"a met condition must dispatch the program: {reasons}")
        assert not any(
            r.startswith(fcc._NOT_APPLICABLE_HINT_PREFIX) for r in reasons), (
            "a clause that RAN must never be recorded not-applicable")


# ── A5 — the marker is a hint, not a failure reason, and it survives ──────
def test_the_marker_is_held_out_of_the_failure_reasons_and_re_emitted():
    """`check_step` must treat the marker the way it treats an advisory one.

    Both halves matter and they pull opposite ways: held out, so a declared
    not-applicable can never become a reason a step FAILED; re-emitted, so the
    exemption cannot become invisible — which is the state this whole change
    exists to remove.
    """
    src = (PROGRAMS / "flow_compliance_check.py").read_text(encoding="utf-8")
    held_out = ("and not r.startswith(_NOT_APPLICABLE_HINT_PREFIX)]")
    assert held_out in src, (
        "the marker must be excluded from `non_hint_reasons`")
    assert "NOT-APPLICABLE (declared," in src, (
        "the marker must be re-emitted onto the step line after the tier "
        "resolves; a held-out hint that is never re-emitted is a silent skip "
        "with extra steps")
    assert "declared_not_applicable" in src, (
        "the same fact must reach the JSON report as a typed field, not only "
        "as prose a consumer has to re-parse")


# ── A6 — the shipped flow declares one on every optional clause ───────────
def _flow_optional_clauses():
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(FLOW_YAML.read_text(encoding="utf-8"))
    found = []

    def walk(node, where):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "optional_program_exit_zero" and isinstance(v, dict):
                    found.append((where, v))
                walk(v, where)
        elif isinstance(node, list):
            for item in node:
                walk(item, where)

    for st in doc.get("steps", []):
        walk(st.get("gate"), f"step {st.get('id')}")
    return found


def test_every_shipped_optional_clause_declares_its_not_applicable():
    clauses = _flow_optional_clauses()
    assert clauses, "the flow declares no optional clause — read the wrong file"
    missing = []
    for where, spec in clauses:
        why = spec.get("absent_condition_reason")
        why = why.strip() if isinstance(why, str) else ""
        if len(why) < fcc._MIN_ABSENT_CONDITION_REASON:
            missing.append(f"{where} {spec.get('command', '').split(' ')[0]}")
    assert not missing, (
        f"{len(missing)} of {len(clauses)} shipped optional clause(s) would "
        f"FAIL at run time on a project that does not carry their input: "
        f"{missing}")


# ── A7 — the declaration is itself gated, and the gate discriminates ──────
def _run_reachability(flow_path: Path):
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "flow_condition_reachability_check.py"),
         str(flow_path), "--baseline", ""],
        capture_output=True, text=True, timeout=_T)
    return r


def test_static_gate_passes_the_shipped_flow_and_fails_an_undeclared_one(tmp_path):
    good = _run_reachability(FLOW_YAML)
    assert "do not declare `absent_condition_reason`" not in good.stdout, (
        f"the shipped flow must satisfy its own gate: {good.stdout[-800:]}")

    # Strip ONE declaration and nothing else.
    lines = FLOW_YAML.read_text(encoding="utf-8").split("\n")
    out, i, stripped = [], 0, 0
    while i < len(lines):
        line = lines[i]
        stripped_line = line.strip()
        if stripped_line == "absent_condition_reason: >-" and stripped == 0:
            indent = len(line) - len(line.lstrip())
            i += 1
            while (i < len(lines) and lines[i].strip()
                   and (len(lines[i]) - len(lines[i].lstrip())) > indent):
                i += 1
            stripped = 1
            continue
        out.append(line)
        i += 1
    assert stripped == 1, "found no declaration to strip"
    hurt = tmp_path / "flow.yaml"
    hurt.write_text("\n".join(out), encoding="utf-8")

    bad = _run_reachability(hurt)
    assert bad.returncode == 1, (
        f"stripping one declaration must FAIL the gate; got rc "
        f"{bad.returncode}\n{bad.stdout[-800:]}")
    assert "do not declare `absent_condition_reason`" in bad.stdout
    assert "rtl_bug_report_schema_check" in bad.stdout, (
        f"the FAIL must NAME the clause: {bad.stdout[-800:]}")


def test_static_gate_reports_the_undeclared_set_in_its_json(tmp_path):
    out = tmp_path / "r.json"
    subprocess.run(
        [sys.executable, str(PROGRAMS / "flow_condition_reachability_check.py"),
         str(FLOW_YAML), "--json", str(out)],
        capture_output=True, text=True, timeout=_T)
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert "undeclared_not_applicable" in doc, (
        "a consumer must be able to read the set without parsing prose")
    assert doc["undeclared_not_applicable"] == []


# ── A8 — one floor, read from both modules ───────────────────────────────
def test_the_runtime_floor_and_the_static_floor_are_the_same_number():
    assert (fcr.MIN_ABSENT_CONDITION_REASON
            == fcc._MIN_ABSENT_CONDITION_REASON), (
        "two hand-kept floors are two floors that drift: a clause the static "
        "gate blesses would then be one the runtime refuses, or worse")


# ── A9 — an EMPTY predicate list is a non-verdict, not a pass ─────────────
@pytest.mark.parametrize("gate,word", [
    ({"files_exist": []}, "files_exist"),
    ({"all_of": []}, "all_of"),
])
def test_an_empty_predicate_list_fails_and_says_it_examined_nothing(gate, word):
    with tempfile.TemporaryDirectory() as td:
        ok, reasons = fcc._evaluate_gate(Path(td), gate)
    assert ok is False, (
        f"`{word}: []` declares a gate and runs none of it; certifying a tree "
        f"from it is the `len(rules) == 0` case util/checkMetadata.py exits 1 "
        f"on")
    blob = " ".join(reasons)
    assert "EMPTY" in blob and word in blob, (
        f"the FAIL must name WHICH empty list it was: {reasons}")


def test_negative_control_origin_main_passed_the_empty_predicate_lists():
    base = _origin_main_fcc()
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        assert base._evaluate_gate(p, {"files_exist": []}) == (True, []), (
            "control no longer discriminates on files_exist: []")
        assert base._evaluate_gate(p, {"all_of": []}) == (True, []), (
            "control no longer discriminates on all_of: []")


def test_any_of_empty_still_refuses_exactly_as_it_always_did():
    """The convention was already in this function; it must not have moved."""
    with tempfile.TemporaryDirectory() as td:
        ok, reasons = fcc._evaluate_gate(Path(td), {"any_of": []})
    assert ok is False
    assert reasons == ["no sub-gate passed in any_of"], (
        f"an untouched branch changed shape: {reasons}")


def test_the_shipped_flow_declares_no_empty_predicate_list():
    """The ratchet lands with ZERO debt, and this is the measurement that says
    so — re-taken every run, so the claim cannot rot into a comment."""
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(FLOW_YAML.read_text(encoding="utf-8"))
    empties = []

    def walk(node, where):
        if isinstance(node, dict):
            for k, v in node.items():
                if (k in ("files_exist", "all_of", "any_of")
                        and isinstance(v, list) and not v):
                    empties.append(f"{where}: {k}")
                walk(v, where)
        elif isinstance(node, list):
            for item in node:
                walk(item, where)

    for st in doc.get("steps", []):
        walk(st.get("gate"), f"step {st.get('id')} gate")
        walk(st.get("condition"), f"step {st.get('id')} condition")
    walk(doc.get("final_gate"), "final_gate")
    assert not empties, (
        f"the shipped flow now carries an empty predicate list, which this "
        f"branch refuses at run time: {empties}")


# ── A10 — the record survives the all_of / any_of whitelist ──────────────
def _step(sid):
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(FLOW_YAML.read_text(encoding="utf-8"))
    return next(s for s in doc["steps"] if str(s.get("id")) == str(sid))


def _tree_where_only_the_optional_inputs_are_absent(root: Path, step: dict):
    """The ordinary doc-to-GDS shape: the step DID its work (its declared
    outputs are there and its RTL exists), and the Phase-1 documents its
    optional clauses read were never authored."""
    for rel in step.get("required_outputs", []):
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("{}\n", encoding="utf-8")
    rtl = root / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "top.v").write_text(
        "module top(input a, output y); assign y = a; endmodule\n",
        encoding="utf-8")


def test_declared_not_applicable_survives_the_all_of_whitelist():
    step = _step(2)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _tree_where_only_the_optional_inputs_are_absent(root, step)
        _, reasons = fcc._evaluate_gate(root, step["gate"])
    carried = [r for r in reasons
               if r.startswith(fcc._NOT_APPLICABLE_HINT_PREFIX)]
    assert carried, (
        "the all_of loop is a WHITELIST: a hint it does not name is dropped "
        "there and the disclosure dies one level below the line meant to "
        f"carry it. Reasons that survived: {[r[:60] for r in reasons]}")
    ran = [r for r in reasons if r.startswith(fcc._RAN_HINT_PREFIX)]
    assert ran, "the denominator must travel with it, or the count is over zero"


def test_check_step_names_the_clauses_that_examined_nothing():
    step = _step(2)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _tree_where_only_the_optional_inputs_are_absent(root, step)
        result = fcc.check_step(root, step, {})
    assert result.declared_not_applicable, (
        f"step {step['id']} reported status={result.status} with no record "
        "that any clause was skipped; a step whose gate list is half "
        "unexecuted must not read like one whose gate list was executed")
    named = " ".join(result.reasons)
    assert "NOT-APPLICABLE (declared," in named
    assert "examined nothing" in named


def test_a_not_applicable_never_becomes_a_reason_the_step_failed():
    """Held out of `non_hint_reasons`, measured rather than read off the source.

    A step whose only unusual reason is a declared not-applicable must keep
    the verdict it would have had; the disclosure is additive.
    """
    step = _step(2)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _tree_where_only_the_optional_inputs_are_absent(root, step)
        result = fcc.check_step(root, step, {})
    assert result.status != "FAIL", (
        f"a declared not-applicable demoted the step to {result.status}: "
        f"{[r[:90] for r in result.reasons]}")


# ── A11 — the advisory slot, same shape, same rule ───────────────────────
_ADV = {
    "command": "fpga_led_probe_lint . --json reports/x.json",
    "condition_files_exist": ["phase2/stage1/fpga/*.qsf"],
}


def test_undeclared_advisory_condition_fails_as_a_wiring_defect():
    with tempfile.TemporaryDirectory() as td:
        ok, reasons = fcc._evaluate_gate(
            Path(td), {"advisory_program_exit_zero": dict(_ADV)})
    assert ok is False, (
        "the advisory tier protects a gate's FINDINGS, not its wiring: this "
        "same branch already FAILs a malformed advisory spec")
    blob = " ".join(reasons)
    assert "phase2/stage1/fpga/*.qsf" in blob and "matched 0 path(s)" in blob


def test_declared_advisory_condition_is_recorded_on_the_advisory_channel():
    why = ("Scoped to a run Quartus actually built; with no .qsf there is no "
           "FPGA top to lint and the slot never blocks.")
    with tempfile.TemporaryDirectory() as td:
        ok, reasons = fcc._evaluate_gate(
            Path(td),
            {"advisory_program_exit_zero": {**_ADV,
                                            "absent_condition_reason": why}})
    assert ok is True
    adv = [r for r in reasons if r.startswith(fcc._ADVISORY_HINT_PREFIX)]
    assert len(adv) == 1, f"expected one advisory record: {reasons}"
    assert "n/a (declared;" in adv[0] and why in adv[0]


def test_negative_control_origin_main_was_silent_on_the_advisory_slot():
    base = _origin_main_fcc()
    with tempfile.TemporaryDirectory() as td:
        ok, reasons = base._evaluate_gate(
            Path(td), {"advisory_program_exit_zero": dict(_ADV)})
    assert ok is True and reasons == [], (
        "control no longer discriminates on the advisory slot")


def test_every_shipped_conditioned_advisory_clause_declares_its_not_applicable():
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(FLOW_YAML.read_text(encoding="utf-8"))
    found = []

    def walk(node, where):
        if isinstance(node, dict):
            for k, v in node.items():
                if (k == "advisory_program_exit_zero" and isinstance(v, dict)
                        and v.get("condition_files_exist")):
                    found.append((where, v))
                walk(v, where)
        elif isinstance(node, list):
            for item in node:
                walk(item, where)

    for st in doc.get("steps", []):
        walk(st.get("gate"), f"step {st.get('id')}")
    walk(doc.get("final_gate"), "final_gate")
    assert found, "the flow declares no conditioned advisory clause"
    missing = [f"{w} {v['command'].split(' ')[0]}" for w, v in found
               if len(str(v.get("absent_condition_reason") or "").strip())
               < fcc._MIN_ABSENT_CONDITION_REASON]
    assert not missing, missing


def test_static_gate_covers_the_advisory_surface_too():
    out_dir = tempfile.mkdtemp()
    out = Path(out_dir) / "r.json"
    subprocess.run(
        [sys.executable, str(PROGRAMS / "flow_condition_reachability_check.py"),
         str(FLOW_YAML), "--json", str(out)],
        capture_output=True, text=True, timeout=_T)
    doc = json.loads(out.read_text(encoding="utf-8"))
    surfaces = {c["surface"] for c in doc["conditions"]}
    assert "advisory" in surfaces, (
        "an advisory clause the runtime now judges must also be visible to "
        "the static gate, or the declaration is enforced on only one of the "
        "two paths that read it")
    assert doc["undeclared_not_applicable"] == []
