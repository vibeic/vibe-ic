#!/usr/bin/env python3
"""The PDK gate could not read the L-doc schema Phase 1 actually emits.

MEASURED DEFECT
===============
`declared_pdk_is_the_pdk_used_check.declared_target()` looked up
``pdk_target`` / ``pdk`` at the JSON TOP LEVEL. Schema-v2 L-docs are

    {"doc_id": "L19", "doc_name": "L19_CONSTRAINTS_PDK",
     "applicability": "APPLICABLE",
     "fields": {"pdk_target": "..."},          <-- the payload
     "schema_version": 2, ...}

so the value the gate needs lives under ``fields``. Reading only the top level
made the gate blind to the canonical shape, and the failure was **silent and
inverted**: on a run that declared a target AND loaded exactly the matching
library, `declared_target()` returned ``(None, None)`` and the gate exited 1
with

    declared_pdk_is_the_pdk_used: FAIL — this run loaded cell libraries but
    declares no PDK target, so it cannot show that it implemented against the
    intended process

The one gate that exists to prove the process was the intended one reported
that the design had named no process at all. Its own docstring says rc=2 is
"reserved for the one case where the question genuinely cannot be asked: the
design declares no target" — that case was being manufactured by the reader.

FIX / BLAST RADIUS
==================
Top level is tried FIRST, so any flat producer keeps its exact precedence;
``fields`` is a pure fallback. No run that resolves a target today can change
verdict — only runs that resolved NOTHING can now resolve something.

chip-, PDK- and vendor-AGNOSTIC: every identifier in this file is a synthetic
placeholder.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import declared_pdk_is_the_pdk_used_check as C  # noqa: E402

L19 = "phase1/merged_docs/L19_CONSTRAINTS_PDK.json"


def _write(root: pathlib.Path, rel: str, obj) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj))


# ------------------------------------------------------------------ the fix --
def test_canonical_schema_v2_l_doc_is_read(tmp_path):
    """The shape phase 1 actually emits: payload under `fields`."""
    _write(tmp_path, L19, {
        "doc_id": "L19", "doc_name": "L19_CONSTRAINTS_PDK",
        "applicability": "APPLICABLE",
        "fields": {"pdk_target": "placeholder_process_a"},
        "schema_version": 2,
    })
    target, source = C.declared_target(tmp_path)
    assert target == "placeholder_process_a", (target, source)
    assert source and "fields." in source, source


def test_nested_alternate_key_is_read(tmp_path):
    """`pdk` is the other accepted key name; it must work nested too."""
    _write(tmp_path, L19, {"fields": {"pdk": "placeholder_process_b"},
                           "schema_version": 2})
    assert C.declared_target(tmp_path)[0] == "placeholder_process_b"


# ------------------------------------------------------- negative controls ----
def test_flat_shape_still_works(tmp_path):
    """Back-compat: a flat producer is unchanged."""
    _write(tmp_path, L19, {"pdk_target": "placeholder_process_c"})
    target, source = C.declared_target(tmp_path)
    assert target == "placeholder_process_c"
    assert source and "fields." not in source, source


def test_the_tree_s_shared_accessor_decides_precedence(tmp_path):
    """Re-anchored (#739). This asserted that TOP LEVEL wins over `fields`.

    That precedence was invented in #736's own rationale — "so no currently-
    passing run can change verdict" — not taken from the tree. `l_doc_fields`
    in `l_doc_consumer_contract` is the tree's single definition of "get the
    payload from either shape", every other L-doc consumer uses it, and it
    merges with `fields` OVERRIDING top level. Having this one gate disagree is
    the private-copy drift the shared accessor exists to prevent.

    MEASURED before changing it, because a precedence rule is only worth
    arguing about if it is observable: across all 195 tracked
    `L19_CONSTRAINTS_PDK.json`, a target key appears in BOTH scopes **0 times**.
    No published run can tell the two rules apart.
    """
    from l_doc_consumer_contract import l_doc_fields
    doc = {"pdk_target": "flat_value", "fields": {"pdk_target": "nested_value"}}
    assert l_doc_fields(doc)["pdk_target"] == "nested_value", (
        "the gate must follow the tree's accessor, not a local rule")
    assert l_doc_fields({"pdk_target": "flat_value"})["pdk_target"] == "flat_value", (
        "a flat producer with no envelope still reads correctly")

def test_absent_target_is_still_absent(tmp_path):
    """A genuinely target-less doc must STILL return None — this fix must not
    invent a target, or it would destroy the rc=2 'cannot be asked' tier."""
    _write(tmp_path, L19, {"doc_id": "L19", "fields": {"notes": "no target"},
                           "schema_version": 2})
    assert C.declared_target(tmp_path) == (None, None)


def test_non_string_and_blank_are_not_targets(tmp_path):
    """A dict/number/empty string under the key is not a declaration."""
    _write(tmp_path, L19, {"fields": {"pdk_target": "   "}})
    assert C.declared_target(tmp_path) == (None, None)
    _write(tmp_path, L19, {"fields": {"pdk_target": {"name": "x"}}})
    assert C.declared_target(tmp_path) == (None, None)


def test_a_non_dict_document_does_not_crash(tmp_path):
    _write(tmp_path, L19, ["not", "a", "dict"])
    assert C.declared_target(tmp_path) == (None, None)
