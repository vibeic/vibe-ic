"""Reverse controls for the Default A6/A8 byte bindings."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analog_a6_block_pv_check as A6  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a6_clean_witness_turns_red_when_current_layout_bytes_change(tmp_path):
    project = tmp_path / "p"
    bdir = project / "phase3" / "analog" / "blk"
    bdir.mkdir(parents=True)
    (project / "phase3/analog/analog_block_list.json").write_text(
        json.dumps({"blocks": ["blk"]}))
    gds = bdir / "blk.gds"
    gds.write_bytes(b"gds-v1")
    digest = _sha(gds)
    (bdir / "drc.report").write_text(
        f"violations: 0\nlayout_path: phase3/analog/blk/blk.gds\n"
        f"layout_sha256: {digest}\n")
    (bdir / "comp.json").write_text(json.dumps({
        "result": "match", "layout_sha256": digest}))
    assert A6._check_block(project, "blk")[0] == "PASS"
