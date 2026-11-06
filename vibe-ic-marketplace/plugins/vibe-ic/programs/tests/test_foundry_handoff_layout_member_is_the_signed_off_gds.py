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






def _gate(proj: Path):
    out = proj / "gate.json"
    rc = C.main([str(proj), "--json", str(out)])
    return rc, json.loads(out.read_text())














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
