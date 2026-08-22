#!/usr/bin/env python3
"""What a corpus walk does with a symlink — MEASURED, then pinned.

WHY (vibe-ic#1241, Appendix C question 19: "was it tested against ... path/symlink
traversal ...?"). Three corpus walks landed on this branch — `corpus_records`,
`corpus_contracts`, `corpus_candidate_sets` and `corpus_candidates` — and each
one globs `**/*.json` under a directory and READS every match. The whole doctrine
of these gates is that a count is stated over a NAMED population, so "which files
are in the population" is not a detail; it is the claim.

MEASURED on CPython 3.10.12 before this file was written:

    a symlinked DIRECTORY inside the corpus   NOT traversed
    a symlinked FILE inside the corpus        followed and counted

Both arms are pinned below, and they are pinned for opposite reasons.

THE DIRECTORY ARM IS A GUARANTEE. `pathlib`'s `**` does not recurse into
symlinked directories, so a corpus cannot be silently extended to documents
living somewhere else — the population stays the tree the gate named. That is
load-bearing and it is not this code's own doing, which is exactly why it is
pinned: CPython 3.13 made this configurable (`Path.glob(recurse_symlinks=...)`)
and a future interpreter or a future rewrite that reaches for `os.walk` could
change it without anyone noticing. If this test goes red, the population these
gates report is no longer the population they searched.

THE FILE ARM IS A DISCLOSURE, NOT A DEFENCE. A symlinked file IS counted, and
that is deliberate: the alternative is dropping it, and "I could not follow it"
becoming "it was never filed" is the exact substitution every gate in this family
exists to refuse. A symlink inside a corpus is a file inside that corpus, git
tracks it explicitly, and the gate prints the path it read. What a reader must
know is that its BYTES may come from outside the tree the corpus names, which is
why it is written down here rather than left to be discovered.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
sys.path.insert(0, str(PROGRAMS))


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, PROGRAMS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


HH = _load("_sym_hh", "ppa_head_to_head_check.py")
CC = _load("_sym_cc", "ppa_contract_check.py")
FC = _load("_sym_fc", "ppa_feasibility_check.py")
PI = _load("_sym_pi", "ppa_problem_integrity_check.py")
MC = _load("_sym_mc", "ppa_measurement_check.py")
PC = _load("_sym_pc", "ppa_pareto_check.py")
AB = _load("_sym_ab", "ppa_ablation_check.py")

import _ppa_corpus as corpus_seam  # noqa: E402  the shared walk


def _seam_walk(predicate):
    """The walk THREE of these gates now share, reached the way they reach it.

    `corpus_contracts`, `corpus_candidate_sets` and `corpus_candidates` were
    replaced by a SELECTION PREDICATE handed to `_ppa_corpus.collect`, and this
    table went on calling the old names -- so it raised AttributeError on three
    of its four rows and the symlink property was held for one walk instead of
    four. THE WALK ITSELF IS STILL PROGRAM CODE: `collect` is the seam and the
    predicate is the gate's own, so nothing about what is under test moves into
    this file. That is what makes this an ADAPTER and not the vacuous shim the
    problem-integrity guard needed instead of one.
    """
    return lambda d: [path for path, _ in corpus_seam.collect(d, predicate).records]


#: (label, walk, the document that walk recognises). One row per corpus walk on
#: this branch, so a walk added later without a row here is visibly missing.
WALKS = [
    ("head_to_head", lambda d: HH.corpus_records(d),
     {"schema": "vibeic.ppa.comparison.v2",
      "arms": [{"flow": "a", "role": "baseline"},
               {"flow": "b", "role": "subject"}]}),
    ("contract", _seam_walk(CC.is_contract),
     {"schema": "vibeic.ppa.contract.v1", "run_label": "x"}),
    ("candidates", _seam_walk(FC.is_candidate_set),
     {"schema": "vibeic.ppa.candidates.v1", "candidates": [],
      "required_views_by_axis": {}, "required_views": [], "limits": {},
      "allow_waivers": False}),
    ("contract_pairs", _seam_walk(PI.is_contract),
     {"schema": "vibeic.ppa.contract.v1", "run_label": "x"}),
    ("coverage_bundles", _seam_walk(MC.is_bundle),
     {"schema": 'vibeic.ppa.metric_bundle.v1', "records": [], "expected": []}),
    ("pareto_candidate_sets", _seam_walk(PC.is_candidate_set),
     {"schema": "vibeic.ppa.candidates.v1", "candidates": [],
      "required_views_by_axis": {}, "required_views": [], "limits": {},
      "allow_waivers": False}),
    # `ppa_ablation_check` reaches the same seam and selects on the DECLARED
    # schema alone, so the recogniser document needs no other key.
    ("ablation", _seam_walk(AB.is_ablation),
     {"schema": "vibeic.ppa.ablation.v1"}),
]

#: The program each row is about, so the table's completeness can be MEASURED
#: against the programs directory rather than asserted by the comment above it.
COVERS = {
    "head_to_head": "ppa_head_to_head_check.py",
    "contract": "ppa_contract_check.py",
    "candidates": "ppa_feasibility_check.py",
    "contract_pairs": "ppa_problem_integrity_check.py",
    "coverage_bundles": "ppa_measurement_check.py",
    "pareto_candidate_sets": "ppa_pareto_check.py",
    "ablation": "ppa_ablation_check.py",
}


def _programs_that_walk_a_corpus():
    """Every ppa_* program that opens a corpus, read off the source.

    A program walks a corpus if it reaches the shared seam (`_ppa_corpus`) or
    carries its own walk (`corpus_records`). Derived here rather than listed,
    because a LIST is the thing that goes quietly out of date -- which is
    exactly what happened to WALKS.
    """
    out = set()
    for f in sorted(PROGRAMS.glob("ppa_*.py")):
        src = f.read_text(encoding="utf-8", errors="replace")
        if "_ppa_corpus" in src or "\ndef corpus_records" in src:
            out.add(f.name)
    return out


def _scene(tmp_path, doc):
    """A corpus holding one real document, one symlinked directory that holds a
    document, and one symlinked file pointing at a document outside."""
    outside = tmp_path / "outside"
    outside.mkdir(parents=True)
    (outside / "smuggled.json").write_text(json.dumps(doc), encoding="utf-8")
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "real.json").write_text(json.dumps(doc), encoding="utf-8")
    os.symlink(outside, corpus / "linkdir")
    os.symlink(outside / "smuggled.json", corpus / "linkfile.json")
    return corpus


@pytest.mark.parametrize("label,walk,doc", WALKS, ids=[w[0] for w in WALKS])
def test_a_symlinked_directory_does_not_extend_the_population(
        tmp_path, label, walk, doc):
    """THE GUARANTEE. A document outside the corpus must not become a member of
    it by linking its directory in — the population must stay the tree named."""
    found = {p.name for p in walk(_scene(tmp_path, doc))}
    assert "smuggled.json" not in found, (
        f"{label}: a symlinked directory extended the population to a document "
        f"outside the corpus; the count is no longer over the tree it names")


@pytest.mark.parametrize("label,walk,doc", WALKS, ids=[w[0] for w in WALKS])
def test_a_symlinked_file_is_counted_and_not_silently_dropped(
        tmp_path, label, walk, doc):
    """THE DISCLOSURE. Dropping it would be 'I could not follow it' becoming
    'it was never filed', which is the substitution these gates exist to refuse.
    It is counted; its bytes may live outside the corpus; that is written down."""
    found = {p.name for p in walk(_scene(tmp_path, doc))}
    assert found == {"real.json", "linkfile.json"}, (
        f"{label}: expected the real document and the symlinked one, got {found}")


def test_the_real_document_is_found_at_all(tmp_path):
    """The positive control. Without it every assertion above would still pass
    over a walk that had stopped finding anything."""
    for label, walk, doc in WALKS:
        found = {p.name for p in walk(_scene(tmp_path / label, doc))}
        assert "real.json" in found, f"{label} found no ordinary document"


def test_the_table_covers_every_program_that_walks_a_corpus():
    """THE TABLE'S OWN BLIND SPOT, and it had one.

    The comment above WALKS said "one row per corpus walk on this branch, so a
    walk added later without a row here is visibly missing". It was a COMMENT.
    Two walks were added later -- `ppa_pareto_check --corpus` and
    `ppa_measurement_check --corpus`, both reaching `_ppa_corpus.collect` -- and
    nothing was visible about it: the file went on holding the symlink property
    for FOUR of SIX walks while reading as though it held it for all of them.

    MEASURED off the programs directory, not restated here, because a list is
    the thing that goes out of date and a derived set is not.
    """
    walk_programs = _programs_that_walk_a_corpus()
    covered = {COVERS[label] for label, _, _ in WALKS}
    missing = sorted(walk_programs - covered)
    assert not missing, (
        "a ppa_* program opens a corpus and no row in WALKS holds the symlink "
        "property for it:\n  " + "\n  ".join(missing))
    stale = sorted(covered - walk_programs)
    assert not stale, (
        "WALKS names a program that no longer walks a corpus; a row that "
        "outlives its subject is the one that gets believed:\n  "
        + "\n  ".join(stale))
    assert walk_programs, "no ppa_* program walks a corpus — the detector has gone dark"
