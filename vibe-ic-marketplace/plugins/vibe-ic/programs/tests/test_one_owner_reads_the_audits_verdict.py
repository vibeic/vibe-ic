"""test_one_owner_reads_the_audits_verdict.py

ONE PRODUCER, THREE READERS, AND THEY DISAGREED.

`flow_compliance_check` answers on two channels: one `Overall: <word>` line and an exit
code. Three programs read that answer and each read it its own way:

    design_one_shot_runner.step_final_audit          the phase-2/3 step table
    phase23_completion_self_audit_check              by its own docstring, "the ONLY signal
                                                     that authorises a 'Phase 2+3 complete'
                                                     claim"
    final_report_generate._run_audit                 the `final_summary.md` headline

MEASURED on main fd9e3342f, driving each real reader with the audit's reconciliation-canary
stdout and rc 1 — a state the audit is DESIGNED to reach (vibe-ic#2092: print the run word,
print "do not quote its counts", say the status is unchanged, `return 1`):

    step_final_audit                    NOT_MEASURED   (fixed in #2572)
    phase23_completion_self_audit_check exit 0, "Overall: PASS — every canonical step
                                        executed and verified."
    final_report_generate               headline PASS

So after #2572 the orchestrator said "could not certify" while the acceptance gate still
authorised completion. Two readers were left with the defect the third had fixed, which is
what a private copy of a shared question buys.

THE RULE, with no tool or step name in it:

    A producer has as many channels as it chooses to use, and one question has one owner.
    A consumer that reads a word while ignoring the exit code has not read the producer;
    three consumers that each read it their own way will eventually publish opposite
    verdicts about one run.

Fixtures quote the producer's OWN prints and the vocabulary's OWN words.
"""
from __future__ import annotations

import io
import contextlib
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import verdict as _V                                   # noqa: E402
import _audit_verdict as A                             # noqa: E402
import _watchdog as _wd                                # noqa: E402
import design_one_shot_runner as D                     # noqa: E402
import phase23_completion_self_audit_check as GATE     # noqa: E402
import final_report_generate as F                      # noqa: E402

HEADER = "Steps: 34 total (34/34 executed PASS, 0 DEFERRED via waiver)\n"


def canary(word: str = "PASS") -> str:
    """The audit's stdout when its own report does not reconcile — its own prints."""
    return (
        "=== Vibe-IC phase1_phase2_phase3 compliance ===\n" + HEADER +
        f"\nOverall: {word}  (strict=True)\n"
        "\nflow_compliance_check: THIS REPORT DOES NOT RECONCILE — 1 of 7 equation(s) over "
        "its own numbers are false. The report was still written, with `reconciled: false`; "
        "do not quote its counts.\n"
        "  ✗ [tally_sums] executed == PASS+FAIL+… — 34 != 33\n"
        f"  (the run's own status is unchanged and still {word}.)\n")


def clean(word: str = "PASS") -> str:
    return canary(word).split("\nflow_compliance_check: THIS REPORT")[0] + "\n"


# ═══ the owner ════════════════════════════════════════════════════════════

def test_the_owner_reads_both_channels():
    assert A.read(clean("PASS"), 0).is_green is True
    assert A.read(canary("PASS"), 1).is_green is False
    assert A.read(canary("PASS"), 1).certified is False
    assert A.read(canary("PASS_WITH_WAIVERS"), 1).is_green is False
    # a word the audit DOES stand behind, however unwelcome
    for w in (_V.Verdict.FAIL.value, _V.Verdict.NOT_MEASURED.value):
        v = A.read(f"\nOverall: {w}  (strict=True)\n", 1)
        assert v.certified is True and v.is_green is False, w
        assert v.word == w


def test_the_owner_returns_the_word_not_a_boolean():
    """A boolean cannot tell "found a defect" from "could not measure" — the distinction
    R-0915-159 exists to keep, and the reason the acceptance gate needed the vocabulary."""
    for w in [v.value for v in _V.RUN_PRECEDENCE]:
        assert A.read(f"\nOverall: {w}  (strict=True)\n", 0).word == w


def test_the_owner_anchors_and_takes_the_last_verdict_line():
    """The audit prints its blocker list AFTER the verdict, and those rows quote gate
    output; an unanchored or first-match rule reads the quotation."""
    out = ("\nOverall: FAIL  (strict=True)\n"
           "\nBlocker list (classified) — 1 non-PASS step(s).\n"
           "       observed : program failed | output: Overall: PASS  (strict=True)\n")
    assert out.rindex("Overall: PASS") > out.rindex("Overall: FAIL")
    assert A.verdict_word(out) == "FAIL"
    # and when there really are two verdict LINES, the later one is the run's
    assert A.verdict_word("Overall: PASS  (x)\nOverall: FAIL  (x)\n") == "FAIL"


def test_the_owner_keeps_issue_483s_token_rule():
    """#483: the token is everything up to the trailing annotation, never the first
    whitespace chunk. The three readers' rules differed; the owner carries the careful one."""
    assert A.verdict_word("Overall: PASS_WITH_OPEN_SOURCE_CONSTRAINTS  (strict=True)\n") == (
        "PASS_WITH_OPEN_SOURCE_CONSTRAINTS")
    assert A.verdict_word("Overall: FA IL\n") == "FA IL"
    assert F._extract_overall_token("Overall: FA IL") == "FA IL"


def test_the_owner_names_the_two_non_verdicts():
    """A timeout and a missing verdict line are not judgements about the design, and a
    green word with NO exit code is not a certificate either."""
    assert A.read("\nOverall: AUDIT_TIMEOUT\n", 124).certified is False
    assert A.read("nothing here\n", 0).word is None
    assert A.read("nothing here\n", 0).certified is False
    assert A.read(clean("PASS"), None).certified is False, (
        "a word read without the audit's exit code was treated as certified")


# ═══ reader 1 — the step table ════════════════════════════════════════════







def test_reader_one_no_longer_owns_the_rule():
    """The helper #2572 put here MOVED; it was not copied. A second name for one rule is
    the defect this branch closes."""
    assert not hasattr(D, "_final_audit_verdict_word"), (
        "`design_one_shot_runner` still exposes its own verdict-word helper, so the rule "
        "exists in two places again")
    assert not hasattr(D, "_FINAL_VERDICT_RE")


# ═══ reader 2 — the sole acceptance gate ══════════════════════════════════

def _gate(monkeypatch, tmp_path, rc, out):
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(GATE, "_run_compliance", lambda p, strict=True: (rc, out))
    monkeypatch.setattr(sys, "argv", ["gate", str(tmp_path)])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = GATE.main()
    return code, buf.getvalue()


def test_the_acceptance_gate_does_not_authorise_an_uncertified_run(monkeypatch, tmp_path):
    """THE REPRODUCTION. On main this exits 0 and prints "every canonical step executed and
    verified" — the one verdict in the tree that authorises a completion claim."""
    code, out = _gate(monkeypatch, tmp_path, 1, canary("PASS"))
    assert code == 1, (
        f"the SOLE ACCEPTANCE GATE authorised completion for a run whose audit exited 1 "
        f"while refusing to vouch for its counts (exit {code})")
    assert "every canonical step executed and verified" not in out, out
    assert "AUDIT_DID_NOT_CERTIFY" in out, out
    assert "did not certify" in out, out


def test_the_acceptance_gate_says_the_same_thing_it_exits(monkeypatch, tmp_path):
    """The printed word and the exit code are ONE decision. These branches keyed on the
    word while the exit keyed on completeness, so reading the rc made them disagree — the
    gate printed `[PASS]` and exited 1 at the first cut of this change."""
    for rc, out_text, want_zero in ((0, clean("PASS"), True),
                                    (0, clean("PASS_WITH_WAIVERS"), True),
                                    (1, canary("PASS"), False),
                                    (1, clean("FAIL"), False),
                                    (1, clean("NOT_MEASURED"), False)):
        code, text = _gate(monkeypatch, tmp_path, rc, out_text)
        head = text.strip().splitlines()[0]
        assert (code == 0) is want_zero, (out_text, code, head)
        says_pass = head.startswith("[PASS]") or head.startswith("[PASS_WITH_WAIVERS]")
        assert says_pass is want_zero, (
            f"the gate printed {head!r} and exited {code}: the human and the script get "
            f"opposite answers")


def test_the_acceptance_gate_knows_the_word_2572_made_reachable(monkeypatch, tmp_path):
    """NOT_MEASURED had no alternative in the old regex: it read as UNKNOWN and printed
    `[FAIL]` — an absence labelled a defect found. It fails closed either way, so this is
    about the LABEL, which is what R-0915-159 is about."""
    code, out = _gate(monkeypatch, tmp_path, 1, clean("NOT_MEASURED"))
    assert code == 1
    assert out.strip().splitlines()[0].startswith("[NOT_MEASURED]"), out
    assert "NOT a FAIL" in out, out


def test_the_acceptance_gate_keeps_the_timeouts_own_name(monkeypatch, tmp_path):
    """#525 NAMED THE TIMEOUT ON PURPOSE, and my first cut of this change lost that name.

    `_audit_verdict` reports a timeout as uncertified — true, but not specific — so folding it
    into the generic did-not-certify branch relabelled it `[AUDIT_DID_NOT_CERTIFY]` and threw
    away #525's distinction (stopped before finishing, versus never audited; neither a verdict
    about the design). The exit code was right either way, which is exactly why only an arm
    about the LABEL catches it. Same shape as `test_the_timeout_tier_is_untouched` in #2572.
    """
    timeout_out = ("Overall: AUDIT_TIMEOUT\nAUDIT TIMEOUT after 900s — the compliance audit "
                   "did not run to completion; this is NOT a verdict on the project "
                   "(INCONCLUSIVE, #525).\n")
    code, out = _gate(monkeypatch, tmp_path, 124, timeout_out)
    assert code == 1, out
    head = out.strip().splitlines()[0]
    assert head.startswith("[AUDIT_TIMEOUT]"), (
        f"the timeout lost its own name and was reported as a generic refusal: {head!r}")
    assert "NOT a verdict on the project" in out, out


def test_the_acceptance_gate_still_passes_a_clean_run(monkeypatch, tmp_path):
    """NEGATIVE CONTROL, and the one that matters most: the gate must still authorise a run
    the audit certified."""
    code, out = _gate(monkeypatch, tmp_path, 0, clean("PASS"))
    assert code == 0, out
    assert "every canonical step executed and verified" in out, out


# ═══ reader 3 — the final_summary.md headline ═════════════════════════════

def _supervised(rc, out):
    return _wd.SupervisedResult(rc=rc, out=out, err="", outcome="completed",
                                elapsed_s=1.0, abort_reason=None, scope=None,
                                supervision=None)


def _run_audit(monkeypatch, tmp_path, rc, out):
    monkeypatch.setattr(F._wd, "run_host_supervised", lambda cmd, **kw: _supervised(rc, out))
    return F._run_audit(tmp_path)


def test_the_headline_does_not_read_pass_for_an_uncertified_audit(monkeypatch, tmp_path):
    """THE REPRODUCTION for reader 3: on main the `final_summary.md` headline reads
    `Overall: PASS` for a run whose audit refused to vouch for its counts."""
    text, overall = _run_audit(monkeypatch, tmp_path, 1, canary("PASS"))
    assert overall == F.AUDIT_DID_NOT_CERTIFY_VERDICT, overall
    assert overall != "PASS"
    assert "AUDIT DID NOT CERTIFY" in text, text[-300:]


def test_the_headline_withholds_counts_but_loads_the_snapshot():
    """THE DECISION, pinned: load the snapshot, withhold the COUNTS.

    MY FIRST CUT OF THIS ARM ASSERTED THE OPPOSITE SHAPE, and it was right about the goal and
    wrong about the means: it required the did-not-certify word to join the set that SKIPS
    `_load_fresh_audit_snapshot`. Skipping the load also hides the "⛔ The audit does not
    reconcile" banner and the "Reported, NOT gating" block, because both render only
    `if isinstance(audit_snapshot, dict)` — so the headline refused and never said why, while
    vibe-ic#2092 requires that banner to be the FIRST thing under Verdict. The snapshot is
    loaded for the DISCLOSURES and the counts are suppressed separately.

    The behaviour is graded in `test_issue2092_the_summary_carries_the_disclosure`, which owns
    the render harness; this pins the structure so the two halves cannot be collapsed again.
    """
    src = (PROGRAMS / "final_report_generate.py").read_text()
    idx = src.index("AUDIT_TIMEOUT_VERDICT, AUDIT_NOT_RUN_VERDICT")
    window = src[idx:idx + 200]
    assert "AUDIT_DID_NOT_CERTIFY_VERDICT" not in window, (
        "the did-not-certify word skips the snapshot load again, which hides the "
        "reconciliation banner that explains the refusal")
    assert "counts_withheld" in src, (
        "nothing suppresses the per-step counts for the did-not-certify state, so the "
        "withdrawn numbers are rendered")
    i_flag = src.index("counts_withheld")
    i_counts = src.index("rollup, count_problems = _audit_step_counts(")
    assert i_flag < i_counts, "the suppression is set after the counts are derived"


def test_the_headline_is_unchanged_for_a_certified_audit(monkeypatch, tmp_path):
    """NEGATIVE CONTROL, all four words the audit stands behind."""
    for w in ("PASS", "PASS_WITH_WAIVERS", "FAIL", "NOT_MEASURED"):
        rc = 0 if w in ("PASS", "PASS_WITH_WAIVERS") else 1
        _t, overall = _run_audit(monkeypatch, tmp_path, rc, clean(w))
        assert overall == w, (w, overall)


# ═══ one owner, and no fourth copy ════════════════════════════════════════

def test_no_program_parses_the_verdict_line_outside_the_owner():
    """THE ARM THAT STOPS THE FOURTH COPY, and it is the reason this branch exists at all:
    three private copies of one question is how two readers kept a defect the third had
    fixed. A new reader must ASK, and this fails the moment one spells the rule itself."""
    import re as _re
    offenders = []
    pat = _re.compile(r'startswith\(\s*["\']Overall:|'
                      r're\.(?:compile|search|match|findall|finditer)\([^)]*Overall:')
    for py in sorted(PROGRAMS.glob("*.py")):
        if py.name == "_audit_verdict.py":
            continue                       # the owner, and its own commentary
        for lineno, line in enumerate(py.read_text(errors="replace").splitlines(), 1):
            if pat.search(line):
                offenders.append(f"{py.name}:{lineno}: {line.strip()[:100]}")
    assert not offenders, (
        "the audit's verdict line is parsed outside `_audit_verdict` again — ask "
        "`_audit_verdict.read(out, rc)` (or `is_verdict_line` for the LINE question) "
        "instead of spelling the rule:\n  " + "\n  ".join(offenders))


def test_all_three_readers_ask_the_owner():
    """The positive half: a sweep that finds no parser is also satisfied by a reader that
    stopped reading the verdict at all."""
    for name in ("design_one_shot_runner", "phase23_completion_self_audit_check",
                 "final_report_generate"):
        src = (PROGRAMS / f"{name}.py").read_text(errors="replace")
        assert "_audit_verdict" in src, f"{name} does not ask the owner"


# ═══ round 2 (review w1a9etzxn) ════════════════════════════════════════════

def test_a_budget_kill_is_the_timeout_whatever_lines_it_carries():
    """MEDIUM 1. The caller that times the audit out PREPENDS its own
    `Overall: AUDIT_TIMEOUT` line and APPENDS the audit's partial stdout, and that partial can
    carry a real verdict line: `flow_compliance_check` prints its `Overall:` and then keeps
    working (blocker list, a second full design-input rescan, the publish), so a kill in that
    tail leaves the verdict line already through the pipe.

    So the LAST-line rule read `Overall: PASS_WITH_WAIVERS` with rc 124 and reported "did not
    certify", naming the #2092 reconciliation canary for what was a TIMEOUT — and a consumer
    keying on `overall == "AUDIT_TIMEOUT"` saw the green word and called the run MEASURED. No
    line ordering fixes this; the rc decides it.
    """
    partial = ("=== Vibe-IC phase1_phase2_phase3 compliance ===\n"
               "  PASS=33 PASS_WITH_WAIVERS=1 FAIL=0\n"
               "\nOverall: PASS_WITH_WAIVERS  (strict=True)\n"
               "Blocker list (classified) — 0 non-PASS step(s).\n")
    out = ("Overall: AUDIT_TIMEOUT\nAUDIT TIMEOUT after 900s — … (INCONCLUSIVE, #525).\n"
           + partial)
    v = A.read(out, A.TIMEOUT_RC)
    assert v.word == A.TIMEOUT_WORD, (
        f"a budget kill was reported as {v.word!r} — the partial output's own verdict line "
        f"outranked the exit code")
    assert v.certified is False
    assert "unknown fraction" in v.why
    # and the misleading word is NAMED rather than silently dropped
    assert "PASS_WITH_WAIVERS" in v.why, v.why
    # the same holds with no partial at all, and for a green word with no timeout line
    assert A.read("Overall: AUDIT_TIMEOUT\n", A.TIMEOUT_RC).word == A.TIMEOUT_WORD
    assert A.read("\nOverall: PASS  (strict=True)\n", A.TIMEOUT_RC).word == A.TIMEOUT_WORD


def test_the_gate_names_the_timeout_even_with_a_verdict_in_the_partial(monkeypatch, tmp_path):
    """The same case through the acceptance gate, which is where it was measured: the label
    must say AUDIT_TIMEOUT, not blame the canary."""
    partial = HEADER + "\nOverall: PASS_WITH_WAIVERS  (strict=True)\n"
    code, out = _gate(monkeypatch, tmp_path, A.TIMEOUT_RC,
                      "Overall: AUDIT_TIMEOUT\nNOT a verdict\n" + partial)
    assert code == 1, out
    assert out.strip().splitlines()[0].startswith("[AUDIT_TIMEOUT]"), out


def test_the_owner_loads_by_path_for_a_caller_outside_programs():
    """MEDIUM 1's sibling, found while wiring the FPGA guard. The pre-burn guard lives in
    `mcp-eda` and loads this module BY PATH through the same resolver it uses to find
    `flow_compliance_check.py`, so that a hardware action and the orchestrator apply ONE rule.

    A module that combines `@dataclass` with `from __future__ import annotations` cannot be
    loaded that way unless the importer registers it in `sys.modules` first — the dataclass
    machinery resolves `sys.modules[cls.__module__].__dict__` and raises AttributeError. This
    arm loads it the way an outside caller does, with no help.
    """
    import importlib.util as ilu
    spec = ilu.spec_from_file_location("byp_audit_verdict",
                                       PROGRAMS / "_audit_verdict.py")
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)            # deliberately NOT registered first
    assert mod.read("\nOverall: PASS  (x)\n", 1).certified is False
    assert mod.read("\nOverall: PASS  (x)\n", 0).certified is True


def test_the_json_summary_carries_both_channels(monkeypatch, tmp_path):
    """MEDIUM 4. `production_tapeout_ready` keyed on the bare word, so an uncertified green
    run published `true` beside `exit 1` — the JSON contradicting the exit status of the
    program that wrote it. This is what the MCP tool and every scripted consumer reads."""
    import json as _json
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(GATE, "_run_compliance",
                        lambda p, strict=True: (1, canary("PASS")))
    monkeypatch.setattr(sys, "argv", ["gate", str(tmp_path), "--json", "-"])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = GATE.main()
    doc = _json.loads(buf.getvalue())
    summary = doc.get("summary", doc)
    assert code == 1
    assert summary["certified"] is False, summary
    assert summary["production_tapeout_ready"] is False, (
        "an uncertified run published production_tapeout_ready=true beside exit 1")
    assert summary["certification_note"], summary
    # the clean control still publishes both as true
    monkeypatch.setattr(GATE, "_run_compliance", lambda p, strict=True: (0, clean("PASS")))
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        code2 = GATE.main()
    s2 = _json.loads(buf2.getvalue()).get("summary", {})
    assert code2 == 0 and s2["certified"] is True and s2["production_tapeout_ready"] is True


def _driver():
    """The FPGA pre-burn guard, loaded the way its own tree loads it."""
    import importlib.util as ilu
    path = (PROGRAMS.parent / "mcp-eda" / "src" / "devices" / "fpga" /
            "terasic-de10lite" / "driver.py")
    spec = ilu.spec_from_file_location("de10lite_driver_under_test", path)
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_fpga_guard_can_reach_the_owner():
    """MEDIUM 3, first half: the rule is LOADED, not mirrored. If this cannot reach the owner
    the guard falls back to rc-only blocking, which is still fail-closed but is not one rule."""
    drv = _driver()
    own = drv._audit_verdict_owner()
    assert own is not None, (
        "the pre-burn guard cannot reach `_audit_verdict`, so a hardware action and the "
        "orchestrator would be applying two different rules")
    assert own.read("\nOverall: PASS  (x)\n", 1).certified is False


def test_the_fpga_guard_no_longer_ranks_pass_above_fail_in_a_substring():
    """MEDIUM 3, second half. The no-JSON fallback searched the whole stream unanchored and
    tested PASS BEFORE FAIL, so a quoted `Overall: PASS` — the audit prints its blocker list
    after the verdict, and those rows quote gate output — outranked the run's real FAIL on the
    path that decides whether to drive a device."""
    drv = _driver()
    own = drv._audit_verdict_owner()
    stream = ("\nOverall: FAIL  (strict=True)\n"
              "       observed : | output: Overall: PASS  (strict=True)\n")
    assert "Overall: PASS" in stream
    assert own.verdict_word(stream) == "FAIL", (
        "the guard's verdict source still prefers a quoted PASS to the run's FAIL")
    src = (PROGRAMS.parent / "mcp-eda" / "src" / "devices" / "fpga" /
           "terasic-de10lite" / "driver.py").read_text(errors="replace")
    assert 'if "Overall: PASS_WITH_WAIVERS" in out_text:' not in src, (
        "the unanchored PASS-before-FAIL ladder is back in the pre-burn guard")


def test_the_fpga_guards_rule_is_driven_not_grepped():
    """MEDIUM 3, the burn itself, and the rule DRIVEN.

    The docstring has always said ">0 = FAIL → reject burn"; only `fc_rc < 0` was ever checked,
    so the canary's rc 1 reached the `verdict in ("PASS","PASS_WITH_WAIVERS")` arm and THE BURN
    PROCEEDED — a hardware action on an audit that withdrew its own certification, against the
    function's own contract.

    MY FIRST ARM FOR THIS ASSERTED A STRING IN THE SOURCE, and a mutation proved it worthless:
    disabling the guard with `if False and …` left the string in place and the arm green. That
    is the `info exists` shape — presence is not reachability. The rule is now a predicate that
    can be CALLED, and it is called here over the whole truth table.
    """
    drv = _driver()
    # the canary: a green word with a positive rc is not certified, so the burn is refused
    assert drv.pre_burn_audit_certified(1, "\nOverall: PASS  (strict=True)\n") is False
    assert drv.pre_burn_audit_certified(
        1, "\nOverall: PASS_WITH_WAIVERS  (strict=True)\n") is False
    # a budget kill is not certified either, whatever the partial output says
    assert drv.pre_burn_audit_certified(
        124, "Overall: AUDIT_TIMEOUT\n\nOverall: PASS  (strict=True)\n") is False
    # NEGATIVE CONTROLS: a clean audit still burns, and a real FAIL is not this rule's business
    # — it is blocked by the pre-existing `verdict not in (PASS, PASS_WITH_WAIVERS)` arm, and
    # this predicate must not pretend to be the only guard.
    assert drv.pre_burn_audit_certified(0, "\nOverall: PASS  (strict=True)\n") is True
    assert drv.pre_burn_audit_certified(1, "\nOverall: FAIL  (strict=True)\n") is True
    # and rc < 0 keeps its own branch: the gate could not run, which is a different refusal
    assert drv.pre_burn_audit_certified(-1, "") is True


def test_the_fpga_guards_rule_actually_gates_the_burn():
    """The other half, and the one the mutation demanded: the predicate must GATE the block.

    An `if` whose test is `False and …` satisfies every source-presence arm, so the call site is
    pinned by AST: the branch that returns the did-not-certify refusal must be guarded by a call
    to `pre_burn_audit_certified`, and its test must contain no falsy constant.
    """
    import ast as _ast
    path = (PROGRAMS.parent / "mcp-eda" / "src" / "devices" / "fpga" /
            "terasic-de10lite" / "driver.py")
    tree = _ast.parse(path.read_text(errors="replace"))
    guarded = []
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.If):
            continue
        body_src = _ast.unparse(_ast.Module(body=node.body, type_ignores=[]))
        if "burn_blocked_pre_burn_audit_did_not_certify" not in body_src:
            continue
        test_src = _ast.unparse(node.test)
        guarded.append(test_src)
        # THE GUARD MUST BE THE DECISION, and the decision is now a VALUE the decider
        # published (`audit_certified`), with the word-and-rc rule as the fallback when a
        # caller built the report itself. My first cut of this arm demanded the predicate be
        # CALLED in the test expression, and I briefly added a call there to satisfy it --
        # writing code to please a test. That call re-broke the genuine-FAIL case, because with
        # no text the owner sees no verdict line and answers "uncertified". The arm asks for the
        # decision instead.
        assert ("_certified" in test_src
                or "audit_certified" in test_src
                or "pre_burn_audit_certified" in test_src), (
            f"the did-not-certify refusal is not guarded by the audit's decision: if {test_src}")
        for sub in _ast.walk(node.test):
            assert not (isinstance(sub, _ast.Constant) and sub.value is False), (
                f"the guard is disabled by a constant: if {test_src}")
    assert len(guarded) == 1, (
        f"expected exactly one did-not-certify refusal branch, found {len(guarded)}")
    # and the value it is guarded by must come from the RULE, not from thin air
    src = path.read_text(errors="replace")
    assert "_certified_from_word_and_rc(verdict, fc_rc)" in src, (
        "the fallback decision is not derived from the shared word-and-rc rule")


def test_a_genuine_fail_keeps_its_own_error_code():
    """THE ORDERING THIS GUARD MUST NOT BREAK, and it broke it once.

    A structural FAIL at rc 1 is blocked by the arm that exists for it, under its own code. My
    first fallback was `fc_rc <= 0`, which called every positive rc uncertified and so stole
    that arm's name — four of `test_device_program_rtl_repair_guard.py`'s own tests went red
    saying so. The rule is over the WORD and the rc together.
    """
    drv = _driver()
    assert drv._certified_from_word_and_rc("FAIL", 1) is True
    assert drv._certified_from_word_and_rc("UNKNOWN", 1) is True
    assert drv._certified_from_word_and_rc("PASS", 1) is False
    assert drv._certified_from_word_and_rc("PASS_WITH_WAIVERS", 1) is False
    assert drv._certified_from_word_and_rc("PASS", 0) is True


def test_the_fpga_guard_blocks_before_it_allows():
    """Order matters on this path: the refusal must precede the arm that lets the burn run."""
    src = (PROGRAMS.parent / "mcp-eda" / "src" / "devices" / "fpga" /
           "terasic-de10lite" / "driver.py").read_text(errors="replace")
    i_block = src.index("burn_blocked_pre_burn_audit_did_not_certify")
    i_allow = src.index('if verdict in ("PASS", "PASS_WITH_WAIVERS"):')
    assert i_block < i_allow, (
        "the did-not-certify block comes AFTER the allow arm, so the burn is permitted first")


def test_the_mcp_tool_reads_the_published_certified_field():
    """MEDIUM 3, the JS side. The decision I took: no mirrored rule and no shared vector file
    — the gate publishes `certified` (decided by the Python owner from the word AND the rc)
    and the tool reads that FIELD, so there is nothing to keep in step across languages."""
    js = (PROGRAMS.parent / "mcp-eda" / "src" / "index.js").read_text(errors="replace")
    # A SOURCE PIN, AND PRECISE ABOUT IT. There is no JS harness in this tree that can drive
    # that handler, so this is a shape check rather than a behavioural one — which means it
    # must be tight enough that disabling the guard fails it. A bare "the string is present"
    # arm did NOT: `if (false && …)` kept every substring. The whole condition is pinned.
    guard = "if (parsed && parsed.summary && parsed.summary.certified === false) {"
    assert guard in js, (
        "the MCP tool's did-not-certify guard is missing or its condition was changed — it "
        "must classify on the published `certified` field, not on the verdict word alone")
    i_cert = js.index(guard)
    i_ret = js.index("return {", i_cert)
    assert 'notMeasured("TOOL_DID_NOT_RUN"' in js[i_cert:i_ret], js[i_cert:i_cert + 300]
    # and nothing falsy precedes the condition on that line
    assert "false &&" not in js[i_cert:i_cert + len(guard)], js[i_cert:i_cert + 120]


# ═══ round 4 (review wqz62nz1u) ════════════════════════════════════════════

def test_the_owner_loader_refuses_a_module_that_is_not_the_owner(monkeypatch, tmp_path):
    """A PATH IS NOT AN IDENTITY.

    `_audit_verdict_owner` loaded whatever `_find_plugin_program("_audit_verdict.py")` returned
    and CACHED it, unchecked. That resolver is overridable (`VIBE_IC_PROGRAMS_DIR`,
    `VIBE_IC_D_PROGRAMS_DIR`), and `mcp-eda/test/test_pre_burn_audit_forwards_allow_thin_input`
    answered EVERY name with a fake `flow_compliance_check.py` — so that file was loaded as the
    owner and then called: `AttributeError: module '_vibeic_audit_verdict' has no attribute
    'verdict_word'`, escaping from the middle of the pre-burn audit and ERRORing three shipped
    tests that are green on main. Reproduced before fixing.

    An unusable module is UNREACHABLE — a state this loader already had, whose meaning is
    already decided: fall back to the word-and-rc rule and keep failing closed.
    """
    drv = _driver()
    stub = tmp_path / "_audit_verdict.py"
    stub.write_text("# a module that is not the owner\nWHAT = 1\n")
    monkeypatch.setattr(drv, "_AUDIT_VERDICT_MOD", None, raising=False)
    monkeypatch.setattr(drv, "_find_plugin_program", lambda name: str(stub))
    assert drv._audit_verdict_owner() is None, (
        "a module without the owner's API was accepted as the owner, so the next call to "
        "`verdict_word` raises from inside the pre-burn audit")
    # and the fallback still decides, closed
    assert drv.pre_burn_audit_certified(1, "", "PASS") is False
    assert drv.pre_burn_audit_certified(1, "", "FAIL") is True


def test_a_wrong_module_is_never_cached_as_the_answer(monkeypatch, tmp_path):
    """And it must not poison the process. The check happens BEFORE the cache is written, so a
    tree that answers wrongly once does not make every later call wrong too."""
    drv = _driver()
    stub = tmp_path / "_audit_verdict.py"
    stub.write_text("# not the owner\n")
    monkeypatch.setattr(drv, "_AUDIT_VERDICT_MOD", None, raising=False)
    monkeypatch.setattr(drv, "_find_plugin_program", lambda name: str(stub))
    assert drv._audit_verdict_owner() is None
    cached = getattr(drv, "_AUDIT_VERDICT_MOD")
    assert cached is False or cached is None, (
        f"a module that failed the API check was cached as the owner: {cached!r}")


def test_the_real_owner_still_loads():
    """NEGATIVE CONTROL: the check must not refuse the genuine module."""
    drv = _driver()
    own = drv._audit_verdict_owner()
    assert own is not None and callable(own.read) and callable(own.verdict_word)
