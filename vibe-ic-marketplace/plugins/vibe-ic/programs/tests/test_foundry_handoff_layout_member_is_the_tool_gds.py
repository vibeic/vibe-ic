"""Migration 38: with step 37 on LibreLane, the hand-off layout member IS the
tool's final GDS.

review70 step 38 (EXTERNAL_NOT_SOFTWARE, P4): no LibreLane/OpenROAD step writes
a mask spec, WAT plan or scribe frame, so step 38 stays a vibe-ic packaging gate
-- "but source its layout member from LibreLane's final GDS so the
prefinish/stale-member defects cannot recur".

`librelane_step37.run` records the finished GDS it promoted in
`phase3/librelane/37-promotion.json` (`source_sha256`, `canonical`). The
existing stale-member rule compares the member with the signed-off COPY; a copy
rewritten after promotion (and the member re-derived from it) passes that rule
while shipping bytes the tool never produced. `foundry_handoff_package_check`
now refuses that under FOUNDRY_HANDOFF_LAYOUT_NOT_THE_TOOL_OUTPUT. Direct mode
has no tool record and is judged exactly as before.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_TESTS = Path(__file__).resolve().parent
for _p in (_PROGRAMS, _TESTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import foundry_handoff_package_check as C                      # noqa: E402

TOOL = b"GDS-bytes-librelane-klayout-density-finished" * 64
REFINISHED = b"GDS-bytes-rewritten-in-place-after-promotion" * 64
RULE = "FOUNDRY_HANDOFF_LAYOUT_NOT_THE_TOOL_OUTPUT"


def _project(tmp: Path, *, shipped: bytes, tool: bytes | None,
             mode: str | None) -> Path:
    for rel in ("phase3/stage4/gds/spm.gds", "phase3/stage3/pnr/spm.gds",
                "phase3/stage4/foundry_handoff/spm.gds"):
        (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp / rel).write_bytes(shipped)
    if mode is not None:
        (tmp / "phase3/librelane_switch.json").write_text(
            json.dumps({"steps": {"37": mode}}))
    if tool is not None:
        fin = tmp / "phase3/librelane/37-magic-finish/03-klayout-density/spm.gds"
        fin.parent.mkdir(parents=True, exist_ok=True)
        fin.write_bytes(tool)
        (tmp / "phase3/librelane/37-promotion.json").write_text(json.dumps({
            "selection": "magic", "source": str(fin),
            "source_sha256": hashlib.sha256(tool).hexdigest(),
            "canonical": str(tmp / "phase3/stage3/pnr/spm.gds"),
            "canonical_sha256": hashlib.sha256(tool).hexdigest()}))
    return tmp


def _gate(proj: Path):
    out = proj / "gate.json"
    rc = C.main([str(proj), "--json", str(out)])
    return rc, json.loads(out.read_text())


def _rules(rep):
    return {f["rule"] for f in rep["findings"]}


def test_a_member_that_is_not_the_librelane_gds_is_refused(tmp_path):
    """Signed-off copy and member agree with each other (the stale rule is
    silent) but neither is what LibreLane finished."""
    proj = _project(tmp_path, shipped=REFINISHED, tool=TOOL, mode="librelane")
    assert C.stale_layout_members(proj) == []
    rc, rep = _gate(proj)
    assert rc == 1, rep
    assert RULE in _rules(rep), rep
    row = rep["tool_layout_binding"][0]
    assert row["tool_source_sha256"] == hashlib.sha256(TOOL).hexdigest(), row
    assert row["member_sha256"] == hashlib.sha256(REFINISHED).hexdigest(), row


def test_dual_mode_is_bound_the_same_way(tmp_path):
    proj = _project(tmp_path, shipped=REFINISHED, tool=TOOL, mode="dual")
    rc, rep = _gate(proj)
    assert rc == 1 and RULE in _rules(rep), rep


def test_a_librelane_switch_without_a_promotion_receipt_is_refused(tmp_path):
    """No receipt: nothing shows the member came from the tool."""
    proj = _project(tmp_path, shipped=TOOL, tool=None, mode="librelane")
    rc, rep = _gate(proj)
    assert rc == 1 and RULE in _rules(rep), rep
    assert "37-promotion.json" in rep["tool_layout_binding"][0]["why"], rep


def test_the_tool_gds_itself_is_accepted(tmp_path):
    """The alarm can stay silent: member == signed-off == LibreLane bytes."""
    proj = _project(tmp_path, shipped=TOOL, tool=TOOL, mode="librelane")
    assert C.tool_layout_binding(proj) == []
    rc, rep = _gate(proj)
    assert RULE not in _rules(rep), rep


def test_direct_mode_ignores_a_leftover_promotion_receipt(tmp_path):
    """A receipt from an earlier LibreLane attempt does not bind a direct run."""
    proj = _project(tmp_path, shipped=REFINISHED, tool=TOOL, mode=None)
    assert C.tool_layout_binding(proj) == []
    rc, rep = _gate(proj)
    assert RULE not in _rules(rep), rep
