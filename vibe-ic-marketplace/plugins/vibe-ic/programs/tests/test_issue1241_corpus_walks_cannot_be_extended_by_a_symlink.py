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

#: (label, walk, the document that walk recognises). One row per corpus walk on
#: this branch, so a walk added later without a row here is visibly missing.
WALKS = [
    ("head_to_head", lambda d: HH.corpus_records(d),
     {"schema": "vibeic.ppa.comparison.v2",
      "arms": [{"flow": "a", "role": "baseline"},
               {"flow": "b", "role": "subject"}]}),
    ("contract", lambda d: CC.corpus_contracts(d),
     {"schema": "vibeic.ppa.contract.v1", "run_label": "x"}),
    ("candidates", lambda d: FC.corpus_candidate_sets(d),
     {"schema": "vibeic.ppa.candidates.v1", "candidates": [],
      "required_views_by_axis": {}, "required_views": [], "limits": {},
      "allow_waivers": False}),
    ("contract_pairs",
     lambda d: PI.corpus_candidates(d, d / "__no_such_baseline__"),
     {"schema": "vibeic.ppa.contract.v1", "run_label": "x"}),
]


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
