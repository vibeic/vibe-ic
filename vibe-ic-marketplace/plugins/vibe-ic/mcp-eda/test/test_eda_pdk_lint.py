#!/usr/bin/env python3
"""Wave 75 — tests for eda_pdk_lint static shape.

Live PDK lint requires docker + a real Liberty/LEF/GDS deck. These
tests verify the wrapper's contract.

Positive: required args (lib/techlef/celllef) are mandatory.
Negative: when docker is unreachable, return early with a clear error.
Edge   : RESISTANCE-missing on tech LEF emits warn (not error) so
         IR-drop fallback can proceed.
SKIP   : cellgds + cts_buf_list are optional; absence must skip the
         corresponding probe (no dockerExec on that branch).
"""
from pathlib import Path

INDEX_JS = Path(__file__).resolve().parent.parent / "src" / "index.js"


def _slice():
    src = INDEX_JS.read_text()
    idx = src.find('"eda_pdk_lint"')
    assert idx > 0
    end = src.find("server.tool(", idx)
    return src[idx:end if end >= 0 else len(src)]


def test_tool_registered():
    assert '"eda_pdk_lint"' in INDEX_JS.read_text()


def test_required_args_have_no_defaults():
    """Positive: lib + techlef + celllef must be required — defaulting
    these would let an agent silently lint a wrong PDK."""
    w = _slice()
    for arg in ("lib", "techlef", "celllef"):
        i = w.find(arg + ":")
        # zod chain on each line
        line = w[i: i + 200]
        assert ".default(" not in line, f"{arg} must be required"
        assert ".describe(" in line, f"{arg} must have a describe()"


def test_optional_args_marked_optional():
    """SKIP-equivalent: cellgds + cts_buf_list must be .optional() so
    decks without those data still run."""
    w = _slice()
    assert "cellgds:" in w
    assert "cts_buf_list:" in w
    # Find the line for each and confirm `.optional()`
    for arg in ("cellgds", "cts_buf_list"):
        i = w.find(arg + ":")
        line = w[i: i + 250]
        assert ".optional()" in line, f"{arg} must be .optional()"


def test_docker_unreachable_short_circuits():
    """Negative: v2.5.1 — when _probeDocker fails, the tool returns
    a structured error rather than spewing dockerExec failures across
    every subsequent check."""
    w = _slice()
    assert "_probeDocker" in w
    assert "docker_unreachable" in w


def test_resistance_missing_is_warn_not_error():
    """Edge: tech LEF without RESISTANCE emits warn — eda_ir_drop has
    via_resistance_ohm fallback, so this should not block PnR."""
    w = _slice()
    assert "RESISTANCE" in w
    # Severity is the first arg of note(...); the resistance call lives
    # on the same line as `note("warn", "tech_lef_resistance", ...)`.
    assert 'note("warn", "tech_lef_resistance"' in w, (
        "missing RESISTANCE must be warn (eda_ir_drop has fallback)"
    )


def test_liberty_too_few_blocks_is_error():
    """Negative: a Liberty file with <10 library/cell blocks is
    almost certainly empty/corrupt; this MUST be an error so synth
    doesn't proceed against a broken deck."""
    w = _slice()
    assert 'note("error", "liberty_syntax"' in w, (
        "<10 Liberty blocks must escalate to error (corrupt deck)"
    )


def test_gds_lef_count_mismatch_is_warn():
    """Edge: GDS-LEF cell-count mismatch >50% emits warn (the deck
    may legitimately ship more cells in GDS than LEF for analog hardmacros)."""
    w = _slice()
    if "gds_lef_count_mismatch" in w:
        assert 'note("warn", "gds_lef_count_mismatch"' in w, (
            "GDS/LEF mismatch must be warn (analog hardmacros legit case)"
        )


def test_summary_counts_severities():
    """Positive: summary emits `N errors, M warnings, K info`."""
    w = _slice()
    assert "errors" in w
    assert "warnings" in w
    assert "info" in w


# Drive the registered handler and its real shell read commands on tiny files.
import json
import subprocess
import pytest

def _handler(tmp_path, text):
    lib=tmp_path/"cells.lib";lib.write_text("library(x) {\n" + "cell(x) {\n"*10)
    cells=tmp_path/"cells.lef";cells.write_text("MACRO cell\n"*30 + "SITE core\n")
    tech=tmp_path/"tech.lef"
    if text is not None:tech.write_text(text)
    src=INDEX_JS.read_text();start=src.rfind("server.tool(",0,src.index('"eda_pdk_lint"'));end=src.find("server.tool(",start+12)
    block=src[start:end]
    script=r'''const {spawnSync}=await import('node:child_process');
let handler;const z=new Proxy(()=>z,{get:()=>z});
const server={tool:(...args)=>handler=args.at(-1)};
const assertSafePath=()=>{},optPath=()=>{},optNoShellMeta=()=>{},guardError=e=>({success:false,error:String(e)});
const _probeDocker=()=>({ok:true}),wrapResult=x=>x;
function dockerExec(cmd){const r=spawnSync('bash',['-c',cmd],{encoding:'utf8'});return {success:r.status===0,output:r.stdout,error:r.stderr};}
BLOCK
console.log(JSON.stringify(await handler(PARAMS)));
'''.replace('BLOCK',block).replace('PARAMS',json.dumps({'lib':str(lib),'techlef':str(tech),'celllef':str(cells)}))
    r=subprocess.run(["node","--input-type=module","-e",script],capture_output=True,text=True)
    assert r.returncode==0,r.stderr
    return json.loads(r.stdout)

@pytest.mark.parametrize("ws",[" ","   ","\t\t","\n  "," \n\t"])
def test_actual_handler_legal_whitespace(tmp_path,ws):
    text=''.join(f'  LAYER m{i}\n TYPE{ws}ROUTING ;\n END m{i}\n' for i in range(7))
    text+='LAYER v1 TYPE\tCUT ; END v1\n'
    r=_handler(tmp_path,text)
    assert r['success'] is True,r
    assert any(f['check']=='tech_lef_layers' and f['message']=='8 layers (7 routing, 1 cut)' for f in r['findings'])

def test_actual_handler_comments_properties_and_via_references(tmp_path):
    text=''.join(f'LAYER m{i} TYPE ROUTING ; END m{i}\n' for i in range(3))
    text+='# LAYER fake TYPE ROUTING ; END fake\nPROPERTY note "TYPE ROUTING ; LAYER fake # quoted" ;\nVia ref LAYER m0 ; RECT 0 0 1 1 ; END ref\n'
    r=_handler(tmp_path,text)
    assert r['success'] is True,r
    assert any(f['check']=='tech_lef_layers' and f['message']=='3 layers (3 routing, 0 cut)' for f in r['findings'])

@pytest.mark.parametrize("text",[None,'LAYER x TYPE ROUTING END x','LAYER x TYPE ROUTING ;','LAYER x TYPE ROUTING ; TYPE ROUTING ; END x','LAYER x TYPE FAKE ; END x'])
def test_actual_handler_unreadable_or_malformed_is_not_count_zero(tmp_path,text):
    r=_handler(tmp_path,text)
    assert r['success'] is False
    assert any(f['check']=='tech_lef_parse_unavailable' for f in r['findings'])
    assert not any(f['check']=='tech_lef_layers' for f in r['findings'])

@pytest.mark.parametrize("count",[0,1,2])
def test_actual_handler_insufficient_measured_routing_refused(tmp_path,count):
    r=_handler(tmp_path,''.join(f'LAYER m{i} TYPE ROUTING ; END m{i}\n' for i in range(count)))
    assert r['success'] is False
    assert any(f['check']=='tech_lef_routing_layers' for f in r['findings'])
    assert not any(f['check']=='tech_lef_parse_unavailable' for f in r['findings'])
