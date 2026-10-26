"""R-0915-86 (1) — the shared table reader and the direction rule.

`_step_verdict_table` is the ONE place `real_ic_gate` and `audit_replay` turn a
compliance artefact into a per-step table and decide which way a step moved.
Two properties have to hold or both programs lie in the same way:

  1. BOTH artefact shapes read as the SAME table. `flow_compliance_check` writes
     `verdict`/`step_counts`/`command_argv` into
     `reports/audit/phase23_completion_audit.json` and `overall`/`counts` into
     the path given to `--json`, with an element-for-element identical `steps[]`
     (MEASURED 2026-09-16 on the frozen subservient_r26 snapshot: 69 steps,
     identical 18-key records, identical counts). A reader that knew one shape
     would read the other as a table with no verdict — i.e. would rank it
     NON_GREEN and report a catastrophic regression that never happened.

  2. The direction rule adds NO vocabulary. It is `verdict`'
     classification, which adjudicates BY SUBTRACTION so a word invented
     tomorrow lands somewhere without anyone remembering to come here. The
     load-bearing test below plants a word registered NOWHERE and requires a
     direction for it.

CALIBRATION (R-0915-86 (3)) is the pair of tests at the end: the differ must
FIRE on a planted flip and stay SILENT on an identical table. An instrument that
has not been shown to do both may not judge.
"""
from __future__ import annotations

import importlib

S = importlib.import_module("_step_verdict_table")
T = importlib.import_module("verdict")


def _audit(steps, ledger=(), **kw):
    """A compliance artefact. `gate_execution_ledger` is present BY DEFAULT and
    empty, because that is what a real run with no unanswered hand-off looks
    like — and because a table with no ledger is deliberately NOT comparable
    (see `test_a_table_with_no_ledger_is_refused`), so a fixture without one
    would be testing the refusal, not the rule under test."""
    doc = {"steps": [{"id": i, "name": "step %s" % i, "stage": "stage1",
                      "status": s} for i, s in steps],
           "gate_execution_ledger": list(ledger),
           "resolved_flow_identity": {
               "schema": "vibeic.resolved-flow-identity.v1",
               "status": "RESOLVED", "flow_id": "109"}}
    doc.update(kw)
    return doc


def _awaiting_row(gate):
    """A ledger row for a gate that reached the flow's AWAITING state — pass one
    done, pass two is an agent's and nobody answered."""
    return {"gate": gate, "cmd": "%s . --check-report" % gate, "rc": 0,
            "verdict": "PASS", "exit_code": S.awaiting_exit_code()}


# ── 1. the two artefact shapes are one table ─────────────────────────────────

def test_completion_audit_and_json_report_read_as_the_same_table():
    """The measured property: only the two top-level key names differ."""
    steps = [("2", "PASS"), ("7", "FAIL"), ("15", "SKIPPED-CONDITION")]
    a = S.table_from_audit(_audit(steps, verdict="FAIL",
                                  step_counts={"PASS": 1},
                                  command_argv=["flow_compliance_check.py",
                                                "/p", "--strict"]))
    b = S.table_from_audit(_audit(steps, overall="FAIL", counts={"PASS": 1}))
    assert a["steps"] == b["steps"]
    assert a["verdict"] == b["verdict"] == "FAIL"
    assert a["verdict_key"] == "verdict" and b["verdict_key"] == "overall"


def test_a_document_with_no_steps_list_is_unreadable_not_empty():
    """An empty table diffs as 'every step removed'. That fabricated
    catastrophe is exactly what a lenient reader would print."""
    try:
        S.table_from_audit({"verdict": "PASS"})
    except S.TableUnreadable as exc:
        assert "no `steps` list" in str(exc)
    else:                                                   # pragma: no cover
        raise AssertionError("a document with no steps[] must be UNREADABLE")


def test_a_refusal_is_ranked_below_a_judgement():
    """`INSUFFICIENT_DATA` means the audit measured nothing. Ranking it as a
    done-claim (which is what `verdict` does with any unregistered
    word, correctly, for STEPS) would let a run that refuses read as an
    improvement over a run that judged. The artefact's OWN
    `verdict_refusal_reason` field is what distinguishes them."""
    t = S.table_from_audit(_audit([("2", "PASS")], verdict="INSUFFICIENT_DATA",
                                  verdict_refusal_reason="0 of 246 gates"))
    assert t["verdict_rank"] == 0


# ── 2. the direction rule is derived, not enumerated ─────────────────────────

def test_an_unregistered_word_still_gets_a_direction():
    """THE LOAD-BEARING PROPERTY, re-pointed by R-0915-85 and STRENGTHENED.

    It used to be: a word in neither EXCUSED nor NON_GREEN is a done-claim by
    subtraction, so it ranks 2. That derivation existed because the vocabulary
    could grow. It cannot now — `verdict.parse` refuses a sixth word — so an
    unregistered word is not a tier this module has to adjudicate, it is an
    artefact written by a producer that does not speak the vocabulary.

    It ranks 0, the FAIL-SAFE side, which is a STRICTER answer than the old
    rank 2: an unreadable word can make a diff look like a REGRESSION and can
    never make one look like an improvement. `PASS -> it` stays a REGRESSION;
    `FAIL -> it` is now a LATERAL rather than an IMPROVEMENT, because nothing
    about the artefact says anything got better.
    """
    word = "A-TIER-INVENTED-TOMORROW"
    assert word not in T.PRODUCER_STATUSES
    assert S.rank(word) == 0
    assert S.direction("PASS", word) == S.REGRESSION
    assert S.direction("FAIL", word) == S.LATERAL


def test_pass_to_skip_is_a_regression_not_a_lateral():
    """The SKIP laundering R-0915-85 names by name: a step that used to run and
    pass, now not run at all. EXCUSED ranks BELOW a qualified done-claim on
    purpose — ranking 'not run' above 'ran and measured little' would make
    laundering the cheapest route to a green table."""
    assert S.direction("PASS", "NOT_APPLICABLE") == S.REGRESSION
    assert S.direction("PASS", "NOT_MEASURED") == S.REGRESSION
    # R-0915-85 — the order between the two non-pass words FLIPS, and the flip
    # is the ruling working. `SKIPPED-CONDITION` (excused, rank 1) used to rank
    # BELOW `INCOMPLETE` (a done-claim by subtraction, rank 2), so a step that
    # measured NOTHING out-ranked one the input declared inapplicable. Now
    # `NOT_MEASURED` (0) ranks below `NOT_APPLICABLE` (1): "nobody measured it"
    # is worse than "the input says there is nothing here", which is the whole
    # distinction the five words were reduced to carry.
    assert S.rank("NOT_MEASURED") < S.rank("NOT_APPLICABLE")


def test_a_rename_at_the_same_rank_is_lateral():
    """R-0915-85 is deleting 23 words down to 5 AT THE PRODUCERS. The gate's job
    during that reform is to tell a rename from a judgement change."""
    # R-0915-85 landed; the words below are its five. A LATERAL is now a real
    # re-classification at the same rank rather than a spelling change, because
    # the five have one spelling each — `verdict.parse` refuses a second, which
    # is why the old `VACUOUS_PASS` / `VACUOUS-PASS` pair no longer exists to
    # test.
    assert S.direction("FAIL", "NOT_MEASURED") == S.LATERAL
    assert S.direction("NOT_MEASURED", "NOT_MEASURED") == S.UNCHANGED
    assert S.direction("NOT_APPLICABLE", "PASS_WITH_WAIVERS") == S.IMPROVEMENT


# ── comparability: the refusal that keeps 69-vs-9 off the page ───────────────

def test_a_different_scope_is_not_comparable():
    """MEASURED: both frozen snapshots' recorded audits were written by a
    STAGE-SCOPED invocation (9 steps) while a full --strict pass yields 69.
    Diffing them prints 60 REMOVED steps and reads as a catastrophe."""
    ref = S.table_from_audit(_audit([("2", "PASS")], verdict="FAIL",
                                    command_argv=["stage4_compliance.py", ".",
                                                  "--exclude-step", "39"]))
    cur = S.table_from_audit(_audit([("2", "PASS")], verdict="FAIL",
                                    command_argv=["flow_compliance_check.py",
                                                  "/p", "--strict"]))
    ok, why = S.comparability(ref, cur)
    assert ok is False and "different producer" in why
    assert S.diff_tables(ref, cur)["comparable"] is False


def test_the_same_program_at_a_different_scope_is_not_comparable_either():
    ref = S.table_from_audit(_audit([("2", "PASS")], verdict="PASS",
                                    command_argv=["flow_compliance_check.py",
                                                  "/p", "--stage-id",
                                                  "stage_analog", "--strict"]))
    cur = S.table_from_audit(_audit([("2", "PASS")], verdict="PASS",
                                    command_argv=["flow_compliance_check.py",
                                                  "/q", "--strict"]))
    ok, why = S.comparability(ref, cur)
    assert ok is False and "different scope" in why


def test_a_different_project_path_is_still_comparable():
    """The subject is held fixed by the caller; the project path is expected to
    differ (a replay works on a copy). Refusing on it would refuse everything."""
    ref = S.table_from_audit(_audit([("2", "PASS")], verdict="PASS",
                                    command_argv=["flow_compliance_check.py",
                                                  "/a/spm", "--strict"]))
    cur = S.table_from_audit(_audit([("2", "PASS")], verdict="PASS",
                                    command_argv=["flow_compliance_check.py",
                                                  "/b/spm", "--strict"]))
    assert S.comparability(ref, cur)[0] is True


def test_omitted_current_flow_and_explicit_109_are_the_same_scope():
    ref = S.table_from_audit(_audit(
        [("D09", "PASS")], verdict="PASS",
        resolved_flow_identity={
            "schema": "vibeic.resolved-flow-identity.v1",
            "status": "RESOLVED", "flow_id": "109"},
        command_argv=["flow_compliance_check.py", "/a", "--strict"]))
    cur = S.table_from_audit(_audit(
        [("D09", "PASS")], verdict="PASS",
        command_argv=["flow_compliance_check.py", "/b", "--flow", "109",
                      "--strict"]))
    assert S.comparability(ref, cur)[0] is True


def test_historical_omitted_flow_without_resolved_identity_is_not_current_109():
    """Old omitted argv meant 70; omission alone must never inherit 109 now."""
    historical = S.table_from_audit(_audit(
        [("1", "PASS")], verdict="PASS",
        resolved_flow_identity=None,
        command_argv=["flow_compliance_check.py", "/old", "--strict"]))
    current = S.table_from_audit(_audit(
        [("D09", "PASS")], verdict="PASS",
        resolved_flow_identity={
            "schema": "vibeic.resolved-flow-identity.v1",
            "status": "RESOLVED", "flow_id": "109"},
        command_argv=["flow_compliance_check.py", "/new", "--strict"]))
    ok, why = S.comparability(historical, current)
    assert ok is False
    assert "reference: omitted --flow has no authoritative" in why


def test_historical_70_and_current_109_are_not_one_runtime_scope():
    old = S.table_from_audit(_audit(
        [("1", "PASS")], verdict="PASS",
        resolved_flow_identity=None,
        command_argv=["flow_compliance_check.py", "/old", "--flow", "70",
                      "--strict"]))
    current = S.table_from_audit(_audit(
        [("D09", "PASS")], verdict="PASS",
        command_argv=["flow_compliance_check.py", "/new", "--flow", "109",
                      "--strict"]))
    ok, why = S.comparability(old, current)
    assert ok is False
    assert "different resolved flow identity" in why
    assert "reference 70" in why and "current 109" in why


def test_a_table_with_no_recorded_argv_is_refused():
    """An unknown scope is not a matching scope. `--json` reports carry no
    `command_argv`, so one used as a reference must refuse rather than be
    assumed full-scope."""
    ref = S.table_from_audit(_audit([("2", "PASS")], overall="PASS"))
    cur = S.table_from_audit(_audit([("2", "PASS")], verdict="PASS",
                                    command_argv=["flow_compliance_check.py",
                                                  "/p", "--strict"]))
    ok, why = S.comparability(ref, cur)
    assert ok is False and "no `command_argv`" in why


# ── CALIBRATION (R-0915-86 (3)): fires on a positive, silent on a negative ───

_ARGV = ["flow_compliance_check.py", "/p", "--strict"]


def _pair(ref_steps, cur_steps, ref_v="PASS_WITH_WAIVERS",
          cur_v="PASS_WITH_WAIVERS"):
    return (S.table_from_audit(_audit(ref_steps, verdict=ref_v,
                                      command_argv=_ARGV)),
            S.table_from_audit(_audit(cur_steps, verdict=cur_v,
                                      command_argv=_ARGV)))


def test_KNOWN_NEGATIVE_an_identical_table_reports_nothing():
    steps = [("2", "PASS"), ("7", "PASS"), ("15", "SKIPPED-CONDITION")]
    d = S.diff_tables(*_pair(steps, steps))
    assert d["comparable"] is True
    assert d["regressed"] is False
    assert d["changed"] == [] and d["added"] == [] and d["removed"] == []
    assert d["unchanged_step_count"] == 3


def test_KNOWN_POSITIVE_one_flipped_step_is_reported_and_named():
    ref = [("2", "PASS"), ("7", "PASS"), ("15", "SKIPPED-CONDITION")]
    cur = [("2", "PASS"), ("7", "FAIL"), ("15", "SKIPPED-CONDITION")]
    d = S.diff_tables(*_pair(ref, cur))
    assert d["regressed"] is True
    assert [e["id"] for e in d["regressions"]] == ["7"]
    assert d["regressions"][0]["reference"] == "PASS"
    assert d["regressions"][0]["current"] == "FAIL"


def test_an_improvement_is_listed_and_is_not_a_regression():
    ref = [("2", "FAIL")]
    cur = [("2", "PASS")]
    d = S.diff_tables(*_pair(ref, cur))
    assert d["regressed"] is False
    assert [e["id"] for e in d["improvements"]] == ["2"]


def test_a_step_the_reference_measured_and_this_table_does_not_is_a_regression():
    """The laundering shape seen from the other side: drop the step and the
    table gets greener. Held as a regression when the reference's word was a
    done-claim."""
    d = S.diff_tables(*_pair([("2", "PASS"), ("7", "PASS")], [("2", "PASS")]))
    assert d["regressed"] is True
    assert [e["id"] for e in d["removed"]] == ["7"]
    assert d["removed"][0]["direction"] == S.REGRESSION


def test_a_removed_step_that_was_already_non_green_is_not_a_regression():
    """Direction, not volume: losing a step that was FAILing is not the table
    getting worse, and calling it one would make the gate cry wolf on every
    flow-yaml edit that retires a red step."""
    d = S.diff_tables(*_pair([("2", "PASS"), ("7", "FAIL")], [("2", "PASS")]))
    assert d["regressed"] is False
    assert d["removed"][0]["direction"] == S.LATERAL


def test_a_new_step_that_arrives_red_is_a_regression():
    d = S.diff_tables(*_pair([("2", "PASS")], [("2", "PASS"), ("9", "FAIL")]))
    assert d["regressed"] is True
    assert [e["id"] for e in d["added"]] == ["9"]


def test_the_top_level_verdict_falling_is_a_regression_on_its_own():
    steps = [("2", "PASS")]
    d = S.diff_tables(*_pair(steps, steps, ref_v="PASS_WITH_WAIVERS",
                             cur_v="FAIL"))
    assert d["verdict"]["direction"] == S.REGRESSION
    assert d["regressed"] is True


def test_the_top_level_verdict_rising_is_not_a_regression():
    """A landing that makes the IC better must not be blocked by the gate that
    watches it. The caller flags the reference as stale instead."""
    steps = [("2", "PASS")]
    d = S.diff_tables(*_pair(steps, steps, ref_v="FAIL", cur_v="PASS"))
    assert d["verdict"]["direction"] == S.IMPROVEMENT
    assert d["regressed"] is False


# ── R-0915-88: the RUN SHAPE axis ───────────────────────────────────────────
#
# THE ESCAPE THIS CLOSES, MEASURED 2026-09-16 BY USING THE GATE. The flow is
# program-first + AI-BACKUP: several steps complete only when an AGENT answers a
# hand-off. A published cell produced by an agent-driven lane run and a table
# produced by a program-only landing gate therefore disagree on those steps at
# EVERY tree — measured at six, spanning a ten-landing range and current main,
# with the tree never moving either verdict. Diffing the two printed "the IC
# regressed" about a landing that had done nothing, in a report a human read.
#
# The discriminator is DERIVED, never a per-step exception list: the run's own
# `gate_execution_ledger` records each gate's `exit_code`, and the AWAITING code
# is `flow_compliance_check`'s own constant for "pass two is somebody else's
# move". A tier invented tomorrow inherits this for free.

def test_the_awaiting_code_is_the_flows_own():
    """RETURNED VALUE against the defining module, not a literal `4` re-typed
    here. A second copy of a constant is the drift this module exists to
    delete, and it would drift silently: the wrong number simply finds no rows
    and every run reads as agent-driven."""
    fcc = importlib.import_module("flow_compliance_check")
    assert S.awaiting_exit_code() == fcc._AWAITING_EXIT_CODE


def test_run_shape_names_the_gates_whose_second_pass_nobody_answered():
    shape = S.run_shape(_audit([("2", "PASS")],
                               ledger=[_awaiting_row("a_track"),
                                       {"gate": "other", "exit_code": 0}]))
    assert shape["unanswered_second_pass"] == ["a_track"]
    assert shape["agent_answered_every_handoff"] is False
    assert shape["source"] == "gate_execution_ledger"


def test_a_run_with_every_handoff_answered_has_an_empty_set_not_None():
    """Empty and unknown are different states, and the difference decides
    whether a diff may proceed."""
    shape = S.run_shape(_audit([("2", "PASS")],
                               ledger=[{"gate": "other", "exit_code": 0}]))
    assert shape["unanswered_second_pass"] == []
    assert shape["agent_answered_every_handoff"] is True


def test_an_ABSENT_ledger_is_NOT_RECORDED_never_an_empty_set():
    """The fail-safe direction. Reading an absent ledger as "nothing was left
    unanswered" would make every artefact with no ledger look agent-driven —
    which is the one reading that lets a cross-shape diff through."""
    shape = S.run_shape({"steps": []})
    assert shape["unanswered_second_pass"] is None
    assert shape["source"] == "NOT_RECORDED"


def test_KNOWN_POSITIVE_two_runs_that_disagree_on_a_handoff_are_NOT_COMPARABLE():
    """THE MEASURED ESCAPE. Same steps, same producer, same flags — and the two
    runs are still not the same experiment."""
    agent_driven = S.table_from_audit(_audit([("2", "PASS")], verdict="PASS",
                                             command_argv=_ARGV))
    program_only = S.table_from_audit(
        _audit([("2", "INCOMPLETE")], ledger=[_awaiting_row("an_expert_track")],
               verdict="FAIL", command_argv=_ARGV))
    ok, why = S.comparability(agent_driven, program_only)
    assert ok is False
    assert "different RUN SHAPE" in why
    assert "an_expert_track" in why, "the refusal must NAME the hand-off"
    d = S.diff_tables(agent_driven, program_only)
    assert d["comparable"] is False


def test_KNOWN_NEGATIVE_two_runs_of_the_same_shape_still_diff_normally():
    """The guard must not refuse everything: two program-only runs with the SAME
    unanswered hand-off are the same experiment, and a real regression between
    them must still be reported."""
    led = [_awaiting_row("an_expert_track")]
    ref = S.table_from_audit(_audit([("2", "PASS")], ledger=led, verdict="PASS",
                                    command_argv=_ARGV))
    cur = S.table_from_audit(_audit([("2", "FAIL")], ledger=led, verdict="FAIL",
                                    command_argv=_ARGV))
    ok, why = S.comparability(ref, cur)
    assert ok is True and "same run shape" in why
    assert [e["id"] for e in S.diff_tables(ref, cur)["regressions"]] == ["2"]


def test_a_table_with_no_ledger_is_refused_against_one_that_has_it():
    """Same fail-safe rule as an unrecorded `command_argv`: an unknown shape is
    not a matching shape."""
    known = S.table_from_audit(_audit([("2", "PASS")], verdict="PASS",
                                      command_argv=_ARGV))
    unknown = S.table_from_audit({"steps": [{"id": "2", "status": "PASS"}],
                                  "verdict": "PASS", "command_argv": _ARGV})
    ok, why = S.comparability(unknown, known)
    assert ok is False and "no gate execution ledger" in why


def test_the_run_shape_is_rendered_so_a_reader_cannot_miss_it():
    """A refusal a human reads must carry its own evidence; the rendered table
    says which kind of run produced it, in both states."""
    program_only = S.table_from_audit(
        _audit([("2", "PASS")], ledger=[_awaiting_row("an_expert_track")],
               verdict="FAIL", command_argv=_ARGV))
    assert "PROGRAM-ONLY" in S.render(program_only)
    assert "an_expert_track" in S.render(program_only)
    agent_driven = S.table_from_audit(_audit([("2", "PASS")], verdict="PASS",
                                             command_argv=_ARGV))
    assert "no unanswered hand-off" in S.render(agent_driven)

# ── the chip-AGNOSTIC declaration these three files make, ENFORCED ──────────
#
# `source_chip_agnostic_check` READS a `CHIP_AGNOSTIC:` declaration and
# DISCLOSES it — its own docstring says so in as many words: "It does NOT
# enforce it: the program's own test is the lane that can refuse, and
# duplicating the refusal here would be two lanes with one rule between them."
# All three files of this change declare `strict-logic`, so this is that lane.
# It covers all three together because they land as one change and the middle
# one is the module the other two import.

_THIS_CHANGE = ("_step_verdict_table.py", "real_ic_gate.py", "audit_replay.py")


def _module_logic(path):
    """The file with its MODULE docstring stripped and nothing else — the exact
    scope `strict-logic` names. Every nested docstring and comment STAYS, which
    is where a literal would really hide."""
    import ast
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    body = tree.body[1:] if (tree.body and isinstance(tree.body[0], ast.Expr)
                             and isinstance(tree.body[0].value, ast.Constant)
                             and isinstance(tree.body[0].value.value, str)
                             ) else tree.body
    return "\n".join(ast.get_source_segment(text, n) or "" for n in body)


def test_all_three_files_DECLARE_strict_logic_inside_the_binding_window():
    """RETURNED VALUE, not a grep. `declared_strictness` is None for a
    declaration below the 4000-byte window — a rule no reader meets — so a
    declaration that drifted down the docstring during an edit fails here
    rather than going quietly unenforced."""
    import pathlib
    chk = importlib.import_module("source_chip_agnostic_check")
    progs = pathlib.Path(__file__).resolve().parents[1]
    for name in _THIS_CHANGE:
        text = (progs / name).read_text(encoding="utf-8")
        assert chk.declared_strictness(text) == "strict-logic", (
            "%s must declare CHIP_AGNOSTIC: strict-logic inside the binding "
            "window (site: %r)" % (name, chk.declared_strictness_site(text)))


def test_no_chip_vendor_or_SKU_token_appears_in_the_LOGIC_of_any_of_them():
    """The refusal itself, using the GATE'S OWN token table rather than a list
    re-typed here: a hand-written copy of "the forbidden names" is stale the
    day the gate learns a new one."""
    import pathlib
    chk = importlib.import_module("source_chip_agnostic_check")
    progs = pathlib.Path(__file__).resolve().parents[1]
    # The gate's own tokens (the NDA table), PLUS the names this change was
    # measured on and the OPEN PDKs. The open PDK names are not NDA-forbidden
    # anywhere in the repo and are perfectly legal in a docstring — but a gate
    # whose subject is "whatever --ic and --pdk name at the call site" may not
    # carry one in its logic, so the three files of this change hold themselves
    # to that. MEASURED: without this extension a planted
    # `SPM_DEFAULT_PDK = "gf180mcuD"` survived the test (falsref mutant M8 was
    # INERT), because `SPM_` is not a word boundary and the PDK name is not in
    # the NDA table. The mutant was right and the test's scope was too narrow.
    token_re = chk._build_token_re(
        ["spm", "subservient", "sha256_run16_pass2",
         "gf180mcud", "sky130a", "ihp-sg13g2", "nangate45", "asap7"])
    for name in _THIS_CHANGE:
        logic = _module_logic(progs / name)
        hits = sorted(set(m.group(1).lower() for m in token_re.finditer(logic)))
        assert not hits, (
            "%s declares strict-logic and its LOGIC names %s — the subject must "
            "come from the call site, never from a literal" % (name, hits))


def test_the_guard_above_can_actually_see_a_planted_literal():
    """CALIBRATION of the guard itself (R-0915-86 (3)): an instrument that
    cannot fire proves nothing about the files it passed. A literal planted in
    a LOGIC position must be found, and the same literal in the module
    docstring must NOT be — that difference IS `strict-logic`."""
    chk = importlib.import_module("source_chip_agnostic_check")
    token_re = chk._build_token_re(["spm"])
    import tempfile, pathlib
    d = pathlib.Path(tempfile.mkdtemp(prefix="agn_"))
    planted = d / "m.py"
    planted.write_text('"""doc mentioning spm."""\nX = "spm"\n', encoding="utf-8")
    assert token_re.search(_module_logic(planted)), \
        "the guard cannot see a literal in the logic — it proves nothing"
    docstring_only = d / "n.py"
    docstring_only.write_text('"""doc mentioning spm."""\nX = 1\n',
                              encoding="utf-8")
    assert not token_re.search(_module_logic(docstring_only)), \
        "strict-logic must permit the docstring to name what it measured on"
