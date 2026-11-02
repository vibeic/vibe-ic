#!/usr/bin/env python3
"""test_issue2150_expectation_authoring_schema.py

The hand-off pack carries the declaration an expectation author needs, derived
from the project's own Phase-1 root — and it is the SAME declaration the
review-time guard reads (vibe-ic#2150 F5).

WHAT WAS MEASURED, ON PRISTINE MAIN
-----------------------------------
`ic_expert_backup_pack.assemble` wrote a HARD-CODED two-entry layer contract

    {"L9": "integration specification",
     "L19": "constraints and implementation context"}

for a project whose Phase-1 root carries 24 layer documents, and an
`answer_contract` documenting `field_path` as `"optional field path"` and
nothing else. An author handed that pack can address only two of the
twenty-four layers, and can only INVENT a path out of the two prose
descriptions it was given. That is where `integration.*` on L9 and
`constraints.*` on L19 came from — and the #2127 guard then refused 46 of 46
field_paths as undeclared. The pack manufactured the authoring defect, and the
guard reported the author for it.

A guard that refuses at review time and a schema that refuses at authoring time
are the SAME declaration read at two moments. Measured on the surviving
opentitan_aes root after this landing: the contract names 24 layers instead of
2, and carries 504 declared field paths instead of none, dated with the root's
own digest.

THE AGREEMENT IS THE POINT, AND IT IS PROVEN BOTH WAYS
------------------------------------------------------
`declared_field_paths` is a candidate GENERATOR whose output is filtered by
`subtree_at` — the one resolver `field_path_status` uses. It is deliberately
not a second authority: an earlier revision of #2127 had exactly that, a
second walk collecting "the paths this document declares", and the two answers
disagreed within a day.

That sweep also caught a bug in this landing's own author-side resolver. Two
layer documents share a numeric prefix (`L8_RTL_CONSTANTS` and
`L8_TIMING_WAVEFORM`); a single-pass match that accepted either an exact name
or the `L<number>` token returned whichever sorted first and answered about the
wrong document. 502 of 504 paths agreed and both disagreements were that
collision. It now matches exactly as `resolve_layer_file` does — exact first,
token second — and the sweep is 504 of 504.

Every fixture is synthesised here from neutral parts. No design, PDK, vendor or
IP-model identifier appears anywhere in this file.

Run: python3 -m pytest programs/tests/test_issue2150_expectation_authoring_schema.py -q
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_expert_parse_track as T   # noqa: E402
import ic_expert_backup_pack as PACK    # noqa: E402
import _path_layout as _pl              # noqa: E402
import _progress_run as _pr             # noqa: E402


_INPUT_DOC = """# Block specification

The block exposes a control surface of four addressable words.
"""

_LAYERS = {
    "L1_DATASHEET": {"doc_id": "L1", "fields": {"word_count": 4}},
    "L4_REGMAP": {"doc_id": "L4",
                  "records": [{"name": "STATUS_WORD", "offset": "0x0"}]},
    "L9_INTEGRATION_SPEC": {"doc_id": "L9",
                            "fields": {"top_ports": ["clk", "rst_n"]}},
    # The prefix collision that this landing's own sweep found.
    "L8_RTL_CONSTANTS": {"doc_id": "L8C", "clock_domains": ["core"]},
    "L8_TIMING_WAVEFORM": {"doc_id": "L8T", "waveforms": ["strobe"]},
}


def _project(tmp_path, name="proj", layers=None):
    p = tmp_path / name
    (p / "input" / "docs").mkdir(parents=True)
    (p / "phase1" / "generated_docs").mkdir(parents=True)
    (p / "input" / "docs" / "spec.md").write_text(_INPUT_DOC)
    for stem, blob in (layers if layers is not None else _LAYERS).items():
        (p / "phase1" / "generated_docs" / f"{stem}.json").write_text(
            json.dumps(blob))
    return p


def _pack_dir(project: Path) -> Path:
    return _pl.report_path(project, "phase1/expert_parse_track").parent \
        / "expert_parse_track_pack"


def _run_track(project: Path):
    env = dict(os.environ)
    env["VIBE_IC_DISABLE_LLM_CONFIRM"] = "1"
    cp = _pr.run(
        [sys.executable, str(_PROGRAMS / "phase1_expert_parse_track.py"),
         str(project)], capture_output=True, text=True, env=env)
    return cp.returncode, cp.stdout, cp.stderr


def _report(project: Path):
    return json.loads(
        _pl.report_path(project, "phase1/expert_parse_track.json").read_text())


# ── the pack now describes the root it is about ────────────────────────────

def test_the_pack_names_every_emitted_layer_not_two(tmp_path):
    """RED ARM. Two hard-coded entries for a root with five layers."""
    p = _project(tmp_path)
    _run_track(p)
    h = json.loads((_pack_dir(p) / "ic_expert_agent_handoff.json").read_text())
    assert sorted(h["generated_layer_contract"]) == sorted(_LAYERS)
    # Not the two prose words an author could only invent a path from.
    assert "L9" not in h["generated_layer_contract"]
    assert "L19" not in h["generated_layer_contract"]


def test_the_pack_carries_the_schema_dated_with_the_root(tmp_path):
    p = _project(tmp_path)
    _run_track(p)
    d = _pack_dir(p)
    h = json.loads((d / "ic_expert_agent_handoff.json").read_text())
    schema = json.loads((d / "authoring_schema.json").read_text())
    assert h["authoring_schema"]["layer_count"] == len(_LAYERS)
    assert h["authoring_schema"]["declared_field_path_count"] > 0
    # DATED. An artefact that does not say which root it is about cannot be
    # told apart from one computed over a different root — #2150 F11.
    assert h["authoring_schema"]["phase1_root_digest"] == \
        T.phase1_root_identity(p)["digest"]
    assert schema["phase1_root"]["layers"] == sorted(_LAYERS)


def test_the_answer_contract_declares_field_path_and_the_split(tmp_path):
    p = _project(tmp_path)
    _run_track(p)
    h = json.loads((_pack_dir(p) / "ic_expert_agent_handoff.json").read_text())
    ac = h["answer_contract"]
    assert "authoring_schema.json" in \
        ac["shape"]["expectations"][0]["field_path"]
    # A grammar the author is never shown is a grammar nobody writes.
    assert "sub_expectations" in ac["split_shape"]["expectations"][0]
    assert "never easier to satisfy" in ac["split_shape"]["not_a_disjunction"]
    assert any("authoring_schema.json" in r for r in ac["rules"])


def test_a_caller_that_supplies_no_schema_keeps_the_root_half_unchanged(
        tmp_path):
    """No schema means no root-specific vocabulary; scope is always required."""
    h = PACK.assemble(
        prompt="Review the generated L documents against this design input.",
        iface=None, target=None, expert_skills=[],
        verify_gates=["phase1_expert_parse_track"], out_dir=tmp_path,
        output_target="l_doc_expectations.json")
    # about THIS ROOT — unchanged
    assert h["generated_layer_contract"] == {
        "L9": "integration specification",
        "L19": "constraints and implementation context"}
    assert "authoring_schema" not in h
    assert not (tmp_path / "authoring_schema.json").exists()
    assert h["answer_contract"]["shape"]["expectations"][0]["field_path"] == \
        "required: a resolvable field path"
    assert not any("authoring_schema.json" in r
                   for r in h["answer_contract"]["rules"])
    # about THE COMPARATOR — present either way
    assert "sub_expectations" in \
        h["answer_contract"]["split_shape"]["expectations"][0]


# ── the schema and the guard are ONE declaration ───────────────────────────

def test_every_declared_path_is_accepted_by_both_readers(tmp_path):
    """THE AGREEMENT, swept over the whole fixture root."""
    p = _project(tmp_path)
    schema = T.authoring_schema(p)
    gd = p / "phase1" / "generated_docs"
    checked = 0
    for stem, info in schema["layers"].items():
        blob = json.loads((gd / f"{stem}.json").read_text())
        for path in info["declared_field_paths"]:
            checked += 1
            assert T.field_path_status(blob, path, stem) == "DECLARED", \
                (stem, path)
            assert T.refuse_undeclared_field_path(schema, stem, path) is None, \
                (stem, path)
    # A sweep with an empty denominator is NOT OBSERVED, not a pass.
    assert checked > 0


def test_a_fabricated_path_is_refused_by_both_readers(tmp_path):
    """The other direction. A check that cannot fail is not a check."""
    p = _project(tmp_path)
    schema = T.authoring_schema(p)
    blob = json.loads(
        (p / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json"
         ).read_text())
    path = "integration.register_map.offsets"
    assert T.field_path_status(blob, path, "L9_INTEGRATION_SPEC") == \
        "UNDECLARED"
    why = T.refuse_undeclared_field_path(schema, "L9_INTEGRATION_SPEC", path)
    assert why is not None
    # The refusal has to be actionable: it names the layer AND what it does
    # declare, or the author has to go and read the root anyway.
    assert "L9_INTEGRATION_SPEC" in why and "top_ports" in why


def test_two_layers_sharing_a_numeric_prefix_resolve_to_themselves(tmp_path):
    """The bug this landing's own 504-path sweep found. Compare identities,
    not names: a single-pass match returned whichever sorted first."""
    p = _project(tmp_path)
    schema = T.authoring_schema(p)
    assert T.refuse_undeclared_field_path(
        schema, "L8_TIMING_WAVEFORM", "waveforms") is None
    assert T.refuse_undeclared_field_path(
        schema, "L8_RTL_CONSTANTS", "clock_domains") is None
    # PAIRED: each still refuses the OTHER's field, so the two documents are
    # genuinely distinguished rather than merged.
    assert T.refuse_undeclared_field_path(
        schema, "L8_TIMING_WAVEFORM", "clock_domains") is not None
    assert T.refuse_undeclared_field_path(
        schema, "L8_RTL_CONSTANTS", "waveforms") is not None


def test_an_omitted_field_path_is_an_unscoped_authoring_refusal(tmp_path):
    p = _project(tmp_path)
    schema = T.authoring_schema(p)
    for empty in (None, "", "   "):
        assert "UNSCOPED" in T.refuse_undeclared_field_path(
            schema, "L9_INTEGRATION_SPEC", empty)


def test_a_truncated_enumeration_refuses_nothing(tmp_path):
    """A partial list is not a proof of absence. A cap that refused on a miss
    would reject paths the layer really declares."""
    big = {f"key_{i:04d}": i for i in range(T.AUTHORING_PATHS_PER_LAYER + 50)}
    p = _project(tmp_path, layers={"L1_DATASHEET": big})
    schema = T.authoring_schema(p)
    info = schema["layers"]["L1_DATASHEET"]
    assert info["truncated"] is True
    assert len(info["declared_field_paths"]) == T.AUTHORING_PATHS_PER_LAYER
    assert info["declared_field_path_count"] > T.AUTHORING_PATHS_PER_LAYER
    # A key that exists but fell outside the cap must NOT be refused.
    late = sorted(big)[-1]
    assert late not in info["declared_field_paths"]
    assert T.refuse_undeclared_field_path(schema, "L1_DATASHEET", late) is None


def test_a_candidate_the_resolver_cannot_walk_is_dropped(tmp_path):
    """The generator is filtered by the resolver, never trusted over it. A key
    containing a dot produces a candidate path no walk can reach."""
    p = _project(tmp_path, layers={
        "L1_DATASHEET": {"plain": 1, "dotted.key": 2}})
    paths = T.authoring_schema(p)["layers"]["L1_DATASHEET"][
        "declared_field_paths"]
    assert "plain" in paths
    assert "dotted.key" not in paths


# ── could not read it is not read it and it was empty ──────────────────────

def test_a_root_with_no_l_docs_yields_no_schema_and_says_so(tmp_path):
    p = tmp_path / "bare"
    (p / "input" / "docs").mkdir(parents=True)
    (p / "input" / "docs" / "spec.md").write_text(_INPUT_DOC)
    schema = T.authoring_schema(p)
    assert schema["status"] == "NOT_MEASURED"
    assert schema["layers"] == {}
    # And it refuses nothing: refusing on a reading that did not happen would
    # be a guess wearing a guard's clothes.
    assert T.refuse_undeclared_field_path(schema, "L1_DATASHEET", "x") is None


def test_the_report_states_whether_the_author_was_handed_a_schema(tmp_path):
    p = _project(tmp_path)
    _run_track(p)
    assert _report(p)["authoring_schema_status"] == "OK"
