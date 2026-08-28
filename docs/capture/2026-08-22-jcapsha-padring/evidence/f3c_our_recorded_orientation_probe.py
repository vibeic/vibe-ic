"""F3c, MEASURED rather than derived.

Claim: our step's side-to-variable mapping is inverted against the tool's
documented contract, so a run that declares one of the two rotations gets a DEF
from us that contradicts what the tool produces for the same declaration.

Both halves are measured:
  ours  -- drive pad_ring_gen and read the orientation it RECORDS per side
  tool  -- already measured in evidence/rotation_two_arm_MEASURED.txt, at the
           same declaration, in its own process
"""
import json, os, pathlib, sys, tempfile
from pathlib import Path
HERE = Path(os.environ.get("VIBEIC_PROGRAMS")
    # was an absolute path under the capturing operator's home; a probe kept
    # as evidence must still be readable on someone else's machine.
    or str(pathlib.Path(__file__).resolve().parents[4]
           / "vibe-ic-marketplace/plugins/vibe-ic/programs"))
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE / "tests"))
import test_pad_ring as T

for label, over in (("PAD_ROTATION_HORIZONTAL=R90 (vertical left at default)",
                     {"PAD_ROTATION_HORIZONTAL": "R90", "PAD_ROTATION_VERTICAL": "R0"}),
                    ("both at the default R0", 
                     {"PAD_ROTATION_HORIZONTAL": "R0", "PAD_ROTATION_VERTICAL": "R0"})):
    tmp = Path(tempfile.mkdtemp())
    root = T._project(tmp, config=T._config(**over))
    rc = T._gen(root)
    rep = T._report(root)
    by_side = {}
    for pad in rep.get("pads") or []:
        by_side.setdefault(pad["side"] if "side" in pad else "?", set()).add(pad["orient"])
    if not by_side:                       # older shape: derive from instance order
        for pad in rep.get("pads") or []:
            by_side.setdefault("?", set()).add(pad.get("orient"))
    print(f"\n=== {label}")
    print(f"    rc={rc} verdict={rep['verdict']}")
    corners = {c["position"]: c["orient"] for c in (rep.get("corners") or [])}
    print(f"    OURS, orientation recorded per side: "
          f"{ {k: sorted(v) for k, v in by_side.items()} }")
    print(f"    corners: {corners}")
