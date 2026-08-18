"""cvdp_gate.json_code_files must recover a FLAT file-map completion
(`{"rtl/foo.sv": "module foo...endmodule"}` with NO "code" wrapper key).

Agents — especially on multi-file problems — repeatedly emit this shape. The
official `parse_model_response` only unwraps a "code" key, so a flat file-map
was written verbatim as the .sv → a line-1 `{` syntax error → ELAB_ERROR even
though clean RTL was inside (observed across ~8 CVDP convergence designs:
elevator_control_*, gcd_0009, huffman_0001, ping_pong_buffer_0001, ...). The
gate now recovers the files so its #680 emit-normalization re-emits a format
the harness decodes.

NEGATIVE no-leak: a JSON-schema / doc-only answer object (no Verilog module)
must NOT be misread as code (stays None → tolerated, not force-compiled).
"""
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
HARNESS = PLUGIN / "benchmark"
sys.path.insert(0, str(HARNESS))
import cvdp_gate as G  # noqa: E402

_MOD = "module foo(input a, output y); assign y = a; endmodule"
_MOD2 = "module bar(input b, output z); assign z = ~b; endmodule"


def test_flat_filemap_single_no_code_key():
    comp = '{"rtl/foo.sv": "%s"}' % _MOD.replace('"', '\\"')
    files = G.json_code_files(comp)
    assert files is not None
    assert "rtl/foo.sv" in files
    assert "endmodule" in files["rtl/foo.sv"]


def test_flat_filemap_multifile_no_code_key():
    import json
    comp = json.dumps({"rtl/foo.sv": _MOD, "rtl/bar.sv": _MOD2})
    files = G.json_code_files(comp)
    assert files is not None
    assert set(files) == {"rtl/foo.sv", "rtl/bar.sv"}
    assert "endmodule" in files["rtl/bar.sv"]


def test_flat_filemap_extracts_via_extract_code():
    import json
    comp = json.dumps({"rtl/foo.sv": _MOD})
    code, kind = G.extract_code(comp)
    assert kind == "json_dict"
    assert code is not None and "endmodule" in code


def test_doc_only_json_object_not_misread_as_code():
    # a JSON-schema / register-description answer carries NO Verilog module —
    # must stay None (tolerated), never force-compiled as bare code.
    import json
    comp = json.dumps({"registers": [{"name": "CTRL", "offset": 0}],
                       "width": 32, "description": "the module config"})
    assert G.json_code_files(comp) is None


def test_code_key_shapes_still_work_regression():
    import json
    # list-of-single-key-dicts (official multi-file)
    lst = json.dumps({"code": [{"rtl/foo.sv": _MOD}, {"rtl/bar.sv": _MOD2}]})
    f1 = G.json_code_files(lst)
    assert f1 is not None and set(f1) == {"rtl/foo.sv", "rtl/bar.sv"}
    # dict form
    dct = json.dumps({"code": {"rtl/foo.sv": _MOD}})
    f2 = G.json_code_files(dct)
    assert f2 is not None and "rtl/foo.sv" in f2


def test_nested_code_list_takes_priority_over_flat_fallback():
    # when a real "code" key is present, the fallback must not run / interfere
    import json
    comp = json.dumps({"code": [{"rtl/foo.sv": _MOD}], "notes": "ignore me"})
    files = G.json_code_files(comp)
    assert files is not None and set(files) == {"rtl/foo.sv"}
