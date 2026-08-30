#!/usr/bin/env python3
"""The stage-5 ON-PASS review: DECLARED, NOT ENABLED — and the half of it that
real published data can still test.

WHY THIS FILE EXISTS
====================
Stage 5 (Manufacturing & Test) is the one stage where nothing compares what came
back from the fab to what the design was supposed to be. MEASURED at v1.12.100:
all five of its gates — `manufacturing_fab_intake_check`,
`wafer_sort_yield_check`, `packaging_intake_check`,
`final_test_attestation_check`, `htol_attestation_check` — carry ZERO references
to `phase1/` or to any L document. Each checks its artefact against itself. So a
package too small to bond out its own die passes every gate in the flow, because
stage 2 checks the netlist against the RTL and stage 3 checks layout against
netlist and PDK, and neither of them is asking about a package.

AND THE RULE IS STILL NOT ENABLED, which is the point of this file rather than
an omission from it. MEASURED 2026-08-30 over the published corpus and this
fleet: of 105 published run roots, 0 carry a `phase3/stage5_manufacturing/`
directory, 0 carry `silicon_received.json`, and no commit in the history of
either repository ever added a file under that path. There is no known-good
artefact and no known-bad one, so both halves of the control would have to be
authored — and a reviewer proven against artefacts its own author created for
the purpose has never been tested. The rule is therefore registered in
`_DECLARED_NOT_ENABLED`, the flow block carries no `gate:` key, and
`--stage stage5_manufacturing` returns 2.

WHAT THIS FILE CAN AND CANNOT ASSERT
====================================
It CANNOT test the artefact side. It does not pretend to, and the first group of
tests below pins that the rule stays unreachable so a later edit cannot enable
it quietly.

It CAN test the INTENT side, because L1 is real and published and states BOTH
what the package provides and what the design needs — so it can contradict
itself with no manufacturing artefact in existence. `read_package_intent` is the
reader R5 depends on, and over the live corpus it partitions
**7 REJECT / 98 DISARMED / 0 ACCEPT / 0 NOT_CHECKED**. The seven are real:
every one declares `no_package_in_input: false` — claiming it read the package
out of the design input — while the same document brings more signals out than
the package it names has pins.

THE ACCEPT DIRECTION HAS NO REAL SUBJECT and is asserted on unit shapes only.
Not one published root declares a package big enough for its own pin list. That
is stated here rather than hidden behind a green run: this reader's rejections
are the half real data has tested.

THE UNIT SHAPES ARE COPIED FROM REAL PUBLISHED CELLS, not invented — the values
in `_UART_SHAPE` and `_HDMI_SHAPE` are verbatim from
`evaluation/phase1_parity/uart` and `evaluation/phase1_parity/hdmi`. The ACCEPT
shape is the one construction here, and it is the direction the corpus cannot
supply; it is built by RAISING the package pin count of the real uart shape,
so the accept and the reject differ in exactly the field under test.
"""
from __future__ import annotations

import json
import os
import subprocess
import shutil
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
PROG = PROGRAMS / "stage_on_pass_review.py"
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
STAGE = "stage5_manufacturing"

sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import stage_on_pass_review as S  # noqa: E402

try:
    import _published_corpus as _pc  # noqa: E402
except Exception:  # pragma: no cover
    _pc = None

yaml = pytest.importorskip("yaml")


def run(project, *extra):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        [sys.executable, str(PROG), str(project), "--stage", STAGE,
         "--flow-def", str(FLOW), *extra],
        capture_output=True, text=True, env=env)


def declaration():
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    for st in doc["stages"]:
        if str(st.get("id")) == STAGE:
            return st.get("on_pass_review")
    return None


# ── the shapes, verbatim from real published cells ──────────────────────────
#: `evaluation/phase1_parity/uart` — a QFP of 0 pins for a design whose own L1
#: lists 38 external pins and states external_pin_count 40.
_UART_SHAPE = {
    "package_info": {"package_type": "QFP", "pin_count": 0,
                     "evidence": "input/docs/"},
    "no_package_in_input": False,
    "external_pin_count": 40,
    "external_pins": ["SIN", "SOUT", "CTS", "RTS", "DSR", "DTR", "DCD", "RI",
                      "OUT1", "OUT2", "TXRDY", "RXRDY", "BAUDOUT", "RCLK",
                      "XIN", "XOUT", "INTR", "MR", "ADS", "DDIS", "RD", "WR",
                      "CS0", "CS1", "CS2", "A0", "A1", "A2", "D0", "D1", "D2",
                      "D3", "D4", "D5", "D6", "D7", "VDD", "VSS"],
    "pin_table": [],
}

#: `evaluation/phase1_parity/hdmi` — the document states 64 pins IN WORDS in
#: the field beside the one that says 5.
_HDMI_SHAPE = {
    "package_info": {"package_type": "QFP", "pin_count": 5,
                     "evidence": "input/docs/"},
    "no_package_in_input": False,
    "external_pin_count": "64-pin PAP (HTQFP) package; 64 pins total",
    "external_pins": ["SDA", "SCL"],
    "pin_table": [{"name": n} for n in
                  ("HSYNC", "VSYNC", "DKEN", "DE", "DVI")],
}

#: `ic/edge_llm_matmul_accel` — the disclosure the disarm exists for.
_DISARM_SHAPE = {
    "package_info": {"style": "bare die on carrier / chipIgnite shuttle",
                     "notes": "Caravel-class user macro"},
    "no_package_in_input": True,
    "external_pins": ["io_in", "io_out", "io_oeb"],
}


def l1(tmp_path, shape) -> Path:
    d = tmp_path / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "L1_DATASHEET.json"
    p.write_text(json.dumps(shape), encoding="utf-8")
    return p


# ═════════════════════════════════════════════════════════════════════════════
# 1. DECLARED, AND PROVABLY NOT ENABLED
# ═════════════════════════════════════════════════════════════════════════════
def test_the_stage_declares_the_review_and_declares_it_not_enabled():
    d = declaration()
    assert d is not None, f"{STAGE} declares no on_pass_review"
    assert d["enabled"] is False, (
        "the block must say NOT ENABLED in the flow, not only in a docstring")
    assert d.get("not_enabled_reason"), (
        "a rule that is off must say why where the declaration is")
    assert d["rule"] == "R5_PACKAGE_CANNOT_BOND_DESIGN"
    assert d["fires_on"] == "stage_pass"
    assert d["verdict"] in ("advisory", "blocking")
    tier = json.loads((PLUGIN / "skills" / "_classification.json")
                      .read_text(encoding="utf-8"))["tiers"]["verification"]["skills"]
    assert d["skill"] in tier, f"{d['skill']!r} is not in the verification tier"
    assert (PLUGIN / "skills" / d["skill"] / "SKILL.md").is_file()


def test_the_declaration_states_what_would_enable_it_as_files():
    """"Get some real data" is not an entry condition anybody can check. The
    two artefacts are named, and the note says one known-good and one known-bad
    — so a later reader can tell whether the condition has been met instead of
    deciding it has."""
    d = declaration()
    assert d["enable_requires"] == [
        "phase3/stage5_manufacturing/silicon_received.json",
        "phase3/stage5_manufacturing/packaging_log.json"]
    note = d["enable_requires_note"]
    assert "known-GOOD" in note and "known-BAD" in note
    assert "neither authored by whoever enables the rule" in note, (
        "the note must say who may NOT supply the artefacts, or the entry "
        "condition can be met by the rule's own author")


def test_the_declaration_carries_no_gate_so_nothing_invokes_it():
    """UNWIRED is a property of the flow, not a promise. A `gate:` key here
    would put an un-controlled rule in front of a run."""
    assert "gate" not in declaration(), (
        "stage5's on_pass_review must carry no gate: the rule has never been "
        "proven on an artefact its author did not write")


def test_the_rule_is_registered_as_not_enabled_and_not_as_a_rule():
    assert STAGE not in S._RULES, (
        "moving R5 into _RULES enables it; the entry condition is one real "
        "known-good and one real known-bad artefact, not a fixture")
    assert STAGE in S._DECLARED_NOT_ENABLED
    ids = [r for r, _fn in S._DECLARED_NOT_ENABLED[STAGE]]
    assert ids == ["R5_PACKAGE_CANNOT_BOND_DESIGN"]
    assert all(len(e) == 2 for e in S._DECLARED_NOT_ENABLED[STAGE]), (
        "same 2-tuple shape as _RULES, so enabling a rule is moving an entry "
        "rather than rewriting it")
    why = S._NOT_ENABLED_REASON["R5_PACKAGE_CANNOT_BOND_DESIGN"]
    assert "105" in why and "0 of" in why, (
        "the reason must carry the measurement, so a reader can re-check it")


def test_asking_the_stage_returns_exactly_two_and_says_why(tmp_path):
    l1(tmp_path, _UART_SHAPE)
    r = run(tmp_path, "--stage-verdict", "PASS", "--json",
            str(tmp_path / "r.json"))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "NOT CHECKED" in r.stdout
    assert "DECLARED AND NOT ENABLED" in r.stdout
    assert "R5_PACKAGE_CANNOT_BOND_DESIGN" in r.stdout
    rec = json.loads((tmp_path / "r.json").read_text())
    assert rec["verdict"] == "NOT_CHECKED"
    assert rec["declared_not_enabled"][0]["rule"] == "R5_PACKAGE_CANNOT_BOND_DESIGN"


def test_it_returns_two_even_on_an_artefact_that_would_reject(tmp_path):
    """The control for the test above: a NOT-ENABLED rule must return 2 for
    being off, NOT because the input happened to be unreviewable. Here the
    artefact EXISTS and contradicts the intent — R5 would reject it — and the
    answer is still 2."""
    l1(tmp_path, _UART_SHAPE)
    pkg = tmp_path / "phase3" / "stage5_manufacturing"
    pkg.mkdir(parents=True)
    (pkg / "packaging_log.json").write_text(
        json.dumps({"package_type": "QFP", "pin_count": 8}), encoding="utf-8")
    assert S.rule_package_cannot_bond_design(
        tmp_path, declaration())["verdict"] == "REJECT", (
        "the rule body must reject this, or the test below proves nothing")
    assert run(tmp_path, "--stage-verdict", "PASS").returncode == 2


def test_the_rule_writes_its_OWN_regression_and_not_another_rules(tmp_path):
    """The failure nobody can see from outside: a rule that passes every test
    while emitting somebody else's body. R5's emitter is registered, so this
    reads the file it actually writes and checks it is about a PACKAGE and a
    pin population — not R1's declared top against a module set, and not R2's
    pin list against a netlist's ports."""
    l1(tmp_path, _UART_SHAPE)
    pkg = tmp_path / "phase3" / "stage5_manufacturing"
    pkg.mkdir(parents=True)
    (pkg / "packaging_log.json").write_text(
        json.dumps({"package_type": "QFP", "pin_count": 8}), encoding="utf-8")
    finding = S.rule_package_cannot_bond_design(tmp_path, declaration())
    finding["rule"] = "R5_PACKAGE_CANNOT_BOND_DESIGN"
    assert finding["verdict"] == "REJECT"

    dest = S.emit_test(tmp_path / "emitted" / "test_r5.py", finding, STAGE)
    body = dest.read_text(encoding="utf-8")

    assert "test_the_assembled_package_carries_every_pin_the_design_brings_out" in body
    assert "packaging_log.json" in body and "L1_DATASHEET.json" in body
    assert "cannot be bonded out" in body
    # NOT another rule's body.
    assert "top_module" not in body, "this is R1's test, not R5's"
    assert "_MODULE_RE" not in body and "declared signal pin" not in body

    # It must FAIL on this run tree today, and be a valid script as well as a
    # pytest module — a test that cannot be run does not prove a rejection.
    r = subprocess.run([sys.executable, str(dest)], capture_output=True,
                       text=True, cwd=str(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "cannot be bonded out" in r.stdout


def test_the_emitted_regression_passes_once_the_package_is_big_enough(tmp_path):
    """The other direction: the emitted test must PASS when repaired, or it is
    a permanent red rather than a regression."""
    l1(tmp_path, _UART_SHAPE)
    pkg = tmp_path / "phase3" / "stage5_manufacturing"
    pkg.mkdir(parents=True)
    (pkg / "packaging_log.json").write_text(
        json.dumps({"package_type": "QFP", "pin_count": 8}), encoding="utf-8")
    finding = S.rule_package_cannot_bond_design(tmp_path, declaration())
    finding["rule"] = "R5_PACKAGE_CANNOT_BOND_DESIGN"
    dest = S.emit_test(tmp_path / "emitted" / "test_r5.py", finding, STAGE)

    (pkg / "packaging_log.json").write_text(
        json.dumps({"package_type": "QFP", "pin_count": 48}), encoding="utf-8")
    r = subprocess.run([sys.executable, str(dest)], capture_output=True,
                       text=True, cwd=str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_rule_with_no_emitter_refuses_rather_than_writing_anothers(tmp_path):
    """The guard main landed, exercised from this stage's side: emit_test
    raises for an unregistered rule instead of falling back to R1's body."""
    finding = {"rule": "R_NOT_REGISTERED", "contradiction": "x"}
    with pytest.raises(KeyError):
        S.emit_test(tmp_path / "x.py", finding, STAGE)


def test_r5_has_its_own_printer_and_does_not_borrow_r1s():
    assert S._PRINTERS["R5_PACKAGE_CANNOT_BOND_DESIGN"] is not S._PRINTERS[
        "R1_INTENT_TOP_NOT_BUILT"]
    assert S._EMITTERS["R5_PACKAGE_CANNOT_BOND_DESIGN"] is not S._EMITTERS[
        "R1_INTENT_TOP_NOT_BUILT"]


# ═════════════════════════════════════════════════════════════════════════════
# 2. THE INTENT SIDE — the half real published data can test
# ═════════════════════════════════════════════════════════════════════════════
def test_a_real_published_intent_that_refuses_its_own_pin_list_is_rejected(tmp_path):
    i = S.read_package_intent(l1(tmp_path, _UART_SHAPE))
    assert i["readable"] and i["provides"] == 0 and i["needs"] == 40
    v = S.intent_self_contradicts(i)
    assert v["verdict"] == "REJECT", v
    assert "0 pin(s) cannot bond out 40" in v["contradiction"]
    assert "no_package_in_input=False" in v["contradiction"], (
        "the evidence must carry the intent's own disclosure, so a reader can "
        "see this is a claim and not a disclosure of ignorance")


def test_the_prose_pin_count_is_read_and_not_scored_as_absent(tmp_path):
    """`external_pin_count` is an int on 21 published roots and PROSE on 5. A
    reader that took only ints would score the prose ones as 'no declaration'
    — an absent count and an unparsed one must not share an outcome."""
    i = S.read_package_intent(l1(tmp_path, _HDMI_SHAPE))
    assert i["needs"] == 64 and i["needs_source"] == "external_pin_count"
    assert S.intent_self_contradicts(i)["verdict"] == "REJECT"


def test_a_sufficient_package_is_accepted(tmp_path):
    """The direction the corpus cannot supply: 0 of 105 published roots declare
    a package big enough for their own pin list. Built by raising ONLY the pin
    count of the real uart shape, so accept and reject differ in exactly the
    field under test."""
    shape = json.loads(json.dumps(_UART_SHAPE))
    shape["package_info"]["pin_count"] = 48
    i = S.read_package_intent(l1(tmp_path, shape))
    assert i["provides"] == 48 and i["needs"] == 40
    assert S.intent_self_contradicts(i)["verdict"] == "ACCEPT", (
        "a reviewer that rejects everything is worse than none")


def test_the_intent_declaring_it_read_no_package_disarms(tmp_path):
    i = S.read_package_intent(l1(tmp_path, _DISARM_SHAPE))
    v = S.intent_self_contradicts(i)
    assert v["verdict"] == "DISARMED"
    assert "could not read a package" in v["observation"]


def test_the_disarm_reads_the_disclosure_field_and_not_a_plausible_string(tmp_path):
    """The narrowness that separates a detector from a rubber stamp: a package
    that NAMES a bare-die style while claiming it read the package out of the
    input is NOT disarmed. Only the disclosure field disarms."""
    shape = json.loads(json.dumps(_DISARM_SHAPE))
    shape["no_package_in_input"] = False
    shape["package_info"]["pin_count"] = 0
    i = S.read_package_intent(l1(tmp_path, shape))
    assert S.intent_self_contradicts(i)["verdict"] == "REJECT"


def test_an_empty_pin_population_is_not_checked_not_accepted(tmp_path):
    """An empty artefact refutes nothing and certifies nothing — the same rule
    the stage-1 review applies to an empty module set."""
    shape = {"package_info": {"package_type": "QFP", "pin_count": 0},
             "no_package_in_input": False, "external_pins": [], "pin_table": []}
    v = S.intent_self_contradicts(S.read_package_intent(l1(tmp_path, shape)))
    assert v["verdict"] == "NOT_CHECKED"
    assert "refutes nothing" in v["why"]


def test_a_true_pin_count_is_not_read_as_one_pin(tmp_path):
    """`True` is an int in Python. A bool must not be a count."""
    shape = {"package_info": {"pin_count": True}, "no_package_in_input": False,
             "external_pins": ["a", "b"]}
    assert S.read_package_intent(l1(tmp_path, shape))["provides"] is None


# ═════════════════════════════════════════════════════════════════════════════
# 3. THE LIVE CORPUS — the whole partition, pinned
# ═════════════════════════════════════════════════════════════════════════════
#: MEASURED 2026-08-30 over every published root carrying an L1. Each is a
#: verified true positive: the package the intent names has fewer pins than the
#: SAME document brings to the outside world, and each declares
#: `no_package_in_input: false`.
_CORPUS_REJECTS = {
    "evaluation/phase1_parity/hdmi",       # QFP  5 pins vs 64 stated in words
    "evaluation/phase1_parity/jtag",       # QFP  0 pins vs 5
    "evaluation/phase1_parity/mipi",       # BGA  0 pins vs 7
    "evaluation/phase1_parity/onfi",       # TSOP 0 pins vs 24
    "evaluation/phase1_parity/pcie_gen5",  # BGA  0 pins vs 5
    "evaluation/phase1_parity/swd",        # BGA  0 pins vs 4
    "evaluation/phase1_parity/uart",       # QFP  0 pins vs 40
}


def _corpus_partition(disarm=True):
    root = _pc.corpus_tree()
    if root is None:
        pytest.skip(_pc.skip_reason())
    docs = sorted(root.rglob("phase1/generated_docs/L1_DATASHEET.json"))
    if not docs:
        pytest.skip("the corpus carries no root with an L1")
    out = {}
    for doc in docs:
        i = S.read_package_intent(doc)
        if not disarm:
            i = dict(i, declares_no_package=False)
        rel = str(doc.parent.parent.parent.relative_to(root))
        out.setdefault(S.intent_self_contradicts(i)["verdict"], set()).add(rel)
    return out


@pytest.mark.skipif(_pc is None, reason="corpus helper unavailable")
def test_the_intent_side_partition_over_the_published_corpus_does_not_move():
    """Named root by root, so a rule that widened shows up as an extra name
    rather than as a count nobody reads."""
    part = _corpus_partition()
    assert part.get("REJECT", set()) == _CORPUS_REJECTS, (
        f"the rejection set moved: "
        f"{sorted(part.get('REJECT', set()) ^ _CORPUS_REJECTS)}")
    assert not part.get("ACCEPT"), (
        "no published root declares a package big enough for its own pin list; "
        "if one now does, this reader's accept direction has a real subject "
        "and this test should say so")


@pytest.mark.skipif(_pc is None, reason="corpus helper unavailable")
def test_removing_the_disarm_moves_a_label_and_not_the_rejection_set():
    """Measured both ways, because a disarm carrying 98 of 105 subjects LOOKS
    load-bearing. It is not: those roots carry no package pin count, so the
    `provides is None` branch already refuses them. Stating it stops a later
    reader from defending the disarm on a strength it does not have."""
    on, off = _corpus_partition(True), _corpus_partition(False)
    assert on.get("REJECT") == off.get("REJECT"), (
        "removing the disarm changed the rejection set; the docstring says it "
        "does not, and one of the two is now wrong")
    assert on.get("DISARMED") == off.get("NOT_CHECKED")


# ═════════════════════════════════════════════════════════════════════════════
# 4. THE CONTROL THAT MUST NOT MOVE
# ═════════════════════════════════════════════════════════════════════════════
_FIX = Path(__file__).resolve().parent / "fixtures" / "stage1_on_pass_review"


@pytest.mark.parametrize("cell,rc", [("accept_spm", 0), ("reject_caravel", 1)])
def test_stage1_still_answers_exactly_as_it_did(tmp_path, cell, rc):
    """Adding a stage must not move another stage's verdict. Exact rc, both
    directions, on the real fixtures stage 1 already ships."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    # The run tree is a COPY and the emit lands inside it. Reviewing the shipped
    # fixture in place with the emit redirected to `tmp_path` put the rejection's
    # proof outside the run, which the engine now refuses (rc 2) — and refusing
    # it is the point: a proof the run cannot open is not a proof.
    run_dir = tmp_path / "run"
    shutil.copytree(_FIX / cell, run_dir)
    r = subprocess.run(
        [sys.executable, str(PROG), str(run_dir), "--stage", "stage1",
         "--flow-def", str(FLOW), "--stage-verdict", "PASS",
         "--emit-test", str(run_dir / "reports" / "emit")],
        capture_output=True, text=True, env=env)
    assert r.returncode == rc, r.stdout + r.stderr
