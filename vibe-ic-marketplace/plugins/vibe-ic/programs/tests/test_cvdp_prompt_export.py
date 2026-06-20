"""cvdp_prompt_export — the context-COMPLETE author-input export must PRESERVE a
record's `input.context` RTL (the original files the task asks the author to
modify), never strip it.

A hand-rolled `{id, prompt}`-only export drops `input.context`, leaving the
blind author to re-invent an interface the hidden harness rejects. This program
is the input-side sole-source that keeps context.

POSITIVE: a record WITH input.context → exported record carries `context` with
the exact rtl files; a from-scratch record (no context) → just `{id, prompt}`.
NEGATIVE no-leak: the GOLDEN `output.response` / `output.context` is NEVER
exported (clean-room — only the problem's own GIVEN input may pass through).
chip-AGNOSTIC: synthetic records only.
"""
import json
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent.parent / "benchmark"
sys.path.insert(0, str(HARNESS))
import cvdp_prompt_export as EX  # noqa: E402

_CTX_REC = {
    "id": "cvdp_copilot_lfsr_0007",
    "input": {
        "prompt": "Modify the 8-bit LFSR to a Fibonacci configuration.",
        "context": {"rtl/lfsr_8bit.sv": "module lfsr_8bit(input clk, output reg [7:0] q); endmodule"},
    },
    "output": {
        "response": "GOLDEN SOLUTION MUST NOT LEAK",
        "context": {"rtl/lfsr_8bit.sv": "module lfsr_8bit(...golden...); endmodule"},
    },
    "harness": {"src/test_lfsr.py": "HARNESS MUST NOT LEAK"},
}
_SCRATCH_REC = {
    "id": "cvdp_copilot_decode_firstbit_0001",
    "input": {"prompt": "Design a first-bit decoder.", "context": {}},
    "output": {"response": "golden"},
}


def _write(tmp_path, recs):
    ds = tmp_path / "ds.jsonl"
    ds.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    return ds


def test_context_record_preserves_input_context(tmp_path):
    ds = _write(tmp_path, [_CTX_REC])
    recs, n_total, n_ctx = EX.export_records(ds)
    assert n_total == 1 and n_ctx == 1
    r = recs[0]
    assert r["id"] == "cvdp_copilot_lfsr_0007"
    assert r["prompt"].startswith("Modify the 8-bit LFSR")
    assert "context" in r, "input.context RTL must be preserved, not stripped"
    assert r["context"] == {
        "rtl/lfsr_8bit.sv": "module lfsr_8bit(input clk, output reg [7:0] q); endmodule"}


def test_golden_and_harness_never_leak(tmp_path):
    """NEGATIVE no-leak: only the problem's own GIVEN input.context passes
    through — never output.response, output.context, or harness."""
    ds = _write(tmp_path, [_CTX_REC])
    recs, _, _ = EX.export_records(ds)
    blob = json.dumps(recs)
    assert "GOLDEN SOLUTION MUST NOT LEAK" not in blob
    assert "...golden..." not in blob
    assert "HARNESS MUST NOT LEAK" not in blob
    # exported record carries ONLY id, prompt, context
    assert set(recs[0].keys()) <= {"id", "prompt", "context"}


def test_scratch_record_has_no_context_key(tmp_path):
    ds = _write(tmp_path, [_SCRATCH_REC])
    recs, n_total, n_ctx = EX.export_records(ds)
    assert n_total == 1 and n_ctx == 0
    assert "context" not in recs[0]
    assert set(recs[0].keys()) == {"id", "prompt"}


def test_dict_branch_unwraps_content_wrapper_no_reblind(tmp_path):
    """COMPLETENESS symmetry (Step-2.7 LOW): a non-canonical dict value wrapped as
    {content|text: <src>} must NOT be silently dropped — the dict branch unwraps
    it like the list branch, so a GIVEN input.context file is never re-blinded."""
    rec = {
        "id": "cvdp_copilot_wrap_0001",
        "input": {
            "prompt": "Complete the module.",
            "context": {
                "rtl/a.sv": {"content": "module a; endmodule"},   # wrapper value
                "rtl/b.sv": {"text": "module b; endmodule"},       # alt wrapper key
                "rtl/c.sv": "module c; endmodule",                 # canonical str
            },
        },
        "output": {"response": "GOLDEN WRAP MUST NOT LEAK"},
    }
    ds = _write(tmp_path, [rec])
    recs, n_total, n_ctx = EX.export_records(ds)
    assert n_total == 1 and n_ctx == 1
    assert recs[0]["context"] == {
        "rtl/a.sv": "module a; endmodule",
        "rtl/b.sv": "module b; endmodule",
        "rtl/c.sv": "module c; endmodule",
    }
    # the unwrap stays input-side: golden never appears
    assert "GOLDEN WRAP MUST NOT LEAK" not in json.dumps(recs)


def test_main_writes_jsonl_and_batches(tmp_path):
    ds = _write(tmp_path, [_CTX_REC, _SCRATCH_REC])
    out = tmp_path / "prompts.jsonl"
    rc = EX.main(["--dataset", str(ds), "--out", str(out)])
    assert rc == 0
    lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
    assert len(lines) == 2
    by = {r["id"]: r for r in lines}
    assert "context" in by["cvdp_copilot_lfsr_0007"]
    assert "context" not in by["cvdp_copilot_decode_firstbit_0001"]
    # batch split
    bd = tmp_path / "batches"
    rc = EX.main(["--dataset", str(ds), "--batch-dir", str(bd), "--batch-size", "1"])
    assert rc == 0
    batches = sorted(bd.glob("batch*.jsonl"))
    assert len(batches) == 2
