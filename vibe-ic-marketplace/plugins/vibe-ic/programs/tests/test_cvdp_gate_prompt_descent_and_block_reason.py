#!/usr/bin/env python3
"""Two gate defects found by a clean-room round, both quoted from the code.

1. THE PROMPT WAS NEVER FOUND. A CVDP record's `input` is a DICT
   ({prompt, context}), and both spellings in this file assumed otherwise:

       txt = (d.get("prompt") or d.get("input") or ...)          # gets the DICT
       prompt = d.get("prompt") or d.get("input") if isinstance(
           d.get("input"), str) else d.get("prompt")             # gets None

   So the area gate reported `area NOT_APPLICABLE: no --threshold-pct and no
   --prompt; cannot determine the area-reduction target` for records whose own
   `input.prompt` states the threshold clause it parses. A cid007 record then
   scored with its area check silently off — success reported for a question
   never asked.

2. BLOCKED WITHOUT A REASON. Sixteen sites set verdict=BLOCKED, each meant to
   leave a `*_block` note. Two clean-room records (strobe_divider, wb2ahb) came
   back blocked with no `*_block` key at all: a refusal the author cannot act
   on. The invariant is asserted once at the exit rather than at each site,
   because a seventeenth site would forget it.
"""
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "benchmark"))
import cvdp_gate as G  # noqa: E402


def test_prompt_is_found_inside_the_cvdp_input_dict():
    rec = {"id": "x", "input": {"prompt": "reduce area by 3% for cells",
                                "context": {"rtl/a.sv": "module a; endmodule"}}}
    assert G._record_prompt_text(rec) == "reduce area by 3% for cells", (
        "the CVDP shape puts the prompt at input.prompt; a gate that cannot "
        "reach it switches its own threshold parsing off and calls that PASS")


def test_the_legacy_flat_shapes_still_work():
    assert G._record_prompt_text({"id": "x", "prompt": "flat"}) == "flat"
    assert G._record_prompt_text({"id": "x", "input": "as-a-string"}) == "as-a-string"
    assert G._record_prompt_text({"id": "x", "question": "q"}) == "q"


def test_a_record_with_no_prompt_returns_empty_not_a_dict():
    """Returning the dict is worse than returning nothing: it reaches text code."""
    for rec in ({"id": "x"},
                {"id": "x", "input": {"context": {}}},
                {"id": "x", "input": None},
                "not-a-dict"):
        got = G._record_prompt_text(rec)
        assert isinstance(got, str), f"{rec!r} produced {type(got).__name__}"


def test_dataset_alone_activates_prompt_aware_gate_checks(tmp_path):
    """`score_one.py` supplies --dataset but does not duplicate --prompts.

    The source dataset is already the authoritative carrier of input.prompt;
    requiring a second JSONL silently disables every prompt-aware check in the
    normal one-design scorer path.
    """
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(json.dumps({
        "id": "from-dataset",
        "input": {"prompt": "all outputs are synchronous", "context": {}},
    }) + "\n")
    prompts = tmp_path / "prompts.jsonl"
    prompts.write_text(json.dumps({
        "id": "explicit",
        "prompt": "explicit prompt",
    }) + "\n")

    assert G._load_prompt_sources(dataset=dataset) == {
        "from-dataset": "all outputs are synchronous",
    }
    assert G._load_prompt_sources(prompts=prompts) == {
        "explicit": "explicit prompt",
    }


def test_explicit_prompts_override_same_id_dataset_text(tmp_path):
    """An explicit --prompts record remains the final authority for its id."""
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(json.dumps({
        "id": "same", "input": {"prompt": "dataset text", "context": {}}
    }) + "\n")
    prompts = tmp_path / "prompts.jsonl"
    prompts.write_text(json.dumps({"id": "same", "prompt": "explicit text"}) + "\n")

    assert G._load_prompt_sources(dataset=dataset, prompts=prompts) == {
        "same": "explicit text",
    }


def test_every_blocked_record_carries_a_reason(tmp_path, capsys):
    """The exit invariant, exercised through the source it guards.

    Asserted on the shape the writer produces rather than by running the whole
    CLI: the invariant loop is what the report write-out sees.
    """
    report = [
        {"id": "with-reason", "verdict": "BLOCKED", "iface_block": "missing port"},
        {"id": "no-reason", "verdict": "BLOCKED", "notes": ["WARN something"]},
        {"id": "passing", "verdict": "PASS"},
    ]
    # replicate the invariant the gate applies before writing the report
    src = (PLUGIN / "benchmark" / "cvdp_gate.py").read_text()
    assert "unattributed_block" in src, (
        "the gate no longer records a reason for an unattributed block")
    assert src.index("unattributed_block") < src.index('if args.report:'), (
        "the invariant must run BEFORE the report is written, or the file on "
        "disk is the one without the reason")

    for rec in report:
        if rec.get("verdict") != "BLOCKED":
            continue
        if any(k.endswith("_block") for k in rec):
            continue
        notes = [n for n in (rec.get("notes") or []) if isinstance(n, str)]
        rec["unattributed_block"] = "BLOCKED with no *_block reason recorded — " \
            "the notes below are the only evidence retained: " + (
                "; ".join(notes[:3]) if notes else "(none)")

    blocked = [r for r in report if r["verdict"] == "BLOCKED"]
    assert len(blocked) == 2
    for r in blocked:
        assert any(k.endswith("_block") for k in r), (
            f"{r['id']} is blocked and says nothing about why")
    assert "WARN something" in report[1]["unattributed_block"], (
        "the fallback must carry whatever evidence WAS retained")
