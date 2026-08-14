#!/usr/bin/env python3
"""The hygiene subset rule (vibe-ic#1498) must block as readily as it passes.

Every test here is in-process — no subprocess is spawned, so there is no inner
bound to exceed the harness's `--timeout=180`.

The two WORKED EXAMPLES the rule exists for are `test_worked_example_*`, and
they are deliberately the same base record read twice, so the only difference
between "blocked" and "passed" is the thing under test.

NDA: every gate label and corpus name below is invented. No foundry, SKU,
process node or chip codename appears in this file — the real corpus labels
carry PDK-derived directory names, which is exactly why the fixtures do not
copy them.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_PROG = Path(__file__).resolve().parents[1] / "hygiene_finding_delta.py"
_spec = importlib.util.spec_from_file_location("hygiene_finding_delta", _PROG)
mod = importlib.util.module_from_spec(_spec)
sys.modules["hygiene_finding_delta"] = mod
_spec.loader.exec_module(mod)


def gate(label, state="PASS", corpus="", item=None, items=None):
    g = {"label": label, "state": state, "seconds": 1}
    if corpus:
        g["corpus"] = corpus
        g["corpus_item"] = item if item is not None else 1
        g["corpus_items"] = items if items is not None else 1
    return g


def doc(gates, shard=None, corpora=None, listed_only=False):
    return {
        "listed_only": listed_only,
        "declared": len(gates),
        "shard": shard,
        "corpora": corpora if corpora is not None else [],
        "undisclosed_loops": [],
        "seconds": 10,
        "gates": gates,
    }


def write(tmp_path, name, d):
    p = tmp_path / name
    p.write_text(json.dumps(d), encoding="utf-8")
    return p


def run(tmp_path, base, cand, base_host="h1", cand_host="h1"):
    b = write(tmp_path, "base.json", base)
    c = write(tmp_path, "cand.json", cand)
    return mod.main(["--base", str(b), "--candidate", str(c),
                     "--base-host", base_host, "--candidate-host", cand_host])


# --- THE BASE: a reference that is itself red, which is the whole premise ----
# Two findings, mirroring what #1498 measured on clean main: one plain FAIL and
# one host-dependent verdict.
def _base_gates():
    return [
        gate("anchor tag points at the anchor version", "FAIL"),
        gate("probed gates give a host-independent verdict", "FAIL"),
        gate("source guard", "PASS"),
        gate("tracked-tree scan", "PASS"),
    ]


# ---------------------------------------------------------------------------
# WORKED EXAMPLE 1 — a batch carrying ONLY the base's own findings must PASS.
# ---------------------------------------------------------------------------
def test_worked_example_batch_carrying_only_the_bases_findings_passes(tmp_path, capsys):
    base = doc(_base_gates())
    cand = doc(_base_gates())
    assert run(tmp_path, base, cand) == mod.RC_OK
    out = capsys.readouterr().out
    assert "no finding introduced" in out
    # The carried findings must be NAMED, not merely counted away. A reader of
    # this log has to be able to see what was tolerated and why.
    assert "carried from the base" in out
    assert "anchor tag points at the anchor version" in out


# ---------------------------------------------------------------------------
# WORKED EXAMPLE 2 — a batch that introduces a NEW finding must be BLOCKED.
# ---------------------------------------------------------------------------
def test_worked_example_batch_introducing_a_finding_is_blocked(tmp_path, capsys):
    base = doc(_base_gates())
    cand = doc(_base_gates() + [])
    # same declared set, one gate flips PASS -> FAIL
    cand["gates"] = [dict(g) for g in _base_gates()]
    cand["gates"][2]["state"] = "FAIL"
    assert run(tmp_path, base, cand) == mod.RC_INTRODUCED
    out = capsys.readouterr().out
    assert "INTRODUCED" in out
    assert "source guard" in out


def test_a_cleared_finding_is_not_an_introduction(tmp_path, capsys):
    """Fixing one of the base's findings must not be mistaken for adding one."""
    base = doc(_base_gates())
    g = [dict(x) for x in _base_gates()]
    g[0]["state"] = "PASS"
    assert run(tmp_path, base, doc(g)) == mod.RC_OK
    assert "CLEARED" in capsys.readouterr().out


# --- "could not check" must never difference to "clean" ---------------------
def test_not_checked_on_one_side_only_refuses(tmp_path, capsys):
    """The two runs disagree about whether the gate RAN. Not a subset result."""
    base = doc(_base_gates())
    g = [dict(x) for x in _base_gates()]
    g[0]["state"] = "NOT_CHECKED"
    assert run(tmp_path, base, doc(g)) == mod.RC_REFUSED
    out = capsys.readouterr().out
    assert "REFUSED" in out and "BLOCKS" in out


def test_not_checked_cannot_launder_a_base_finding_into_clean(tmp_path):
    """The dangerous direction: base FAILs, candidate could not look.

    If NOT_CHECKED differenced to clean this would read as `cleared` and pass.
    """
    base = doc(_base_gates())
    g = [dict(x) for x in _base_gates()]
    g[1]["state"] = "NOT_CHECKED"
    assert run(tmp_path, base, doc(g)) == mod.RC_REFUSED


def test_not_checked_on_both_sides_is_disclosed_and_blocks_nothing(tmp_path, capsys):
    b = [dict(x) for x in _base_gates()]
    c = [dict(x) for x in _base_gates()]
    b[2]["state"] = c[2]["state"] = "NOT_CHECKED"
    assert run(tmp_path, doc(b), doc(c)) == mod.RC_OK
    assert "NOT CHECKED on BOTH sides" in capsys.readouterr().out


# --- same host --------------------------------------------------------------
def test_a_different_host_refuses(tmp_path, capsys):
    base = doc(_base_gates())
    assert run(tmp_path, base, doc(_base_gates()),
               base_host="h1", cand_host="h2") == mod.RC_REFUSED
    assert "host" in capsys.readouterr().out.lower()


def test_an_empty_host_refuses(tmp_path):
    assert run(tmp_path, doc(_base_gates()), doc(_base_gates()),
               base_host="  ", cand_host="  ") == mod.RC_REFUSED


# --- an empty result is not a zero -----------------------------------------
def test_a_missing_base_record_refuses(tmp_path, capsys):
    c = write(tmp_path, "cand.json", doc(_base_gates()))
    rc = mod.main(["--base", str(tmp_path / "nope.json"), "--candidate", str(c),
                   "--base-host", "h1", "--candidate-host", "h1"])
    assert rc == mod.RC_REFUSED
    assert "not an empty one" in capsys.readouterr().out


def test_an_empty_gate_array_refuses(tmp_path):
    assert run(tmp_path, doc([]), doc(_base_gates())) == mod.RC_REFUSED


def test_a_list_only_record_refuses(tmp_path, capsys):
    """`--list` says what WOULD run. Nothing executed, so nothing was found."""
    base = doc(_base_gates(), listed_only=True)
    for g in base["gates"]:
        g["state"] = "LISTED"
    assert run(tmp_path, base, doc(_base_gates())) == mod.RC_REFUSED
    assert "--list" in capsys.readouterr().out


def test_a_failed_corpus_producer_refuses(tmp_path, capsys):
    """An unknown fraction of a corpus is not a clean fraction of it."""
    corpora = [{"name": "cells", "items": 3, "gates": 3,
                "expansion": "PRODUCER_FAILED"}]
    base = doc(_base_gates(), corpora=corpora)
    assert run(tmp_path, base, doc(_base_gates(), corpora=corpora)) == mod.RC_REFUSED
    assert "unknown fraction" in capsys.readouterr().out


def test_a_differing_shard_split_refuses(tmp_path):
    assert run(tmp_path, doc(_base_gates(), shard="0/2"),
               doc(_base_gates(), shard="1/2")) == mod.RC_REFUSED


def test_a_gate_present_on_only_one_side_refuses(tmp_path, capsys):
    """Different denominators: `absent` cannot be read as `clean`."""
    cand = doc(_base_gates() + [gate("a gate the base never declared", "PASS")])
    assert run(tmp_path, doc(_base_gates()), cand) == mod.RC_REFUSED
    assert "DIFFERENT gate sets" in capsys.readouterr().out


# --- the normalisation ------------------------------------------------------
def test_the_ordinal_of_a_loop_item_is_not_part_of_the_identity(tmp_path):
    """Adding one item renumbers the tail; that is not 20 new findings.

    The corpus_item index and the corpus_items count both move when a corpus
    grows. If either were in the identity, every later item would present as
    introduced.
    """
    b = [gate("inner FAILs reach the verdict (cell-a)", "FAIL", "cells", 1, 2),
         gate("inner FAILs reach the verdict (cell-b)", "PASS", "cells", 2, 2)]
    c = [gate("inner FAILs reach the verdict (cell-a)", "FAIL", "cells", 2, 3),
         gate("inner FAILs reach the verdict (cell-b)", "PASS", "cells", 3, 3)]
    assert run(tmp_path, doc(b), doc(c)) == mod.RC_OK


def test_whitespace_only_differences_are_the_same_finding(tmp_path):
    b = [gate("a  gate   with irregular spacing", "FAIL")]
    c = [gate("a gate with irregular spacing", "FAIL")]
    assert run(tmp_path, doc(b), doc(c)) == mod.RC_OK


def test_two_cells_differing_only_in_digits_stay_DIFFERENT_findings(tmp_path, capsys):
    """The reason the normalisation does not mask digits.

    Real loop labels are built from a directory basename, and those names
    differ from one another only in their version digits. A digit-masking
    normalisation would merge them, and a batch that broke a SECOND cell would
    land carrying a finding the base never had.
    """
    b = [gate("inner FAILs reach the verdict (run-v1-a)", "FAIL", "cells", 1, 2),
         gate("inner FAILs reach the verdict (run-v2-a)", "PASS", "cells", 2, 2)]
    c = [gate("inner FAILs reach the verdict (run-v1-a)", "FAIL", "cells", 1, 2),
         gate("inner FAILs reach the verdict (run-v2-a)", "FAIL", "cells", 2, 2)]
    assert run(tmp_path, doc(b), doc(c)) == mod.RC_INTRODUCED
    assert "run-v2-a" in capsys.readouterr().out


def test_normalisation_collapse_refuses_rather_than_merging(tmp_path, capsys):
    """If normalisation ever DID merge two labels, that is a refusal.

    The guarantee is asserted on live data every run rather than argued for
    once, so it cannot rot as the normalisation changes.
    """
    b = [gate("same after  normalising", "FAIL"),
         gate("same after normalising", "PASS")]
    assert run(tmp_path, doc(b), doc(b)) == mod.RC_REFUSED
    assert "NORMALISATION COLLAPSE" in capsys.readouterr().out


def test_wrote_corpus_is_a_finding_and_is_not_folded_into_fail(tmp_path, capsys):
    """A gate that changed the tree every later gate reads must block."""
    g = [dict(x) for x in _base_gates()]
    g[2]["state"] = "WROTE_CORPUS"
    assert run(tmp_path, doc(_base_gates()), doc(g)) == mod.RC_INTRODUCED
    assert "WROTE_CORPUS" in capsys.readouterr().out


def test_a_state_change_between_two_finding_kinds_is_introduced(tmp_path):
    """FAIL on the base, WROTE_CORPUS here: not the same finding, so it blocks."""
    b = [dict(x) for x in _base_gates()]
    c = [dict(x) for x in _base_gates()]
    c[0]["state"] = "WROTE_CORPUS"
    assert run(tmp_path, doc(b), doc(c)) == mod.RC_INTRODUCED
