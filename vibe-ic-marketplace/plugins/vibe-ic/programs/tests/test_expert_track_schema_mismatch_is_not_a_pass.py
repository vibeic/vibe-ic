#!/usr/bin/env python3
"""test_expert_track_schema_mismatch_is_not_a_pass.py

An AI answer that arrives in an UNEXPECTED SHAPE was recorded as
CONSUMED-with-nothing and published as a PASS.

    exps = data.get("expectations")
    status.update(status="CONSUMED",
                  reason=f"read {len(exps) if isinstance(exps, list) else 0} "
                         f"expectation(s) from a prior agent invocation",
                  expectations=exps if isinstance(exps, list) else [])

`x if isinstance(x, list) else []` maps EVERY shape the consumer did not expect
onto the empty list, and the empty list is precisely what an agent with nothing
to say produces. The record then reads `CONSUMED — read 0 expectation(s)`, and
nothing anywhere distinguishes:

    (a) the agent answered and genuinely had nothing to add, and
    (b) the agent answered with substance in a schema this consumer cannot
        read, and the consumer threw it away.

MEASURED, not hypothetical: one real expert review — a verdict of "gaps",
`complete: false`, and two named cross-layer defects — used its own schema with
no `expectations` key. It was flattened to `[]`, recorded as CONSUMED, and
published as `verdict PASS / blocking False / 0 findings`. A zero denominator
passed instead of refusing, which is what this repo's own
`gate_zero_denominator_refuses_check` exists to prevent — and it is worse than
an ordinary silent pass, because the answer EXISTED and was discarded.

WHAT IS PINNED HERE
  * a parsing-but-unexpected answer is REFUSED — never CONSUMED, never a PASS;
  * the refusal names WHAT ARRIVED (the top-level keys present), so a reader
    can tell a schema mismatch from an empty answer;
  * `CONSUMED_EMPTY` (the agent really said nothing) is a DIFFERENT token from
    `ANSWER_SCHEMA_MISMATCH` (the consumer could not read what it said), and
    neither of them is a PASS;
  * the refusal outranks a completely clean deterministic half — the case that
    produced the published PASS, and the one a fix that only corrects the
    status token would leave lying;
  * a well-formed answer still converges and still bites, so none of the above
    was bought by making the track refuse everything.

Every fixture is synthesised here from neutral parts. No design, PDK, vendor or
IP-model identifier appears anywhere in this file.

Run: python3 -m pytest programs/tests/test_expert_track_schema_mismatch_is_not_a_pass.py -q
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_expert_parse_track as T          # noqa: E402
import _path_layout as _pl                     # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# ── fixtures ────────────────────────────────────────────────────────────────

_INPUT_DOC = """# Block specification

The converter accepts an external reference on the REFHI terminal and
digitises to 12 bits at 500 ksps. Trim values are restored at power-up.
"""


def _project(tmp_path, name="proj", l1=None):
    """The state every design on the fleet is in: no deterministic rule
    applies, so the AI half is the ONLY half that can examine anything."""
    p = tmp_path / name
    (p / "input" / "docs").mkdir(parents=True)
    (p / "phase1" / "generated_docs").mkdir(parents=True)
    (p / "input" / "docs" / "spec.md").write_text(_INPUT_DOC)
    (p / "phase1" / "generated_docs" / "L1_DATASHEET.json").write_text(
        json.dumps(l1 if l1 is not None else
                   {"doc_id": "L1", "fields": {"resolution_bits": 12}}))
    return p


def _lef(master: str, power_pins, ground_pins=("VSS",)) -> str:
    body = ["VERSION 5.8 ;", f"MACRO {master}", "  CLASS BLOCK ;",
            "  SIZE 100.0 BY 100.0 ;"]
    for p in power_pins:
        body += [f"  PIN {p}", "    DIRECTION INOUT ;", "    USE POWER ;",
                 f"  END {p}"]
    for g in ground_pins:
        body += [f"  PIN {g}", "    DIRECTION INOUT ;", "    USE GROUND ;",
                 f"  END {g}"]
    body += ["  PIN clk", "    DIRECTION INPUT ;", "    USE SIGNAL ;",
             "  END clk", f"END {master}", "END LIBRARY"]
    return "\n".join(body) + "\n"


_RTL_WITH_BURN_LOGIC = """
module chip_top (
  input         clk,
  input         rst_n,
  input         prog_req,
  input  [8:0]  prog_addr,
  input  [31:0] prog_data,
  output        prog_busy,
  input         VDDC,
  input         VPROG,
  input         VSS
);
  wire       burn_start;
  wire [8:0] burn_addr;
  reg        burn_busy;
  {MASTER} u_array (.clk(clk));
  assign prog_busy = burn_busy;
endmodule
"""


def _project_with_a_clean_deterministic_half(tmp_path, name="clean"):
    """A design whose deterministic half APPLIES and whose every expectation
    is MET. Without the AI half this is the shape that legitimately reaches a
    non-empty denominator — which is what makes it the right place to ask
    whether a discarded answer can still be called a pass."""
    master = "mem_array_512x32"
    p = tmp_path / name
    (p / "input" / "pdk_local" / "memlib").mkdir(parents=True)
    (p / "input" / "design_src" / "rtl").mkdir(parents=True)
    (p / "phase1" / "generated_docs").mkdir(parents=True)
    (p / "input" / "pdk_local" / "memlib" / f"{master}.lef").write_text(
        _lef(master, ("VDDC", "VPROG")))
    (p / "input" / "design_src" / "rtl" / "chip_top.v").write_text(
        _RTL_WITH_BURN_LOGIC.replace("{MASTER}", master))
    (p / "phase1" / "generated_docs" / "L1_DATASHEET.json").write_text(
        json.dumps({"doc_id": "L1", "fields": {
            "pinout": {n: {"type": "supply"}
                       for n in ("VDDC", "VPROG", "VSS")}}}))
    (p / "phase1" / "generated_docs" / "L21_POWER_INTENT.json").write_text(
        json.dumps({"doc_id": "L21",
                    "fields": {"power_rails": ["VDDC", "VPROG"]}}))
    return p


def _pack_dir(project: Path) -> Path:
    return _pl.report_path(project, "phase1/expert_parse_track").parent \
        / "expert_parse_track_pack"


def _write_answer(project: Path, blob) -> Path:
    """Put an answer file where the consumer looks for it. `blob` is written
    VERBATIM — the point of this file is what the consumer does with a shape it
    did not expect, so nothing here may normalise it first."""
    d = _pack_dir(project)
    d.mkdir(parents=True, exist_ok=True)
    f = d / "l_doc_expectations.json"
    f.write_text(json.dumps(blob))
    return f


#: The measured shape: substantive expert content, this consumer's key absent.
#: Reconstructed as a NEUTRAL fixture — same schema shape, no design identity.
_ANSWER_IN_ANOTHER_SCHEMA = {
    "gate": "phase1_expert_parse_track",
    "subagent": "vibe-ic:ic-expert-agent",
    "verdict": "gaps",
    "complete": False,
    "internally_consistent": False,
    "cross_layer_inconsistencies": [
        {"id": "L1-PIN-INVENTORY", "severity": "real", "layer": "L1.pin_table",
         "finding": "entries in the pin table are not terminals"},
        {"id": "L9-PORT-SET", "severity": "real", "layer": "L9.top_level_ports",
         "finding": "the integration port set omits a declared interface"},
    ],
    "what_is_correctly_captured": ["the clock", "the reset"],
}


def _run_track(project: Path):
    env = dict(os.environ)
    env["VIBE_IC_DISABLE_LLM_CONFIRM"] = "1"     # force the no-backend path
    cp = _pr.run(
        [sys.executable, str(_PROGRAMS / "phase1_expert_parse_track.py"),
         str(project)], capture_output=True, text=True, env=env)
    return cp.returncode, cp.stdout, cp.stderr


def _report(project: Path):
    return json.loads(
        _pl.report_path(project, "phase1/expert_parse_track.json").read_text())


# ── the defect ──────────────────────────────────────────────────────────────

def test_an_answer_in_another_schema_is_refused_and_is_not_a_pass(tmp_path):
    """THE defect. Before this landing: `ai_subtrack.status == "CONSUMED"`,
    `reason == "read 0 expectation(s) from a prior agent invocation"`,
    `verdict == "PASS"`, `findings == []`, rc 0."""
    p = _project(tmp_path)
    _write_answer(p, _ANSWER_IN_ANOTHER_SCHEMA)
    rc, out, _ = _run_track(p)
    rep = _report(p)

    # BEHAVIOUR FIRST, ON LITERALS. Every assertion below holds against the
    # pre-fix module too — it just does not hold TRUE there. Leading with a
    # module constant the old file lacks would make this test fail on an
    # AttributeError against the old code, which proves the symbol is new and
    # says nothing about whether the test bites.
    ai = rep["ai_subtrack"]
    assert rep["verdict"] != "PASS", (
        "an answer that exists and was discarded published a PASS")
    assert ai["status"] != "CONSUMED", (
        "an answer this consumer could not read was recorded as consumed")
    assert "read 0 expectation(s)" not in ai["reason"], (
        "a discarded answer is described in the words of an empty one")
    assert rc == 2, f"a refusal exited {rc}"
    assert rep["verdict"] == "REFUSED"
    # and it is PRINTED where a human sees it, not only filed
    assert "REFUSED" in out
    # only now the vocabulary itself
    assert ai["status"] == T.AI_SCHEMA_MISMATCH
    assert ai["status"] not in T.AI_READ_STATES, (
        "an answer this consumer cannot read was counted as a reading")


def test_the_refusal_names_what_arrived_not_only_what_was_expected(tmp_path):
    """"no expectations key" sends a reader nowhere. "no expectations key, and
    here are the seven keys it does carry, one of them
    `cross_layer_inconsistencies`" sends them to where the answer actually is.
    """
    p = _project(tmp_path)
    _write_answer(p, _ANSWER_IN_ANOTHER_SCHEMA)
    _, out, _ = _run_track(p)
    rep = _report(p)

    keys = rep["ai_subtrack"]["answer_top_level_keys"]
    assert keys == sorted(_ANSWER_IN_ANOTHER_SCHEMA), keys
    # the key holding the discarded substance is among them, by name
    assert "cross_layer_inconsistencies" in keys
    fs = [f for f in rep["findings"]
          if f["rule"] == T.RULE_AI_ANSWER_SCHEMA_MISMATCH]
    assert len(fs) == 1, rep["findings"]
    assert fs[0]["about"] == "track", (
        "a consumer that could not read an answer says nothing about the "
        "design, and counting it as a design finding would inflate the AI half")
    assert "cross_layer_inconsistencies" in fs[0]["message"]
    assert "cross_layer_inconsistencies" in out
    # never the words of an agent that had nothing to say
    assert "read 0 expectation(s)" not in rep["ai_subtrack"]["reason"]


def test_a_genuinely_empty_answer_gets_its_own_token(tmp_path):
    """The pair that makes the refusal mean something. BOTH states are
    legitimate outcomes of a run and they are NOT the same outcome, so they get
    different tokens: `CONSUMED_EMPTY` is an answer that named nothing,
    `ANSWER_SCHEMA_MISMATCH` is an answer nobody read. Under one token the only
    downstream consumer of this report — which reads `.status` and nothing else
    — could not tell them apart."""
    p = _project(tmp_path)
    _write_answer(p, {"expectations": []})
    rc, _, _ = _run_track(p)
    rep = _report(p)

    # behaviour first, on literals — see the note in the test above
    assert rep["ai_subtrack"]["status"] != "CONSUMED", (
        "the two zeros still share one token")
    assert rep["verdict"] != "PASS", "a zero denominator passed"
    assert rc == 2
    assert rep["ai_subtrack"]["status"] == T.AI_CONSUMED_EMPTY
    assert T.AI_CONSUMED_EMPTY != T.AI_SCHEMA_MISMATCH != T.AI_CONSUMED
    # it IS a reading — that is the difference from the refusal
    assert rep["ai_subtrack"]["status"] in T.AI_READ_STATES
    assert [f["rule"] for f in rep["findings"]] == [T.RULE_AI_ANSWER_EMPTY]


def test_expectations_present_but_not_a_list_is_refused(tmp_path):
    """The second half of the coerced predicate. `isinstance(x, list) else []`
    swallowed a wrong TYPE exactly as silently as a missing key."""
    p = _project(tmp_path)
    _write_answer(p, {"expectations": {"EXP_1": "a mapping, not a list"}})
    rc, _, _ = _run_track(p)
    rep = _report(p)

    assert rep["verdict"] != "PASS" and rc == 2
    assert rep["ai_subtrack"]["status"] != "CONSUMED"
    assert rep["ai_subtrack"]["status"] == T.AI_SCHEMA_MISMATCH
    assert rep["verdict"] == "REFUSED"
    # the refusal says what the type WAS, in the reader's own vocabulary
    assert "object" in rep["ai_subtrack"]["answer_schema_why"]
    assert "expectations" in rep["ai_subtrack"]["answer_top_level_keys"]


def test_a_top_level_array_answer_is_refused_not_a_crash(tmp_path):
    """An answer whose top level is a JSON array reached `data.get(...)` on a
    list. That raised, the track exited 1, and the runner reported "the expert
    track did not complete" — a shape the old predicate never even got to
    coerce. A refusal states the same fact without losing the report."""
    p = _project(tmp_path)
    _write_answer(p, [{"id": "a::b", "layer": "L1_DATASHEET"}])
    rc, _, err = _run_track(p)
    rep = _report(p)          # the report EXISTS — the track completed

    assert rep["verdict"] != "PASS" and rc == 2
    assert "did not complete" not in err
    assert rep["ai_subtrack"]["status"] == T.AI_SCHEMA_MISMATCH
    assert rep["ai_subtrack"]["answer_json_type"] == "array"
    assert rep["verdict"] == "REFUSED"


def test_the_refusal_outranks_a_completely_clean_deterministic_half(tmp_path):
    """THE published shape, and the one a status-only fix would leave lying.

    The deterministic half applies here and every one of its expectations is
    met — so with the answer discarded, the old consumer had nothing at all to
    report and printed `PASS`. Correcting the STATUS while this still came out
    PASS would have fixed the label and not the lie: half of a dual track
    refused to read an answer that exists, and no top-line word on that run may
    imply it was examined.

    The deterministic findings are not suppressed by the refusal — they are
    still listed and still printed. What the refusal replaces is the CLAIM of
    coverage, never the evidence."""
    p = _project_with_a_clean_deterministic_half(tmp_path)
    _write_answer(p, _ANSWER_IN_ANOTHER_SCHEMA)
    rc, out, _ = _run_track(p)
    rep = _report(p)

    # the deterministic half really did apply and really was clean
    applicable = [r for r in rep["deterministic_subtrack"] if r["applicable"]]
    assert applicable, "the fixture stopped exercising the deterministic half"
    assert all(e["met"] for r in applicable for e in r["expectations"])

    # behaviour first, on literals — this is the assertion that fails against
    # the pre-fix consumer, and it fails because the run PASSED, not because a
    # symbol was missing
    assert rep["verdict"] != "PASS", (
        "a clean deterministic half plus a discarded answer still published a "
        "PASS — the status was corrected and the lie was not")
    assert rc == 2
    assert rep["verdict"] == "REFUSED"
    assert rep["denominator"]["deterministic"] > 0
    assert rep["ai_subtrack"]["status"] == T.AI_SCHEMA_MISMATCH
    assert rep["denominator"]["ai"] == 0, (
        "a refused answer contributed to the denominator")


# ── the anti-vacuity pair ───────────────────────────────────────────────────

def test_a_well_formed_answer_still_converges_and_still_bites(tmp_path):
    """None of the above may be bought by making the track refuse everything.
    A well-formed answer naming a fact no L-doc carries must still reach
    CONSUMED and must still produce its named design finding.

    Written entirely on LITERALS and on rule ids that predate this landing, so
    it holds against the pre-fix consumer too. That is the point: it is the
    arm of the control that must stay GREEN on the old code, or "every test in
    this file fails against origin/main" would be equally explained by the file
    simply not importing there."""
    p = _project(tmp_path)
    _write_answer(p, {"expectations": [{
        "id": "external_reference::REFHI",
        "layer": "L1_DATASHEET",
        "field_path": "fields.pinout",
        "requirement": "a terminal for the external reference",
        "evidence": ["input/docs/spec.md: external reference on REFHI"],
        "expected_tokens": ["REFHI"]}]})
    rc, out, _ = _run_track(p)
    rep = _report(p)

    assert rep["ai_subtrack"]["status"] == "CONSUMED"
    assert rep["verdict"] == "FINDINGS" and rc == 0
    assert [f for f in rep["findings"]
            if f["rule"].startswith(T.RULE_AI_UNMET)]
    assert not [f for f in rep["findings"]
                if f["rule"].endswith("ANSWER_SCHEMA_MISMATCH")]


def test_an_answer_that_does_not_parse_is_still_an_error(tmp_path):
    """Unchanged, and stated so the new refusal cannot quietly absorb it. A
    file that is not JSON at all was never mistaken for a reading; that is a
    different failure with a different remedy and it keeps its own token.

    The second arm of the control that must stay GREEN on the old code."""
    p = _project(tmp_path)
    d = _pack_dir(p)
    d.mkdir(parents=True, exist_ok=True)
    (d / "l_doc_expectations.json").write_text("{not json")
    _run_track(p)
    rep = _report(p)

    assert rep["ai_subtrack"]["status"] == "ERROR"
    assert rep["ai_subtrack"]["status"] != "ANSWER_SCHEMA_MISMATCH"
    assert [f for f in rep["findings"] if f["rule"] == T.RULE_AI_SKIPPED]


# ── the house rules this verdict has to match ───────────────────────────────

def test_every_verdict_discloses_its_denominator(tmp_path):
    """`gate_discloses_denominator_check` — a PASS must say how much it looked
    at. Asserted on the PRINTED output, because that is what the roll-up and a
    human both read."""
    p = _project(tmp_path)
    _write_answer(p, {"expectations": [{
        "id": "external_reference::REFHI", "layer": "L1_DATASHEET",
        "requirement": "a terminal", "expected_tokens": ["REFHI"]}]})
    _, out, _ = _run_track(p)
    assert "examined 1 expectation(s)" in out, out
    assert _report(p)["examined_expectations"] == 1


def test_a_zero_denominator_never_exits_zero(tmp_path):
    """`gate_zero_denominator_refuses_check` — a gate that read NOTHING must
    not exit 0. Both zero-denominator shapes are checked: the refused answer
    and the honestly empty one."""
    for name, blob in (("refused", _ANSWER_IN_ANOTHER_SCHEMA),
                       ("empty", {"expectations": []})):
        p = _project(tmp_path, name=name)
        _write_answer(p, blob)
        rc, out, _ = _run_track(p)
        rep = _report(p)
        # behaviour first, on literals
        assert rc != 0, f"{name}: a zero denominator exited 0"
        assert rep["verdict"] != "PASS", f"{name}: a zero denominator passed"
        assert "examined 0 expectation(s)" in out, out
        assert rep["examined_expectations"] == 0
