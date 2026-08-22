"""A NON-PAD entry in the upstream-parity register, and its two-sided pin.

WHY A SECOND SUBJECT MATTERS
============================
The register shipped with two entries and both were `pad_ring.*`. A rule whose
only instances are pads reads as a pad rule however carefully its docstring is
worded, and the general-core test asks whether the LOGIC touches a pad. It does
not: this entry is a Magic command sequence for writing a hardmacro's LEF
abstract, and it exercises the same register unchanged.

WHAT IS RE-IMPLEMENTED
======================
`digital_hardmacro_gen.build_lef_tcl` emits the Magic TCL that
`librelane/scripts/magic/lef.tcl` runs. Upstream has TWO routes and
`MAGIC_LEF_WRITE_USE_GDS` picks between them; its default is FALSE, which reads
the views and the DEF rather than the GDS alone.

That default is load-bearing and the producer's docstring records what taking
the other route cost: an abstract with an outline, obstructions, and ZERO PINS,
because the port labels sit on layers the PDK's Magic technology does not map.
Adding the DEF read produced pins matching the DEF's own count.

So the invariant is: GEOMETRY from the GDS, PORTS from the DEF, and the two
abstraction knobs spelled the way upstream spells them.

WHEN THE DISTRIBUTION IS NOT REACHABLE the upstream half SKIPS and names the
missing input. It does not pass. Our half needs nothing external and always
runs.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PROGRAMS = HERE.parent
sys.path.insert(0, str(PROGRAMS))

import digital_hardmacro_gen as GEN   # noqa: E402
REGISTER = PROGRAMS / "upstream_contract_parity.json"
ENTRY_ID = "digital_hardmacro.lef_write_route"
ENV_ROOT = "VIBEIC_UPSTREAM_ROOT"
FALLBACKS = ("/usr/local/lib/python3.12/dist-packages",
             "/usr/lib/python3/dist-packages")


def _entry() -> dict:
    doc = json.loads(REGISTER.read_text(encoding="utf-8"))
    for e in doc["entries"]:
        if e.get("id") == ENTRY_ID:
            return e
    raise AssertionError(f"{ENTRY_ID} is not in the register")


def _upstream_text() -> tuple[str, Path]:
    rel = _entry()["upstream"]["file"]
    roots = [os.environ[ENV_ROOT]] if os.environ.get(ENV_ROOT) else []
    roots += list(FALLBACKS)
    for r in roots:
        p = Path(r) / rel
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace"), p
    pytest.skip(
        f"upstream {rel} is not readable under any of {roots}. Set "
        f"{ENV_ROOT} to a distribution root. NOT a pass: the upstream half of "
        f"this invariant was not checked.")


# ── THEIR half ──────────────────────────────────────────────────────────────

def test_the_file_is_the_one_the_register_snapshotted():
    text, path = _upstream_text()
    recorded = _entry()["snapshot"]["file_sha256"]
    actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert actual == recorded, (
        f"{path} has changed since the register snapshotted it. Recorded "
        f"{recorded[:12]}, read {actual[:12]}. Re-measure the entry.")


def test_upstream_still_has_two_routes_and_the_default_reads_the_def():
    """`MAGIC_LEF_WRITE_USE_GDS` true -> GDS alone; false -> views + DEF."""
    text, path = _upstream_text()
    m = re.search(r"if \{ \$::env\(MAGIC_LEF_WRITE_USE_GDS\) \} \{(.*?)\} else \{(.*?)\n\}",
                  text, re.S)
    assert m, f"{path}: the two-route branch on MAGIC_LEF_WRITE_USE_GDS is gone."
    gds_route, def_route = m.group(1), m.group(2)
    assert "gds read" in gds_route, f"{path}: the TRUE route no longer reads the GDS."
    assert "read_def" in def_route, (
        f"{path}: the FALSE route -- upstream's DEFAULT, and the one this "
        f"producer mirrors -- no longer reads the DEF. Taking the GDS-only "
        f"route produced a LEF with zero pins on a real run.")


def test_upstream_spells_the_two_abstraction_knobs_the_way_we_emit_them():
    text, path = _upstream_text()
    assert "lappend lefwrite_opts -hide" in text, (
        f"{path}: `-hide` is no longer how upstream asks for the abstract view.")
    assert "lappend lefwrite_opts -pinonly" in text, (
        f"{path}: `-pinonly` is no longer upstream's spelling.")
    assert re.search(r"if \{ \$::env\(MAGIC_WRITE_FULL_LEF\) \} \{", text), (
        f"{path}: `-hide` is no longer conditioned on MAGIC_WRITE_FULL_LEF.")


# ── OUR half ────────────────────────────────────────────────────────────────

def test_we_take_the_default_route_geometry_from_gds_ports_from_def():
    tcl = GEN.build_lef_tcl("top", "a.gds", "b.def", "o.lef",
                               full_lef=False, pinonly=False)
    assert "gds read a.gds" in tcl, tcl
    assert "def read b.def" in tcl, (
        "the DEF read is what supplies the PORTS; without it the abstract "
        "comes out with no pins at all.\n" + tcl)


def test_hide_is_emitted_for_the_abstract_and_withheld_for_the_full_lef():
    g = GEN
    assert "-hide" in g.build_lef_tcl("t", "g", "d", "o", full_lef=False,
                                      pinonly=False)
    assert "-hide" not in g.build_lef_tcl("t", "g", "d", "o", full_lef=True,
                                          pinonly=False)


def test_pinonly_is_emitted_only_when_asked():
    g = GEN
    assert "-pinonly" in g.build_lef_tcl("t", "g", "d", "o", full_lef=False,
                                         pinonly=True)
    assert "-pinonly" not in g.build_lef_tcl("t", "g", "d", "o", full_lef=False,
                                             pinonly=False)
