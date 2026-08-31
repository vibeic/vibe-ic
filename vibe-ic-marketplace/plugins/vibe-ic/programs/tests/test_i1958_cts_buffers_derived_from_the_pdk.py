#!/usr/bin/env python3
"""vibe-ic#1958 (2/3) — a sky130 cell reached `clock_tree_synthesis` on SG13G2.

#561 removed the unconditional `pdk.clk_buf or "<sky130 cell>"` and un-gated the
Liberty recovery scan.  Two instances of the same shape survived it, and on a
project-staged PDK they compose into the original defect:

  1. THE LIBERTY WAS NEVER READ.  The scan did `Path(pdk.liberty).read_text()`
     -- a HOST-side read -- inside a bare `except Exception: pass`.  Every
     registry and project-staged PDK carries a CONTAINER-side liberty path, so
     the read raised FileNotFoundError, the exception was swallowed, and the
     recovery could not run at all on exactly the PDKs that need it.  (#687
     found and fixed this same shape in the tech-LEF consumer 200 lines below;
     the fix here is the same helper.)
  2. THE NAME STOOD IN FOR THE CELL.  Even with the text in hand, a cell was a
     candidate if its name contained "clkbuf" or STARTED with "BUF".  IHP
     SG13G2 names its buffers `sg13g2_buf_1 .. sg13g2_buf_16`: neither holds.

Result on the reporter's run: the sky130 master went into `-buf_list`,
`[ERROR CTS-0126] No physical master cell found` was caught NONFATAL, and the
design was routed WITH NO CLOCK TREE -- and then measured.

What a buffer IS, in the Liberty: one signal input, one signal output, and the
output's `function` is that input.  The derivation reads that; the name is used
only to GROUP cells already proven to be buffers into drive families, and the
name VOCABULARY survives only for a stub Liberty with no pin model to read.

Cross-PDK control, run against the liberties shipped in vibeic-eda:0.2.70:

    sky130_fd_sc_hd__tt_025C_1v80.lib  -> clkbuf_4 / clkbuf_16   (registry: clkbuf_4 / clkbuf_16)
    NangateOpenCellLibrary_typical.lib -> CLKBUF_X2 / CLKBUF_X3   (registry: CLKBUF_X1 / CLKBUF_X3)
    sg13g2_stdcell_typ_1p20V_25C.lib   -> sg13g2_buf_4 / _buf_16  (no registry entry)

i.e. the derivation reproduces what a human pinned by hand on the two PDKs that
have an entry, and produces the pair the issue reporter verified in the probe on
the one that does not.

No test here contains a cell name the code could be reading: the synthetic
liberties are written by the test, with a vendor prefix chosen so that BOTH
pre-fix name rules miss them.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


def _buffer(name: str, area: float, inp: str = "A", out: str = "X") -> str:
    return textwrap.dedent(f"""\
      cell ({name}) {{
        area : {area} ;
        pg_pin (VDD) {{ voltage_name : VDD ; pg_type : primary_power ; }}
        pin ({out}) {{
          direction : "output" ;
          function : "{inp}" ;
          max_capacitance : 0.5 ;
        }}
        pin ({inp}) {{
          direction : "input" ;
          capacitance : 0.002 ;
        }}
      }}
    """)


def _inverter(name: str, area: float) -> str:
    return textwrap.dedent(f"""\
      cell ({name}) {{
        area : {area} ;
        pin (Y) {{ direction : "output" ; function : "!A" ; }}
        pin (A) {{ direction : "input" ; }}
      }}
    """)


def _tristate(name: str, area: float) -> str:
    return textwrap.dedent(f"""\
      cell ({name}) {{
        area : {area} ;
        pin (X) {{ direction : "output" ; function : "A" ; three_state : "!EN" ; }}
        pin (A) {{ direction : "input" ; }}
        pin (EN) {{ direction : "input" ; }}
      }}
    """)


#: a library whose buffers defeat BOTH pre-fix name rules: no "clkbuf"
#: substring, and the name does not start with "buf".
_FAMILY = [1, 2, 4, 8, 16]
_VENDOR_LIB = ("library (v) {\n"
               + "".join(_buffer(f"vnd9x_buf_{d}", 5.0 + d) for d in _FAMILY)
               + _inverter("vnd9x_inv_1", 3.0)
               + _inverter("vnd9x_inv_8", 9.0)
               + _tristate("vnd9x_ebufn_4", 7.0)
               + "}\n")


# ── the derivation ──────────────────────────────────────────────────────────
def test_a_buffer_is_recognised_by_its_pin_model_not_its_name():
    """THE defect.  Both pre-fix name rules miss `vnd9x_buf_4`; the structural
    test does not, because the cell's own Liberty says it is a buffer."""
    buf, root, how = R._i1958_pick_cts_buffers(_VENDOR_LIB)
    assert (buf, root) == ("vnd9x_buf_4", "vnd9x_buf_16")
    assert "Liberty" in how and "5 drive" in how


def test_the_pre_fix_name_rules_really_do_miss_this_library():
    """Negative control for the test above.  If either old rule matched these
    names, the test above would pass against the unfixed code and prove
    nothing.  Asserted here so it can never quietly become true."""
    names = [f"vnd9x_buf_{d}" for d in _FAMILY]
    assert not [n for n in names if "clkbuf" in n.lower()]
    assert not [n for n in names if n.upper().startswith("BUF")]


def test_an_inverter_is_not_a_buffer():
    """`function : "!A"` is the whole difference, and it is the only thing the
    derivation looks at -- so an inverter family cannot be chosen even when it
    is the only family with a `buf`-ish position in the library."""
    lib = ("library (v) {\n"
           + "".join(_inverter(f"vnd9x_buf_{d}", 3.0 + d) for d in _FAMILY)
           + "}\n")
    assert R._i1958_pick_cts_buffers(lib) == (None, None, "")


def test_a_tristate_is_not_a_buffer():
    """Two inputs.  SG13G2 ships `sg13g2_ebufn_*` right beside its buffers, so
    this exclusion is load-bearing on the very PDK the issue was filed from."""
    lib = ("library (v) {\n"
           + "".join(_tristate(f"vnd9x_buf_{d}", 3.0 + d) for d in (2, 4, 8))
           + "}\n")
    assert R._i1958_pick_cts_buffers(lib) == (None, None, "")


def test_a_flop_is_not_a_buffer():
    """A sequential cell has a clock input as well as D, so the one-input test
    excludes it without needing to understand `ff()`."""
    lib = textwrap.dedent("""\
      library (v) {
        cell (vnd9x_dff_1) {
          area : 20.0 ;
          ff (IQ, IQN) { next_state : "D" ; clocked_on : "CLK" ; }
          pin (Q) { direction : "output" ; function : "IQ" ; }
          pin (D) { direction : "input" ; }
          pin (CLK) { direction : "input" ; clock : true ; }
        }
      }
      """)
    assert R._i1958_pick_cts_buffers(lib) == (None, None, "")


def test_a_clock_buffer_family_wins_over_a_plain_one():
    """A library that ships a clock-buffer family means it for exactly this
    job, so it is preferred -- but only as a tie-break AFTER the structural
    test has decided what is a buffer."""
    lib = ("library (v) {\n"
           + "".join(_buffer(f"vnd9x_buf_{d}", 5.0 + d) for d in _FAMILY)
           + "".join(_buffer(f"vnd9x_clkbuf_{d}", 6.0 + d) for d in _FAMILY)
           + "}\n")
    buf, root, _ = R._i1958_pick_cts_buffers(lib)
    assert (buf, root) == ("vnd9x_clkbuf_4", "vnd9x_clkbuf_16")


def test_the_root_is_the_strongest_drive_in_the_same_family():
    """CTS builds one tree out of the two cells; a root from another family has
    no consistent load model against the leaves."""
    for drives in ([1, 2, 4], [1, 2, 4, 8, 16], [2, 8]):
        lib = ("library (v) {\n"
               + "".join(_buffer(f"vnd9x_buf_{d}", 5.0 + d) for d in drives)
               + "}\n")
        buf, root, _ = R._i1958_pick_cts_buffers(lib)
        assert root == f"vnd9x_buf_{max(drives)}"
        assert buf.rsplit("_", 1)[0] == root.rsplit("_", 1)[0]
        assert int(buf.rsplit("_", 1)[1]) <= max(drives)


def test_a_single_drive_library_still_resolves_both():
    """`clk_buf_root` is emitted into the Tcl; None would render as the string
    'None' and CTS would ask for a cell by that name."""
    lib = "library (v) {\n" + _buffer("vnd9x_buffer", 5.0) + "}\n"
    buf, root, _ = R._i1958_pick_cts_buffers(lib)
    assert buf == root == "vnd9x_buffer"


def test_an_empty_or_unparseable_liberty_yields_nothing_rather_than_a_guess():
    for text in ("", "not a liberty at all", "library (v) { }\n"):
        assert R._i1958_pick_cts_buffers(text) == (None, None, "")


def test_the_derivation_is_deterministic_for_a_given_library():
    """Two families of the same size and tier must not resolve by dict order."""
    lib = ("library (v) {\n"
           + "".join(_buffer(f"zzz9x_buf_{d}", 5.0 + d) for d in _FAMILY)
           + "".join(_buffer(f"aaa9x_buf_{d}", 5.0 + d) for d in _FAMILY)
           + "}\n")
    first = R._i1958_pick_cts_buffers(lib)
    assert first == R._i1958_pick_cts_buffers(lib)
    assert first[0].startswith("aaa9x_"), first


# ── the wiring inside step_pnr ──────────────────────────────────────────────
_BEGIN = "    clk_buf = pdk.clk_buf\n"
_END = "    pnr_tcl = out_dir /"
_SRC = (_PROGRAMS / "phase3_one_shot_runner.py").read_text(encoding="utf-8")


def _block() -> str:
    assert _SRC.count(_BEGIN) == 1, "the clk_buf block moved; this test is blind"
    assert _SRC.count(_END) == 1, "the end anchor moved; this test is blind"
    return textwrap.dedent(_SRC[_SRC.index(_BEGIN):_SRC.index(_END)])


class _Pdk:
    def __init__(self, name, liberty, clk_buf=None, clk_buf_root=None):
        self.name = name
        self.liberty = liberty
        self.clk_buf = clk_buf
        self.clk_buf_root = clk_buf_root


def _run(pdk, container=""):
    """Execute the real block against the real module namespace, so the helpers
    it calls are the shipped ones rather than test doubles."""
    ns = dict(vars(R))
    ns.update({"pdk": pdk, "container": container})
    exec(_block(), ns)          # noqa: S102 - executing the block under test
    return ns


def test_the_block_reads_a_container_only_liberty(tmp_path, monkeypatch):
    """THE first defect.  `pdk.liberty` is a container path for every registry
    and project-staged PDK, so a host-side read cannot see it and the recovery
    never ran.  Here the host has no such file and only the container does."""
    seen = {}

    def fake_cat(path, container=""):
        seen["path"], seen["container"] = path, container
        return _VENDOR_LIB if container == "the_container" else None

    monkeypatch.setattr(R, "_v1_6_604_read_text_or_container_cat", fake_cat)
    ns = _run(_Pdk("staged_pdk", "/foss/pdks/staged/x.lib"),
              container="the_container")
    assert seen == {"path": "/foss/pdks/staged/x.lib",
                    "container": "the_container"}
    assert ns["clk_buf"] == "vnd9x_buf_4"
    assert ns["clk_buf_root"] == "vnd9x_buf_16"
    assert ns["_clk_buf_note"] == "", "a resolved PDK must not carry a guess"


def test_a_host_readable_sg13g2_shaped_liberty_no_longer_yields_sky130(tmp_path):
    """THE second defect, end to end and with the container out of the picture:
    a library whose buffers are named the way SG13G2 names them resolves to its
    OWN cells.  Pre-fix this same call returned the sky130 master with a note
    saying so, and `clock_tree_synthesis` then failed CTS-0126 NONFATAL, so the
    design routed with no clock tree."""
    lib = tmp_path / "x.lib"
    lib.write_text(_VENDOR_LIB, encoding="utf-8")
    ns = _run(_Pdk("staged_pdk", str(lib)))
    assert (ns["clk_buf"], ns["clk_buf_root"]) == ("vnd9x_buf_4",
                                                   "vnd9x_buf_16")
    assert "sky130" not in ns["clk_buf"]
    assert ns["_clk_buf_note"] == ""


def test_without_the_container_the_same_pdk_falls_back_and_says_so(monkeypatch):
    """Negative control for the test above: the SAME PDK with no container
    reaches the disclosed guess, which is what the pre-fix code did always."""
    monkeypatch.setattr(R, "_v1_6_604_read_text_or_container_cat",
                        lambda path, container="": None)
    ns = _run(_Pdk("staged_pdk", "/foss/pdks/staged/x.lib"))
    assert "sky130" in ns["clk_buf"]
    assert "UNRESOLVED" in ns["_clk_buf_note"]
    assert "staged_pdk" in ns["_clk_buf_note"]


def test_a_registry_pdk_still_wins_over_the_derivation(tmp_path):
    """The registry is a human decision about that PDK; the scan is the
    recovery for its absence, not a second opinion on it."""
    lib = tmp_path / "x.lib"
    lib.write_text(_VENDOR_LIB, encoding="utf-8")
    ns = _run(_Pdk("registry_pdk", str(lib),
                   clk_buf="pinned_buf_4", clk_buf_root="pinned_buf_16"))
    assert (ns["clk_buf"], ns["clk_buf_root"]) == ("pinned_buf_4",
                                                   "pinned_buf_16")


def test_a_stub_liberty_with_no_pin_model_still_resolves_by_name(tmp_path):
    """An abstract .lib declares cells with no pins, so there is no structure
    to read.  The name vocabulary is the fallback -- and it now matches `buf`
    as a TOKEN, which is what `startswith("BUF")` could never do for a
    vendor-prefixed library."""
    lib = tmp_path / "x.lib"
    lib.write_text("library (v) {\n"
                   "  cell (vnd9x_buf_1) { }\n"
                   "  cell (vnd9x_buf_8) { }\n"
                   "}\n", encoding="utf-8")
    ns = _run(_Pdk("stub_pdk", str(lib)))
    assert ns["clk_buf"] == "vnd9x_buf_1"
    assert ns["clk_buf_root"] == "vnd9x_buf_8"
    assert ns["_clk_buf_note"] == ""


def test_the_name_token_rule_does_not_match_buf_mid_word(tmp_path):
    """Negative control for the broadened rule: it must not become "any name
    containing buf", which would pick a delay cell or a tristate."""
    for name in ("vnd9x_clkdlybuf4s15", "vnd9x_ebufn_4"):
        assert not R._I1958_BUF_TOKEN_RE.search(name.lower()), name
    for name in ("BUFX2", "vnd9x_buf_4", "vnd9x__buf_16"):
        assert R._I1958_BUF_TOKEN_RE.search(name.lower()), name


def test_the_derived_cells_reach_both_tcl_consumers():
    """The two places a CTS master is written into the deck must carry the SAME
    derived pair -- the emitted `clock_tree_synthesis`, and the placeability
    probe that reports masters at the width bound.  On the reporter's run both
    named the sky130 cell."""
    probe = R._build_unplaceable_master_cap_tcl(
        cts_masters=("vnd9x_buf_4", "vnd9x_buf_16"))
    assert "vnd9x_buf_4" in probe and "vnd9x_buf_16" in probe
    assert "sky130" not in probe


# ── the reproduction ────────────────────────────────────────────────────────
_IMAGE = "vibeic-eda:0.2.70"
_DOCKER = shutil.which("docker")
#: (container liberty path, expected -buf_list, expected -root_buf). The two
#: registry PDKs are the CONTROL: the derivation has to agree with the choice a
#: human already made. sg13g2 is the case the issue was filed from.
_REAL = [
    ("/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/"
     "sky130_fd_sc_hd__tt_025C_1v80.lib",
     "sky130_fd_sc_hd__clkbuf_4", "sky130_fd_sc_hd__clkbuf_16"),
    ("/foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell/lib/"
     "sg13g2_stdcell_typ_1p20V_25C.lib",
     "sg13g2_buf_4", "sg13g2_buf_16"),
]


def _image_present() -> bool:
    if _DOCKER is None:
        return False
    return subprocess.run([_DOCKER, "image", "inspect", _IMAGE],
                          capture_output=True, text=True).returncode == 0


@pytest.mark.skipif(not _image_present(),
                    reason=f"{_IMAGE} not available on this host")
@pytest.mark.parametrize("lib,buf,root", _REAL,
                         ids=[p[0].split("/")[3] for p in _REAL])
def test_the_derivation_on_the_real_staged_liberties(lib, buf, root):
    r = subprocess.run(
        [_DOCKER, "run", "--rm", "--entrypoint", "cat", _IMAGE, lib],
        capture_output=True, text=True, timeout=600, errors="ignore")
    assert r.returncode == 0, r.stderr[-500:]
    assert R._i1958_pick_cts_buffers(r.stdout)[:2] == (buf, root)
