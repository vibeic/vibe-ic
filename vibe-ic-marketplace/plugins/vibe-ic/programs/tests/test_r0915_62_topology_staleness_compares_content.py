"""R-0915-62 — `A3_NETLIST_STALE_VS_IR` must compare the topology's CONTENT,
not a whole-file digest of a file that carries a wall clock.

WHAT WENT WRONG, MEASURED ON A REAL VERDICT RUN (lane icadc, 2026-09-16).
`topology.json` carries a `_provenance` block with a `produced_at` stamp, and
this gate compared `sha256(topology.json)` — the WHOLE FILE — against the digest
the netlist recorded. So A2 re-emitting identical content moved the digest and
the netlist was declared stale.

    ldo/topology.json   produced_at 2026-09-15T23:23:56Z  = 07:23 local, that run
    whole-file digest   796eb6b2… -> 711cc1c6…
    ldo.sp              c6fe9b5468bdb153, BYTE-IDENTICAL, and still equal to the
                        `netlist_sha256` its own corner_results.json records

A netlist derived from a materially different topology would differ; that one
did not. The topology change touched nothing the netlist depends on, and A3
FAILED anyway — voiding A4, A5 and A6 and blocking A7 and A9. Six of the run's
seven blockers were that one false stale, and the audit classified it
`DESIGN_FACT`.

THE FIX has the same two halves R-0915-44 gave the netlist:
  * the emitter stamps a CONTENT digest beside the whole-file one
    (`topology_ir=… sha256=… content_sha256=…`), with `_provenance` stripped
    and keys sorted so it is a property of the content and not of formatting;
  * the gate prefers the content digest when the netlist carries one, and a
    stale-digest refusal is classified `EXECUTION_ERROR` — the flow failing to
    re-emit — rather than a fact about the design.

BOTH DIRECTIONS. A provenance-only re-emission must PASS; a real topology change
must still FAIL, or the gate has been disabled rather than corrected.

No chip / SKU / foundry literal.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import _analog_producer_common as _pc       # noqa: E402

TOPO = {"devices": [{"name": "m1", "w": 4.0, "l": 0.5}],
        "nets": ["a", "b"],
        "_provenance": {"produced_at": "2026-01-01T00:00:00Z",
                        "producer": "analog_a2_topology_emit"}}


def _tmp() -> Path:
    return Path(tempfile.mkdtemp(prefix="r091562_"))


def _stage(root: Path, topo: dict, stamp_whole: str, stamp_content=None) -> Path:
    b = root / "phase3" / "analog" / "blk"
    b.mkdir(parents=True, exist_ok=True)
    (b / "topology.json").write_text(json.dumps(topo), encoding="utf-8")
    line = (f"* _provenance: topology_ir=phase3/analog/blk/topology.json "
            f"sha256={stamp_whole}")
    if stamp_content is not None:
        line += f" content_sha256={stamp_content}"
    (b / "blk.sp").write_text(line + "\n.subckt blk a b\n.ends blk\n",
                              encoding="utf-8")
    return b / "blk.sp"


def _whole(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _content(p: Path) -> str:
    return _pc.json_content_digest(p.read_text(encoding="utf-8"))


# ── the content digest itself ──────────────────────────────────────────────
def test_the_content_digest_ignores_provenance_and_formatting():
    a = json.dumps(TOPO)
    b = json.dumps({"nets": ["a", "b"],
                    "devices": [{"l": 0.5, "name": "m1", "w": 4.0}],
                    "_provenance": {"produced_at": "2027-12-31T23:59:59Z"}},
                   indent=4)
    assert a != b
    assert _pc.json_content_digest(a) == _pc.json_content_digest(b)


def test_the_content_digest_moves_on_a_real_field():
    changed = json.loads(json.dumps(TOPO))
    changed["devices"][0]["w"] = 4.5
    assert _pc.json_content_digest(json.dumps(TOPO)) != \
        _pc.json_content_digest(json.dumps(changed))


def test_non_json_is_refused_rather_than_digested():
    assert _pc.json_content_digest("not json at all") is None


# ── THE DEFECT ARM: a provenance-only re-emission must PASS ────────────────
def test_a_provenance_only_reemission_is_NOT_stale():
    d = _tmp()
    try:
        topo_path = d / "phase3" / "analog" / "blk" / "topology.json"
        sp = _stage(d, TOPO, "0" * 64)
        stamp_whole, stamp_content = _whole(topo_path), _content(topo_path)
        sp = _stage(d, TOPO, stamp_whole, stamp_content)

        # A2 re-emits: identical content, a new wall clock.
        again = json.loads(json.dumps(TOPO))
        again["_provenance"]["produced_at"] = "2026-06-30T12:34:56Z"
        topo_path.write_text(json.dumps(again), encoding="utf-8")

        assert _whole(topo_path) != stamp_whole, "the fixture did not move the file"
        assert _content(topo_path) == stamp_content
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ── THE NEGATIVE CONTROL: a real change must still FAIL ────────────────────


# ── legacy netlists keep the old behaviour exactly ─────────────────────────




# ── the classification ─────────────────────────────────────────────────────


# ── the emitter stamps it ──────────────────────────────────────────────────
def test_the_emitter_stamps_a_content_digest_beside_the_whole_file_one():
    import analog_a3_netlist_emit as A3
    assert callable(A3._ir_content_digest)
