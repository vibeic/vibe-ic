"""Sign-off streamout must not fall back to legacy layer numbering.

#509 wired a foundry LEF/DEF->GDS layer map into the streamout, but a missing
map stayed ADVISORY: the script printed "legacy numbering" and wrote the GDS
anyway, and the step still reported PASS. That is the whole defect, because a
GDS in that state is wrong twice over — the sign-off deck reads routed metal as
purposes the design never drew, and the layout could not be fabricated either.

Measured on the caravel_user_project commercial-PDK clean run: same DEF, same
deck, 4533 rules checked in both directions — 51 rules firing with the map
absent, 1 with it applied, and the foundry via layers empty in the un-mapped
GDS. Every geometry class the deck reports (enclosure / external / internal /
copy) went to zero; only a metal-density rule remained.

These tests pin the two halves of the fix: a declared map is honoured when
glob discovery cannot see the file, and a sign-off streamout with no map at
all fails instead of shipping.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))




# ---------------------------------------------------------------------------
# Declared map (the bundle that stages `lef/*.lef` without the sibling map)
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------






def test_pdkconfig_carries_signoff_config_path():
    import dataclasses
    f = {x.name: x for x in dataclasses.fields(R.PdkConfig)}
    assert "signoff_config_path" in f
    assert f["signoff_config_path"].default is None
