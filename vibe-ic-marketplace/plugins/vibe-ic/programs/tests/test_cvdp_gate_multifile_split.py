"""cvdp_gate must SPLIT a single concatenated RTL blob into one file per
response path for a MULTI-FILE problem (the scorer-visible response contract
lists >1 rtl/*.sv), so the official scorer does not write the whole blob into EACH
expected slot → duplicate-module compile FAIL.

Root cause of 7 residual failures in the CVDP convergence campaign
(axis_border_gen_0014, elevator_control_0006/0026, huffman_0001,
ping_pong_buffer_0001, …): a multi-file deliverable emitted as one .sv.

No-leak: only response file KEYS shown in the official question are consumed;
reference solution values are never read. A single-file/unknown contract stays
bare.
"""
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
HARNESS = PLUGIN / "benchmark"
# Import the module-under-test by FILE PATH, never by bare name: in a
# two-tree session a same-named module from the other tree may already sit
# in sys.modules, and a bare import would silently bind these assertions to
# the OTHER tree's code (measured: exactly the 2 prompt-export tests red in
# the two-tree arm). Same hermetic pattern as
# test_gate_never_reinjects_a_harness_staged_module._gate().
_spec = importlib.util.spec_from_file_location(
    "cvdp_gate_multifile_split_under_test", HARNESS / "cvdp_gate.py")
G = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(G)

A = "module foo(input a, output y);\n assign y = a;\nendmodule"
B = "module bar(input b, output z);\n assign z = ~b;\nendmodule"
HELPER = "module helper(input c, output w);\n assign w = c;\nendmodule"


def test_parse_modules_flat():
    mods = G._parse_modules(A + "\n\n" + B)
    assert set(mods) == {"foo", "bar"}
    assert "endmodule" in mods["foo"] and mods["foo"].startswith("module foo")


def test_split_two_files_matched_by_basename():
    split = G._split_blob_to_expected(A + "\n\n" + B,
                                      ["rtl/foo.sv", "rtl/bar.sv"])
    assert split is not None
    assert set(split) == {"rtl/foo.sv", "rtl/bar.sv"}
    assert "module foo" in split["rtl/foo.sv"] and "module bar" not in split["rtl/foo.sv"]
    assert "module bar" in split["rtl/bar.sv"]


def test_split_extra_helper_goes_to_first_file_once():
    split = G._split_blob_to_expected(A + "\n\n" + B + "\n\n" + HELPER,
                                      ["rtl/foo.sv", "rtl/bar.sv"])
    assert split is not None
    blob = "\n".join(split.values())
    # every module appears EXACTLY once across the file set
    assert blob.count("module helper") == 1
    assert blob.count("module foo") == 1 and blob.count("module bar") == 1
    assert "module helper" in split["rtl/foo.sv"]   # extra → first file


def test_split_incomplete_returns_none():
    # expected bar.sv has no `module bar` in the blob → conservative: no split
    assert G._split_blob_to_expected(A + "\n\n" + HELPER,
                                     ["rtl/foo.sv", "rtl/bar.sv"]) is None


def test_split_single_file_returns_none():
    assert G._split_blob_to_expected(A, ["rtl/foo.sv"]) is None


def test_emit_or_split_multifile_emits_json_envelope():
    out = G._emit_or_split(A + "\n\n" + B, ["rtl/foo.sv", "rtl/bar.sv"])
    obj = json.loads(out)
    assert "code" in obj and isinstance(obj["code"], list)
    paths = set(k for d in obj["code"] for k in d)
    assert paths == {"rtl/foo.sv", "rtl/bar.sv"}


def test_emit_or_split_singlefile_is_bare():
    assert G._emit_or_split(A, ["rtl/foo.sv"]) == A
    assert G._emit_or_split(A, None) == A


def test_load_response_contract_reads_keys_not_context_guesses(tmp_path):
    # Official dataset_processor shows output.context KEYS to the candidate and
    # chooses response schema from their count. Values stay held back and are
    # irrelevant. A sanitized response_contract is the equivalent export shape.
    ds = tmp_path / "ds.jsonl"
    ds.write_text("\n".join([
        json.dumps({"id": "m2", "output": {"context": {
            "rtl/foo.sv": "SECRET-A", "rtl/bar.sv": "SECRET-B"}}}),
        json.dumps({"id": "s1", "output": {"context": {
            "rtl/only.sv": "SECRET"}}}),
        json.dumps({"id": "public", "response_contract": {
            "files": ["rtl/a.sv", "rtl/b.sv"]}}),
        json.dumps({"id": "input_only", "input": {"context": {
            "rtl/x.sv": "x", "rtl/y.sv": "y"}}}),
    ]))
    m = G._load_response_contract_map(ds)
    assert m == {
        "m2": ["rtl/foo.sv", "rtl/bar.sv"],
        "s1": ["rtl/only.sv"],
        "public": ["rtl/a.sv", "rtl/b.sv"],
    }
    assert "SECRET" not in repr(m)


_HAS_TOOLCHAIN = (shutil.which("iverilog") is not None
                  and shutil.which("yosys") is not None)


@pytest.mark.skipif(not _HAS_TOOLCHAIN,
                    reason="asserts a PASS verdict end-to-end: needs a real "
                           "iverilog AND yosys.")
def test_gate_record_splits_bare_multifile_blob(tmp_path):
    # end-to-end: a bare blob with foo+bar for a 2-file problem → gate emits the
    # split JSON envelope (not the duplicated blob).
    rec = {"id": "p", "completion": A + "\n\n" + B}
    ok, out_rec, entry = G.gate_record(
        rec, tmp_path, response_files=["rtl/foo.sv", "rtl/bar.sv"])
    assert ok, entry
    obj = json.loads(out_rec["completion"])
    paths = set(k for d in obj["code"] for k in d)
    assert paths == {"rtl/foo.sv", "rtl/bar.sv"}


# ── empty-sibling clobber + bare-single-file emit (convergence tick3) ──────────
CTX_TARGET = ("module inter_block(input a, output y);\n"
              "  intra_block u(.a(a), .y(y));\nendmodule")


def test_single_authored_file_keeps_multifile_schema_without_empty_context():
    # a modify task: input.context has inter_block.sv + intra_block.sv; the author
    # correctly authors ONLY inter_block (instantiates the sibling). The gate must
    # The response contract is multi-file, so retain JSON even though only the
    # authored target remains. Never emit an empty sibling that clobbers context.
    out = G._emit_or_split(
        CTX_TARGET, ["rtl/inter_block.sv", "rtl/intra_block.sv"],
        {"rtl/intra_block.sv": "module intra_block; endmodule"})
    assert set(k for d in json.loads(out)["code"] for k in d) == {"rtl/inter_block.sv"}


def test_multi_authored_files_still_envelope():
    # when the author genuinely authors BOTH modules into their eponymous files,
    # the multi-file envelope is preserved (existing 7-residual-fix behaviour).
    blob = A.replace("foo", "aaa") + "\n\n" + B.replace("bar", "bbb")
    out = G._emit_or_split(blob, ["rtl/aaa.sv", "rtl/bbb.sv"])
    assert out.lstrip().startswith('{"code"')
    j = json.loads(out)
    paths = {list(d.keys())[0] for d in j["code"]}
    assert paths == {"rtl/aaa.sv", "rtl/bbb.sv"}
    for d in j["code"]:
        assert list(d.values())[0].strip()          # no empty slot


def test_no_empty_slot_ever_emitted():
    # a blob defining only one of two expected modules must never yield an empty
    # file for the other (empty .sv clobbers a passed-through context sibling).
    out = G._emit_or_split(
        A, ["rtl/foo.sv", "rtl/other.sv"],
        {"rtl/other.sv": "module other; endmodule"})
    if out.lstrip().startswith('{"code"'):
        for d in json.loads(out)["code"]:
            assert list(d.values())[0].strip(), "empty slot emitted"
    else:
        assert "module foo" in out
