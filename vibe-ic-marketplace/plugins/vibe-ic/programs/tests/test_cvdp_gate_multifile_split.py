"""cvdp_gate must SPLIT a single concatenated RTL blob into one file per
expected path for a MULTI-FILE problem (the dataset's output.context lists >1
rtl/*.sv), so the official scorer does not write the whole blob into EACH
expected slot → duplicate-module compile FAIL.

Root cause of 7 residual failures in the CVDP convergence campaign
(axis_border_gen_0014, elevator_control_0006/0026, huffman_0001,
ping_pong_buffer_0001, …): a multi-file deliverable emitted as one .sv.

No-leak: a SINGLE-file problem (or no --dataset / incomplete split) is emitted
bare, unchanged — the split NEVER activates without an authoritative complete
expected-file match.
"""
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
HARNESS = PLUGIN / "benchmark"
sys.path.insert(0, str(HARNESS))
import cvdp_gate as G  # noqa: E402

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


def test_load_expected_files_map_only_multifile(tmp_path):
    # OFFICIAL-COMPLIANCE: the expected-file layout is read from `input.context`
    # (a legitimate model input), NEVER from `output.context` (the reference-
    # solution field, held back from the model). A multi-file record whose
    # input.context carries >1 rtl/*.sv yields the split list; a single-file one
    # is omitted; an output.context-only record is IGNORED (proving the loader no
    # longer reads the reference-solution field).
    ds = tmp_path / "ds.jsonl"
    ds.write_text("\n".join([
        json.dumps({"id": "m2", "input": {"context": {
            "rtl/foo.sv": "x", "rtl/bar.sv": "y", "docs/x.md": ""}}}),
        json.dumps({"id": "s1", "input": {"context": {"rtl/only.sv": "z"}}}),
        json.dumps({"id": "o1", "output": {"context": {
            "rtl/a.sv": "", "rtl/b.sv": ""}}}),   # output-only → must be IGNORED
    ]))
    m = G._load_expected_files_map(ds)
    assert m == {"m2": ["rtl/bar.sv", "rtl/foo.sv"]}   # s1 single, o1 output-only omitted


def test_gate_record_splits_bare_multifile_blob(tmp_path):
    # end-to-end: a bare blob with foo+bar for a 2-file problem → gate emits the
    # split JSON envelope (not the duplicated blob).
    rec = {"id": "p", "completion": A + "\n\n" + B}
    ok, out_rec, entry = G.gate_record(
        rec, tmp_path, expected_files=["rtl/foo.sv", "rtl/bar.sv"])
    assert ok, entry
    obj = json.loads(out_rec["completion"])
    paths = set(k for d in obj["code"] for k in d)
    assert paths == {"rtl/foo.sv", "rtl/bar.sv"}
