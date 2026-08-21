#!/usr/bin/env python3
"""ORGANIC #680 — cvdp_gate emits the AUTHOR'S format verbatim: a JSON code-dict
on a SINGLE-FILE problem gates PASS (the gate extracts + compiles clean RTL)
but ELAB-fails at scoring because `local_import` writes the raw JSON as the .sv.

現象 (round-1 v1.0.x CVDP nonagentic, 302): `extract_code` accepts json_dict /
fenced / bare payloads, extracts RTL, compiles it (PASS), then writes the
author's ORIGINAL completion VERBATIM into responses.jsonl. The official harness
`model_helpers.parse_model_response` for SINGLE-FILE problems
(`determine_schema` → `no_schema=True`, 297/302 of nonagentic problems) only
runs `extract_code_blocks`: with NO ```fence present it FALLS BACK to
`res.strip()`, writing the ENTIRE completion as the RTL file. So a JSON
code-dict (`{"code":[{"rtl/x.sv":"module …"}]}`, no fence) sent to a single-file
problem → the gate extracts RTL + compiles PASS + emits the JSON verbatim, but
local_import writes `{"code": [{…` as the RTL → `iverilog` syntax error line 1 →
scorer ELAB_ERROR. Measured 26/302 clean-room problems hit this (~41% of the
residual fails).

根因 (verified against the harness parser as documented in cvdp_gate.py): for a
single-file problem `determine_schema` returns no_schema=True and
`parse_model_response` on a raw-JSON completion returns the raw JSON as
direct_text (uncompilable); the SAME RTL fenced/bare returns clean `module …`.

FIX (chip-AGNOSTIC): the gate NORMALIZES its emit to the format the harness
decodes for THIS problem's schema — never echoes the author's format.
  • SINGLE-FILE (no prompt JSON-schema directive AND ≤1 RTL file in the dict) →
    emit BARE de-fenced RTL (the exact bytes the gate compiled) so the harness's
    extract_code_blocks no-fence `res.strip()` fallback writes clean RTL.
  • MULTI-FILE (prompt carries an explicit JSON `{"code":[` schema directive,
    OR the dict spans >1 RTL file) → keep the JSON code-dict (the harness
    decodes it under the schema).
The single-vs-multi decision mirrors determine_schema's signal structurally
(prompt-prose / RTL-file-count), with a NEGATION guard so "single-file, NO json
schema" is correctly read as no-schema.

POSITIVE: a single-file JSON-dict completion → emit is bare/fenced RTL (not raw
JSON), decodes + compiles verbatim (the scorer's res.strip() path).
§4.05 NEGATIVE no-leak:
  (a) a MULTI-FILE (>1 RTL file) JSON-dict STILL emits JSON;
  (b) a prompt with an explicit JSON `{"code":[` schema directive keeps JSON
      even for a single RTL file;
  (c) an already-fenced single-file completion stays decodable (de-fenced);
  (d) a bare-RTL single-file completion stays bare/unchanged;
  (e) a "NO json schema" prompt does NOT force JSON (negation guard).

ACCEPTANCE END-STATE (issue 驗收): the emit for a single-file JSON-dict
completion does NOT start with '{'.

chip-AGNOSTIC: synthetic drafts/prompts only; pure schema/format structure; no
chip/vendor/SKU literal. iverilog/yosys-gated (drive cvdp_gate.py directly when
absent).
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
HARNESS = PLUGIN / "benchmark"
sys.path.insert(0, str(HARNESS))
import cvdp_gate as G  # noqa: E402

_HAS_IVERILOG = shutil.which("iverilog") is not None
_HAS_YOSYS = shutil.which("yosys") is not None
_HAS_TOOLS = _HAS_IVERILOG and _HAS_YOSYS


# ── fixtures (shaped like the 現象) ──────────────────────────────────────────

# single-RTL-file JSON code-dict, no fence — the exact 現象 shape.
SINGLE_JSON = json.dumps({"code": [{"rtl/foo.sv":
    "module foo(input a, output y); assign y = ~a; endmodule"}]})

# >1 RTL file → genuinely multi-file deliverable.
MULTI_JSON = json.dumps({"code": [
    {"rtl/foo.sv": "module foo(input a, output y); assign y = ~a; endmodule"},
    {"rtl/bar.sv": "module bar(input b, output z); assign z = b; endmodule"}]})

# single-file, but the PROMPT explicitly carries the JSON `{"code":[` schema.
SCHEMA_PROMPT = ('Implement module foo. Respond with a JSON object of the form '
                 '{"code": [{"rtl/foo.sv": "..."}]}.')
# single-file, prompt says NO json schema — must stay single-file (negation).
NOSCHEMA_PROMPT = ('Design module foo, save to rtl/foo.sv '
                   '(single-file, no JSON schema)')

FENCED = ("```verilog\n"
          "module foo(input a, output y);\n  assign y = ~a;\nendmodule\n```\n")
BARE = "module foo(input a, output y);\n  assign y = ~a;\nendmodule\n"


def _wd(tmp_path: Path) -> Path:
    d = tmp_path / "wd"
    d.mkdir(exist_ok=True)
    return d


def _verbatim_compiles(completion: str, tmp_path: Path) -> bool:
    """Write the completion VERBATIM to a .sv exactly as the official CVDP
    scorer's res.strip() no-fence fallback does, then compile it."""
    sv = tmp_path / "verbatim.sv"
    sv.write_text(completion)
    r = subprocess.run(["iverilog", "-g2012", "-o", str(tmp_path / "a.out"),
                        str(sv)], capture_output=True, text=True)
    return r.returncode == 0


def _run_main(tmp_path, recs, prompts=None):
    b = tmp_path / "drafts.jsonl"
    b.write_text("".join(json.dumps(r) + "\n" for r in recs))
    out = tmp_path / "responses.jsonl"
    argv = ["--batch", str(b), "--out", str(out),
            "--report", str(tmp_path / "rep.json")]
    if prompts is not None:
        p = tmp_path / "prompts.jsonl"
        p.write_text("".join(
            json.dumps({"id": k, "prompt": v}) + "\n"
            for k, v in prompts.items()))
        argv += ["--prompts", str(p)]
    G.main(argv)
    emitted = {}
    if out.is_file():
        for ln in out.read_text().splitlines():
            if ln.strip():
                d = json.loads(ln)
                emitted[d["id"]] = d["completion"]
    return emitted


# ── ACCEPTANCE END-STATE (issue 驗收) ────────────────────────────────────────

@pytest.mark.skipif(not _HAS_TOOLS, reason="iverilog/yosys not on this host")
def test_acceptance_single_file_json_emit_not_raw_json(tmp_path):
    """驗收 END-STATE: a single-file JSON-dict completion + a single-file prompt
    → the emitted completion does NOT start with '{' (was AssertionError: the
    gate emitted raw JSON for a single-file problem)."""
    emitted = _run_main(
        tmp_path,
        [{"id": "cvdp_copilot_fmt_0001", "completion": SINGLE_JSON}],
        prompts={"cvdp_copilot_fmt_0001": NOSCHEMA_PROMPT})
    c = emitted["cvdp_copilot_fmt_0001"]
    assert not c.lstrip().startswith("{"), (
        f"BUG: gate emitted raw JSON for single-file: {c[:40]!r}")
    assert "module foo" in c
    assert _verbatim_compiles(c, tmp_path)


# ── POSITIVE: single-file JSON dict normalizes (no prompt → file-count signal) ─

@pytest.mark.skipif(not _HAS_TOOLS, reason="iverilog/yosys not on this host")
def test_single_file_json_dict_normalized_via_gate_record(tmp_path):
    ok, out_rec, entry = G.gate_record(
        {"id": "p1", "completion": SINGLE_JSON}, _wd(tmp_path))
    assert ok and entry["verdict"] == "PASS"
    c = out_rec["completion"]
    assert not c.lstrip().startswith("{")
    assert "module foo" in c and "```" not in c
    assert _verbatim_compiles(c, tmp_path)
    assert "bare RTL" in entry.get("emit_format", "")


@pytest.mark.skipif(not _HAS_TOOLS, reason="iverilog/yosys not on this host")
def test_single_file_json_dict_normalized_via_main_no_prompts(tmp_path):
    """Default (no --prompts): a single-RTL-file JSON dict normalizes by the
    file-count signal alone — the safe 297/302 default."""
    emitted = _run_main(tmp_path, [{"id": "p1", "completion": SINGLE_JSON}])
    assert not emitted["p1"].lstrip().startswith("{")
    assert _verbatim_compiles(emitted["p1"], tmp_path)


# ── §4.05 NEGATIVE no-leak ───────────────────────────────────────────────────

@pytest.mark.skipif(not _HAS_TOOLS, reason="iverilog/yosys not on this host")
def test_NOLEAK_multifile_json_stays_json(tmp_path):
    """(a) a >1-RTL-file JSON dict is a real multi-file deliverable → stays the
    JSON shape (the harness decodes it under its schema)."""
    ok, out_rec, entry = G.gate_record(
        {"id": "pm", "completion": MULTI_JSON}, _wd(tmp_path))
    assert ok and entry["verdict"] == "PASS"
    c = out_rec["completion"]
    files = G.json_code_files(c)
    assert files is not None and len(
        [k for k in files if k.endswith(".sv")]) == 2
    assert "json_dict" in entry.get("emit_format", "")


@pytest.mark.skipif(not _HAS_TOOLS, reason="iverilog/yosys not on this host")
def test_NOLEAK_schema_prompt_keeps_json_for_single_file(tmp_path):
    """(b) a single-RTL-file JSON dict whose PROMPT carries an explicit JSON
    `{"code":[` schema directive stays JSON (the harness parses under schema)."""
    ok, out_rec, entry = G.gate_record(
        {"id": "ps", "completion": SINGLE_JSON}, _wd(tmp_path),
        prompt_text=SCHEMA_PROMPT)
    assert ok and entry["verdict"] == "PASS"
    assert G.json_code_files(out_rec["completion"]) is not None
    assert "json_dict" in entry.get("emit_format", "")


@pytest.mark.skipif(not _HAS_TOOLS, reason="iverilog/yosys not on this host")
def test_NOLEAK_fenced_single_file_stays_decodable(tmp_path):
    """(c) an already-fenced single-file completion stays decodable (de-fenced
    by the existing #626 path — the #680 change must not touch it)."""
    ok, out_rec, entry = G.gate_record(
        {"id": "pf", "completion": FENCED}, _wd(tmp_path))
    assert ok and entry["verdict"] == "PASS"
    c = out_rec["completion"]
    assert "```" not in c and "module foo" in c
    assert _verbatim_compiles(c, tmp_path)


@pytest.mark.skipif(not _HAS_TOOLS, reason="iverilog/yosys not on this host")
def test_NOLEAK_bare_single_file_stays_bare(tmp_path):
    """(d) a bare-RTL single-file completion stays bare/unchanged."""
    ok, out_rec, entry = G.gate_record(
        {"id": "pb", "completion": BARE}, _wd(tmp_path))
    assert ok and entry["verdict"] == "PASS"
    assert out_rec["completion"] == BARE          # hygiene-clean, untouched
    assert _verbatim_compiles(out_rec["completion"], tmp_path)


def test_NOLEAK_noschema_negation_does_not_force_json(tmp_path):
    """(e) the schema-directive heuristic must NOT fire on a NEGATED mention:
    "single-file, no JSON schema" → single-file (no schema)."""
    assert G.prompt_requires_json_schema(NOSCHEMA_PROMPT) is False
    assert G.prompt_requires_json_schema(SCHEMA_PROMPT) is True
    # incidental / negated mentions stay single-file
    assert G.prompt_requires_json_schema(
        "Implement module bar; do not respond in json") is False
    assert G.prompt_requires_json_schema(
        "Plain SystemVerilog FSM, no schema") is False
    # the literal envelope and a positive directive are multi-file
    assert G.prompt_requires_json_schema('{"code": [{"rtl/a.sv": "x"}]}') is True
    assert G.prompt_requires_json_schema(
        "Return your answer as a JSON object with the code field") is True


def test_NOLEAK_json_dict_is_multifile_signal():
    """Unit-pin the single-vs-multi decision: >1 RTL file OR a schema prompt =
    multi; ≤1 RTL file with no schema directive = single."""
    one = {"rtl/a.sv": "module a; endmodule"}
    two = {"rtl/a.sv": "module a; endmodule",
           "rtl/b.sv": "module b; endmodule"}
    assert G.json_dict_is_multifile(one) is False
    assert G.json_dict_is_multifile(two) is True
    assert G.json_dict_is_multifile(one, prompt_text=SCHEMA_PROMPT) is True
    assert G.json_dict_is_multifile(one, prompt_text=NOSCHEMA_PROMPT) is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
