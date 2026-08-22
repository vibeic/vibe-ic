"""Drive the PRE-FIX pad_ring_gen at a PDK whose IO LEFs carry only the
SITE-REFERENCE form and whose tech view declares the site, and print what the
refusal artefact actually disclosed."""
import json, sys, tempfile
from pathlib import Path
HERE = Path("/home/reyerchu/_jcapsha_wt/vibe-ic-marketplace/plugins/vibe-ic/programs")
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE / "tests"))
import test_pad_ring as T
import _pad_ring as PR

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
TECH_CFG = """set ::env(PAD_SITE_NAME)        "io_site"
set ::env(PAD_CORNER_SITE_NAME) "io_corner_site"
# Create fake pad sites
# Note: This is needed if site definition are not in LEF
set ::env(PAD_FAKE_SITES) [dict create]
dict set ::env(PAD_FAKE_SITES) "io_site"  "1.0, 350"
dict set ::env(PAD_FAKE_SITES) "io_corner_site" "350, 350"
"""

tmp = Path(tempfile.mkdtemp())
root = T._project(tmp, io_lib=False)
lef = root / "pdk/proc/libs.ref/proc_io/lef"; lef.mkdir(parents=True)
(lef / "io.lef").write_text(REF_ONLY_LEF)
tech = root / "pdk/proc/libs.tech/librelane/proc_io"; tech.mkdir(parents=True)
(tech / "config.tcl").write_text(TECH_CFG)

rc = T._gen(root)
rep = T._report(root)
print("rc =", rc)
print("verdict =", rep["verdict"])
print("reason  =", rep["reason"])
print("io_cell_library =", json.dumps(rep["io_cell_library"], indent=2))
