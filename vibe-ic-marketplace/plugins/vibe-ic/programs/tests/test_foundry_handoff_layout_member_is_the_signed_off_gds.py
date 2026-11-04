"""The foundry hand-off package's layout member IS the signed-off GDS.

MEASURED on spm run23 (lane icspm5): a full phase-3 re-run moved pnr/spm.gds
and stage4/gds/spm.gds a7bf4526... -> 46459f4a... (signed off), while
stage4/foundry_handoff/spm.gds kept a7bf4526... . The runner packaged members
copy-if-absent by HARDLINK; the source's rewrite-by-rename left the link on the
old inode, and nothing compared the member with what was signed off.

Now: `foundry_handoff_pack_gen.package_layout_members` re-derives every member
from the signed-off GDS on every run (by copy) and records member + source
sha256 in mask_spec.json; `foundry_handoff_package_check` (step 38's blocking
gate) refuses a member whose bytes are not the signed-off GDS's.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import foundry_handoff_package_check as C          # noqa: E402

OLD = b"GDS-bytes-a7bf4526-old-run" * 64
NEW = b"GDS-bytes-46459f4a-signed-off" * 64


def _project(tmp: Path, member: bytes, signed: bytes) -> Path:
    for rel, data in (("phase3/stage4/gds/spm.gds", signed),
                      ("phase3/stage3/pnr/spm.gds", signed),
                      ("phase3/stage4/foundry_handoff/spm.gds", member)):
        (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp / rel).write_bytes(data)
    _admit(tmp)
    return tmp


def _admit(project: Path) -> None:
    import _gds_admission as admission
    gate = project / "reports/phase3/prestream_gate.json"
    gate.parent.mkdir(parents=True, exist_ok=True)
    gate.write_text(json.dumps({"verdict": "PASS", "layout_digest": "a" * 64}))
    pnr = project / "phase3/stage3/pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    if not (pnr / "spm.gds").is_file():
        (pnr / "spm.gds").write_bytes(
            (project / "phase3/stage4/gds/spm.gds").read_bytes())
    basis = []
    for name in ("routed.def", "constraint.sdc"):
        path = pnr / name
        path.write_text("synthetic layout input\n")
        basis.append(path)
    admission.admit_gds(project, pnr / "spm.gds", "a" * 64, basis)


def _gate(proj: Path):
    out = proj / "gate.json"
    rc = C.main([str(proj), "--json", str(out)])
    return rc, json.loads(out.read_text())


def test_a_stale_member_is_refused_by_the_gate(tmp_path):
    rc, rep = _gate(_project(tmp_path, OLD, NEW))
    assert rc == 1, rep
    rules = {f["rule"] for f in rep["findings"]}
    assert "FOUNDRY_HANDOFF_STALE_LAYOUT_MEMBER" in rules, rep
    s = rep["stale_layout_members"][0]
    assert s["source"] == "phase3/stage4/gds/spm.gds", s
    assert s["member_sha256"] != s["source_sha256"], s


def test_a_member_equal_to_the_signed_off_gds_is_not_stale(tmp_path):
    proj = _project(tmp_path, NEW, NEW)
    assert C.stale_layout_members(proj) == []
    rc, rep = _gate(proj)
    assert "FOUNDRY_HANDOFF_STALE_LAYOUT_MEMBER" not in {
        f["rule"] for f in rep["findings"]}, rep


def test_the_producer_refreshes_a_hardlinked_member_after_a_re_run(tmp_path):
    """The exact run23 mechanism: member hardlinked to the old signed-off GDS,
    then the signed-off GDS rewritten by rename (a new inode)."""
    import foundry_handoff_pack_gen as G
    proj = tmp_path
    src = proj / "phase3/stage4/gds/spm.gds"
    src.parent.mkdir(parents=True)
    src.write_bytes(OLD)
    hd = proj / "phase3/stage4/foundry_handoff"
    hd.mkdir(parents=True)
    os.link(src, hd / "spm.gds")                    # the old runner's packaging
    tmp = src.with_suffix(".tmp")
    tmp.write_bytes(NEW)
    os.replace(tmp, src)                            # the re-run's stream-out
    assert (hd / "spm.gds").read_bytes() == OLD     # the defect, reproduced
    assert C.stale_layout_members(proj), "the gate must see it"
    _admit(proj)
    rec = G.package_layout_members(proj)
    assert rec["written"] == ["spm.gds"], rec
    assert (hd / "spm.gds").read_bytes() == NEW
    assert not os.path.samefile(hd / "spm.gds", src), "a member is a copy"
    m = rec["members"]["spm.gds"]
    assert m["sha256"] == m["source_sha256"] == C.sha256_file(src), m
    assert m["source"] == "phase3/stage4/gds/spm.gds" and m["signed_off_source"]
    assert C.stale_layout_members(proj) == []


def test_a_fresh_member_is_kept_not_rewritten(tmp_path):
    import foundry_handoff_pack_gen as G
    proj = _project(tmp_path, NEW, NEW)
    rec = G.package_layout_members(proj)
    assert rec["kept"] == ["spm.gds"] and rec["written"] == [], rec


def test_the_signed_off_gds_wins_over_a_pnr_gds_of_the_same_name(tmp_path):
    proj = _project(tmp_path, OLD, NEW)
    (proj / "phase3/stage3/pnr/spm.gds").write_bytes(OLD)     # pre-finishing
    assert C.layout_member_sources(proj)["spm.gds"] == \
        proj / "phase3/stage4/gds/spm.gds"
    assert C.stale_layout_members(proj), "OLD member vs NEW signed-off"


def test_a_recorded_digest_that_no_longer_matches_is_refused(tmp_path):
    proj = _project(tmp_path, NEW, NEW)
    (proj / "phase3/stage4/foundry_handoff/mask_spec.json").write_text(
        json.dumps({"layout_members": {"spm.gds": {"sha256": "0" * 64}}}))
    stale = C.stale_layout_members(proj)
    assert stale and "records a different digest" in stale[0]["why"], stale


def test_pnr_layouts_remain_the_fallback_when_no_final_gds_exists(tmp_path):
    pnr = tmp_path / 'phase3/stage3/pnr'
    pnr.mkdir(parents=True)
    legacy = pnr / 'legacy_name.gds'
    legacy.write_bytes(OLD)
    final = tmp_path / 'phase3/stage4/gds'
    final.mkdir(parents=True)
    # Comparison-only data is not a signed-off layout set.
    (final / 'comparison.prefinish.gds').write_bytes(NEW)
    assert C.layout_member_sources(tmp_path) == {legacy.name: legacy}
