"""Regression for ORGANIC #626 — cvdp_gate.gate_record() fenced branch emits a
markdown-fenced completion VERBATIM (parse de-fences, emit did NOT).

現象 (round-1 v1.0.0 CVDP nonagentic no_commercial, 302): the gate's fenced
branch extracts the code-fence BODY, hygiene-fixes it, COMPILES the de-fenced
code (verdict PASS, "compile clean"), but then EMITTED the completion by
splicing each fixed body back into the ORIGINAL fenced text — so the fence
MARKERS (```verilog ... ```) were RETAINED. The official scorer writes the
emitted completion VERBATIM to rtl/<id>.sv, so line 1 is "```verilog" →
iverilog reads the backtick as a macro directive → ":1: macro verilog
undefined" + ":1: syntax error" → the problem ELAB_ERRORs at scoring even
though the gate proved the de-fenced code compiles clean. 8 of 9 ELAB_ERROR
problems had a fence-led completion the gate marked PASS (~2.6% silently
broken). Worse, the emit was GATED on a hygiene diff, so an unchanged fenced
draft (the dominant shape) kept the fence verbatim.

Fix: the fenced branch EMITS `combined` — the de-fenced concatenation of the
hygiene-fixed fence bodies, i.e. the EXACT bytes the gate compiled — never the
original text with fence markers retained, and UNCONDITIONALLY (not gated on a
hygiene diff).

The load-bearing INVARIANT (issue): the bytes the gate COMPILED == the bytes
the scorer compiles from the emitted completion. This test asserts the end
state by writing the emitted completion VERBATIM to a .sv (exactly as the
official scorer does) and compiling it — it must compile clean, while the
ORIGINAL fenced completion written verbatim does NOT (anchoring the 現象).

NEGATIVE no-leak (issue-specified, must preserve):
  (a) a JSON-dict completion still emits in the official json_code_files shape;
  (b) a bare (fence-less) code completion passes through unchanged;
  (c) a multi-fence completion emits ALL module bodies (concatenated);
  (d) a doc_only completion stays doc_only.

chip-AGNOSTIC: synthetic drafts only; pure code-fence/compile structure.
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
from _sim_tools import NEEDS_SIM  # noqa: E402

_HAS_IVERILOG = shutil.which("iverilog") is not None


# ── defect-artifact fixtures (shaped like the 現象) ──────────────────────────

# The overwhelmingly common LLM output form: a single ```verilog fence.
FENCED = ("```verilog\n"
          "module foo(input a, output b);\n"
          "  assign b = a;\n"
          "endmodule\n"
          "```\n")

# Prose ```text fence THEN the code fence — prose written verbatim to .sv would
# also break it; the emit must drop everything but the compiled code body.
PROSE_THEN_FENCED = ("```text\nHere is my analysis.\n```\n\n"
                     "```verilog\n"
                     "module bar(input c, output d);\n"
                     "  assign d = ~c;\n"
                     "endmodule\n"
                     "```\n")

# Two verilog fences (multiple modules) — no-leak (c): ALL bodies must survive.
TWO_FENCES = ("First:\n\n```verilog\n"
              "module f1(input a, output y); assign y = a; endmodule\n```\n\n"
              "Second:\n\n```verilog\n"
              "module f2(input clk, output reg q);\n"
              "  always @(posedge clk) q <= ~q;\nendmodule\n```\n")

# Bare (fence-less) compilable code — no-leak (b).
BARE = ("module baz(input e, output f);\n  assign f = e;\nendmodule\n")

# Official JSON code-dict shape — no-leak (a).
JSON_DICT = json.dumps({
    "code": [{"rtl/qux.sv": "module qux(input g, output h); assign h = g; "
                            "endmodule\n"}]})

DOC_ONLY = ("The bug is in the handshake: ready must be deasserted while "
            "busy. No code change is required to the datapath itself.")


def _wd(tmp_path: Path) -> Path:
    """A created workdir. gate_record's bare/doc_only branches call
    hygiene_fix directly on the workdir (they assume the caller — normally
    G.main — already created it), so a direct gate_record() call must too."""
    d = tmp_path / "wd"
    d.mkdir(exist_ok=True)
    return d


def _verbatim_compiles(completion: str, tmp_path: Path) -> bool:
    """Write the completion VERBATIM to rtl/<id>.sv exactly as the official
    CVDP scorer does, then compile it. Returns True iff iverilog exits 0.
    This is the END-STATE proxy for 'the scorer compiles what we emit'."""
    sv = tmp_path / "verbatim.sv"
    sv.write_text(completion)
    r = subprocess.run(["iverilog", "-g2012", "-o", str(tmp_path / "a.out"),
                        str(sv)], capture_output=True, text=True)
    return r.returncode == 0


# ── (1) the fix: emitted completion is de-fenced AND compiles verbatim ───────

@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
@NEEDS_SIM
def test_fenced_emit_is_defenced_and_compiles_verbatim(tmp_path):
    ok, out_rec, entry = G.gate_record({"id": "p1", "completion": FENCED},
                                       _wd(tmp_path))
    assert ok and entry["verdict"] == "PASS"
    emitted = out_rec["completion"]
    # de-fenced: no markdown fence markers survive into the emitted completion
    assert "```" not in emitted, f"fence marker retained: {emitted!r}"
    # INVARIANT: the bytes the scorer writes verbatim compile clean
    assert _verbatim_compiles(emitted, tmp_path), (
        "emitted completion does not compile when written verbatim — the "
        "scorer would ELAB_ERROR")


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
def test_original_fenced_completion_would_elab_error_verbatim(tmp_path):
    """Anchors the 現象: the ORIGINAL fenced completion, written verbatim to a
    .sv (what the scorer does), does NOT compile — line 1 ```verilog is a
    backtick macro directive → syntax error. This is the defect the fix
    removes; if THIS ever starts compiling the fixture has gone stale."""
    assert not _verbatim_compiles(FENCED, tmp_path), (
        "the raw fenced completion unexpectedly compiled verbatim — the "
        "fence-marker defect shape is no longer reproduced")


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
@NEEDS_SIM
def test_unchanged_fenced_draft_still_defenced(tmp_path):
    """The emit must be UNCONDITIONAL: even a fenced draft that needs NO
    hygiene fix (the dominant ELAB_ERROR shape) must be de-fenced. Before the
    fix the emit was gated on a hygiene diff, so an unchanged draft kept the
    fence verbatim."""
    ok, out_rec, entry = G.gate_record({"id": "p_clean", "completion": FENCED},
                                       _wd(tmp_path))
    assert ok and entry["verdict"] == "PASS"
    # FENCED already passes hygiene unchanged, yet must still be de-fenced.
    assert "```" not in out_rec["completion"]
    assert out_rec["completion"] != FENCED


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
@NEEDS_SIM
def test_prose_then_fenced_emits_only_compiled_code(tmp_path):
    ok, out_rec, entry = G.gate_record(
        {"id": "p_prose", "completion": PROSE_THEN_FENCED}, _wd(tmp_path))
    assert ok and entry["verdict"] == "PASS"
    emitted = out_rec["completion"]
    assert "```" not in emitted and "analysis" not in emitted
    assert "module bar" in emitted
    assert _verbatim_compiles(emitted, tmp_path)


# ── (2) NEGATIVE no-leak ─────────────────────────────────────────────────────

@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
@NEEDS_SIM
def test_multifence_emits_all_bodies_NOLEAK(tmp_path):
    """no-leak (c): a multi-fence completion emits ALL module bodies, not just
    the first, and de-fenced."""
    ok, out_rec, entry = G.gate_record(
        {"id": "p_multi", "completion": TWO_FENCES}, _wd(tmp_path))
    assert ok and entry["verdict"] == "PASS"
    emitted = out_rec["completion"]
    assert "```" not in emitted
    assert "module f1" in emitted and "module f2" in emitted
    assert _verbatim_compiles(emitted, tmp_path)


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
@NEEDS_SIM
def test_bare_completion_unchanged_NOLEAK(tmp_path):
    """no-leak (b): a bare fence-less code completion passes through unchanged
    (it was never fenced; the fix must not touch this path)."""
    ok, out_rec, entry = G.gate_record({"id": "p_bare", "completion": BARE},
                                       _wd(tmp_path))
    assert ok and entry["verdict"] == "PASS"
    assert out_rec["completion"] == BARE  # unchanged (hygiene-clean)
    assert _verbatim_compiles(out_rec["completion"], tmp_path)


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
@NEEDS_SIM
def test_json_dict_single_file_normalized_to_bare_rtl_NOLEAK(tmp_path):
    """no-leak (a), SUPERSEDED BY #680: a SINGLE-RTL-FILE JSON code-dict
    completion is the dominant `no_schema=True` shape (297/302). The harness
    writes it VERBATIM, so a raw JSON dict ELAB_ERRORs on line 1. The gate now
    NORMALIZES it to BARE de-fenced RTL (the exact bytes it compiled), like the
    fenced kind. (The old assertion that a single-file JSON dict is emitted
    verbatim WAS the #680 defect; a multi-file dict still stays JSON — see
    test_json_dict_multifile_stays_json_NOLEAK.)"""
    ok, out_rec, entry = G.gate_record(
        {"id": "p_json", "completion": JSON_DICT}, _wd(tmp_path))
    assert ok and entry["verdict"] == "PASS"
    emitted = out_rec["completion"]
    # single-file → normalized to bare RTL, NOT raw JSON
    assert not emitted.lstrip().startswith("{"), (
        f"single-file JSON dict emitted verbatim (the #680 defect): "
        f"{emitted[:40]!r}")
    assert "module qux" in emitted
    assert _verbatim_compiles(emitted, tmp_path)


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
@NEEDS_SIM
def test_json_dict_multifile_stays_json_NOLEAK(tmp_path):
    """no-leak (a'), #680: a genuinely MULTI-FILE JSON code-dict (>1 RTL file)
    is decoded by the harness under its schema, so it MUST stay the JSON
    shape (json_code_files can re-parse it). Only the single-file shape
    normalizes to bare RTL."""
    multi = json.dumps({"code": [
        {"rtl/qux.sv": "module qux(input g, output h); assign h = g; "
                       "endmodule\n"},
        {"rtl/quux.sv": "module quux(input i, output j); assign j = ~i; "
                        "endmodule\n"}]})
    ok, out_rec, entry = G.gate_record(
        {"id": "p_json_multi", "completion": multi}, _wd(tmp_path))
    assert ok and entry["verdict"] == "PASS"
    emitted = out_rec["completion"]
    files = G.json_code_files(emitted)
    assert files is not None and len(
        [k for k in files if k.endswith(".sv")]) == 2


def test_doc_only_stays_doc_only_NOLEAK(tmp_path):
    """no-leak (d): a doc_only completion stays doc_only, emitted unchanged
    (no compile, no de-fencing)."""
    ok, out_rec, entry = G.gate_record(
        {"id": "p_doc", "completion": DOC_ONLY}, _wd(tmp_path))
    assert ok and entry["verdict"] == "PASS_DOC_ONLY"
    assert out_rec["completion"] == DOC_ONLY


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
