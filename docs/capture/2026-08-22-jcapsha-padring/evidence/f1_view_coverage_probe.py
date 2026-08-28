"""The predicate that SURVIVES for F1, and its control.

NOT 'say which views you read' — measured earlier, the pre-fix refusal already
said that. NOT 'pin the input set against upstream' — measured just now, the
dropped variable is in no enumerable upstream input set for this step.

The one with teeth: A REFUSAL ON ABSENCE MUST HAVE READ EVERY VIEW THE
DISTRIBUTION SHIPS FOR THAT CLASS OF THING. A PDK tree's view directories are
a fixed, small, ON-DISK set. A step that opened files under one of them and
concluded 'not found' consulted one view of N, and the artefact it already
emits records exactly which files it opened -- so the comparison is a set
difference over directories that exist, with no judgement in it.
"""
import os
import pathlib
import json, sys, tempfile
from pathlib import Path
HERE = Path(os.environ.get("VIBEIC_PROGRAMS")
    # was an absolute path under the capturing operator's home; a probe kept
    # as evidence must still be readable on someone else's machine.
    or str(pathlib.Path(__file__).resolve().parents[4]
           / "vibe-ic-marketplace/plugins/vibe-ic/programs"))
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE / "tests"))
import test_pad_ring as T

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


def build():
    tmp = Path(tempfile.mkdtemp())
    root = T._project(tmp, io_lib=False)
    lef = root / "pdk/proc/libs.ref/proc_io/lef"; lef.mkdir(parents=True)
    (lef / "io.lef").write_text(REF_ONLY_LEF)
    tech = root / "pdk/proc/libs.tech/librelane/proc_io"; tech.mkdir(parents=True)
    (tech / "config.tcl").write_text(TECH_CFG)
    return root


def view_dirs(pdk_tree: Path):
    """Every top-level view directory the distribution ships. On disk, enumerated."""
    return sorted(p.name for p in pdk_tree.iterdir() if p.is_dir())


def views_read(report: dict):
    """Which view directories the paths in the artefact actually came from."""
    lib = report.get("io_cell_library") or {}
    paths = list(lib.get("lefs") or []) + list(lib.get("site_declarations") or [])
    out = set()
    for p in paths:
        parts = Path(p).parts
        for i, seg in enumerate(parts):
            if seg.startswith("libs."):
                out.add(seg)
    return sorted(out)


root = build()
rc = T._gen(root)
rep = T._report(root)
tree = root / "pdk/proc"
ships, read = view_dirs(tree), views_read(rep)
unread = sorted(set(ships) - set(read))
print(f"verdict          : {rep['verdict']} (rc {rc})")
print(f"refuses on absence: {rep['reason'].startswith('PAD_SITE_NOT_FOUND')}")
print(f"views the distribution ships : {ships}")
print(f"views the artefact says it read: {read}")
print(f"UNREAD VIEWS     : {unread}")
print(f"PREDICATE FIRES  : {bool(unread) and rep['reason'].startswith('PAD_SITE_NOT_FOUND')}")
