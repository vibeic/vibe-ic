#!/usr/bin/env python3
"""Tests for ORGANIC #144 — eda_analog_layout geometry-emptiness honesty.

BEFORE the fix, `eda_analog_layout` ran a Magic TCL that is `readspice` +
`gds write` + `puts INFO` (no placement) and returned `success: exitCode === 0`
— so an EMPTY-geometry stream (netlist loaded, nothing placed) was reported as
a real DONE layout. This test proves:

  A. Static checks on src/index.js — the tool imports the geometry detector,
     gates DRC/LVS on real geometry (`layoutOk`), and no longer sets
     `success = exitCode === 0` unconditionally (SCAFFOLD path exists).

  B. Runtime checks on src/lib/analog_layout_geometry.mjs via node — the
     no-leak pair: a GDS/.mag carrying real geometry → status DONE
     (hasGeometry:true); an empty-geometry stream → status SCAFFOLD
     (hasGeometry:false, success would be false).

Skips runtime checks if node is not on PATH.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

MCP_ROOT = Path(__file__).resolve().parent.parent
INDEX_JS = MCP_ROOT / "src" / "index.js"
GEOM_MJS = MCP_ROOT / "src" / "lib" / "analog_layout_geometry.mjs"


# ── A. static checks on the wiring ─────────────────────────────────────────

def test_index_imports_geometry_detector() -> None:
    src = INDEX_JS.read_text()
    assert "analog_layout_geometry.mjs" in src
    assert "layoutHasGeometry" in src


def test_index_gates_drc_lvs_on_geometry() -> None:
    src = INDEX_JS.read_text()
    # DRC/LVS may only run when magic ran AND real geometry exists.
    assert "const layoutOk = exitCode === 0 && geom.hasGeometry" in src
    assert "if (drc_check && layoutOk)" in src
    assert "if (lvs_check && layoutOk)" in src


def test_index_no_unconditional_success_and_has_scaffold_status() -> None:
    src = INDEX_JS.read_text()
    # The old blanket `result.success = exitCode === 0;` is GONE.
    assert "result.success = exitCode === 0;" not in src
    # The honest SCAFFOLD path exists.
    assert '"SCAFFOLD"' in src or "SCAFFOLD" in src
    assert "geom.hasGeometry" in src
    # The manifest records the real status, not a hardcoded PASS.
    assert "status: result.status" in src


# ── B. runtime no-leak proof on the detector module ────────────────────────

NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_geometry_detector_no_leak_pair(tmp_path: Path) -> None:
    # A real GDS: one BOUNDARY (0x08) record + padding.
    (tmp_path / "real.gds").write_bytes(bytes([0x00, 0x04, 0x08, 0x00]) + b"\x00" * 508)
    # An empty-geometry GDS: HEADER record + padding, NO geometry record.
    (tmp_path / "empty.gds").write_bytes(bytes([0x00, 0x06, 0x00, 0x02]) + b"\x00" * 508)

    script = f"""
import {{ layoutHasGeometry, gdsGeometryCount, magGeometryCount }} from {json.dumps(str(GEOM_MJS))};
const real = layoutHasGeometry({{ gdsPath: {json.dumps(str(tmp_path / 'real.gds'))} }});
const empty = layoutHasGeometry({{ gdsPath: {json.dumps(str(tmp_path / 'empty.gds'))} }});
const none = layoutHasGeometry({{ gdsPath: {json.dumps(str(tmp_path / 'nope.gds'))} }});
const magReal = magGeometryCount("magic\\ntech sky130A\\nrect 0 0 100 100\\n");
const magStub = magGeometryCount("magic\\n# padding " + "x".repeat(400));
console.log(JSON.stringify({{ real, empty, none, magReal, magStub }}));
"""
    r = subprocess.run([NODE, "--input-type=module", "-e", script],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    # Real geometry → DONE / hasGeometry true.
    assert out["real"]["hasGeometry"] is True
    assert out["real"]["status"] == "DONE"
    # Empty-geometry stream → SCAFFOLD, never a success.
    assert out["empty"]["hasGeometry"] is False
    assert out["empty"]["status"] == "SCAFFOLD"
    # No artefact at all → SCAFFOLD.
    assert out["none"]["status"] == "SCAFFOLD"
    # .mag parse: real paint vs padded stub.
    assert out["magReal"] >= 1
    assert out["magStub"] == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
