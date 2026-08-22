"""#593 cause 2 — a document that IS a verification plan contributed nothing.

`phase1_doc_input_completeness_check` reported 24 uncaptured tokens on the
checklist input — `SPEC_COMPLETE`, `FPV_MAIN_ASSERTIONS_PROVEN`,
`SIM_SMOKE_TEST_PASSING`, `PRE_VERIFIED_SUB_MODULES_V1..V3`, … The ingester read
the checklist's prose and never its milestone IDENTIFIERS.

THE SCOPING DECISION IS THE DOCUMENT'S, NOT THE EMITTER'S. #593 asks whether
some of these are "pure project-tracking metadata with no design meaning" and
says the answer must be RECORDED rather than silently waived. It does not have
to be guessed — the table states a `Type` per row:

    Type          | Item                 | Resolution | Note/Collaterals
    --------------|----------------------|------------|-----------------
    Documentation | [SPEC_COMPLETE][]    | Done       | [AES Design Spec](…)
    RTL           | [CLKRST_CONNECTED][] | Done       |

so each milestone carries the document's own `type` and `resolution`, and a
consumer that wants only design-bearing items filters on it. Nothing is dropped.

MEASURED on the shipped checklist: 103 milestones, across 12 of the document's
own type categories and 8 stages (D1..V3), and every one of the identifiers the
issue names is captured.

CORPUS SAFETY, which #593 makes an explicit acceptance item — "must not
spuriously emit on non-checklist docs": over 390 tracked input docs, exactly 3
emit, and all three are the same checklist file under different run
directories. Zero non-checklist documents emit.

RE-MEASURED after the published results moved to vibeic/benchmark-data. The 390
counted the per-RUN copies of each input doc as well as the input tree itself,
and the run trees are gone from this checkout. The retained design input — the
originals, of which those were copies — is 55 documents, and exactly ONE of
them emits: `ic/opentitan_aes/input/docs/aes_checklist.md`, with the same 103
milestones. Both halves of the acceptance item therefore still hold, on a
smaller and non-duplicated population, and both are still measured here rather
than skipped: see the note above `_tracked_input_docs`.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


EM = _load("l22_checklist_milestone_emit")

_CHK = """## Design Checklist

### D1

Type          | Item                           | Resolution  | Note/Collaterals
--------------|-----------------------         |-------------|------------------
Documentation | [SPEC_COMPLETE][]              | Done        | [Spec](../README.md)
RTL           | [CLKRST_CONNECTED][]           | Done        |
RTL           | [PHYSICAL_MACROS_DEFINED_80][] | N/A         |

### V1

Type          | Item                     | Resolution | Note/Collaterals
--------------|--------------------------|------------|------------------
Testbench     | [SIM_SMOKE_TEST_PASSING][] | Done     |
"""


# ── the shape ───────────────────────────────────────────────────────────────
def test_the_identifiers_are_lifted():
    got = [m["id"] for m in EM.extract_milestones(_CHK)]
    assert got == ["SPEC_COMPLETE", "CLKRST_CONNECTED",
                   "PHYSICAL_MACROS_DEFINED_80", "SIM_SMOKE_TEST_PASSING"], got


def test_the_documents_own_classification_is_recorded_not_judged():
    """The scoping decision #593 requires to be recorded. `type` is read off
    the table; nothing here decides what counts as design content."""
    by = {m["id"]: m for m in EM.extract_milestones(_CHK)}
    assert by["SPEC_COMPLETE"]["type"] == "Documentation"
    assert by["CLKRST_CONNECTED"]["type"] == "RTL"
    assert by["SIM_SMOKE_TEST_PASSING"]["type"] == "Testbench"


def test_the_resolution_and_stage_travel_with_it():
    by = {m["id"]: m for m in EM.extract_milestones(_CHK)}
    assert by["PHYSICAL_MACROS_DEFINED_80"]["resolution"] == "N/A"
    assert by["SPEC_COMPLETE"]["stage"] == "D1"
    assert by["SIM_SMOKE_TEST_PASSING"]["stage"] == "V1"


def test_outer_pipes_are_optional():
    """The real tables have none, and requiring them is why this shape had no
    path. The bordered form must still work."""
    t = ("| Item | Resolution |\n|------|------------|\n"
         "| [SPEC_COMPLETE][] | Done |\n")
    assert [m["id"] for m in EM.extract_milestones(t)] == ["SPEC_COMPLETE"]


def test_a_bare_or_backticked_identifier_is_accepted():
    t = ("Item | Resolution\n-----|-----------\n"
         "`LINT_SETUP` | Done\nFPV_MAIN_ASSERTIONS_PROVEN | Done\n")
    assert [m["id"] for m in EM.extract_milestones(t)] == [
        "LINT_SETUP", "FPV_MAIN_ASSERTIONS_PROVEN"]


# ── it must not fire on anything else ───────────────────────────────────────
def test_a_register_map_is_not_a_checklist():
    """LOAD-BEARING, and #593's explicit acceptance item. A register map has
    Name/Offset and no resolution column."""
    t = ("| Name | Offset | Length |\n|:-----|:-------|-------:|\n"
         "| CTRL_SHADOWED | 0x74 | 4 |\n")
    assert EM.extract_milestones(t) == []


def test_a_pin_list_is_not_a_checklist():
    t = ("| Signal | Direction | Width |\n|:-------|:----------|------:|\n"
         "| CLK_I | input | 1 |\n")
    assert EM.extract_milestones(t) == []


def test_a_table_with_a_resolution_column_but_no_item_column_is_refused():
    t = ("| Bug | Resolution |\n|:----|:-----------|\n| FOO_BAR | Done |\n")
    assert EM.extract_milestones(t) == []


def test_an_item_column_WITHOUT_a_resolution_column_is_refused():
    """The guard the other negatives do not reach. A bill of materials, a
    glossary, a table of contents — all have an `Item` column and no
    resolution, and a checklist is what has BOTH. Found by mutation: dropping
    the resolution requirement left every other negative test passing, because
    each of them was being rejected for a different reason."""
    t = ("Item | Quantity | Supplier\n-----|----------|---------\n"
         "FOO_BAR | 12 | ACME\n")
    assert EM.extract_milestones(t) == []


def test_prose_that_merely_mentions_a_milestone_is_not_lifted():
    assert EM.extract_milestones(
        "The SPEC_COMPLETE milestone was reached in Q3.\n") == []


# ── the write-back ──────────────────────────────────────────────────────────
def _project(tmp_path, chk=_CHK):
    (tmp_path / "phase1" / "input_doc").mkdir(parents=True)
    (tmp_path / "phase1" / "input_doc" / "x_checklist.txt").write_text(
        chk, encoding="utf-8")
    g = tmp_path / "phase1" / "generated_docs"
    g.mkdir(parents=True)
    (g / "L22_VERIFICATION_PLAN.json").write_text(
        json.dumps({"fields": {"coverage_goals": []}}), encoding="utf-8")
    return tmp_path


def test_the_milestones_reach_l22(tmp_path):
    p = _project(tmp_path)
    rep = EM.run(p)
    assert rep["status"] == "OK" and rep["emitted_count"] == 4, rep
    d = json.loads((p / "phase1/generated_docs/L22_VERIFICATION_PLAN.json")
                   .read_text())
    assert [m["id"] for m in d["fields"]["checklist_milestones"]][0] \
        == "SPEC_COMPLETE"


def test_re_running_adds_nothing(tmp_path):
    """A layer that grows every time the emitter runs is not a record."""
    p = _project(tmp_path)
    EM.run(p)
    rep = EM.run(p)
    assert rep["emitted_count"] == 0
    d = json.loads((p / "phase1/generated_docs/L22_VERIFICATION_PLAN.json")
                   .read_text())
    assert len(d["fields"]["checklist_milestones"]) == 4


def test_no_checklist_means_nothing_written(tmp_path):
    """REFUSES rather than guesses, like its `_post_emit_*` neighbours."""
    p = _project(tmp_path, chk="just some prose about verification\n")
    rep = EM.run(p)
    assert rep["status"] == "NOTHING_TO_EMIT" and rep["emitted_count"] == 0


def test_a_missing_l22_is_a_skip_not_a_crash(tmp_path):
    (tmp_path / "phase1" / "input_doc").mkdir(parents=True)
    assert EM.run(tmp_path)["status"] == "SKIPPED"


# ── wired into the runner ───────────────────────────────────────────────────
def test_the_post_emit_hook_is_called():
    src = (_PROGRAMS / "phase1_doc_one_shot_runner.py").read_text(
        encoding="utf-8")
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    assert "_post_emit_l22_checklist_milestones(project)" in code, (
        "the emitter is defined and the runner never calls it")


# ── the shipped document ────────────────────────────────────────────────────
#
# WHERE THE SUBJECT LIVES NOW. Both tests below were written against
# `benchmark-data/ic/opentitan_aes/phase1/input_doc/aes_checklist.txt` — the
# copy of the checklist that a RUN tree carries. Run trees are published cells
# now and live in vibeic/benchmark-data, so that path is gone from this
# checkout. The checklist itself is NOT gone: it is DESIGN INPUT, it is exactly
# what `benchmark-data/` still holds, and it is tracked here at
# `ic/opentitan_aes/input/docs/aes_checklist.md`.
#
# So neither of these needs the published corpus and neither is marked with it.
# They are re-pointed at the retained input tree, where the same 103 milestones
# and the same "exactly one document emits" result are measurable in a plain
# checkout — which is a strictly better place for them than a corpus that may
# not be present: this acceptance item of #593 can now be measured on every
# run rather than on the runs that happen to have cells.
_INPUT_ROOT = _REPO / "benchmark-data"
_CHECKLIST = _INPUT_ROOT / "ic/opentitan_aes/input/docs/aes_checklist.md"


def _tracked_input_docs():
    """Every tracked design-input document, wherever the layout puts it.

    Two globs, not one, and both on purpose: `ic/<IC>/input/**` is where the
    design input is tracked today, and `**/phase1/input_doc/*` is the run-tree
    copy — absent here, present in a checkout that still carries cells or in a
    clone of the published corpus. Whichever exists is measured; the claim
    ("every document that emits is a checklist") is the same either way.
    """
    seen = {}
    for pat in ("ic/*/input/**/*", "**/phase1/input_doc/*"):
        for p in _INPUT_ROOT.glob(pat):
            if p.is_file() and p.suffix.lower() in (".txt", ".md"):
                seen[p] = True
    return sorted(seen)


def test_the_real_checklist_yields_every_identifier_the_issue_names():
    doc = _CHECKLIST
    if not doc.is_file():
        pytest.skip("the tracked checklist is absent")
    got = {m["id"] for m in EM.extract_milestones(doc.read_text(errors="replace"))}
    for want in ("SPEC_COMPLETE", "DESIGN_SPEC_REVIEWED",
                 "FPV_MAIN_ASSERTIONS_PROVEN", "SIM_SMOKE_TEST_PASSING",
                 "PRE_VERIFIED_SUB_MODULES_V1", "PRE_VERIFIED_SUB_MODULES_V2",
                 "PRE_VERIFIED_SUB_MODULES_V3", "SEC_CM_DOCUMENTED"):
        assert want in got, f"{want} is still uncaptured"
    assert len(got) >= 90, f"only {len(got)} milestones lifted"


def test_it_emits_on_the_checklist_and_on_nothing_else():
    """#593's acceptance, measured over the tracked input docs rather than
    asserted. Every emitting document must be a checklist."""
    docs = _tracked_input_docs()
    if not docs:
        # The same condition the sibling test above already skips on, and the
        # same reason: a shipped-plugin install carries these tests without
        # `benchmark-data/` at all. NOT the published-corpus skip — the design
        # input is retained in this repository, so a checkout that has the
        # repository and no documents is a change, and the floor below fails
        # on it rather than skipping.
        pytest.skip("the tracked input documents are absent")
    emitting = []
    for p in docs:
        try:
            if EM.extract_milestones(p.read_text(errors="replace")):
                emitting.append(p.name)
        except OSError:
            continue
    assert len(docs) >= 40, (
        f"only {len(docs)} input document(s) scanned; the negative half of "
        f"this acceptance item is measured over the population, and a "
        f"population that collapsed makes 'nothing else emits' vacuous")
    assert emitting, "the emitter fires on nothing at all"
    assert all("checklist" in n.lower() for n in emitting), (
        f"emitted on non-checklist input(s): "
        f"{sorted({n for n in emitting if 'checklist' not in n.lower()})}")
