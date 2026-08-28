#!/usr/bin/env python3
"""Tests for ORGANIC-20260531 — the two mcp-eda fixes:

  1. eda_lvs mode=netgen: REAL verdict parse + DID-NOT-RUN guard + std-cell-lib
     load + Magic `_flat` auto-name-align — replacing the naive
     `output.match(/uniquely/i) || /match/i` boolean that scored
     property-error mismatches and aborted ("Cannot find cell") runs as PASS.
     (ORGANIC-20260531-eda-lvs-netgen-false-positive-and-no-stdcell-lib)

  2. eda_run_tcl engine=magic: export PDK + PDK_ROOT + foundry `-rcfile`
     (fixes the env(PDK) startup-abort), and eda_extraction: a
     `promote_ports`/`port_makeall` param that injects `port makeall` so the
     emitted `.subckt <top>_flat` carries top-level ports.
     (ORGANIC-20260531-magic-extraction-no-toplevel-ports)

The test does three things:

  A. Static checks on src/index.js — the naive `/match/i` boolean is GONE from
     the netgen branch; the netgen branch is verdict-parser-driven; the magic
     eda_run_tcl path exports PDK/PDK_ROOT + -rcfile; eda_extraction has the
     promote_ports param and injects `port makeall`.

  B. Runtime checks on src/lib/netgen_verdict.mjs via node — classify the EXACT
     netgen 1.5.316 phrasings captured in-container (clean match / property
     error / topology mismatch / Cannot-find-cell) and prove
     `matched` is NEVER true on a fail / did-not-run.

  C. A regression assertion that the OLD naive logic WOULD have false-positived
     the property-error + did-not-run cases (so the fix is load-bearing).

Skips runtime checks if node is not on PATH.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

for _anc in Path(__file__).resolve().parents:
    for _cand in (_anc / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
                  _anc / "programs"):
        if (_cand / "_progress_run.py").is_file():
            sys.path.insert(0, str(_cand))
            break
    else:
        continue
    break
import _progress_run as _pr  # noqa: E402

MCP_ROOT = Path(__file__).resolve().parent.parent
INDEX_JS = MCP_ROOT / "src" / "index.js"
VERDICT_MJS = MCP_ROOT / "src" / "lib" / "netgen_verdict.mjs"
assert INDEX_JS.is_file(), f"missing {INDEX_JS}"
assert VERDICT_MJS.is_file(), f"missing {VERDICT_MJS}"

NODE = shutil.which("node")


def _strip_js_comments(s: str) -> str:
    """Remove // and /* */ comments so we test the CODE, not the changelog
    prose that mentions the old `/match/i` form by name."""
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.DOTALL)
    s = re.sub(r"//[^\n]*", "", s)
    return s


def _extract_tool_block(src: str, tool: str) -> str:
    m = re.search(
        r'server\.tool\(\s*"' + re.escape(tool) + r'".*?^\);',
        src, re.DOTALL | re.MULTILINE,
    )
    assert m, f"{tool} tool registration not found in index.js"
    return m.group(0)


# ───────────────────────── A. static index.js checks ─────────────────────────

def test_netgen_branch_drops_naive_match_regex():
    """The naive `output.match(/uniquely/i) || ... /match/i` boolean and the
    `match != null && !fail` matched/success derivation MUST be gone from the
    eda_lvs CODE (comments documenting the historical bug are allowed)."""
    block = _strip_js_comments(_extract_tool_block(INDEX_JS.read_text(), "eda_lvs"))
    assert "result.output.match(/uniquely/i)" not in block, \
        "the naive /uniquely/i verdict regex must NOT remain in the netgen branch"
    assert "match != null && !fail" not in block, \
        "the naive `match != null && !fail` matched/success derivation must be gone"


def test_netgen_branch_uses_verdict_parser():
    """The netgen branch derives its verdict from classifyNetgenVerdict and a
    DID-NOT-RUN report probe — not a bare token match."""
    block = _extract_tool_block(INDEX_JS.read_text(), "eda_lvs")
    for required in (
        "classifyNetgenVerdict",
        "reportWritten",          # DID-NOT-RUN guard probes the report file
        "verdict.matched",        # success/matched come from the parsed verdict
        "load_stdcell_lib",       # std-cell-lib load param
        "resolveLayoutTop",       # `_flat` auto-name-align
    ):
        assert required in block, f"eda_lvs netgen branch missing: {required!r}"


def test_index_imports_netgen_verdict_module():
    src = INDEX_JS.read_text()
    assert "from \"./lib/netgen_verdict.mjs\"" in src, \
        "index.js must import the netgen_verdict parser module"


def test_eda_run_tcl_magic_exports_pdk_and_rcfile():
    """engine=magic must export PDK + PDK_ROOT and pass a foundry -rcfile."""
    block = _strip_js_comments(_extract_tool_block(INDEX_JS.read_text(), "eda_run_tcl"))
    # the magic case builds an env preamble + -rcfile
    assert "export PDK=" in block, "magic engine must export PDK"
    assert "export PDK_ROOT=" in block, "magic engine must export PDK_ROOT"
    assert "-rcfile" in block, "magic engine must pass a foundry -rcfile"
    assert "magicPdkEnv" in block, "magic engine must resolve the foundry magicrc"


def test_eda_extraction_has_promote_ports_and_injects_port_makeall():
    block = _extract_tool_block(INDEX_JS.read_text(), "eda_extraction")
    assert "promote_ports" in block, "eda_extraction must expose a promote_ports param"
    assert "port makeall" in block, "eda_extraction must be able to inject `port makeall`"


# ───────────────────── B. runtime verdict-parser checks ──────────────────────

# EXACT netgen 1.5.316 (sky130A) phrasings captured in-container during the fix.
_CLEAN_MATCH = (
    "Device classes myinv and myinv are equivalent.\n"
    "\nFinal result: Circuits match uniquely.\n.\nLVS Done.\n"
)
_PROPERTY_ERROR = (  # transistor W-delta: topology matches, properties don't
    "Netlists match uniquely with property errors.\n"
    "sky130_fd_pr__pfet_01v8:1 vs. sky130_fd_pr__pfet_01v8:1:\n"
    " W circuit1: 1   circuit2: 2   (delta=66.7%, cutoff=1%)\n"
    "Final result: Circuits match uniquely.\n"
    "Property errors were found.\n"
    "The following cells had property errors:\n myinv\n"
)
_TOPOLOGY_MISMATCH = (
    "Number of devices: 2 **Mismatch**          |Number of devices: 3 **Mismatch**\n"
    "*** MISMATCH ***\n"
    "Netlists do not match.\n"
    "Port matching may fail to disambiguate symmetries.\n"
    "Final result: Top level cell failed pin matching.\n"
)
_DID_NOT_RUN = (
    "Reading netlist file /tmp/lay.spice for /tmp/lay.spice myinv_flat\n"
    "Cannot find cell myinv_flat in file /tmp/lay.spice\n"
    "===REPORT===\n"  # report file was empty / never written
)


def _node_classify(output: str, report_written) -> dict:
    """Invoke classifyNetgenVerdict via a tiny node script and return its JSON."""
    js = (
        f'import {{ classifyNetgenVerdict }} from "{VERDICT_MJS.as_posix()}";\n'
        "let chunks=[];process.stdin.on('data',d=>chunks.push(d));"
        "process.stdin.on('end',()=>{"
        "const inp=JSON.parse(Buffer.concat(chunks).toString());"
        "const r=classifyNetgenVerdict(inp.output,{reportWritten:inp.reportWritten});"
        "process.stdout.write(JSON.stringify(r));});"
    )
    payload = json.dumps({"output": output, "reportWritten": report_written})
    p = _pr.run(
        [NODE, "--input-type=module", "-e", js],
        input=payload, capture_output=True, text=True)
    assert p.returncode == 0, f"node failed: {p.stderr}"
    return json.loads(p.stdout)


@pytest.mark.skipif(not NODE, reason="node not on PATH")
def test_clean_match_is_pass():
    r = _node_classify(_CLEAN_MATCH, True)
    assert r["verdict"] == "MATCH"
    assert r["matched"] is True


@pytest.mark.skipif(not NODE, reason="node not on PATH")
def test_property_error_is_fail_not_pass():
    """The headline false-positive: 'match uniquely WITH property errors' +
    'Property errors were found' must be FAIL, matched=false."""
    r = _node_classify(_PROPERTY_ERROR, True)
    assert r["verdict"] == "FAIL", r
    assert r["matched"] is False
    assert r["property_errors"] is True


@pytest.mark.skipif(not NODE, reason="node not on PATH")
def test_topology_mismatch_is_fail():
    r = _node_classify(_TOPOLOGY_MISMATCH, True)
    assert r["verdict"] == "FAIL"
    assert r["matched"] is False


@pytest.mark.skipif(not NODE, reason="node not on PATH")
def test_did_not_run_is_never_a_pass():
    """'Cannot find cell' + no report => DID_NOT_RUN, matched=null (NEVER true).
    This is the most dangerous old failure: a non-compared run scored a verdict."""
    r = _node_classify(_DID_NOT_RUN, False)
    assert r["verdict"] == "DID_NOT_RUN", r
    assert r["matched"] is None
    assert r["did_not_run"] is True
    assert r["parse_error"] is True


@pytest.mark.skipif(not NODE, reason="node not on PATH")
def test_no_report_no_final_result_is_did_not_run():
    r = _node_classify("some preamble\nReading netlist...\n", False)
    assert r["verdict"] == "DID_NOT_RUN"
    assert r["matched"] is None


# Real netgen 1.5.316 output captured in-container when both `lvs` args point
# at the same netlist (self-compare guard) — must be DID_NOT_RUN, never a pass.
_SAME_NETLIST = (
    "Reading netlist file /tmp/hdlc_a.spice for /tmp/hdlc_a.spice hdlc_core_flat\n"
    "Call to undefined subcircuit sky130_fd_pr__nfet_01v8\n"
    "Both cells are in the same netlist:  Cannot compare!\n"
    "===REPORT===\n"
)


@pytest.mark.skipif(not NODE, reason="node not on PATH")
def test_same_netlist_cannot_compare_is_did_not_run():
    """A real netgen 'Both cells are in the same netlist: Cannot compare!'
    abort (even if a report happened to exist) is DID_NOT_RUN, never a pass."""
    r = _node_classify(_SAME_NETLIST, True)
    assert r["verdict"] == "DID_NOT_RUN", r
    assert r["matched"] is None


@pytest.mark.skipif(not NODE, reason="node not on PATH")
def test_unparseable_never_defaults_to_match():
    r = _node_classify("entirely unrelated tool log\n", True)
    assert r["verdict"] == "PARSE_ERROR"
    assert r["matched"] is None


@pytest.mark.skipif(not NODE, reason="node not on PATH")
def test_resolve_layout_top_flat_alignment():
    """Magic `<top>_flat` must be matched when the caller asks for `<top>`."""
    js = (
        f'import {{ resolveLayoutTop }} from "{VERDICT_MJS.as_posix()}";\n'
        'const a=resolveLayoutTop(".subckt myinv_flat A Y\\n.ends","myinv");'
        'const b=resolveLayoutTop(".subckt myinv A Y\\n.ends","myinv");'
        'process.stdout.write(JSON.stringify({a,b}));'
    )
    p = _pr.run([NODE, "--input-type=module", "-e", js],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["a"] == {"name": "myinv_flat", "aligned": True}
    assert out["b"] == {"name": "myinv", "aligned": False}


@pytest.mark.skipif(not NODE, reason="node not on PATH")
def test_stdcell_spice_path_per_pdk():
    js = (
        f'import {{ stdcellSpicePath }} from "{VERDICT_MJS.as_posix()}";\n'
        'process.stdout.write(JSON.stringify({'
        's:stdcellSpicePath("sky130"),g:stdcellSpicePath("gf180"),'
        'c:stdcellSpicePath("custom")}));'
    )
    p = _pr.run([NODE, "--input-type=module", "-e", js],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["s"].endswith("sky130_fd_sc_hd/spice/sky130_fd_sc_hd.spice")
    assert out["g"].endswith("gf180mcu_fd_sc_mcu7t5v0/spice/gf180mcu_fd_sc_mcu7t5v0.spice")
    assert out["c"] is None


@pytest.mark.skipif(not NODE, reason="node not on PATH")
def test_build_netgen_lvs_tcl_loads_stdcell_into_schematic():
    """When stdcellSpice is given, the driver TCL loads it INTO the schematic
    circuit (readnet spice <std> $schCkt) and does NOT top-level-source the
    foundry setup (which runs `cells list` and needs circuits first)."""
    js = (
        f'import {{ buildNetgenLvsTcl }} from "{VERDICT_MJS.as_posix()}";\n'
        'const t=buildNetgenLvsTcl({layoutNetlist:"/l.sp",schematicNetlist:"/s.sp",'
        'layoutTop:"t_flat",schematicTop:"t",setupFile:"/setup.tcl",'
        'reportPath:"/r.txt",stdcellSpice:"/std.spice"});'
        'process.stdout.write(t);'
    )
    p = _pr.run([NODE, "--input-type=module", "-e", js],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    tcl = p.stdout
    assert "readnet spice /std.spice $schCkt" in tcl
    assert "$layCkt t_flat" in tcl and "$schCkt t" in tcl
    # must NOT source the foundry setup at top level
    assert not re.search(r"(?m)^source /setup\.tcl", tcl)


# ───────── C. regression: old naive logic WOULD have false-positived ─────────

def _old_naive_verdict(output: str) -> dict:
    """Faithful re-implementation of the PRE-fix index.js netgen verdict."""
    match = re.search(r"uniquely", output, re.I) or re.search(r"match", output, re.I)
    fail = re.search(r"mismatch|NOT match|FAIL", output, re.I)
    return {"matched": bool(match) and not fail, "success": not fail}


def test_old_logic_was_a_false_positive_on_property_error():
    """Proves the fix is load-bearing: the OLD logic scored the property-error
    mismatch as matched=true (the silent false sign-off the backlog reports)."""
    old = _old_naive_verdict(_PROPERTY_ERROR)
    assert old["matched"] is True, \
        "guard test: the OLD naive logic DID false-positive this case"


def test_old_logic_scored_did_not_run_as_success():
    """The OLD logic returned success=true on a 'Cannot find cell' run that
    never compared (it would have written a PASS manifest)."""
    old = _old_naive_verdict(_DID_NOT_RUN)
    assert old["success"] is True, \
        "guard test: the OLD naive logic DID treat a did-not-run as success"


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
