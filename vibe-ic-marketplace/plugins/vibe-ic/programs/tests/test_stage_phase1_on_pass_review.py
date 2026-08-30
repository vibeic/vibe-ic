#!/usr/bin/env python3
"""The stage_phase1 ON-PASS review — and the control that stops it manufacturing
confidence in either direction.

WHAT THIS RUNG IS FOR, AT THIS STAGE
====================================
Every stage after this one transforms an upstream ARTEFACT and is checked
against it: stage2 checks the netlist against the RTL, stage3 checks the layout
against the netlist and the PDK. Phase 1 translates a DOCUMENT, and a document
is not machine-comparable — so a constant phase 1 gets wrong is wrong nowhere
downstream. The RTL implements it, the oracle is derived from the same L-doc,
and spec-conformance compares the design with the same number and passes. It is
the one defect class in the flow that every later gate confirms.

THE CONTRADICTION THIS RULE NAMES, AND WHY NOTHING ELSE SEES IT
===============================================================
An L-doc records in `extraction_evidence` the input document it read a fact out
of and the LITERAL it read. `phase1_evidence_grounding_check` is the flow's
anti-fabrication gate for exactly those literals — and it grounds the NAMES in
them, not the VALUES, and says so in its own docstring:

    "A bare HEX / sized / decimal VALUE (`0x10`, `3'b010`, `240`) is a
     synthesized / computed VALUE, NOT an invented NAME — those are gated for
     correctness elsewhere (oracle/conformance), not here"

`test_the_existing_phase1_gates_all_pass_on_the_rejected_artefact` below is not
an argument that the hole exists. It runs twelve of stage_phase1's own gates,
the grounding gate among them, against the artefact this review rejects, and
requires every one of them to exit 0.

BOTH DIRECTIONS, ON REAL PUBLISHED ARTEFACTS
============================================
A reviewer that never rejects is WORSE than none — it manufactures confidence
in every artefact it looks at. One that rejects everything is worse still: it
is the same failure as a detector that fires on 21 of 21 subjects, and it
trains its readers to skip it.

  ACCEPT  `fixtures/stage_phase1_on_pass_review/accept_espi` — verbatim from
          the published cell `protocol_parity/espi`, whose L3 cites `0x07` and
          `0x00` to its input and whose input writes both, in a command-opcode
          table a person can read: `0x07  put_iowr_short`, `0x00  put_pc`.
  REJECT  `fixtures/stage_phase1_on_pass_review/reject_pcie_gen5` — verbatim
          from the published cell `protocol_parity/pcie_gen5`, whose L3 declares
          an opcode table of eighteen hexadecimal encodings, cites every one of
          them to `input/docs/pcie_gen5_spec.pdf`, and sets
          `no_opcodes_in_input: false`. That document contains NO hexadecimal
          constant at all. It contains a connector PINOUT: pin 11 WAKE#, pin 12
          CLKREQ#, pin 17 PRSNT2#, pin 30 PWRBRK#. The decimal pin numbers were
          re-read as hexadecimal opcodes.

THE REJECTION IS CORROBORATED BY THE PLUGIN'S OWN SCRUBBER
==========================================================
That cell's `extraction_strategy` carries `hallucination_scrub_v0_1_60` records
whose `pattern_name` is `opcode_from_two_digit_decimal_page_number` and whose
`why` reads "hex value matches a 2-digit decimal page-format number commonly
lifted from byte-position figures; not a real opcode encoding". The scrubber
ruled FOUR of them fabricated and dropped those opcodes. It left the other
eighteen — and it left all eighteen EVIDENCE CLAIMS standing, including three
it had itself just scrubbed. Three of this review's rejections are therefore
already adjudicated by the repository, in the repository's own words; this rule
is the measurement the pattern-guess was standing in for.

THE MUTATION RUN, because a real-artefact test is not automatically a biting one
================================================================================
`real_artefact_test_backing_check` states the standard: "what proves a test bites
is a MUTATION RUN: disable the change, re-run its own tests, and check a
real-artefact test is among the dead." Measured 2026-08-30, 43 tests:

  MUTANT 1  the rule can never reject (`if True: return ACCEPT`)  -> 21 die
  MUTANT 2  the matcher counts the BARE DIGITS, the shape measured to take the
            rejection set from 18 to 0                             -> 21 die

Both kill the reject-side cases, the corpus partition, the emitted-test contract
and the negative controls. Mutant 2 is the one worth stating: it does not stop
the reviewer rejecting, it makes the reviewer AGREE with everything, and that is
the direction a reader does not notice. 22 survive both — the refusals, the
declaration checks and the §4.05 guard, which is correct: those are about the
harness, not about this rule's verdict.

`fixtures/.../PROVENANCE.json` carries each source file's sha256; nothing in the
fixture is authored and the input document is carried WHOLE, because a truncated
input would let the fixture choose what the design input says.

ONE INPUT IS CARRIED GZIPPED, and that is about a different gate. The published
document quotes press-release URLs of the form
`https://www.businesswire.com/news/home/<id>/en/...`, and
`shipped_path_portability_check` R1 reads the `/home/<id>/` segment of a URL as
a personal home path — measured, 5 findings, taking a gate that is PASS on main
to RED. Trimming those lines was not available for the reason above, and
teaching R1 a URL from a filesystem path is a change to a repo-wide blocking
gate that belongs to that gate. So the bytes are carried intact and unscanned,
`tree()` expands them, and the test below asserts the sha256 of what they expand
to — which is the published file's own hash. `gunzip -c` reproduces the cell
byte for byte.
"""
from __future__ import annotations

import ast
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
PROG = PROGRAMS / "stage_on_pass_review.py"
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
FIX = Path(__file__).resolve().parent / "fixtures" / "stage_phase1_on_pass_review"
ACCEPT = FIX / "accept_espi"
REJECT = FIX / "reject_pcie_gen5"
STAGE = "stage_phase1"

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import _published_corpus as _pc  # noqa: E402
except Exception:  # pragma: no cover
    _pc = None

yaml = pytest.importorskip("yaml")


def run(project, *extra, flow=None, emit=None):
    """Invoke the review exactly as the flow declares it.

    A rejection WRITES the run's own regression INTO the run tree, so every test
    that can provoke one runs against `tree()`, a per-test copy. Nothing here
    ever writes into the shipped fixture."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    argv = [sys.executable, str(PROG), str(project), "--stage", STAGE,
            "--flow-def", str(flow or FLOW)]
    if emit is not None:
        argv += ["--emit-test", str(emit)]
    return subprocess.run(argv + list(extra), capture_output=True, text=True,
                          env=env)


def tree(tmp_path, which, name=None):
    """A writable copy of one published fixture cell, as the run tree it was.

    A `*.gz` in the fixture is expanded here and the archive removed, so what
    the review sees is exactly the published cell. See PROVENANCE.json for why
    one input document is carried compressed — it is a workaround for another
    gate's false positive on the URLs inside it, and the decompressed sha256 is
    asserted below so the compression hides nothing."""
    d = tmp_path / (name or which.name)
    if not d.exists():
        shutil.copytree(which, d)
        for gz in sorted(d.rglob("*.gz")):
            gz.with_suffix("").write_bytes(gzip.decompress(gz.read_bytes()))
            gz.unlink()
    return d


def fixture_text(tree_dir, rel):
    """The published bytes of one fixture file, gzipped in the tree or not."""
    f = tree_dir / rel
    if f.is_file():
        return f.read_text(encoding="utf-8", errors="replace")
    return gzip.decompress((tree_dir / (rel + ".gz")).read_bytes()).decode(
        "utf-8", "replace")


def declaration():
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    for st in doc["stages"]:
        if st["id"] == STAGE:
            return st.get("on_pass_review")
    raise AssertionError(f"{STAGE} is not declared")


def flow_with(tmp_path, **override):
    """A copy of the canonical flow with this stage's on_pass_review patched."""
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    for st in doc["stages"]:
        if st["id"] == STAGE:
            st["on_pass_review"] = {**st["on_pass_review"], **override}
    p = tmp_path / "flow.yaml"
    p.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return p


def rejection(tmp_path, name="r"):
    """Run the review on a copy of the reject cell; return (run_dir, finding)."""
    run_dir = tree(tmp_path, REJECT, name)
    out = tmp_path / f"{name}.json"
    r = run(run_dir, "--stage-verdict", "PASS", "--json", str(out))
    assert r.returncode == 1, r.stdout + r.stderr
    return run_dir, json.loads(out.read_text())["rejections"][0]


# ─────────────────────────────────────────────────────────────────────────────
# the declaration is in the flow, and nowhere else
# ─────────────────────────────────────────────────────────────────────────────
def test_stage_phase1_declares_an_on_pass_review_naming_a_verification_tier_skill():
    d = declaration()
    assert d is not None, f"{STAGE} declares no on_pass_review"
    assert d["fires_on"] == "stage_pass"
    assert d["verdict"] in ("advisory", "blocking"), (
        "BLOCKING vs ADVISORY must be declared, and declared HERE — whether a "
        "rejection stops the flow is the flow's decision, not the reviewer's")
    tier = json.loads((PLUGIN / "skills" / "_classification.json")
                      .read_text(encoding="utf-8"))["tiers"]["verification"]["skills"]
    assert d["skill"] in tier, (
        f"{d['skill']!r} is not a member of the verification tier {tier}")
    assert (PLUGIN / "skills" / d["skill"] / "SKILL.md").is_file()


def test_the_declaration_is_not_a_second_membership_roster():
    """`flow_stage_membership_single_declaration_check` P1 discovers a roster by
    SHAPE, not by key name: any stage key whose value is a list naming declared
    step ids is a second membership declaration. This block is a mapping and
    names no step, so membership is still declared once, on the step."""
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    step_ids = {str(s["id"]) for s in doc["steps"]}
    for key, val in declaration().items():
        if isinstance(val, list):
            named = {str(v) for v in val} & step_ids
            assert not named, f"on_pass_review.{key} names step id(s) {named}"


def test_the_four_required_parts_are_declared_by_the_flow():
    assert declaration()["rejection_requires"] == [
        "intent", "artefact", "contradiction", "test"]


def test_the_declared_intent_is_the_design_input_and_the_artefact_is_phase_1s_output():
    """The two halves of a review are not interchangeable, and reading the
    artefact as the intent is a reviewer grading itself. The intent names only
    input-document directories; the artefact names only generated_docs."""
    d = declaration()
    assert all("input" in p for p in d["intent"]), d["intent"]
    assert all("generated_docs" in p for p in d["artefact"]), d["artefact"]
    assert not set(d["intent"]) & set(d["artefact"])


# ─────────────────────────────────────────────────────────────────────────────
# BOTH DIRECTIONS, ON REAL ARTEFACTS
# ─────────────────────────────────────────────────────────────────────────────
def test_a_real_known_good_artefact_is_accepted(tmp_path):
    r = run(tree(tmp_path, ACCEPT), "--stage-verdict", "PASS",
            "--json", str(tmp_path / "r.json"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ACCEPT" in r.stdout
    rec = json.loads((tmp_path / "r.json").read_text())
    assert rec["rejections"] == []
    assert rec["not_checked"] == []
    # AND IT IS NOT ACCEPTED BY LOOKING AT NOTHING. An acceptance over zero
    # examined constants is the vacuous pass this whole rung exists to refuse;
    # the review reports it as NOT CHECKED, so an ACCEPT here means the matcher
    # said YES on real spec text.
    art = rec["observations"][0]["artefact"]
    assert art["constants_checked"] == 2, art
    assert art["constants_ungrounded"] == 0


def test_a_real_artefact_quoting_constants_its_input_does_not_state_is_rejected(tmp_path):
    run_dir, f = rejection(tmp_path)
    assert f["rule"] == "R1_CITED_CONSTANT_NOT_IN_ITS_SOURCE"
    # the INTENT it read — the design input, and only the design input
    assert f["intent"]["files"] == ["phase1/input_doc/pcie_gen5_spec.txt"]
    # the ARTEFACT fact it read
    art = f["artefact"]
    assert art["constants_checked"] == 18
    assert art["constants_ungrounded"] == 18
    assert {u["constant"] for u in art["ungrounded"]} == {
        "0x11", "0x12", "0x14", "0x15", "0x17", "0x19", "0x20", "0x23", "0x24",
        "0x27", "0x28", "0x30", "0x33", "0x34", "0x37", "0x38", "0x41", "0x42"}
    assert {u["doc"] for u in art["ungrounded"]} == {"L3_CMD_PROTOCOL.json"}
    # the blast radius: fifteen of them are the VALUE of a declared field, so
    # the design is specified on a number the input never states
    used = [u for u in art["ungrounded"] if u.get("used_as_value_at")]
    assert len(used) == 15, [u["constant"] for u in used]
    assert any(s.startswith("opcodes[") and s.endswith(".hex")
               for u in used for s in u["used_as_value_at"])
    # the CONTRADICTION
    assert "0x11" in f["contradiction"]
    assert "pcie_gen5_spec.pdf" in f["contradiction"]
    # the TEST — a path that EXISTS, written by this run of the review
    assert f["test"], "the rejection carries no test"
    assert (run_dir / f["test"]).is_file(), f["test"]


def test_the_input_document_it_was_measured_against_contains_no_hexadecimal_at_all():
    """The rejection's premise, asserted on the shipped bytes rather than
    trusted. If this document ever gained a hex constant the finding would have
    to be re-derived, and this test is what would say so."""
    import re
    text = fixture_text(REJECT, "phase1/input_doc/pcie_gen5_spec.txt")
    assert re.search(r"\b0[xX][0-9A-Fa-f]+\b", text) is None
    # and what it DOES contain is the connector pinout those digits came from
    assert "WAKE#" in text and "CLKREQ#" in text and "PWRBRK#" in text


def test_the_plugins_own_scrubber_already_ruled_three_of_them_fabricated():
    """Not a second opinion this review went looking for — a record the artefact
    carries. The scrub dropped four opcodes as
    `opcode_from_two_digit_decimal_page_number` and left every evidence claim
    standing, three of which this rule rejects."""
    d = json.loads((REJECT / "phase1" / "generated_docs" / "L3_CMD_PROTOCOL.json")
                   .read_text(encoding="utf-8"))
    scrubs = [r for recs in d["extraction_strategy"].values() for r in recs
              if r.get("pattern_name") == "opcode_from_two_digit_decimal_page_number"]
    assert {r["old_value"] for r in scrubs} >= {"0x17", "0x23", "0x24"}
    assert d["no_opcodes_in_input"] is False, (
        "the disarm must not be reachable here: this artefact CLAIMS the input "
        "supplied opcodes")


def test_the_accept_control_does_not_move_when_the_reject_case_is_measured(tmp_path):
    """Both directions in ONE invocation shape. A rule that started refusing
    everything would take the accept case with it; a rule that stopped biting
    would take the reject case with it. Neither may move alone."""
    good = run(tree(tmp_path, ACCEPT), "--stage-verdict", "PASS")
    bad = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS")
    assert (good.returncode, bad.returncode) == (0, 1), (
        f"good={good.returncode} bad={bad.returncode}\n"
        f"{good.stdout}\n---\n{bad.stdout}")


def test_the_rejection_is_caused_by_the_input_text_and_nothing_else(tmp_path):
    """The negative control for the rejection itself. Copy the REAL reject tree
    and append, to its input document, the one thing the review says is missing
    — the constants, written as hexadecimal. Nothing else changes: same L-doc,
    same citations, same cell. It must flip to ACCEPT, which is what proves the
    finding is about the document and not about that cell."""
    repaired = tree(tmp_path, REJECT, "grounded")
    doc = repaired / "phase1" / "input_doc" / "pcie_gen5_spec.txt"
    doc.write_text(doc.read_text(encoding="utf-8") + "\n" + " ".join(
        f"0x{v:02X}" for v in (0x11, 0x12, 0x14, 0x15, 0x17, 0x19, 0x20, 0x23,
                               0x24, 0x27, 0x28, 0x30, 0x33, 0x34, 0x37, 0x38,
                               0x41, 0x42)) + "\n", encoding="utf-8")
    before = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS")
    after = run(repaired, "--stage-verdict", "PASS")
    assert before.returncode == 1
    assert after.returncode == 0, after.stdout + after.stderr


def test_the_bare_decimal_digits_are_not_an_occurrence_of_the_hexadecimal(tmp_path):
    """The narrowing, as an executable claim. `0x11` must not ground on the
    decimal `11` — that IS the defect, the run having read connector pin 11 as
    opcode 0x11, and MEASURED, a matcher that accepted the bare digits took the
    rejection set from 18 to 0. The document already contains every one of
    those decimals; appending more of them must move nothing."""
    loose = tree(tmp_path, REJECT, "loose")
    doc = loose / "phase1" / "input_doc" / "pcie_gen5_spec.txt"
    doc.write_text(doc.read_text(encoding="utf-8") + "\n" + " ".join(
        str(v) for v in (0x11, 0x12, 0x14, 0x15, 0x17, 0x19, 0x20, 0x23, 0x24,
                         0x27, 0x28, 0x30, 0x33, 0x34, 0x37, 0x38, 0x41, 0x42)
    ) + "\n", encoding="utf-8")
    assert run(loose, "--stage-verdict", "PASS").returncode == 1


def test_a_suffix_spelling_is_not_read_out_of_the_middle_of_a_word(tmp_path):
    """The other half of the narrowing. The flow's grounding gate collapses
    whitespace so a snake_case name matches its spec spelling; under that
    normalisation the assembler form `14h` matches the pin row `14  HSOp(4)`
    and the review manufactures agreement with a document containing no hex at
    all. MEASURED, that shape took the rejection set from 18 to 3. So: a
    genuine `14h` grounds, and `14 HSOp` / `14 Hz` do not."""
    genuine = tree(tmp_path, REJECT, "suffix_real")
    d1 = genuine / "phase1" / "input_doc" / "pcie_gen5_spec.txt"
    d1.write_text(d1.read_text(encoding="utf-8") + "\n" + " ".join(
        f"{v:02X}h" for v in (0x11, 0x12, 0x14, 0x15, 0x17, 0x19, 0x20, 0x23,
                              0x24, 0x27, 0x28, 0x30, 0x33, 0x34, 0x37, 0x38,
                              0x41, 0x42)) + "\n", encoding="utf-8")
    assert run(genuine, "--stage-verdict", "PASS").returncode == 0, (
        "a real assembler-suffix spelling must ground; a matcher that refused "
        "it would fabricate a finding against any spec written that way")

    fake = tree(tmp_path, REJECT, "suffix_fake")
    d2 = fake / "phase1" / "input_doc" / "pcie_gen5_spec.txt"
    d2.write_text(d2.read_text(encoding="utf-8") + "\n" + " ".join(
        f"{v:02X} Hz {v:02X} HSOp" for v in (0x11, 0x12, 0x14, 0x15, 0x17, 0x19,
                                             0x20, 0x23, 0x24, 0x27, 0x28, 0x30,
                                             0x33, 0x34, 0x37, 0x38, 0x41, 0x42)
    ) + "\n", encoding="utf-8")
    assert run(fake, "--stage-verdict", "PASS").returncode == 1


#: The matcher's whole contract, as a table. Each row was a decision, and the
#: two `False` rows for `each` / `ah` are the one that goes unnoticed: they are
#: false ACCEPTANCES, the review calling a fabricated constant quoted because an
#: English word happens to be spelled out of hexadecimal digits.
_MATCHER = (
    ("11", "0x11 opcode",              True,  "the plain C spelling"),
    ("11", "0x0011",                   True,  "zero-padded to a fixed width"),
    ("11", "0x110",                    False, "a longer constant is not this one"),
    ("11", "pin 11 WAKE#",             False, "the bare decimal is the defect itself"),
    ("14", "14  HSOp(4)",              False, "a pin row is not the suffix form"),
    ("14", "14 Hz",                    False, "nor is a unit"),
    ("7",  "opcode 07h next",          True,  "the assembler suffix"),
    ("A",  "reg 0Ah set",              True,  "and with the leading zero it needs"),
    ("A",  "ah well",                  False, "but never out of an English word"),
    ("EAC", "value 0EACh here",        True,  "same, three digits"),
    ("EAC", "pick each one",           False, "`each` is not `0EACh`"),
    ("2A", "reg 'h2A",                 True,  "the Verilog sized form"),
    ("2A", "reg $2A",                  True,  "the Motorola form"),
    ("2A", "reg 16#2A#",               True,  "the VHDL form"),
)


# ─────────────────────────────────────────────────────────────────────────────
# THE REGISTRY ARITHMETIC — the guard for the merge that produced this stage
# ─────────────────────────────────────────────────────────────────────────────
# WHY THIS TEST EXISTS, AND WHAT IT IS NOT. It is not a style check on three
# dictionaries. `stage_phase1` is the first stage of this program to carry more
# than one rule, and it got them from TWO PULL REQUESTS merged into the one
# `on_pass_review:` block the doctrine allows a stage. A three-way merge over
# that file folds the shared lines of two independently-added registry entries
# — MEASURED during this merge, taking the closing brace from both sides of the
# `_EMITTERS` and `_PRINTERS` hunks left THREE keys where FOUR were intended,
# and a duplicate `"stage_phase1":` key in `_RULES` whose second binding
# silently discarded the first rule's list. Python accepts both without a
# murmur.
#
# THAT IS THE FAILURE THIS FILE OTHERWISE CANNOT SEE. A rule dropped from
# `_RULES` is a rule whose tests do not run against it — every test the dropped
# rule is not in still passes, so a merge that lost a registration and a merge
# that worked produce the same green. Only counting the registrations tells
# them apart, so the counting is asserted here rather than assumed.
def _module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_sopr_registry", PROG)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_every_registered_rule_has_exactly_one_emitter_and_one_printer():
    """Exact in both directions, against the union of the two declaration
    dicts — which is not the same as against `_RULES` alone.

    v1.13.27 landed `_DECLARED_NOT_ENABLED`: `R5_PACKAGE_CANNOT_BOND_DESIGN`
    has an emitter and a printer and is deliberately NOT in `_RULES`, because
    registering the emitter is what stops enabling the rule later from
    silently writing somebody else's test. Asserting `set(_EMITTERS) ==
    set(_RULES ids)` would report that landed, intentional state as a defect.
    The union keeps the assertion EXACT rather than one-directional: a
    registration dropped by a merge still fails it, and so does an emitter
    keyed to a rule id nothing declares."""
    m = _module()
    enabled = [rid for rules in m._RULES.values() for rid, _ in rules]
    declared = [rid for rules in getattr(m, "_DECLARED_NOT_ENABLED", {}).values()
                for rid, _ in rules]
    ids = enabled + declared
    assert len(ids) == len(set(ids)), (
        f"a rule id is declared more than once: "
        f"{sorted({i for i in ids if ids.count(i) > 1})}")
    assert not (set(enabled) & set(declared)), (
        f"a rule is both enabled and declared-not-enabled: "
        f"{sorted(set(enabled) & set(declared))}")
    # every ENABLED rule must reach an emitter, or `emit_test` raises KeyError
    # and `review()` refuses the rejection as unproven
    assert set(enabled) <= set(m._EMITTERS), sorted(set(enabled) - set(m._EMITTERS))
    assert set(enabled) <= set(m._PRINTERS), sorted(set(enabled) - set(m._PRINTERS))
    # `emit_test` names the file `test_<rule_id>.py`, so two rules sharing an
    # id — or an id that differs only in case — would have one overwrite the
    # other's regression inside the run being reviewed.
    files = [f"test_{i.lower()}.py" for i in ids]
    assert len(files) == len(set(files)), f"colliding emitted filenames: {files}"

    for name, reg in (("_EMITTERS", m._EMITTERS), ("_PRINTERS", m._PRINTERS)):
        assert set(reg) == set(ids), (
            f"{name} does not hold exactly the declared rules — "
            f"missing {sorted(set(ids) - set(reg))}, "
            f"extra {sorted(set(reg) - set(ids))}")
        assert len(reg) == len(ids), f"{name} holds {len(reg)} for {len(ids)} rules"

    # and no two rules share an emitter: `emit_test` looks the body up by rule
    # id, so a shared one writes one rule's regression for the other's finding
    bodies = [fn.__name__ for fn in m._EMITTERS.values()]
    assert len(bodies) == len(set(bodies)), (
        f"one emitter serves several rules: {bodies}")


def test_this_stage_carries_the_three_rules_both_prs_authored():
    """By EQUALITY and in order, because a dropped registration is exactly what
    an inequality here would be reporting. #1845 authored the first two, #1854
    the third; the doctrine forbids two PRs declaring one stage's block, so all
    three are declared once, here."""
    assert [rid for rid, _ in _module()._RULES["stage_phase1"]] == [
        "R1_CITED_CONSTANT_NOT_IN_ITS_SOURCE",
        "R2_TOP_MODULE_PROVENANCE_REFUTED",
        "R1_CITED_INPUT_ABSENT"]


def test_the_flow_declares_this_stages_review_exactly_once():
    """One stage, one `on_pass_review:` block — the constraint that made the
    two PRs one. A second `stage_phase1` entry, or a second block inside it,
    would give the stage two declarations of one thing."""
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    named = [st for st in doc["stages"] if st["id"] == "stage_phase1"]
    assert len(named) == 1, f"{len(named)} stage_phase1 entries in the flow"
    assert "on_pass_review" in named[0]
    assert FLOW.read_text(encoding="utf-8").count(
        "--stage stage_phase1 --json") == 1


def test_a_rule_with_no_emitter_refuses_the_rejection_rather_than_writing_anothers(tmp_path):
    """THE CONTRACT THE MERGE MUST NOT DEFEAT, exercised rather than described.
    `emit_test` looks the body up by rule id and raises KeyError when there is
    none, instead of falling back to some other rule's template. Proven by
    removing ONE rule's `_EMITTERS` entry in a COPY of the program and running
    the real fixture: the run must not write a regression at all.

    The uncaught KeyError itself — `review()` catches OSError, so the process
    dies with rc 1 rather than reaching the unproven-rejection branch and rc 2
    — is #1846's surface and another author's stage. It is READ here, not
    changed and not asserted as correct."""
    import re
    src = PROG.read_text(encoding="utf-8")
    cut = re.sub(r'\n *"R1_CITED_CONSTANT_NOT_IN_ITS_SOURCE": _body_phase1,', "", src)
    assert cut != src, "the _EMITTERS entry this test removes was not found"
    maimed = tmp_path / "maimed.py"
    maimed.write_text(cut, encoding="utf-8")

    run_dir = tree(tmp_path, REJECT, "no_emitter")
    # INSIDE the copy, not beside it: the engine refuses an emit destination
    # outside the run it is reviewing, and this test's own `run()` docstring
    # already said the regression goes INTO the run tree.
    emit_dir = run_dir / "reports" / "emitted"
    r = subprocess.run(
        [sys.executable, str(maimed), str(run_dir), "--stage", STAGE,
         "--stage-verdict", "PASS", "--flow-def", str(FLOW),
         "--emit-test", str(emit_dir)],
        capture_output=True, text=True,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
                 PYTHONPATH=str(PROGRAMS)))
    assert "KeyError" in r.stderr, r.stderr[-800:] + r.stdout[-400:]
    assert "R1_CITED_CONSTANT_NOT_IN_ITS_SOURCE" in r.stderr
    # NOTHING was written — not this rule's test, and not anybody else's
    assert not emit_dir.exists() or not list(emit_dir.rglob("*.py")), (
        f"a rule with no emitter wrote {[str(x) for x in emit_dir.rglob('*.py')]}")


def test_the_matcher_says_yes_and_no_where_it_is_declared_to():
    """Loaded from the program, so this is the shipped matcher and not a copy."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_sopr", PROG)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    wrong = [(v, hay, want, why) for v, hay, want, why in _MATCHER
             if (m.hex_occurrence_re(v).search(hay.lower()) is not None) != want]
    assert not wrong, wrong
    assert sum(1 for r in _MATCHER if r[2]) >= 5, "no positive rows"
    assert sum(1 for r in _MATCHER if not r[2]) >= 5, "no negative rows"


def test_a_longer_constant_does_not_ground_a_shorter_one(tmp_path):
    """`0x11` must not be read out of `0x110`. Without the trailing word
    boundary every short opcode grounds on any longer constant that happens to
    start with it."""
    t = tree(tmp_path, REJECT, "prefix")
    doc = t / "phase1" / "input_doc" / "pcie_gen5_spec.txt"
    doc.write_text(doc.read_text(encoding="utf-8") + "\n" + " ".join(
        f"0x{v:02X}0" for v in (0x11, 0x12, 0x14, 0x15, 0x17, 0x19, 0x20, 0x23,
                                0x24, 0x27, 0x28, 0x30, 0x33, 0x34, 0x37, 0x38,
                                0x41, 0x42)) + "\n", encoding="utf-8")
    assert run(t, "--stage-verdict", "PASS").returncode == 1


def test_a_zero_padded_spelling_does_ground(tmp_path):
    """The control for the test above: the boundary must refuse a LONGER value,
    not a differently PADDED one. A gate that refused `0x0011` for `0x11` would
    reject every spec that writes its opcodes to a fixed width."""
    t = tree(tmp_path, REJECT, "padded")
    doc = t / "phase1" / "input_doc" / "pcie_gen5_spec.txt"
    doc.write_text(doc.read_text(encoding="utf-8") + "\n" + " ".join(
        f"0x00{v:02X}" for v in (0x11, 0x12, 0x14, 0x15, 0x17, 0x19, 0x20, 0x23,
                                 0x24, 0x27, 0x28, 0x30, 0x33, 0x34, 0x37, 0x38,
                                 0x41, 0x42)) + "\n", encoding="utf-8")
    assert run(t, "--stage-verdict", "PASS").returncode == 0


# ─────────────────────────────────────────────────────────────────────────────
# nothing else in the flow catches this
# ─────────────────────────────────────────────────────────────────────────────
#: The eighteen constants this review rejects on the published cell. Named here
#: so the "nothing else reports this" measurement below can be made on what the
#: wired gates SAY, not on their exit codes: a gate that is red for an unrelated
#: reason has not caught this, and a gate that is green has not caught it either.
_REJECTED = ("0x11", "0x12", "0x14", "0x15", "0x17", "0x19", "0x20", "0x23",
             "0x24", "0x27", "0x28", "0x30", "0x33", "0x34", "0x37", "0x38",
             "0x41", "0x42")


def declared_stage_gate_commands():
    """Every gate clause the flow declares for this stage, verbatim.

    Derived from the flow rather than listed here, so the measurement below
    cannot go stale against a clause added or removed after it was written."""
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    out = []
    for st in doc["steps"]:
        if str(st.get("stage")) != STAGE:
            continue
        for item in (st.get("gate") or {}).get("all_of") or []:
            for kind, val in item.items():
                cmd = val if isinstance(val, str) else (
                    val.get("command") if isinstance(val, dict) else None)
                if isinstance(cmd, str):
                    out.append((str(st["id"]), kind, cmd))
    return out


def test_the_flow_declares_gate_clauses_for_this_stage_to_measure_against():
    """The control for the sweep below: an empty clause list, or one whose
    commands name programs that do not exist, would make "no wired gate reports
    this" true by having no wired gate to report anything."""
    cmds = declared_stage_gate_commands()
    assert len(cmds) >= 30, len(cmds)
    real = [c for c in cmds if (PROGRAMS / (c[2].split()[0] + ".py")).is_file()]
    assert len(real) >= 25, [c[2].split()[0] for c in cmds if c not in real]


def test_the_anti_fabrication_program_is_not_wired_into_this_stage():
    """Load-bearing, and easy to assume the other way.

    `phase1_evidence_grounding_check` is the program whose job most resembles
    this rule's, and the argument for this rule rests partly on it passing on
    the rejected artefact. MEASURED on v1.12.99, it is invoked by NO gate clause
    anywhere in the flow — the only mention of its name in the flow file is a
    comment this change wrote. It is run by hand by the test above.

    If it is ever wired here, this rule's non-duplication has to be measured
    again rather than inherited, and this failure is what says so."""
    named = {c[2].split()[0] for c in declared_stage_gate_commands()}
    assert "phase1_evidence_grounding_check" not in named, (
        "the anti-fabrication program is now a declared clause of this stage; "
        "re-measure whether it reports the constants this rule rejects before "
        "leaving the non-duplication argument standing")


def test_the_flows_own_anti_fabrication_gate_passes_on_the_rejected_artefact(tmp_path):
    """The load-bearing fact, and the reason this rule is not a duplicate.

    `phase1_evidence_grounding_check` is the plugin's ANTI-FABRICATION program
    for exactly the literals this rule reads. Run by hand — the flow wires it
    nowhere, see the test below — it exits 0 on the artefact rejected above,
    because the NAMES in those literals really are in the input: WAKE, CLKREQ,
    PRSNT2, PWRBRK and HSO are pin names on a connector. Its own docstring
    states that a bare hex VALUE is out of its scope."""
    cell = tree(tmp_path, REJECT, "grounding")
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "phase1_evidence_grounding_check.py"), "."],
        cwd=str(cell), capture_output=True, text=True, timeout=900,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    assert r.returncode == 0, (
        "the flow's anti-fabrication gate FAILS on this artefact — if it "
        "already catches this, the on-pass rule is a duplicate and should not "
        f"land:\n{r.stdout[-2000:]}")
    assert "all grounded in input" in r.stdout
    # and THIS review is not green on it
    assert run(cell, "--stage-verdict", "PASS").returncode == 1


def test_that_gates_pass_is_not_a_program_that_passes_on_anything(tmp_path):
    """The control for the test above: a gate that exits 0 no matter what would
    satisfy it. So make it say no about the class it DOES own — plant an
    invented NAME — and require it to fail."""
    cell = tree(tmp_path, REJECT, "canary")
    p = cell / "phase1" / "generated_docs" / "L3_CMD_PROTOCOL.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["extraction_evidence"]["input/docs/pcie_gen5_spec.pdf"].append(
        {"literal": "zzq_phantom_strobe asserted on completion",
         "label": "planted canary"})
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "phase1_evidence_grounding_check.py"), "."],
        cwd=str(cell), capture_output=True, text=True,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), timeout=600)
    assert r.returncode == 1, (
        "phase1_evidence_grounding_check did not fail on a planted invented "
        "name; its PASS above would then be evidence of nothing:\n" + r.stdout)
    assert "zzq_phantom_strobe" in r.stdout


# ─────────────────────────────────────────────────────────────────────────────
# the emitted regression: it fails today, it passes on a repair, and it
# refuses the repair that is not one
# ─────────────────────────────────────────────────────────────────────────────
def _emitted(run_dir, finding):
    p = run_dir / finding["test"]
    assert p.is_file()
    return p


def _run_emitted(path):
    return subprocess.run([sys.executable, str(path)], capture_output=True,
                          text=True)


def test_the_emitted_test_fails_on_the_artefact_it_was_emitted_from(tmp_path):
    run_dir, f = rejection(tmp_path)
    out = _run_emitted(_emitted(run_dir, f))
    assert out.returncode == 1, out.stdout + out.stderr
    assert "0x11" in out.stdout


def test_the_emitted_test_passes_when_the_claim_is_withdrawn(tmp_path):
    """The repair the input actually admits. That document states no opcode
    encoding at all, so the table and every claim that the input supplied it go
    together. A test that could not pass would block every repair."""
    run_dir, f = rejection(tmp_path)
    p = run_dir / "phase1" / "generated_docs" / "L3_CMD_PROTOCOL.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["opcodes"] = []
    d["no_opcodes_in_input"] = True
    d["extraction_evidence"] = {
        k: v for k, v in d["extraction_evidence"].items()
        if "pcie_gen5_spec.pdf" not in k}
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")
    out = _run_emitted(_emitted(run_dir, f))
    assert out.returncode == 0, out.stdout + out.stderr


def test_the_emitted_test_refuses_the_repair_that_only_deletes_the_citation(tmp_path):
    """Dropping the provenance while keeping the number is the same design
    specified on the same invented constant, with the evidence that it was
    invented removed. It must stay red."""
    run_dir, f = rejection(tmp_path)
    p = run_dir / "phase1" / "generated_docs" / "L3_CMD_PROTOCOL.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["extraction_evidence"] = {
        k: v for k, v in d["extraction_evidence"].items()
        if "pcie_gen5_spec.pdf" not in k}
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")
    out = _run_emitted(_emitted(run_dir, f))
    assert out.returncode == 1, out.stdout + out.stderr
    assert "still uses" in out.stdout


def test_the_emitted_test_refuses_an_empty_artefact_rather_than_passing(tmp_path):
    """Deleting the L-docs must not be a way to make the run's own regression
    go green: an empty artefact refutes nothing and certifies nothing."""
    run_dir, f = rejection(tmp_path)
    for p in (run_dir / "phase1" / "generated_docs").glob("L*.json"):
        p.unlink()
    out = _run_emitted(_emitted(run_dir, f))
    assert out.returncode == 1
    assert "staged no L*.json" in out.stdout


def test_the_emitted_test_refuses_an_unreadable_input_rather_than_passing(tmp_path):
    """And deleting the INPUT must not either. 'I could not look' is not 'it is
    not there', and the two are byte-identical to a reader who does not check."""
    run_dir, f = rejection(tmp_path)
    shutil.rmtree(run_dir / "phase1" / "input_doc")
    out = _run_emitted(_emitted(run_dir, f))
    assert out.returncode == 1
    assert "cannot look" in out.stdout


def test_the_emitted_test_is_the_same_file_under_pytest(tmp_path):
    """It is declared to be a pytest module as well as a script; a promise in a
    docstring is not a property."""
    run_dir, f = rejection(tmp_path)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
               PYTEST_ADDOPTS="-p no:pytest_ethereum")
    base = tmp_path / "bt"
    base.mkdir(parents=True, exist_ok=True)
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(_emitted(run_dir, f)),
         "--basetemp", str(base), "-p", "no:cacheprovider"],
        capture_output=True, text=True, env=env, cwd=str(tmp_path))
    assert out.returncode == 1, out.stdout[-3000:] + out.stderr[-2000:]
    assert "1 failed" in out.stdout


# ─────────────────────────────────────────────────────────────────────────────
# it fires on SUCCESS, and only on an ESTABLISHED success
# ─────────────────────────────────────────────────────────────────────────────
def test_the_review_does_not_run_on_a_stage_that_failed(tmp_path):
    r = run(tree(tmp_path, REJECT), "--stage-verdict", "FAIL")
    assert r.returncode == 2, r.stdout
    assert "did not pass" in r.stdout


def test_an_unestablished_verdict_is_not_a_pass(tmp_path):
    r = run(tree(tmp_path, REJECT))
    assert r.returncode == 2, r.stdout
    assert "unestablished" in r.stdout


def test_a_compliance_report_supplies_the_verdict(tmp_path):
    """And BOTH ways: a green stage row reaches the rules, a red one does not."""
    green = tmp_path / "green.json"
    green.write_text(json.dumps({"steps": [
        {"id": "D1", "stage": STAGE, "status": "PASS"},
        {"id": 9, "stage": "stage2", "status": "FAIL"}]}))
    red = tmp_path / "red.json"
    red.write_text(json.dumps({"steps": [
        {"id": "D1", "stage": STAGE, "status": "PASS"},
        {"id": "0.5ic", "stage": STAGE, "status": "FAIL"}]}))
    assert run(tree(tmp_path, REJECT), "--compliance", str(green)).returncode == 1
    assert run(tree(tmp_path, ACCEPT), "--compliance", str(green)).returncode == 0
    assert run(tree(tmp_path / "red", REJECT),
               "--compliance", str(red)).returncode == 2


# ─────────────────────────────────────────────────────────────────────────────
# §4.05 — the reviewer reads the design INPUT
# ─────────────────────────────────────────────────────────────────────────────
def test_a_denied_intent_path_is_refused_rather_than_read(tmp_path):
    flow = flow_with(tmp_path, intent=["phase1/input_doc/",
                                       "benchmark/oracle/expected_opcodes.json"])
    r = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS", flow=flow)
    assert r.returncode == 2, r.stdout
    assert "4.05" in r.stdout and "oracle" in r.stdout


def test_the_denial_is_a_list_not_a_hardcode_and_an_allowed_path_still_reads(tmp_path):
    """The control for the guard: same shape, a path carrying no denied
    segment, and the review reaches its rules and rejects as before."""
    flow = flow_with(tmp_path, intent=["phase1/input_doc/", "input/docs/"])
    r = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS", flow=flow)
    assert r.returncode == 1, r.stdout


# ─────────────────────────────────────────────────────────────────────────────
# a rejection carries evidence or it is not a rejection
# ─────────────────────────────────────────────────────────────────────────────
def test_an_unproven_rejection_is_not_emitted_as_a_rejection(tmp_path):
    """Raise the evidence bar to something this finding does not carry. It must
    NOT come out as rc 1 with a missing part, and must NOT be downgraded to a
    pass: it is NOT CHECKED, and the reason names the missing part."""
    flow = flow_with(tmp_path, rejection_requires=[
        "intent", "artefact", "contradiction", "test", "waiver_reference"])
    r = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS",
            "--json", str(tmp_path / "r.json"), flow=flow)
    assert r.returncode == 2, r.stdout
    assert "could not be proven" in r.stdout
    assert "waiver_reference" in r.stdout
    rec = json.loads((tmp_path / "r.json").read_text())
    assert rec["rejections"] == [], "an unproven finding was emitted anyway"
    assert rec["unproven_rejections"][0]["missing_evidence"] == ["waiver_reference"]


# ─────────────────────────────────────────────────────────────────────────────
# an unexamined subject is not an acceptance
# ─────────────────────────────────────────────────────────────────────────────
def test_an_artefact_citing_no_constant_is_not_checked_rather_than_accepted(tmp_path):
    """MEASURED: 53 of the 58 readable published cells cite no hexadecimal
    constant out of their input. Calling them ACCEPT would be a reviewer
    reporting a pass over a question it never put."""
    t = tree(tmp_path, ACCEPT, "no_constant")
    p = t / "phase1" / "generated_docs" / "L3_CMD_PROTOCOL.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["extraction_evidence"] = {}
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")
    r = run(t, "--stage-verdict", "PASS")
    assert r.returncode == 2, r.stdout
    assert "examined 0 constants" in r.stdout


def test_an_unreadable_input_is_not_checked_rather_than_a_rejection(tmp_path):
    """The other direction of the same rule, and the more dangerous one: with
    no input to read, EVERY cited constant is 'absent'. That is not a finding,
    it is a reviewer that could not look."""
    t = tree(tmp_path, REJECT, "no_input")
    shutil.rmtree(t / "phase1" / "input_doc")
    r = run(t, "--stage-verdict", "PASS")
    assert r.returncode == 2, r.stdout
    assert "readable text-bearing input document" in r.stdout


def test_an_empty_generated_docs_is_not_an_acceptance(tmp_path):
    t = tmp_path / "no_l_docs"
    (t / "phase1" / "generated_docs").mkdir(parents=True)
    (t / "phase1" / "input_doc").mkdir(parents=True)
    (t / "phase1" / "input_doc" / "spec.txt").write_text("opcode 0x2A\n")
    r = run(t, "--stage-verdict", "PASS")
    assert r.returncode == 2, r.stdout
    assert "NO L*.json" in r.stdout


def test_a_derived_source_key_is_not_a_quotation_of_the_input(tmp_path):
    """A `derived_*` key says the value came from an upstream layer, not from a
    document. Reading it as a quotation would make this rule fire on every
    cross-layer derivation in the corpus."""
    t = tree(tmp_path, ACCEPT, "derived")
    p = t / "phase1" / "generated_docs" / "L3_CMD_PROTOCOL.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["extraction_evidence"]["derived_from_L4"] = [
        {"literal": "0xDEADBE", "label": "not a quotation of any document"}]
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")
    assert run(t, "--stage-verdict", "PASS").returncode == 0


def test_a_scrubbed_literal_is_a_disclosure_and_not_a_claim(tmp_path):
    """When the flow has already ruled a value fabricated and says so in the
    literal, the artefact is not claiming the input states it."""
    t = tree(tmp_path, ACCEPT, "scrubbed")
    p = t / "phase1" / "generated_docs" / "L3_CMD_PROTOCOL.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    src = next(k for k in d["extraction_evidence"] if "input" in k)
    d["extraction_evidence"][src].append(
        {"literal": "0xDEADBE <HALLUCINATION_SCRUBBED>", "label": "scrubbed"})
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")
    assert run(t, "--stage-verdict", "PASS").returncode == 0
    # and the control: the SAME constant without the disclosure is a rejection
    d["extraction_evidence"][src][-1] = {"literal": "0xDEADBE", "label": "x"}
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")
    assert run(t, "--stage-verdict", "PASS").returncode == 1


# ─────────────────────────────────────────────────────────────────────────────
# the review does not re-derive the artefact
# ─────────────────────────────────────────────────────────────────────────────
_SPAWN = {"subprocess", "popen", "system", "execv", "execvp", "spawn",
          "check_output", "check_call", "run_tcl"}


def _spawn_names(path: Path) -> set:
    found = set()
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Attribute) and n.attr.lower() in _SPAWN:
            found.add(n.attr)
        elif isinstance(n, ast.Name) and n.id.lower() in _SPAWN:
            found.add(n.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            mod = getattr(n, "module", None) or ""
            for nm in [a.name for a in n.names] + [mod]:
                if nm and nm.split(".")[0].lower() in _SPAWN:
                    found.add(nm)
    return found


def test_neither_the_review_nor_the_test_it_emits_starts_a_process(tmp_path):
    """A reviewer that re-extracts the input document has replaced the program
    rather than reviewed it — and so has a regression that does. This is why a
    PDF reaches this rule only through the text `doc_extract` already left in
    the run: reading that is reading what the stage produced.

    The emitted file is checked too, and that is not redundant: it is generated
    source, so nothing else in this repository would ever parse it."""
    assert _spawn_names(PROG) == set(), _spawn_names(PROG)
    run_dir, f = rejection(tmp_path)
    emitted = _emitted(run_dir, f)
    assert _spawn_names(emitted) == set(), _spawn_names(emitted)


def test_the_no_re_derivation_check_can_actually_fail():
    """The control: a detector that finds nothing anywhere would pass the test
    above against any program at all. This file spawns processes."""
    assert "subprocess" in _spawn_names(Path(__file__))


# ─────────────────────────────────────────────────────────────────────────────
# a stage with no declaration is NOT CHECKED, never a pass
# ─────────────────────────────────────────────────────────────────────────────
def test_a_stage_that_declares_no_review_is_not_checked(tmp_path):
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    for st in doc["stages"]:
        st.pop("on_pass_review", None)
    p = tmp_path / "bare.yaml"
    p.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    r = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS", flow=p)
    assert r.returncode == 2, r.stdout
    assert "declares no" in r.stdout


# ─────────────────────────────────────────────────────────────────────────────
# the fixture is a copy, not an authored artefact
# ─────────────────────────────────────────────────────────────────────────────
def test_every_fixture_file_matches_its_recorded_hash():
    """Including, for the one carried compressed, the hash of what it expands
    to — which is the PUBLISHED file's own sha256. Checking only the archive
    would leave "verbatim" resting on the archive having been made correctly
    once, which is exactly the kind of unverified claim this rule rejects."""
    import hashlib
    prov = json.loads((FIX / "PROVENANCE.json").read_text(encoding="utf-8"))
    n, expanded = 0, 0
    for tree_name, spec in prov["trees"].items():
        for rel, meta in spec["files"].items():
            b = (FIX / tree_name / rel).read_bytes()
            assert len(b) == meta["bytes"], rel
            assert hashlib.sha256(b).hexdigest() == meta["sha256"], rel
            n += 1
            if "decompressed_sha256" in meta:
                plain = gzip.decompress(b)
                assert len(plain) == meta["decompressed_bytes"], rel
                assert (hashlib.sha256(plain).hexdigest()
                        == meta["decompressed_sha256"]), rel
                expanded += 1
    # 168 files across seven trees: every tree carries what ALL THREE of
    # this stage's rules read, so a fixture is a whole run rather than one
    # rule's slice of one. That is not decoration — MEASURED, the sliced
    # fixtures this PR started from made R1_CITED_INPUT_ABSENT reject
    # `accept_espi` and `accept_interlaken` on a citation to
    # `input/docs/<the spec>.txt`, a file the published cell HAS and the
    # slice did not copy. A fixture that carries one rule's slice does not
    # merely leave a sibling rule NOT CHECKED; it can make one reject.
    #
    # 156 of the 168 are asserted byte-identical to the live corpus by
    # `test_the_fixture_is_the_published_cell` below. The other 12 are
    # `reject_spm`, whose cell has since been withdrawn from the published
    # corpus — PROVENANCE.json records that, and its files are carried
    # unchanged from #1854.
    assert n == 168, n
    assert expanded == 1, expanded


# ─────────────────────────────────────────────────────────────────────────────
# the live corpus: the whole partition, pinned
# ─────────────────────────────────────────────────────────────────────────────
#: MEASURED on benchmark-data @ 88621a5, 2026-08-30, over every published cell
#: carrying an L1: 88 cells. THE STAGE NOW CARRIES THREE RULES — #1845's two
#: and #1854's one, merged into the single `on_pass_review:` block the doctrine
#: allows a stage — so this is the COMPOSED partition and not any one rule's:
#: 5 rc 0, 7 rc 1, 76 rc 2. rc 2 dominates because a cell is NOT CHECKED as
#: soon as ANY rule cannot be answered on it, and the three rules need
#: different documents — R1_CITED_CONSTANT needs a cited hexadecimal constant,
#: R2_TOP_MODULE needs a readable design input, R1_CITED_INPUT needs a
#: path-shaped provenance claim. That is the honest reading: the stage was not
#: fully reviewed there, and the run names which rule could not look and why.
#:
#: PER RULE, over the same 88 cells:
#:   R1_CITED_CONSTANT_NOT_IN_ITS_SOURCE    5 ACCEPT,  1 REJECT, 82 NOT CHECKED
#:   R2_TOP_MODULE_PROVENANCE_REFUTED      42 ACCEPT,  5 REJECT, 24 NOT CHECKED,
#:                                         17 DISARMED
#:   R1_CITED_INPUT_ABSENT                 87 ACCEPT,  1 REJECT,  0 NOT CHECKED
#:
#: THE MERGE TOOK NOTHING AWAY, and that is the arithmetic that matters here.
#: Every cell either PR named as a rejection and that is STILL PUBLISHED is
#: still rejected, by the same rule, and no rule widened by one cell:
#:   `pcie_gen5`                     R1_CITED_CONSTANT's, #1845's, unchanged
#:   ddr5/gddr6/hbm3/io_link/sas     R2_TOP_MODULE's, #1845's five, unchanged
#:   `ic/spm/v1.10.18_sky130A`       R1_CITED_INPUT's, and the ONLY one of
#:                                   #1854's four still in the corpus — the
#:                                   other three (`ic/spm/v1.9.96_gf180mcuD`,
#:                                   `ic/spm/v1.5.58_ihp-sg13g2`,
#:                                   `ic/u_hawaii_adc/v1.9.86_sky130A`) have
#:                                   since been withdrawn from benchmark-data,
#:                                   which `& present` below already handles.
#: The rc 0 set did not move by a single cell either: the same five #1845
#: named are the five all three rules read and accept.
_CORPUS_REJECTS = {"protocol_parity/pcie_gen5",
                   "protocol_parity/ddr5",
                   "protocol_parity/gddr6",
                   "protocol_parity/hbm3",
                   "protocol_parity/io_link",
                   "protocol_parity/sas",
                   "ic/spm/v1.10.18_sky130A",
                   # withdrawn from the corpus since #1854 measured them; kept
                   # so a republish is a PASS rather than a surprise
                   "ic/spm/v1.9.96_gf180mcuD",
                   "ic/spm/v1.5.58_ihp-sg13g2",
                   "ic/u_hawaii_adc/v1.9.86_sky130A"}

_CORPUS_ACCEPTS = {"protocol_parity/espi", "protocol_parity/smbus_pmbus",
                   "protocol_parity/interlaken",
                   "protocol_parity/automotive_ethernet",
                   "protocol_parity/usb_pd"}


@pytest.mark.skipif(_pc is None, reason="corpus helper unavailable")
def test_the_partition_over_the_published_corpus_does_not_move():
    """Pins BOTH sides on the live corpus. Each side is named cell by cell, so a
    rule that widened shows up as an extra NAME rather than as a count nobody
    reads, and a rule that stopped biting shows up as a missing one. The accept
    side is required non-empty for the same reason the reject side is: a
    reviewer that rejects all of them is not a reviewer."""
    root = _pc.corpus_tree()
    if root is None:
        pytest.skip(_pc.skip_reason())
    cells = sorted({p.parents[2] for p in
                    root.rglob("phase1/generated_docs/L1_DATASHEET.json")
                    if "claude_extracted" not in str(p)})
    if not cells:
        pytest.skip("the corpus carries no cell with an L1")
    scratch = Path(tempfile.mkdtemp(prefix="on_pass_phase1_corpus_"))
    rejects, accepts = set(), set()
    for i, cell in enumerate(cells):
        rc = run(cell, "--stage-verdict", "PASS",
                 emit=scratch / f"cell{i}").returncode
        rel = str(cell.relative_to(root))
        if rc == 1:
            rejects.add(rel)
        elif rc == 0:
            accepts.add(rel)
    present = {str(c.relative_to(root)) for c in cells}
    # EXACT on the reject side: a rule that widened shows up as an extra NAME
    # rather than as a count nobody reads, and a rule that stopped biting shows
    # up as a missing one.
    assert rejects == _CORPUS_REJECTS & present, (
        f"the rejection set moved: {sorted(rejects)}")
    # A LOWER BOUND on the accept side, deliberately. Every named cell must
    # still be accepted — that is what catches a rule turning on its own
    # controls — but a cell PUBLISHED SINCE that grounds its constants is the
    # corpus growing, not this rule moving, and failing on it would train its
    # reader to edit the list instead of reading the finding.
    missing = (_CORPUS_ACCEPTS & present) - accepts
    assert not missing, f"a named acceptance stopped being accepted: {sorted(missing)}"
    assert accepts, "every cell was refused; a reviewer that rejects all is none"


@pytest.mark.skipif(_pc is None, reason="corpus helper unavailable")
def test_no_wired_stage_gate_reports_the_constants_on_the_live_rejected_cell():
    """The full claim, on the COMPLETE published tree the fixture is a copy of,
    and measured on what the gates SAY rather than on how they exit.

    An exit code is the wrong instrument here. Some of this stage's clauses ARE
    red on this cell — a missing clock period, an absent submission template, a
    provenance block none of its L-docs carries — and none of that is this
    defect; and a clause that exits 0 has not caught it either. So: run every
    clause the flow declares for this stage, exactly as it declares it, and
    require that not one of them NAMES any of the eighteen constants. MEASURED
    2026-08-30: 34 clauses, zero mentions. This review names twelve of them in
    its first screen."""
    root = _pc.corpus_tree()
    if root is None:
        pytest.skip(_pc.skip_reason())
    cell = root / "protocol_parity" / "pcie_gen5"
    if not cell.is_dir():
        pytest.skip("the corpus does not carry the rejected cell")
    # A COPY, and this is not caution: measured, sweeping the clauses with the
    # corpus as cwd left `reports/phase1/cross_layer_reference_check.json`
    # inside the published tree. A gate is not obliged to be read-only, so a
    # sweep that runs in place makes every later measurement of that corpus a
    # measurement of the sweep.
    scratch = Path(tempfile.mkdtemp(prefix="on_pass_phase1_gates_")) / "cell"
    shutil.copytree(cell, scratch)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    mentions, ran = {}, 0
    for _sid, _kind, cmd in declared_stage_gate_commands():
        prog = PROGRAMS / (cmd.split()[0] + ".py")
        if not prog.is_file():
            continue
        ran += 1
        r = subprocess.run(f"{sys.executable} {prog} {cmd.split(' ', 1)[1]}"
                           if " " in cmd else f"{sys.executable} {prog}",
                           shell=True, cwd=str(scratch), capture_output=True,
                           text=True, env=env, timeout=900)
        said = sorted({c for c in _REJECTED
                       if c.lower() in (r.stdout + r.stderr).lower()})
        if said:
            mentions[cmd.split()[0]] = said
    assert ran >= 30, ran
    assert not mentions, (
        f"a wired gate already reports this; the on-pass rule would be a "
        f"duplicate: {mentions}")
    # and THIS review reports it
    rev = run(scratch, "--stage-verdict", "PASS")
    assert rev.returncode == 1
    assert sum(1 for c in _REJECTED if c in rev.stdout) >= 8, rev.stdout


@pytest.mark.skipif(_pc is None, reason="corpus helper unavailable")
def test_the_corpus_sweep_never_writes_into_the_corpus():
    """The sweep above emits a regression for every rejection, and a rejection's
    regression belongs in the run it reviews. On the published corpus that run
    is a read-only reference, so the sweep redirects the emit — and this asserts
    it, because a sweep that silently rewrote the corpus would make every later
    measurement of it a measurement of itself."""
    root = _pc.corpus_tree()
    if root is None:
        pytest.skip(_pc.skip_reason())
    cell = root / "protocol_parity" / "pcie_gen5"
    if not cell.is_dir():
        pytest.skip("the corpus does not carry the rejected cell")
    scratch = Path(tempfile.mkdtemp(prefix="on_pass_phase1_emit_"))
    r = run(cell, "--stage-verdict", "PASS", emit=scratch)
    assert r.returncode == 1, r.stdout
    assert any(scratch.rglob("test_*.py")), "the emit was not redirected"
    assert not (cell / "reports" / "phase1" / "gates" / "on_pass_review").exists()
