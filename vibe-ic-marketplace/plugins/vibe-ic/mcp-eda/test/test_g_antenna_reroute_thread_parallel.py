"""G-ANTENNA-REROUTE (MCP parity) — port the phase3 PnR-session parallelization
to the MCP `eda_pnr` tool (the SECONDARY, agentic PnR path), which emits its OWN
OpenROAD Tcl.

Background: OpenROAD DEFAULTS TO 1 THREAD. The phase3 runner now emits
`set_thread_count N` as the first PnR-Tcl command so global_route / detailed_route
/ the antenna repair loop / CTS all run threaded (measured floor: single-threaded
the subservient/commercial PDK antenna reroute was ~394 s/round and blew the step cap;
at 8 threads 74 s/round and the design reaches GDS in budget). `eda_pnr` must
parallelize identically or the two PnR paths drift.

What is tested:
  1. The real JS helper (`src/lib/pnr_threads.mjs`) under node returns a positive
     int thread count; VIBEIC_OPENROAD_THREADS overrides (int or "max").
  2. `threadCountTcl()` emits a single `set_thread_count N` line.
  3. index.js IMPORTS the helper and places `threadCountTcl()` at the TOP of the
     eda_pnr Tcl — before global_route / detailed_route (provable parity).
chip/PDK-AGNOSTIC (machine property only).
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import sys
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
THREADS_MJS = MCP_ROOT / "src" / "lib" / "pnr_threads.mjs"

node = shutil.which("node")
needs_node = pytest.mark.skipif(node is None, reason="node not installed")


def _node(js: str, env: dict | None = None) -> str:
    import os
    e = dict(os.environ)
    if env:
        e.update(env)
    r = _pr.run([node, "-e", js], capture_output=True, text=True,
                       env=e)
    assert r.returncode == 0, r.stderr
    return r.stdout


@needs_node
def test_thread_count_helper_positive_int():
    out = _node(
        f"import({str(THREADS_MJS)!r}).then(m => "
        f"process.stdout.write(String(m.openroadThreadCount())))",
        env={"VIBEIC_OPENROAD_THREADS": ""})
    assert out.strip().isdigit() and int(out.strip()) >= 1


@needs_node
def test_thread_count_helper_env_override_int():
    out = _node(
        f"import({str(THREADS_MJS)!r}).then(m => "
        f"process.stdout.write(String(m.openroadThreadCount())))",
        env={"VIBEIC_OPENROAD_THREADS": "6"})
    assert out.strip() == "6"


@needs_node
def test_thread_count_helper_env_invalid_falls_back():
    out = _node(
        f"import({str(THREADS_MJS)!r}).then(m => "
        f"process.stdout.write(String(m.openroadThreadCount())))",
        env={"VIBEIC_OPENROAD_THREADS": "nonsense"})
    assert out.strip().isdigit() and int(out.strip()) >= 1


@needs_node
def test_thread_count_tcl_line():
    out = _node(
        f"import({str(THREADS_MJS)!r}).then(m => "
        f"process.stdout.write(m.threadCountTcl()))",
        env={"VIBEIC_OPENROAD_THREADS": "5"})
    assert out.strip() == "set_thread_count 5"


def test_index_js_imports_and_places_thread_count_first():
    src = INDEX_JS.read_text()
    assert 'from "./lib/pnr_threads.mjs"' in src
    assert "threadCountTcl" in src
    # It leads the eda_pnr Tcl template — emitted immediately before the first
    # read_lef, so it governs the whole session (global_route / detailed_route /
    # antenna repair loop / CTS all run threaded).
    assert "${threadCountTcl()}read_lef " in src
    # ...and the interpolation point precedes global_route inside the template
    # body (global_route -verbose appears only in the emitted tclScript).
    i_tc = src.index("${threadCountTcl()}read_lef ")
    assert i_tc < src.index("global_route -verbose")
