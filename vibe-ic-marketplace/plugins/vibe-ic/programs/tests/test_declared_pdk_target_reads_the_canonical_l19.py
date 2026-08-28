#!/usr/bin/env python3
"""The PDK gate could not read the L19 Phase 1 actually writes, or find it.

MEASURED DEFECT
===============
`declared_pdk_is_the_pdk_used_check.declared_target()` returned ``(None, None)``
on **every one** of the 106 tracked projects that carry a
``phase1/generated_docs/L19_CONSTRAINTS_PDK.json`` — including the 20 that
declare a non-empty target. Four of those runs had loaded cell libraries and
were therefore told:

    declared_pdk_is_the_pdk_used: FAIL — this run loaded cell libraries but
    declares no PDK target, so it cannot show that it implemented against the
    intended process

The one gate that exists to prove the process was the intended one reported
that a design which names a process had named none. The remaining 102 fell to
rc=2 NOT CHECKED, the tier the gate's own docstring reserves for "the design
declares no target at all" — a state the reader was manufacturing.

TWO INDEPENDENT CAUSES, AND EITHER ONE ALONE STILL READS NOTHING
================================================================
LEVEL — the payload of a schema-v2 L-doc lives under ``fields``. The producer
is explicit: ``phase1_doc_one_shot_runner._emit_l19_to_l23_skeletons`` does
``skeleton["fields"]["pdk_target"] = _pdk_tgt``. Corpus: ``pdk_target`` occurs
0 times at the top level of an L19 and 106 times under ``fields``.

PATH — the probe table reached ``phase1/merged_docs/`` and ``phase1/``. The
canonical emit location is ``phase1/generated_docs/`` (``_write_l_doc``,
``_path_layout.generated_docs_dir``). Corpus: 106 L19 documents in
``generated_docs/``, 1 in ``merged_docs/``, 0 directly under ``phase1/``.

So a fields-only fix moves 1 of 107 projects. That is why the two are tested
apart below: `test_canonical_location_is_probed_at_all` fails on a FLAT
document, with the envelope removed from the question entirely.

WHY THE FIXTURES ARE NOT HAND-BUILT
===================================
A hand-built dict proves only that the reader agrees with the test author. The
shape under test here is produced two ways that do not depend on this file:

  * `test_the_producers_own_document_is_readable` builds the document by
    CALLING THE PRODUCER — ``phase1_post_process.emit_l_doc_skeleton("L19")``
    — and populates it exactly as the runner does, then writes it through
    ``_path_layout.generated_docs_dir``. Nothing about the shape or the
    location is asserted by this test; both are taken from the emitter.
  * `test_every_committed_l19_that_declares_a_target_is_readable` replays the
    tracked corpus: every committed ``generated_docs/L19_*.json`` that carries
    a non-empty declaration is copied VERBATIM into a run directory and must
    resolve. It asserts a property of documents this repo already ships.

Chip-, PDK- and vendor-AGNOSTIC: this file writes no process, foundry or
design identifier. The only literal target string is a synthetic placeholder;
the corpus test discovers whatever the committed documents happen to say.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import declared_pdk_is_the_pdk_used_check as GATE     # noqa: E402
import _path_layout as _pl                            # noqa: E402
import phase1_post_process as _pp                     # noqa: E402

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PLACEHOLDER = "placeholder_process_a"


def _canonical_l19_path(run: pathlib.Path) -> pathlib.Path:
    """Where Phase 1 writes L19 — asked of the layout module, not hardcoded."""
    return _pl.generated_docs_dir(run) / "L19_CONSTRAINTS_PDK.json"


def _write(p: pathlib.Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2), encoding="utf-8")


# ───────────────────────────────────────────── the producer's own document ──
def test_the_producers_own_document_is_readable(tmp_path):
    """The exact object Phase 1 emits, built by calling Phase 1's emitter.

    Fails before the fix on BOTH counts at once: wrong directory, and the
    value nested under `fields`.
    """
    skeleton = _pp.emit_l_doc_skeleton("L19")
    assert isinstance(skeleton.get("fields"), dict), (
        "the producer no longer emits a `fields` envelope for L19 — this "
        "test's premise, and the gate's reader, both need re-deriving")
    assert "pdk_target" in skeleton["fields"], (
        "the L19 skeleton template no longer carries `pdk_target`")
    # Exactly what `_emit_l19_to_l23_skeletons` does when extraction found a
    # target.
    skeleton["fields"]["pdk_target"] = PLACEHOLDER
    skeleton["extraction_status"] = "PARTIALLY_EXTRACTED"
    _write(_canonical_l19_path(tmp_path), skeleton)

    target, source = GATE.declared_target(tmp_path)
    assert target == PLACEHOLDER, (target, source)
    assert source and "generated_docs" in source, source
    assert source.endswith("fields.pdk_target"), source


def test_canonical_location_is_probed_at_all(tmp_path):
    """The PATH defect, isolated from the envelope defect.

    The document here is FLAT, so an envelope-aware reader that still looks
    only in `merged_docs/` and `phase1/` fails this test. It is the control
    that separates the two causes.
    """
    _write(_canonical_l19_path(tmp_path), {"pdk_target": PLACEHOLDER})
    assert GATE.declared_target(tmp_path)[0] == PLACEHOLDER


def test_alternate_key_spelling_is_read_nested(tmp_path):
    """`pdk` is the other accepted spelling; it must work in the envelope."""
    _write(_canonical_l19_path(tmp_path),
           {"doc_id": "L19", "fields": {"pdk": PLACEHOLDER},
            "schema_version": 2})
    assert GATE.declared_target(tmp_path)[0] == PLACEHOLDER


# ──────────────────────────────────────────────────── the tracked corpus ────
def _committed_declarations():
    """Every committed generated_docs L19 that declares a non-empty target."""
    root = _PROGRAMS
    for _ in range(8):                       # walk up to the repo root
        if (root / ".git").exists():
            break
        root = root.parent
    corpus = root / "benchmark-data"
    if not corpus.is_dir():
        return []
    out = []
    for p in sorted(corpus.rglob("phase1/generated_docs/L19_*.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        fields = doc.get("fields") if isinstance(doc.get("fields"), dict) else {}
        for k in ("pdk_target", "pdk"):
            for scope in (doc, fields):
                v = scope.get(k)
                if isinstance(v, str) and v.strip():
                    out.append((p, v.strip()))
                    break
            else:
                continue
            break
    return out


def test_every_committed_l19_that_declares_a_target_is_readable(tmp_path):
    """Replay the tracked corpus. No shape is invented by this test."""
    declarations = _committed_declarations()
    if not declarations:
        pytest.skip("benchmark-data/ not present — corpus replay unavailable")
    unreadable = []
    for i, (src, expected) in enumerate(declarations):
        run = tmp_path / f"run{i}"
        dst = _canonical_l19_path(run)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)           # verbatim, not reconstructed
        got, _source = GATE.declared_target(run)
        if got != expected:
            unreadable.append((str(src), expected, got))
    assert not unreadable, (
        f"{len(unreadable)} of {len(declarations)} committed L19 documents "
        f"declare a PDK target the gate cannot read: {unreadable[:5]}")


# ────────────────────────────────────────────────── precedence / non-regress ─
def test_pre_existing_records_keep_precedence(tmp_path):
    """A record that resolved before must still win, so no run that resolves
    a target today can resolve a DIFFERENT one after this change."""
    _write(tmp_path / "phase1" / "pdk_staging_read.json",
           {"adopted_pdk_target": "record_wins"})
    _write(tmp_path / "phase1" / "merged_docs" / "L19_CONSTRAINTS_PDK.json",
           {"pdk_target": "merged_second"})
    _write(_canonical_l19_path(tmp_path), {"fields": {"pdk_target": "canonical_third"}})
    assert GATE.declared_target(tmp_path)[0] == "record_wins"

    (tmp_path / "phase1" / "pdk_staging_read.json").unlink()
    assert GATE.declared_target(tmp_path)[0] == "merged_second"


def test_a_null_envelope_does_not_shadow_a_root_value(tmp_path):
    """A merged document — root payload, `fields` extras — must still resolve.

    The shared accessor gives the envelope precedence, which is right when the
    key is populated in both. A `null` there is not a declaration and must not
    hide one at the root.
    """
    _write(_canonical_l19_path(tmp_path),
           {"pdk_target": PLACEHOLDER, "fields": {"pdk_target": None}})
    target, source = GATE.declared_target(tmp_path)
    assert target == PLACEHOLDER, (target, source)
    assert source and not source.endswith("fields.pdk_target"), source


def test_a_populated_envelope_wins_over_the_root(tmp_path):
    """Control for the line above: when BOTH carry a value, the payload wins."""
    _write(_canonical_l19_path(tmp_path),
           {"pdk_target": "root_value", "fields": {"pdk_target": "payload_value"}})
    target, source = GATE.declared_target(tmp_path)
    assert target == "payload_value", (target, source)
    assert source.endswith("fields.pdk_target"), source


def test_a_target_less_document_is_still_target_less(tmp_path):
    """The rc=2 'the question cannot be asked' tier must survive.

    An emitter skeleton whose extraction found nothing carries
    `fields.pdk_target = None`. That must NOT become a declaration.
    """
    skeleton = _pp.emit_l_doc_skeleton("L19")
    _write(_canonical_l19_path(tmp_path), skeleton)
    assert GATE.declared_target(tmp_path) == (None, None)


def test_blank_and_non_string_are_not_declarations(tmp_path):
    _write(_canonical_l19_path(tmp_path), {"fields": {"pdk_target": "   "}})
    assert GATE.declared_target(tmp_path) == (None, None)
    _write(_canonical_l19_path(tmp_path),
           {"fields": {"pdk_target": {"name": "x"}}})
    assert GATE.declared_target(tmp_path) == (None, None)


def test_a_non_object_document_does_not_crash(tmp_path):
    _write(_canonical_l19_path(tmp_path), ["not", "an", "object"])
    assert GATE.declared_target(tmp_path) == (None, None)


# ─────────────────────── what the repaired read then reaches, end to end ────
# Both behaviours below were UNREACHABLE before the read was repaired —
# `declared_target` resolved nothing, so no run ever got past the no-target
# branch. They are pinned here because the repair is what exposes them, and
# without them the repair's only measurable effect on 16 tracked projects
# would have been a verdict that misstates the evidence.

def _gate(run: pathlib.Path):
    """rc and the JSON record, for one run directory."""
    gate = _PROGRAMS / "declared_pdk_is_the_pdk_used_check.py"
    rec = run / "rec.json"
    p = _pr.run([sys.executable, str(gate), str(run), "--json", str(rec)],
                       capture_output=True, text=True)
    return p.returncode, (json.loads(rec.read_text()) if rec.is_file() else {}), \
        p.stdout + p.stderr


def test_an_explicit_not_applicable_is_not_a_declaration(tmp_path):
    """An IP that writes down "no target" is in the rc=2 state, not a FAIL.

    12 of the 28 non-empty declarations in the tracked corpus are of this form.
    Read as targets they FAIL with "cannot show which process it used", about a
    design that says it implements none.
    """
    _write(_canonical_l19_path(tmp_path),
           {"doc_id": "L19", "fields": {"pdk_target": "N/A (not a tapeout)"},
            "schema_version": 2})
    rc, rec, out = _gate(tmp_path)
    assert rc == 2, out
    assert rec["verdict"] == "NOT CHECKED"
    assert rec["declared_target"] is None
    # The written value is disclosed, not discarded.
    assert rec["declared_not_applicable"] == "N/A (not a tapeout)"
    assert "generated_docs" in (rec["declared_not_applicable_source"] or "")


def test_not_applicable_that_still_names_a_process_is_a_declaration(tmp_path):
    """Control: the absence vocabulary must not swallow a real target."""
    _write(_canonical_l19_path(tmp_path),
           {"fields": {"pdk_target": "N/A for the analog block; digital is sky130A"}})
    target, _ = GATE.declared_target(tmp_path)
    assert target and not GATE.declares_no_target(target)


def test_a_named_declaration_with_no_load_is_not_accused(tmp_path):
    """REFUSED, for the true reason — vibe-ic#1002 moved the rc, not the point.

    With no library loaded, every named process in the declaration is trivially
    "uncorroborated", so the contradiction branch would fire on every run that
    names a process and has not run a tool yet — printing "no loaded library
    carries that identity" above `loaded : 0`. That is the unsupported
    accusation the no-load branch exists to remove, and it still is.

    What changed is the VERDICT this state earns. It asserted rc 1 through
    #710; a state whose own output says "nothing to compare" is a zero
    denominator, and the house rule (`gate_zero_denominator_refuses_check`) is
    that a zero denominator REFUSES. Every other assertion below is unchanged.
    """
    _write(_canonical_l19_path(tmp_path), {"fields": {"pdk_target": "sky130A"}})
    rc, rec, out = _gate(tmp_path)
    assert rc == 2, out
    assert rec["verdict"] == "NOT CHECKED"
    assert rec["no_library_load_recorded"] is True
    assert rec.get("contradicting_named_pdks", []) == [], rec
    assert "no loaded library carries that identity" not in out, out


def test_a_real_contradiction_still_fires(tmp_path):
    """Control: with libraries actually loaded, the contradiction branch stands."""
    _write(_canonical_l19_path(tmp_path), {"fields": {"pdk_target": "sky130A"}})
    logs = tmp_path / "phase3"
    logs.mkdir(parents=True, exist_ok=True)
    logs.joinpath("pnr.log").write_text(
        "[INFO ODB-0227] LEF file: /pdks/othernode_fd_sc_hd.lef\n",
        encoding="utf-8")
    rc, rec, out = _gate(tmp_path)
    assert rc == 1, out
    assert rec["contradicting_named_pdks"], rec
    assert rec["libraries_loaded"], rec
    assert rec.get("no_library_load_recorded") is not True


def test_a_non_l_doc_record_is_not_unwrapped(tmp_path):
    """`input/project.json` is not an L-doc. Its read must not change.

    A `fields` key there means whatever that file means by it, and this gate
    must not start reading into it.
    """
    _write(tmp_path / "input" / "project.json",
           {"fields": {"pdk": "not_an_l_doc_payload"}})
    assert GATE.declared_target(tmp_path) == (None, None)
    _write(tmp_path / "input" / "project.json", {"pdk": PLACEHOLDER})
    assert GATE.declared_target(tmp_path)[0] == PLACEHOLDER
