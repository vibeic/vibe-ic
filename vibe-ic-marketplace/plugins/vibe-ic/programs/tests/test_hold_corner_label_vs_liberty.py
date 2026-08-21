#!/usr/bin/env python3
"""The LABEL is the claim, the LIBERTY is the evidence — and they are
ARBITRATED, never UNIONed.

WHY THIS FILE EXISTS
--------------------
Two repairs to `hold_corner_coverage_check` are composed on this branch and
neither subsumes the other:

  * the LABEL arbitration — a hold-view line's explicit `process=<corner>`
    assignment is a DECLARATION, judged against the evidence beside it, with a
    THIRD state (`HOLD_CORNER_CONTRADICTION` / `HOLD_CORNER_UNRESOLVED`) for
    "the corner was not measured";
  * the LIBERTY-CONTENT reader — the corner a `.lib` DECLARES in its own
    header, so a PDK whose filenames carry no `ff`/`ss`/`tt` token is
    classifiable at all, and a filename that lies is overruled.

Each REGRESSES against base where the other is strong, and the composition of
them is not the union of their outputs. `_line_corners` is wired in as the
EVIDENCE SIDE of `_judge_view_line`. Union the label and the evidence instead
and the emitter's own banner

    === HOLD corner: process=FF liberty=/foss/pdks/…/…__ss_….lib, SPEF=… ===

resolves to {FF, SS}, `FF in judged` is true, and the gate PASSES a hold
sign-off that read the SLOW library — the exact defect it exists to catch.

THE CASE TABLE BELOW IS THE MEASUREMENT, NOT AN ILLUSTRATION.
Every case carries `truth`, the ground truth about the artefact:

    "ff"          the hold analysis provably ran at the fast corner  -> PASS
    "not_ff"      it provably ran somewhere else                     -> FAIL
    "unmeasured"  the artefact does not settle its own corner        -> FAIL

`test_zero_false_passes` asserts rc==0 on exactly the `truth == "ff"` rows and
rc!=0 on every other row, so "zero false PASSes" is an executed claim over the
whole table rather than a sentence.

BIDIRECTIONAL CONTROL — the same table run against the three other modules is
recorded per case in `differs_from`, and pinned by
`test_the_table_discriminates_all_three_inputs`, which fails if any of the
three predecessors would satisfy this table. That is the guard against the
table having been narrowed until it only describes the code that exists:

    base   b85d68acc  (md5 d0390374c2f89145e3c227ceb4367e8d)
    #841   1f8fbbf7d  s27/841-three-state-corner
    #849   049b793a1

MECHANISM vs SYMBOL-DEATH: the differential rows are BEHAVIOURAL. Each names a
(rc, reason) a predecessor module actually returns on the same input — not
"symbol X is absent". `_line_corners` and `_judge_view_line` both EXIST on a
predecessor (one each); the rows that discriminate are the ones where the
composed WIRING between them changes the verdict.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hold_corner_coverage_check as mod  # noqa: E402


# ───────────────────────────── fixtures ──────────────────────────────────
#: The flow's emitter prints the Liberty through `_to_container_path`, so the
#: path on the banner is a CONTAINER path and is normally UNOPENABLE on the
#: host running this gate. Every emitter case below asserts that precondition
#: explicitly — if the path ever became openable the case would be measuring a
#: different thing, and it must say so rather than quietly pass.
_CONTAINER = "/foss/pdks/vibeic_compose_probe_not_a_real_pdk/lib"


def _lib(d: Path, name: str, oc: str, default: bool = True) -> str:
    """A minimal Liberty DECLARING `operating_conditions (<oc>)`."""
    body = [
        f"library ({name}) {{",
        "  delay_model : table_lookup;",
        "  time_unit : \"1ns\";",
        f"  operating_conditions ({oc}) {{",
        "    process : 1.0;",
        "    temperature : 25.0;",
        "    voltage : 1.8;",
        "  }",
    ]
    if default:
        body.append(f"  default_operating_conditions : {oc};")
    body.append("  cell (SOMECELL) { area : 1.0; }")
    body.append("}")
    p = d / f"{name}.lib"
    p.write_text("\n".join(body) + "\n")
    return str(p)


def _banner(process: str, liberty: str) -> str:
    """The emitter's line, byte-for-byte in shape —
    `phase3_one_shot_runner._emit_mcorner_ocv_sta._pass`."""
    return (f'puts $_f "=== HOLD corner: process={process} liberty={liberty}, '
            f'SPEF=design.spef ==="')


def _deck(*lines: str) -> str:
    """A hold deck: the given lines plus the min-path invocation that proves a
    hold analysis exists at all."""
    return "\n".join(lines + ("report_worst_slack -min",
                              "report_checks -path_delay min")) + "\n"


# ═══════════════════════════ THE CASE TABLE ══════════════════════════════
# build(tmp_path) -> deck text.  `truth` is the ground truth (see module
# docstring).  `differs_from` maps a predecessor module name to the (rc,
# reason) IT returns — recorded only where it differs from composed.
_CASES = []


def _case(cid, group, truth, rc, reason, build, differs_from=None, note=""):
    _CASES.append({"id": cid, "group": group, "truth": truth, "rc": rc,
                   "reason": reason, "build": build,
                   "differs_from": differs_from or {}, "note": note})


# ── GROUP E — EMITTER-FAITHFUL: container path, UNOPENABLE on the host ────
# The blocking cases. Content contributes NOTHING here (the path cannot be
# opened), so the arbitration falls back to the filename tokens on the line —
# and that fallback is what makes the label's lie visible.
_case("E1", "emitter", "ff", 0, "HOLD_AT_FF",
      lambda t: _deck(_banner("FF", f"{_CONTAINER}/acme_sc__ff_n40C_1v95.lib")),
      note="label and filename agree at FF — the ordinary shape, unmoved")
_case("E2", "emitter", "not_ff", 1, "HOLD_CORNER_CONTRADICTION",
      lambda t: _deck(_banner("FF", f"{_CONTAINER}/acme_sc__ss_100C_1v60.lib")),
      differs_from={"base": (1, "HOLD_NOT_AT_FF"), "a849": (0, "HOLD_AT_FF")},
      note="THE BLOCKING CASE: on #849 the label is unreadable as a claim, so "
           "the line's tokens union to {FF,SS} and it PASSES a hold sign-off "
           "that read the slow library. base FAILs it, but for a reason it "
           "has not earned — it never read the label at all")
_case("E3", "emitter", "not_ff", 1, "HOLD_CORNER_CONTRADICTION",
      lambda t: _deck(_banner("FF", f"{_CONTAINER}/acme_sc__tt_025C_1v80.lib")),
      differs_from={"base": (1, "HOLD_NOT_AT_FF"), "a849": (0, "HOLD_AT_FF")},
      note="same, typical library")
_case("E4", "emitter", "not_ff", 1, "HOLD_NOT_AT_FF",
      lambda t: _deck(_banner("SS", f"{_CONTAINER}/acme_sc__ss_100C_1v60.lib")),
      note="label and filename agree at SS — an honest record of a WRONG "
           "corner, and it must stay HOLD_NOT_AT_FF, not become a "
           "contradiction")

# ── GROUP C — label arbitrated against an OPENABLE Liberty ────────────────
_case("C1", "label_vs_content", "ff", 0, "HOLD_AT_FF",
      lambda t: _deck(f"read_liberty {_lib(t, 'corelib_bestcase', 'fast')}",
                      _banner("FF", str(t / "corelib_bestcase.lib"))),
      differs_from={"base": (1, "NO_FEED_CORNER")},
      note="tokenless Liberty declaring fast, label agrees — content confirms")
_case("C2", "label_vs_content", "not_ff", 1, "HOLD_CORNER_CONTRADICTION",
      lambda t: _deck(f"read_liberty {_lib(t, 'corelib_worstcase', 'slow')}",
                      _banner("FF", str(t / "corelib_worstcase.lib"))),
      differs_from={"base": (1, "NO_FEED_CORNER"), "a841": (0, "HOLD_AT_FF"),
                    "a849": (1, "HOLD_NOT_AT_FF")},
      note="#841 REGRESSES HERE: with no corner token anywhere in the "
           "filename, its evidence side is empty, the label stands "
           "unopposed and it PASSES a slow-corner hold sign-off")
_case("C3", "label_vs_content", "unmeasured", 1, "HOLD_CORNER_CONTRADICTION",
      lambda t: _deck(f"read_liberty {_lib(t, 'corelib_bestcase', 'fast')}",
                      _banner("SS", str(t / "corelib_bestcase.lib"))),
      differs_from={"base": (1, "NO_FEED_CORNER"), "a841": (1, "HOLD_NOT_AT_FF"),
                    "a849": (0, "HOLD_AT_FF")},
      note="THE MIRROR of C2 and the reason the composition ARBITRATES rather "
           "than letting content decide: content alone answers PASS on a "
           "sign-off record that contradicts itself")
_case("C4", "label_vs_content", "not_ff", 1, "HOLD_NOT_AT_FF",
      lambda t: _deck(f"read_liberty {_lib(t, 'corelib_worstcase', 'slow')}",
                      _banner("SS", str(t / "corelib_worstcase.lib"))),
      differs_from={"base": (1, "NO_FEED_CORNER")},
      note="label and content agree at SS — honest record, wrong corner. "
           "#841 reaches the SAME verdict by a different route (the label "
           "alone), which is why this row does not discriminate it")
_case("C5", "label_vs_content", "ff", 0, "HOLD_AT_FF",
      lambda t: _deck(f"read_liberty {_lib(t, 'corelib__ss_0p9v', 'fast')}",
                      _banner("FF", str(t / "corelib__ss_0p9v.lib"))),
      differs_from={"base": (1, "HOLD_NOT_AT_FF"),
                    "a841": (1, "HOLD_CORNER_CONTRADICTION")},
      note="a MISLEADING FILENAME (_ss_) on a Liberty declaring fast. #841 "
           "arbitrates the label against the filename and manufactures a "
           "false contradiction; opening the file dissolves it")
_case("C6", "label_vs_content", "not_ff", 1, "HOLD_CORNER_CONTRADICTION",
      lambda t: _deck(f"read_liberty {_lib(t, 'corelib__ff_1p1v', 'slow')}",
                      _banner("FF", str(t / "corelib__ff_1p1v.lib"))),
      differs_from={"base": (0, "HOLD_AT_FF"), "a841": (0, "HOLD_AT_FF"),
                    "a849": (1, "HOLD_NOT_AT_FF")},
      note="the same misleading filename in the other direction — base AND "
           "#841 both certify FF off a name while the file declares slow")
_case("C7", "label_vs_content", "ff", 0, "HOLD_AT_FF",
      lambda t: _deck(f"read_liberty {_lib(t, 'corelib_bestcase', 'fast')}",
                      f"read_liberty {_lib(t, 'sram_macro_typ', 'typical')}",
                      _banner("FF", str(t / "corelib_bestcase.lib"))),
      differs_from={"base": (1, "HOLD_NOT_AT_FF")},
      note="a hard-macro Liberty at the typical corner must not outvote the "
           "sign-off line — the false FAIL the rule-2 layering exists for")
_case("C8", "label_vs_content", "ff", 0, "HOLD_AT_FF",
      lambda t: _deck(f"read_liberty {_lib(t, 'corelib_bestcase', 'fast')}",
                      f"read_liberty {_lib(t, 'sram_macro_wc', 'slow')}",
                      _banner("FF", str(t / "corelib_bestcase.lib"))),
      differs_from={"base": (1, "NO_FEED_CORNER")},
      note="content does NOT leak across lines: a macro Liberty declaring "
           "slow on its OWN read_liberty line is not evidence against the "
           "banner's Liberty")

# ── GROUP N — NO label at all: rule 3, the feed union ─────────────────────
_case("N1", "no_label", "ff", 0, "HOLD_AT_FF",
      lambda t: _deck(f"read_liberty {_lib(t, 'corelib_bestcase', 'fast')}"),
      differs_from={"base": (1, "NO_FEED_CORNER"), "a841": (1, "NO_FEED_CORNER")},
      note="tokenless Liberty, no banner — unclassifiable before #849")
_case("N2", "no_label", "not_ff", 1, "HOLD_NOT_AT_FF",
      lambda t: _deck(f"read_liberty {_lib(t, 'corelib_worstcase', 'slow')}"),
      differs_from={"base": (1, "NO_FEED_CORNER"), "a841": (1, "NO_FEED_CORNER")},
      note="right verdict for the right reason — base is right by accident")
_case("N3", "no_label", "not_ff", 1, "HOLD_NOT_AT_FF",
      lambda t: _deck(f"read_liberty {_lib(t, 'corelib__ff_1p1v', 'slow')}"),
      differs_from={"base": (0, "HOLD_AT_FF"), "a841": (0, "HOLD_AT_FF")},
      note="a FALSE PASS on base and #841: the filename says ff, the file "
           "says slow")
_case("N4", "no_label", "ff", 0, "HOLD_AT_FF",
      lambda t: _deck(f"read_liberty {_lib(t, 'corelib__ss_0p9v', 'fast')}"),
      differs_from={"base": (1, "HOLD_NOT_AT_FF"), "a841": (1, "HOLD_NOT_AT_FF")},
      note="the mirror false FAIL — the repair moves verdicts BOTH ways")
_case("N5", "no_label", "ff", 0, "HOLD_AT_FF",
      lambda t: (_lib(t, "corelib_bestcase", "fast"),
                 _deck("read_liberty corelib_bestcase.lib"))[1],
      differs_from={"base": (1, "NO_FEED_CORNER"), "a841": (1, "NO_FEED_CORNER")},
      note="RELATIVE Liberty path — proves `base=` is threaded from the "
           "script's own directory, not merely accepted as a keyword")

# ── GROUP B — the BRACKET half of the delimiter superset ──────────────────
# ADDED BECAUSE A MUTATION SURVIVED. Reverting `()[]{}`from `_PROC_RE`'s
# delimiter class — keeping only `=` — killed NONE of the 152 tests. Both
# halves of the superset were adopted together; only the `=` half was pinned,
# so the bracket half was a change nothing could have caught being undone.
# Tcl brace-quoting is ordinary and it puts a brace directly against the corner
# token, where no other delimiter appears.
#
# DISCLOSED, and NOT pinned as correct: `_PROC_RE` consumes its trailing
# delimiter, so two corner tokens separated by a SINGLE character
# (`-corners {ss tt}`) still yield only the first. That is pre-existing base
# behaviour, unchanged by this branch, and fixing it means making the trailing
# delimiter a lookahead — a third change, not a composition of these two.
_case("B1", "delimiter", "ff", 0, "HOLD_AT_FF",
      lambda t: _deck("read_liberty {ff_n40C_1v95.lib}"),
      differs_from={"base": (1, "NO_FEED_CORNER"),
                    "a841": (1, "NO_FEED_CORNER")},
      note="Tcl brace-quoted Liberty, corner token flush against the brace — "
           "invisible without `{` in the delimiter class")
_case("B2", "delimiter", "not_ff", 1, "HOLD_NOT_AT_FF",
      lambda t: _deck("set_operating_conditions -library corelib {ss}"),
      differs_from={"base": (1, "NO_FEED_CORNER"),
                    "a841": (1, "NO_FEED_CORNER")},
      note="the FAIL direction of the same widening — a brace-quoted SLOW "
           "operating condition must be read, not skipped into a blind "
           "NO_FEED_CORNER")

# ── GROUP U — the THIRD STATE: an assignment the gate cannot read ─────────
_case("U1", "unresolved", "unmeasured", 1, "HOLD_CORNER_UNRESOLVED",
      lambda t: _deck(_banner("$::env(HOLD_CORNER)",
                              f"{_CONTAINER}/acme_sc__ff_n40C_1v95.lib")),
      differs_from={"base": (0, "HOLD_AT_FF"), "a849": (0, "HOLD_AT_FF")},
      note="a FALSE PASS on base and #849: an unreadable assignment falls "
           "back onto the very filename it superseded")
_case("U2", "unresolved", "unmeasured", 1, "HOLD_CORNER_UNRESOLVED",
      lambda t: _deck(f"read_liberty {_lib(t, 'corelib_bestcase', 'fast')}",
                      _banner("$::env(HOLD_CORNER)",
                              str(t / "corelib_bestcase.lib"))),
      differs_from={"base": (1, "NO_FEED_CORNER"), "a849": (0, "HOLD_AT_FF")},
      note="PRECEDENCE PIN: an openable Liberty declaring FAST does NOT "
           "rescue an unreadable assignment. Promoting this to PASS would be "
           "the one widening in the composition that moves a verdict toward "
           "pass on an artefact whose own declaration could not be read")
_case("U3", "unresolved", "unmeasured", 1, "HOLD_CORNER_UNRESOLVED",
      lambda t: _deck(_banner("SF",
                              f"{_CONTAINER}/acme_sc__ff_n40C_1v95.lib")),
      differs_from={"base": (0, "HOLD_AT_FF"), "a849": (0, "HOLD_AT_FF")},
      note="a CROSS corner, outside this gate's FF/SS/TT model — assigned, "
           "and not resolvable")
_case("U4", "unresolved", "unmeasured", 1, "HOLD_CORNER_UNRESOLVED",
      lambda t: _deck(f"read_liberty {_lib(t, 'vendorlib_bci', 'fast')}",
                      _banner("bci", str(t / "vendorlib_bci.lib"))),
      differs_from={"base": (1, "NO_FEED_CORNER"), "a849": (0, "HOLD_AT_FF")},
      note="a PDK's own corner name as the label — same precedence as U2")
_case("U5", "unresolved", "unmeasured", 1, "HOLD_CORNER_CONTRADICTION",
      lambda t: _deck('puts $_f "=== HOLD corner: process=FF pvt=SS '
                      'liberty=none ==="'),
      differs_from={"base": (1, "NO_FEED_CORNER"), "a849": (0, "HOLD_AT_FF")},
      note="TWO assignments on one line that disagree — the contradiction "
           "that needs no evidence side at all")

# ── GROUP R — REVERSE controls: shapes that must NOT move ─────────────────
_case("R1", "reverse", "ff", 0, "HOLD_AT_FF",
      lambda t: _deck(f"read_liberty {_CONTAINER}/acme_sc__ff_n40C_1v95.lib",
                      f"read_liberty {_CONTAINER}/sram__tt_025C_1v80.lib",
                      _banner("FF", f"{_CONTAINER}/acme_sc__ff_n40C_1v95.lib")),
      note="macro-bearing design, nothing openable — the pre-existing "
           "filename route, untouched")
_case("R2", "reverse", "ff", 0, "HOLD_AT_FF",
      lambda t: _deck("set_hold_view -corner ff_view",
                      f"read_liberty {_CONTAINER}/acme_sc__ff_n40C_1v95.lib"),
      note="space-delimited MCMM with NO key=value assignment — falls "
           "through to the union rule exactly as before")
_case("R3", "reverse", "unmeasured", 1, "NO_HOLD_ANALYSIS",
      lambda t: f"read_liberty {_CONTAINER}/acme_sc__ff_n40C_1v95.lib\n",
      note="no min-path invocation — nothing was verified")
_case("R4", "reverse", "unmeasured", 1, "INPUT_EMPTY",
      lambda t: "   \n\n",
      note="empty artefact")
_case("R5", "reverse", "unmeasured", 1, "NO_FEED_CORNER",
      lambda t: _deck("read_verilog design.v", "link_design top"),
      note="a hold analysis with no Liberty and no corner anywhere")

_EMITTER = [c for c in _CASES if c["group"] == "emitter"]
_FIXTURE = [c for c in _CASES if c["group"] != "emitter"]


def _run(case, tmp_path):
    text = case["build"](tmp_path)
    return mod.evaluate(text, base=tmp_path)


# ═════════════════════════════ the pins ══════════════════════════════════
def test_the_table_is_the_size_it_claims():
    """25 fixture cases + 4 emitter cases. Pinned so a case cannot be dropped
    to make the suite green.

    (23 + 4 as first built; B1/B2 were added when a mutation reverting the
    bracket half of the delimiter superset survived the whole suite.)"""
    assert len(_EMITTER) == 4
    assert len(_FIXTURE) == 25
    assert len({c["id"] for c in _CASES}) == 29


def test_the_container_path_is_genuinely_unopenable():
    """PROBE CHECK. Every emitter case depends on the banner's Liberty NOT
    being openable — that is what makes it fall back to the filename tokens.
    If this host ever mounted that path the emitter cases would be measuring
    the content route instead, and would pass for the wrong reason."""
    for c in _EMITTER:
        text = c["build"](Path("/nonexistent"))
        for raw in mod._LIB_PATH_RE.findall(text):
            if raw.startswith(_CONTAINER):
                assert not Path(raw).exists(), (
                    f"{raw} is openable on this host — the emitter cases are "
                    f"no longer exercising the unopenable-container route")


@pytest.mark.parametrize("case", _CASES, ids=lambda c: c["id"])
def test_case_table(case, tmp_path):
    verdict, rc, rep = _run(case, tmp_path)
    assert (rc, rep.get("reason")) == (case["rc"], case["reason"]), (
        f"{case['id']}: {case['note']}")
    assert verdict == ("PASS" if rc == 0 else "FAIL")


@pytest.mark.parametrize("case", _CASES, ids=lambda c: c["id"])
def test_zero_false_passes(case, tmp_path):
    """rc==0 on exactly the rows whose ground truth is "the hold analysis
    provably ran at FF", and on no other row."""
    _v, rc, _rep = _run(case, tmp_path)
    if case["truth"] == "ff":
        assert rc == 0, f"{case['id']}: false FAIL — {case['note']}"
    else:
        assert rc != 0, f"{case['id']}: FALSE PASS — {case['note']}"


@pytest.mark.parametrize(
    "case", [c for c in _CASES if c["truth"] != "ff"], ids=lambda c: c["id"])
def test_every_non_pass_row_says_whether_it_measured(case, tmp_path):
    """`hold_corner_measured` is the machine-readable third state. A reader
    who sees only FAIL cannot tell "the corner is wrong" from "the corner was
    never read", and those call for different repairs."""
    _v, _rc, rep = _run(case, tmp_path)
    if case["reason"] in ("HOLD_CORNER_CONTRADICTION",
                          "HOLD_CORNER_UNRESOLVED", "NO_FEED_CORNER"):
        assert rep["hold_corner_measured"] is False, case["id"]
    elif case["reason"] == "HOLD_NOT_AT_FF":
        assert rep["hold_corner_measured"] is True, case["id"]


def test_the_contradiction_says_which_evidence_disagreed(tmp_path):
    """`evidence_source` is what keeps `HOLD_CORNER_CONTRADICTION` as
    actionable as the narrower `HOLD_NOT_AT_FF` would have been: it names
    whether the label was contradicted by a Liberty we OPENED or by a filename
    token we could not check."""
    lib = _lib(tmp_path, "corelib_worstcase", "slow")
    _v, rc, rep = mod.evaluate(
        _deck(f"read_liberty {lib}", _banner("FF", lib)), base=tmp_path)
    assert rc == 1
    d = rep["hold_corner_contradictions"][0]
    assert d["evidence_source"] == "liberty_content"
    assert rep["liberty_declared_corners"] == [
        {"liberty": lib, "declared_corners": ["SS"]}]

    _v, rc, rep = mod.evaluate(
        _deck(_banner("FF", f"{_CONTAINER}/acme_sc__ss_100C_1v60.lib")),
        base=tmp_path)
    assert rc == 1
    d = rep["hold_corner_contradictions"][0]
    assert d["evidence_source"] == "line_tokens"
    assert "liberty_declared_corners" not in rep


def test_the_union_would_pass_the_blocking_case(tmp_path):
    """THE COMPOSITION RULE, executed. This is the wiring the branch rejected:
    `_line_corners` UNIONed in beside the label instead of arbitrated against
    it. Run on the blocking case it yields {FF, SS}, `FF in judged` is true,
    and the gate would answer PASS. The composed module returns FAIL on the
    same input two lines down.

    Without this the branch's central claim — "not a second union" — is a
    sentence in a docstring that nothing executes."""
    line = _banner("FF", f"{_CONTAINER}/acme_sc__ss_100C_1v60.lib")
    union = sorted(set(mod._assigned_corners_in(line))
                   | set(mod._line_corners(line, tmp_path, {}, [])))
    assert union == ["FF", "SS"]
    assert "FF" in union, "the union route reaches the gate's PASS predicate"

    _v, rc, rep = mod.evaluate(_deck(line), base=tmp_path)
    assert (rc, rep["reason"]) == (1, "HOLD_CORNER_CONTRADICTION")


def test_project_mode_resolves_a_relative_liberty_against_the_script(tmp_path):
    """PROJECT MODE threads `base=` too, and it must be the SCRIPT's directory.

    ADDED BECAUSE A MUTATION SURVIVED. Replacing
    `evaluate(text, base=path.parent)` with `evaluate(text)` inside
    `_judge_source` killed NOT ONE of the 151 tests: every project-mode case in
    the suite happened to write ABSOLUTE Liberty paths into its deck, so the
    `base` argument was never load-bearing there. A deck emitted next to its
    own Liberty — or any deck a user runs through the directory entry point
    rather than the file one — silently lost the content route.

    Relative resolution is also what makes `base` the SCRIPT's directory rather
    than the project root: the Liberty here sits beside the Tcl, three levels
    below the project directory being judged.
    """
    sta = tmp_path / "phase3" / "stage3" / "sta"
    sta.mkdir(parents=True)
    _lib(sta, "corelib_bestcase", "fast")          # beside the script
    (sta / "sta_mcorner_ocv_hold.tcl").write_text(
        _deck("read_liberty corelib_bestcase.lib"))  # RELATIVE

    verdict, rc, rep = mod.judge_project(tmp_path)
    assert (verdict, rc) == ("PASS", 0), (
        "the Liberty sits beside the script and declares fast — project mode "
        "must resolve it, not fall back to a corner-token search that finds "
        "nothing")
    assert rep["reason"] == "HOLD_AT_FF"
    assert rep["liberty_declared_corners"] == [
        {"liberty": str(sta / "corelib_bestcase.lib"),
         "declared_corners": ["FF"]}]

    # NEGATIVE CONTROL, same shape: a relative Liberty declaring SLOW must
    # FAIL. Without it the assertion above is satisfied by any code path that
    # answers PASS, including one that never opened the file.
    (sta / "sta_mcorner_ocv_hold.tcl").write_text(
        _deck("read_liberty corelib_worstcase.lib"))
    _lib(sta, "corelib_worstcase", "slow")
    verdict, rc, rep = mod.judge_project(tmp_path)
    assert (verdict, rc, rep["reason"]) == ("FAIL", 1, "HOLD_NOT_AT_FF")


def test_the_table_discriminates_all_three_inputs():
    """BIDIRECTIONAL CONTROL, and the guard against a table written to fit.

    Every one of base / #841 / #849 must be REFUTED by at least one row, and
    every `differs_from` entry is a BEHAVIOURAL claim — a (rc, reason) that
    module returns on this exact input. If a predecessor satisfied the whole
    table, the table would not be measuring the composition."""
    refuted = {}
    for c in _CASES:
        for other, got in c["differs_from"].items():
            assert got != (c["rc"], c["reason"]), (
                f"{c['id']}: {other} is recorded as DIFFERING but the recorded "
                f"value equals composed's — that is not a difference")
            refuted.setdefault(other, []).append(c["id"])
    assert set(refuted) == {"base", "a841", "a849"}, (
        f"a predecessor is not refuted by any row: {sorted(refuted)}")
    # #841 and #849 must each be refuted by a row the OTHER one gets right —
    # that is what "neither subsumes the other" means, executed.
    only_841 = [c["id"] for c in _CASES
                if "a841" in c["differs_from"] and "a849" not in c["differs_from"]]
    only_849 = [c["id"] for c in _CASES
                if "a849" in c["differs_from"] and "a841" not in c["differs_from"]]
    assert only_841, "no row where #841 is wrong and #849 is right"
    assert only_849, "no row where #849 is wrong and #841 is right"
