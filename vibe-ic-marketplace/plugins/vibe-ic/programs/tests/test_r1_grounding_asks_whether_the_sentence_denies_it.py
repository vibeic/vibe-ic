"""A constant that appears only inside a sentence that DENIES it is not quoted.

vibe-ic#712's shape, in R1_CITED_CONSTANT_NOT_IN_ITS_SOURCE. The rule asked
whether an L-doc's cited hexadecimal constant OCCURS in the design input:

    if hex_occurrence_re(m.group(1)).search(haystack):
        continue                                   # -> grounded, ACCEPT

`search` reads "the string appears somewhere in the input" as "the input STATES
it", and those are different claims. This repo has already paid for that exact
substitution twice in one day, in two other fields, found by the same activity:

    #706  pdk_target          "This block is NOT targeted at <PDK>."
                              -> pdk_target = <PDK>
    #711  die_area_budget_um  a die the document says "has NO meaning here and
                              is REMOVED, not translated" -> re-declared as a
                              mandate

Here it lands on the ACCEPT side, which is the quiet direction: an input saying
"the opcodes are NOT 0x11 … in this revision" GROUNDS a cited 0x11 on its own
denial, and the review reports a fabricated constant as a faithful VERBATIM
quotation — citing the sentence that refutes it as the authority. Nothing goes
red. `prose_polarity_consulted_check` names this function for exactly that, and
it was the only NEW offender in the set.

THE EXPERIMENT IS THE REPO'S OWN, WITH ONE WORD CHANGED.
`test_the_rejection_is_caused_by_the_input_text_and_nothing_else` takes the
published `reject_pcie_gen5` cell — whose input document contains NO hexadecimal
constant at all, asserted there — appends the eighteen missing opcodes as plain
hexadecimal, and proves the rejection flips to ACCEPT. Every case below appends
the SAME eighteen constants to the SAME document in the SAME place. The only
thing that varies is the polarity of the sentence they are written in.

    plain      "0x11 0x12 …"                        -> ACCEPT   (rc 0)
    denied     "The opcodes are NOT 0x11, 0x12, …"  -> REJECT   (rc 1)

The first is the CONTROL and it is green in both arms: it is the existing test's
own claim, and if it ever went red this file would be measuring a rule that had
stopped grounding anything rather than one that had learned polarity.
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
PROG = PROGRAMS / "stage_on_pass_review.py"
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
FIX = Path(__file__).resolve().parent / "fixtures" / "stage_phase1_on_pass_review"
REJECT = FIX / "reject_pcie_gen5"
STAGE = "stage_phase1"
RULE = "R1_CITED_CONSTANT_NOT_IN_ITS_SOURCE"
DOC_REL = Path("phase1") / "input_doc" / "pcie_gen5_spec.txt"

#: The eighteen opcodes the published cell cites and its input never writes.
OPCODES = (0x11, 0x12, 0x14, 0x15, 0x17, 0x19, 0x20, 0x23, 0x24,
           0x27, 0x28, 0x30, 0x33, 0x34, 0x37, 0x38, 0x41, 0x42)
HEX = " ".join(f"0x{v:02X}" for v in OPCODES)

pytest.importorskip("yaml")


def tree(tmp_path, name):
    """A writable copy of the published reject cell, gz expanded as published."""
    d = tmp_path / name
    shutil.copytree(REJECT, d)
    for gz in sorted(d.rglob("*.gz")):
        gz.with_suffix("").write_bytes(gzip.decompress(gz.read_bytes()))
        gz.unlink()
    return d


def append(root: Path, sentence: str) -> Path:
    doc = root / DOC_REL
    doc.write_text(doc.read_text(encoding="utf-8") + "\n\n" + sentence + "\n",
                   encoding="utf-8")
    return root


def run(project):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        [sys.executable, str(PROG), str(project), "--stage", STAGE,
         "--flow-def", str(FLOW), "--stage-verdict", "PASS"],
        capture_output=True, text=True, env=env)


# ── the control, green in both arms ──────────────────────────────────────────

def test_CONTROL_the_constants_written_plainly_still_ground(tmp_path):
    """The existing rule's own claim, restated here so the negatives below mean
    something. A matcher that had simply stopped grounding anything would make
    every denial case pass for the wrong reason."""
    r = run(append(tree(tmp_path, "plain"), HEX))
    assert r.returncode == 0, r.stdout + r.stderr


def test_CONTROL_the_untouched_published_cell_is_still_rejected(tmp_path):
    """And the other end: with nothing appended the cell rejects, as published."""
    r = run(tree(tmp_path, "bare"))
    assert r.returncode == 1, r.stdout + r.stderr


# ── the fix ──────────────────────────────────────────────────────────────────

DENIALS = {
    "not": "The opcode encodings are NOT {hex} in this revision.",
    "no": "This device has no support for the encodings {hex}.",
    "never": "The command opcodes are never {hex} on this part.",
    "removed": "The opcode block {hex} is removed, not translated.",
}


@pytest.mark.parametrize("word", sorted(DENIALS))
def test_a_constant_only_inside_a_denying_sentence_does_not_ground(
        tmp_path, word):
    """THE FIX. The constants ARE in the document — appended verbatim, in the
    same place the control appends them — and the sentence around them denies
    them. Grounding on that is the review citing the sentence that refutes the
    constant as the authority for it."""
    root = append(tree(tmp_path, f"denied_{word}"),
                  DENIALS[word].format(hex=HEX))
    r = run(root)
    assert r.returncode == 1, (
        f"a constant written only inside a {word.upper()} sentence was accepted "
        f"as a verbatim quotation:\n{r.stdout}\n{r.stderr}")


def test_the_denial_is_reported_as_a_denial_and_not_as_an_absence(tmp_path):
    """ABSENT AND DENIED ARE DIFFERENT FINDINGS. A reader told the constant does
    not appear, when it appears in a sentence that refutes it, is sent to look
    in the wrong place — and this rule's whole value is telling an author where
    to look."""
    root = append(tree(tmp_path, "reported"), DENIALS["not"].format(hex=HEX))
    r = run(root)
    assert r.returncode == 1, r.stdout
    rec = json.loads((root / "phase1" / "on_pass_review"
                      / f"{STAGE}.json").read_text(encoding="utf-8")) \
        if (root / "phase1" / "on_pass_review" / f"{STAGE}.json").is_file() \
        else None
    blob = r.stdout + r.stderr + (json.dumps(rec) if rec else "")
    assert "deny" in blob.lower() or "denies" in blob.lower() \
        or "denied" in blob.lower(), (
        "the finding does not distinguish a denied constant from an absent "
        f"one:\n{blob[:2000]}")


def test_a_denial_in_a_NEIGHBOURING_sentence_does_not_retract_this_one(tmp_path):
    """The over-reach control, and the reason the reach comes from
    `_prose_polarity.sentence_scope` rather than a flat character window.

    A denial belongs to ITS OWN sentence. If it reached across a full stop into
    the next one, this rule would start refusing constants the document states
    plainly — the SILENT direction, where the extractor reports less than it
    read and no gate goes red."""
    root = append(tree(tmp_path, "neighbour"),
                  "Vendor-specific encodings are not supported.\n"
                  f"The command opcodes are {HEX}.")
    r = run(root)
    assert r.returncode == 0, (
        "a denial in the PRECEDING sentence retracted a constant this document "
        f"states plainly:\n{r.stdout}\n{r.stderr}")


def test_a_constant_stated_plainly_ELSEWHERE_survives_one_denial(tmp_path):
    """Every occurrence is tried, not just the first. One denial does not
    retract a constant the document also states plainly somewhere else, and
    stopping at the first hit would let the order of two sentences decide."""
    root = append(tree(tmp_path, "both"),
                  DENIALS["not"].format(hex=HEX)
                  + "\n\nThe command opcodes are " + HEX + ".")
    r = run(root)
    assert r.returncode == 0, (
        "a constant the document states plainly was retracted by a denial "
        f"elsewhere:\n{r.stdout}\n{r.stderr}")


def test_a_denial_in_a_NEIGHBOURING_TABLE_ROW_does_not_retract_this_row(
        tmp_path):
    """THE REGRESSION THIS REACH WAS CHOSEN FOR, pinned so it cannot come back.

    A hexadecimal constant in a specification lives in an OPCODE TABLE, and a
    table has no ". " in it. Scoped as prose, one row's polarity runs on into
    the next rows — MEASURED on the published `accept_espi` cell, whose table is

        0x00  PUT_PC   Put a posted/completion Peripheral Channel transaction
        0x04  PUT_NP   Put a non-posted Peripheral Channel transaction

    where `0x04`'s "non-" was read as a denial of `0x00`, three rows above it.
    That manufactured a contradiction on a cell this review had always accepted
    and took five shipped ACCEPT controls red at once. A neighbouring row is a
    different statement."""
    # EVERY CITED CONSTANT GETS A CLEAN ROW. The "non-" sits on a row for
    # `0x99`, which the artefact does not cite — so the only way it can reach a
    # cited constant is by running past the end of its own record.
    rows = "\n".join(f"  0x{v:02X}  OP_{v:02X}  Put a posted transaction"
                     for v in OPCODES)
    rows += "\n  0x99  OP_NP   Put a non-posted transaction"
    r = run(append(tree(tmp_path, "table"),
                   "Command Opcodes (CMD field, 8 bits)\n" + rows))
    assert r.returncode == 0, (
        "a denial in a NEIGHBOURING table row retracted this row's constant:\n"
        f"{r.stdout}\n{r.stderr}")


def test_the_denial_still_bites_INSIDE_one_table_row(tmp_path):
    """And the reach is not so narrow that it stops working: a row that denies
    its OWN constant is still a denial."""
    rows = "\n".join(f"  0x{v:02X}  OP_{v:02X}  not supported on this part"
                     for v in OPCODES)
    r = run(append(tree(tmp_path, "table_denied"),
                   "Command Opcodes (CMD field, 8 bits)\n" + rows))
    assert r.returncode == 1, (
        "a row that denies its own constant grounded it anyway:\n"
        f"{r.stdout}\n{r.stderr}")
