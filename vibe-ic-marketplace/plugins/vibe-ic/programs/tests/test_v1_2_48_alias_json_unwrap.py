#!/usr/bin/env python3
"""Tests for v1.2.48 alias JSON-completion unwrap.

Run:  python3 -m pytest test_v1_2_48_alias_json_unwrap.py -q
(or)  python3 test_v1_2_48_alias_json_unwrap.py

Why — cvdp_harness_toplevel_alias (v1.2.40/v1.2.47) emitted nothing when the
author's completion was the JSON envelope `{"code":[{path:content}, ...]}` or
the flat `{path: content, ...}` shape: `author_top_and_ports` did its bare
`module <name>(…);` regex scan on the raw envelope string, found no
top-level ANSI header (only a JSON-string value), and returned None →
alias SKIPPED. The three `run_v1239_converge` MULTI-FILE JSON-completion pids
(axis_border_gen_0014, axi_alu_0001, ping_pong_buffer_0001) therefore never
benefited from the alias chain.

The benchmark-fail facts that motivated this fix:
  * `axis_border_gen_0014` — completion carries the port-list-compatible
    rename `module axis_image_border_gen_with_resizer (…)` inside
    `{"code":[{"rtl/axis_border_gen_with_resize.sv":"…module…"}, …]}`; harness
    compiles `-s axis_border_gen_with_resize`; author declared a different
    name → alias fix recovers.
  * `ping_pong_buffer_0001` — author declared the harness's exact TOPLEVEL
    `ping_pong_buffer` inside the JSON; alias is a NO-OP (already correct
    module name); the residual `dual_port_memory` undefined-instantiation is
    a structural RTL bug. The alias path MUST no-op cleanly here, NOT
    corrupt the JSON envelope.
  * `axi_alu_0001` — bare Verilog; `module axi_alu` already declared; alias
    no-op (the v1.2.40 path), not part of v1.2.48's JSON path.

`cvdp_gate.completion_module_names` ALREADY unwraps JSON (it calls
`extract_code` → `json_code_files`); this fix mirrors that behaviour in the
alias-side WITHOUT importing cvdp_gate (avoids circular-dependency risk
under §4.05 — never re-correlate emitter↔checker helpers).

Tests:
  1. JSON-unwrap path correct (alias injected into first RTL entry's value).
  2. JSON no-op when harness top already declared.
  3. JSON non-RTL response form ignored (`{"response":"…"}` envelope).
  4. Flat file-map fallback (`{"rtl/foo.sv":"…"}`, no `code` wrapper key).
  5. Bare-Verilog regression-guard (the v1.2.40 path unchanged).
  6. Parameter module in JSON (v1.2.47's `#(…)` forward carries through).
  7. JSON iverilog compile check (skipped if iverilog absent).
  8. JSON first-file-empty fallback (skip empty `rtl/empty.sv:""`,
     pick the FIRST non-empty RTL entry for wrapper injection).
"""
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "..", "..", "benchmark"))
import cvdp_harness_toplevel_alias as A


class _FakeModuleNames:
    """Stand-in for `cvdp_gate.completion_module_names`. Returns a fixed set
    of declared module names — mimics the gate's interface without importing
    cvdp_gate (the alias module must stay self-sufficient, per §4.05)."""

    def __init__(self, names):
        self._names = set(names)

    def __call__(self, _completion):
        return set(self._names)


# ── 1: JSON-unwrap path correct ──────────────────────────────────────────────
JSON_AUTHOR_MYTOP = (
    "module mytop (input clk, output reg q); "
    "always @(posedge clk) q <= ~q; "
    "initial q = 0; "
    "endmodule\n"
)


def test_json_unwrap_appends_wrapper_into_first_rtl_entry():
    """Agent emits JSON `{"code":[{"rtl/foo.sv":"module mytop …"}]}`, harness
    wants `cvdp_copilot_foo` (NOT `mytop`). `maybe_alias_completion` must
    (a) unwrap the JSON, (b) parse `mytop`'s ANSI header, (c) emit the alias
    wrapper INTO `rtl/foo.sv`'s value (NOT a brand-new JSON entry — that would
    be silently dropped by the harness's explicit-source iverilog invocation),
    (d) re-encode the JSON envelope cleanly parseable by the scorer's
    `find('{')` → `json.loads` decoder.
    """
    completion = json.dumps(
        {"code": [{"rtl/foo.sv": JSON_AUTHOR_MYTOP}]},
        ensure_ascii=False)
    out = A.maybe_alias_completion(
        completion, "cvdp_copilot_foo", _FakeModuleNames({"mytop"}))
    # re-encode must be parseable as JSON
    parsed = json.loads(out)
    code_list = parsed.get("code")
    assert isinstance(code_list, list) and len(code_list) == 1, \
        f"JSON envelope must preserve the single-entry shape: {parsed!r}"
    entry = code_list[0]
    assert "rtl/foo.sv" in entry, \
        f"the wrapper MUST be injected into the existing rtl/foo.sv entry, "\
        f"not a new one: {list(entry.keys())!r}"
    foo_value = entry["rtl/foo.sv"]
    # original `module mytop …` still present (we did NOT rewrite the author
    # RTL — only appended the alias wrapper)
    assert "module mytop" in foo_value, "author module must be byte-intact"
    # alias wrapper synthesized into the same value
    assert "module cvdp_copilot_foo" in foo_value, \
        "alias wrapper module declaration must appear"
    # alias wires the author top through the wrapper
    assert "mytop u_mytop" in foo_value, \
        "wrapper must instantiate the author declared top"


# ── 2: JSON no-op when harness top already declared ─────────────────────────
def test_json_noop_when_harness_top_already_declared():
    """JSON envelope where the author's first RTL entry declares the exact
    harness TOPLEVEL → returned BIT-EQUIVALENT (no mutation). Preserves the
    181-pass baseline (every passing problem already declares its harness
    top inside the RTL — same applies in JSON shape)."""
    src = "module foo (input clk); endmodule\n"
    completion = json.dumps(
        {"code": [{"rtl/foo.sv": src}]}, ensure_ascii=False)
    out = A.maybe_alias_completion(
        completion, "foo", _FakeModuleNames({"foo"}))
    # byte-equivalent — harness-top IS declared, no alias emission
    assert out == completion, \
        "already-correct JSON completion must be returned byte-identical "\
        "(§4.05 — never inject an alias wrapper that would shadow the author)"


# ── 3: JSON non-RTL response form ignored (`{"response":"…"…}`) ─────────────
def test_json_non_rtl_response_envelope_ignored():
    """A `{"response":"…"}` envelope is a code-comprehension / doc-only
    payload — the scorer treats it as `subjective.txt`. The alias MUST NOT
    mis-revive it as a multi-file code map and inject a wrapper that the
    harness would silently drop."""
    completion = '{"response":"Here is the answer: tristate buffer mux"}'
    # `_FakeModuleNames({})` because if we DID unwrap the response, harness_top
    # would still need to be NOT declared — but the unwrap itself must fail
    # first (no `code` key, no `rtl/*.sv` flat-file-map keys).
    out = A.maybe_alias_completion(
        completion, "cvdp_copilot_foo", _FakeModuleNames(set()))
    # byte-identical — the unwrap helper returned None (prose envelope)
    assert out == completion, \
        "`{\"response\":…}` prose envelope must be returned byte-identical "\
        "(§4.05 — never inject wrapper into doc-only payload)"


# ── 4: Flat file-map fallback (no `code` wrapper key) ───────────────────────
def test_flat_file_map_fallback_unwraps():
    """A `{"rtl/foo.sv":"module mytop …"}` flat object (NO `code` wrapper)
    is also a multi-file code map — some agents emit this shape instead of
    the structured `{"code":[…]}` envelope (mirrors `cvdp_gate.json_code_files`
    flat-file-map fallback at line 263-285). The alias path must unwrap this
    too."""
    src = (
        "module mytop (input clk, output reg q); "
        "always @(posedge clk) q <= ~q; "
        "initial q = 0; "
        "endmodule\n")
    completion = json.dumps(
        {"rtl/foo.sv": src}, ensure_ascii=False)
    out = A.maybe_alias_completion(
        completion, "cvdp_copilot_foo", _FakeModuleNames({"mytop"}))
    parsed = json.loads(out)
    foo_value = parsed["rtl/foo.sv"]
    assert "module mytop" in foo_value, "author module byte-intact in flat shape"
    assert "module cvdp_copilot_foo" in foo_value, \
        "alias wrapper emitted into the flat-file-map's only entry"


# ── 5: Bare-Verilog regression-guard (v1.2.40/v1.2.47 unchanged) ─────────────
def test_bare_verilog_path_unchanged():
    """A bare Verilog completion with no leading `{` MUST still flow through
    the v1.2.40/v1.2.47 append-to-end path — the JSON unwrap helper
    returns None on a bare Verilog completion (no leading `{`), so this
    exact behaviour is preserved."""
    bare = (
        "module mytop (input clk, output reg q); "
        "always @(posedge clk) q <= ~q; "
        "initial q = 0; "
        "endmodule\n")
    out = A.maybe_alias_completion(
        bare, "cvdp_copilot_foo", _FakeModuleNames({"mytop"}))
    # author top preserved at the head
    assert out.startswith(bare), \
        "bare-Verilog path appends wrapper to the end (no JSON re-encode)"
    # wrapper appended
    assert "module cvdp_copilot_foo" in out, \
        "alias wrapper must be appended to bare Verilog (the v1.2.40 path)"


# ── 6: Parameter module in JSON (v1.2.47's `#(…)` forward) ──────────────────
def test_param_module_in_json_carries_param_port_list():
    """A parameter module's port widths reference parameter names; the alias
    wrapper MUST re-declare `#(parameter int InWidth_g = 32, …)` so iverilog
    binds parameter names referenced by `[InWidth_g-1:0]`. This is the
    v1.2.47 parameter-port forwarding carried THROUGH the v1.2.48 JSON
    unwrap (byte-for-byte non-regression).
    """
    src = (
        "module decode_firstbit #(\n"
        "    parameter int InWidth_g = 32\n"
        ") (\n"
        "    input  logic                          Clk,\n"
        "    input  logic                          Rst,\n"
        "    input  logic [InWidth_g-1:0]          In_Data,\n"
        "    input  logic                          In_Valid,\n"
        "    output logic [$clog2(InWidth_g)-1:0]  Out_FirstBit,\n"
        "    output logic                          Out_Found,\n"
        "    output logic                          Out_Valid\n"
        ");\n"
        "endmodule\n"
    )
    completion = json.dumps(
        {"code": [{"rtl/foo.sv": src}]}, ensure_ascii=False)
    out = A.maybe_alias_completion(
        completion, "cvdp_copilot_decode_firstbit",
        _FakeModuleNames({"decode_firstbit"}))
    parsed = json.loads(out)
    inner = parsed["code"][0]["rtl/foo.sv"]
    # wrapper synthesized
    assert "module cvdp_copilot_decode_firstbit" in inner
    # wrapper MUST re-declare the parameter port block (no `Unable to bind
    # parameter 'InWidth_g'` regression)
    assert "parameter" in inner, \
        "parameter port list must be re-declared on the wrapper"
    assert "InWidth_g" in inner, \
        "parameter name 'InWidth_g' must appear on the wrapper header"


# ── 7: JSON iverilog compile check (skipped if iverilog absent) ─────────────
def _has_iverilog():
    try:
        subprocess.run(["iverilog", "-V"], capture_output=True, check=True)
        return True
    except Exception:
        return False


def test_json_wrapped_completion_compiles_under_iverilog():
    """Unwrap-then-wrap a clean `mytop` fixture (single-port module with a
    `wire`-declared output, NOT self-driving an input — that would be a
    fixture-internal Verilog bug, unrelated to v1.2.48). Verify the WRAPPED
    RTL (author module + alias wrapper) compiles cleanly under
    `iverilog -g2012 -s <harness_top> -t null`. The alias output is a JSON
    envelope, so this test extracts the FIRST RTL entry's value (which now
    carries the wrapper) and writes THAT to a .sv file for compile.

    Skipped if iverilog is absent (the test environment may lack it).
    """
    if not _has_iverilog():
        return  # iverilog absent — skip without failing
    src = (
        "module mytop (input clk, output reg q);\n"
        "  always @(posedge clk) q <= ~q;\n"
        "  initial q = 0;\n"
        "endmodule\n")
    completion = json.dumps(
        {"code": [{"rtl/foo.sv": src}]}, ensure_ascii=False)
    out = A.maybe_alias_completion(
        completion, "cvdp_copilot_foo", _FakeModuleNames({"mytop"}))
    # `out` is a JSON envelope (the scorer decode). Extract the first RTL
    # entry's value (now carries the wrapped RTL) for compile.
    parsed = json.loads(out)
    inner_value = parsed["code"][0]["rtl/foo.sv"]
    with tempfile.NamedTemporaryFile("w", suffix=".sv", delete=False) as f:
        f.write(inner_value)
        path = f.name
    try:
        r = subprocess.run(
            ["iverilog", "-g2012", "-s", "cvdp_copilot_foo",
             "-t", "null", path],
            capture_output=True, text=True)
        assert r.returncode == 0, \
            f"JSON-wrapped completion compile FAILED: stderr={r.stderr!r} "\
            f"stdout={r.stdout!r}"
    finally:
        os.unlink(path)


# ── 8: JSON first-file-empty fallback ────────────────────────────────────────
def test_json_first_file_empty_falls_through_to_first_nonempty():
    """Some agent completions put the full RTL module in the SECOND entry of
    `code` while the FIRST entry is an empty stub (e.g. `axis_border_gen_0014`
    has 3 entries — first is full, other 2 are empty). The v1.2.48 unwrap must
    pick the FIRST NON-EMPTY RTL-suffix entry for `author_top_and_ports` AND
    for the wrapper-injection target (so the harness's explicit-source
    iverilog invocation — which lists the FIRST entry's path in `.env`
    `VERILOG_SOURCES=` — picks up the wrapper).

    This test inverts the shape (FIRST empty, SECOND non-empty) to nail the
    non-empty selection rule — the LIVE axis_border_gen fixture is the
    OTHER order, also covered by the gate-repro in Step (B) of the v1.2.48
    plan."""
    src = (
        "module myup (input clk, output reg q); "
        "always @(posedge clk) q <= ~q; "
        "initial q = 0; "
        "endmodule\n")
    completion = json.dumps(
        {"code": [
            {"rtl/empty.sv": ""},
            {"rtl/up.sv": src},
        ]},
        ensure_ascii=False)
    out = A.maybe_alias_completion(
        completion, "cvdp_copilot_up", _FakeModuleNames({"myup"}))
    parsed = json.loads(out)
    code_list = parsed["code"]
    # entry[0] is still the empty stub (untouched — byte-for-byte empty)
    assert code_list[0]["rtl/empty.sv"] == "", \
        "the empty stub must be untouched"
    # entry[1] is the injection target where the wrapper was appended
    assert "module myup" in code_list[1]["rtl/up.sv"], \
        "the non-empty RTL entry must carry the author module byte-intact"
    assert "module cvdp_copilot_up" in code_list[1]["rtl/up.sv"], \
        "wrapper must be injected into the FIRST NON-EMPTY RTL entry"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"PASS {fn.__name__}")
    print(f"\n{passed}/{len(fns)} tests passed")
