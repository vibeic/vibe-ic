"""THIRD formulation. The first two over-fired; this one is decidable on disk.

NOT "did you read every view" -- 8 of the 10 in-scope programs read exactly one
view, for good reasons, and a rule that fires on all of them is a bug.

INSTEAD:  A REFUSAL THAT A DECLARED NAME IS ABSENT MUST BE FALSIFIED AGAINST
          THE VIEWS THAT WERE NOT READ. It fires only when the refused NAME is
          actually FINDABLE in a view the step did not open.

That is a grep over directories that exist for a string the step itself chose,
so it has no judgement in it, and it CANNOT fire on a step that read one view
and was right -- the name simply is not there.
"""
import os
import pathlib
import json, sys, tempfile
from pathlib import Path
import importlib

PROGRAMS = Path(sys.argv[1] if len(sys.argv) > 1 else
    os.environ.get("VIBEIC_PROGRAMS")
    # was an absolute path under the capturing operator's home; a probe kept
    # as evidence must still be readable on someone else's machine.
    or str(pathlib.Path(__file__).resolve().parents[4]
           / "vibe-ic-marketplace/plugins/vibe-ic/programs"))
sys.path.insert(0, str(PROGRAMS)); sys.path.insert(0, str(PROGRAMS / "tests"))
T = importlib.import_module("test_pad_ring")

REF_ONLY_LEF = """VERSION 5.8 ;
UNITS
  DATABASE MICRONS 1000 ;
END UNITS
MACRO pad_bidir
  CLASS PAD ;
  SIZE 75 BY 350 ;
  SITE io_site ;
END pad_bidir
MACRO pad_corner
  CLASS PAD ;
  SIZE 350 BY 350 ;
  SITE io_corner_site ;
END pad_corner
MACRO pad_fill1
  CLASS PAD ;
  SIZE 1 BY 350 ;
  SITE io_site ;
END pad_fill1
END LIBRARY
"""
TECH_CFG = '''set ::env(PAD_SITE_NAME)        "io_site"
set ::env(PAD_CORNER_SITE_NAME) "io_corner_site"
set ::env(PAD_FAKE_SITES) [dict create]
dict set ::env(PAD_FAKE_SITES) "io_site"  "1.0, 350"
dict set ::env(PAD_FAKE_SITES) "io_corner_site" "350, 350"
'''


def build(with_tech=True):
    tmp = Path(tempfile.mkdtemp())
    root = T._project(tmp, io_lib=False)
    lef = root / "pdk/proc/libs.ref/proc_io/lef"; lef.mkdir(parents=True)
    (lef / "io.lef").write_text(REF_ONLY_LEF)
    if with_tech:
        tech = root / "pdk/proc/libs.tech/librelane/proc_io"; tech.mkdir(parents=True)
        (tech / "config.tcl").write_text(TECH_CFG)
    return root


def falsify(report, pdk_tree: Path):
    """Fires only when the refused NAME is findable in a view that was not read."""
    reason = report.get("reason", "")
    if "_NOT_FOUND" not in reason and "_ABSENT" not in reason:
        return None, "verdict does not refuse on absence"
    # the name the step refused on, taken from its own report
    name = (report.get("config") or {}).get("PAD_SITE_NAME")
    if not name:
        return None, "no refused name in the artefact"
    lib = report.get("io_cell_library") or {}
    read = set()
    for p in list(lib.get("lefs") or []) + list(lib.get("site_declarations") or []):
        for seg in Path(p).parts:
            if seg.startswith("libs."):
                read.add(seg)
    unread = [d for d in pdk_tree.iterdir() if d.is_dir() and d.name not in read]
    found_in = []
    for d in unread:
        for f in d.rglob("*"):
            if f.is_file():
                try:
                    if name in f.read_text(errors="replace"):
                        found_in.append(str(f.relative_to(pdk_tree))); break
                except OSError:
                    pass
        if found_in:
            break
    return (bool(found_in), f"refused {name!r}; unread views "
            f"{[d.name for d in unread]}; findable in {found_in or 'none'}")


for label, with_tech in (("PDK DOES declare it in the other view", True),
                         ("PDK declares it NOWHERE (the control)", False)):
    root = build(with_tech)
    rc = T._gen(root)
    rep = T._report(root)
    fires, why = falsify(rep, root / "pdk/proc")
    print(f"\n=== {label}")
    print(f"    rc {rc}  verdict {rep['verdict']}")
    print(f"    {why}")
    print(f"    PREDICATE FIRES: {fires}")
