"""#603 — the structural half of TEST coverage: which faults no test can detect.

Raw FAULT coverage is `detected / total`; sign-off TEST coverage is
`detected / (total - untestable)`. This classifier produces the untestable set.
It does not grade faults and does not compute a coverage number.

WHICH WAY IT MUST ERR. Marking a testable fault untestable INFLATES coverage —
a false PASS. Marking an untestable one testable only leaves coverage
conservative. Every rule under-excludes, and every test below is written to
catch the inflating direction.

THE SYNTHETIC CONTROL WAS NOT ENOUGH, which is the lesson worth keeping. A
hand-built fixture passed both directions while the classifier was
catastrophically wrong on a real netlist: `fault cut` wires every pseudo-PI and
pseudo-PO through a CONTINUOUS ASSIGNMENT, not a cell pin — 3191 of them in
sha256's cut netlist — and ignoring them left 33 primary outputs instead of
1583. The backward closure then had almost nothing to start from:

    ignoring `assign`      7717 of 8187 nets "unobservable"    (94 %)
    modelling `assign`       51 of 11385                       (0.4 %)

94 % excluded is the coverage-inflating direction. The fixture could not see it
because a fixture nobody wired an `assign` into has no `assign` in it.

MEASURED ON REAL ARTEFACTS, all four run:

    synthetic, fully testable      untestable 0          rc 0
    synthetic, tie chain + stub    untestable 3          rc 0
    sha256 cut netlist + sky130    untestable 48/11385   rc 0
    spm cut netlist + WRONG lib    REFUSES               rc 2

NOT CLAIMED: the 746-fault caravel figure in the issue. No `coverage.yml` and no
`sa0Uncovered` bucket is committed anywhere under `benchmark-data` — every
tracked DFT directory carries `dft_atpg_not_run.json` — so the comparison the
issue asks for cannot be made from the corpus, and is not made here.
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PROG = _PROGRAMS / "atpg_untestable_fault_classify.py"
_REPO = _PROGRAMS.parents[3]


def _load():
    spec = importlib.util.spec_from_file_location(
        "atpg_untestable_fault_classify", PROG)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["atpg_untestable_fault_classify"] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load()

_LIB = '''
library (tiny) {
  cell (INV)   { pin (A) { direction : input; }  pin (Z) { direction : output; } }
  cell (NAND2) { pin (A) { direction : input; }  pin (B) { direction : input; }
                 pin (Z) { direction : output; } }
  cell (TIE0)  { pin (Z) { direction : output; } }
}
'''

_FULL = '''
module m ( a, b, y );
  input a;
  input b;
  output y;
  NAND2 g0 ( .A(a), .B(b), .Z(n1) );
  INV   g1 ( .A(n1), .Z(y) );
endmodule
'''

_BROKEN = _FULL.replace("endmodule", '''  TIE0 t0 ( .Z(k1) );
  INV  g2 ( .A(k1), .Z(k2) );
  INV  g3 ( .A(b),  .Z(d1) );
endmodule''')


def _run(tmp_path, netlist, lib=_LIB, extra=()):
    n = tmp_path / "n.v"
    n.write_text(netlist, encoding="utf-8")
    args = [sys.executable, str(PROG), "--netlist", str(n)]
    if lib is not None:
        p = tmp_path / "l.lib"
        p.write_text(lib, encoding="utf-8")
        args += ["--liberty", str(p)]
    return subprocess.run(args + list(extra), capture_output=True, text=True,
                          timeout=60)


# ── liberty: directions come from the file, never from a pin name ───────────
def test_quoted_direction_values_are_read():
    """sky130 writes `direction : "input";`. A pattern that only took the bare
    form found all 428 cells in a real liberty and ZERO pins in them — and no
    pin direction means no edge, which means an empty untestable set that reads
    exactly like a clean one."""
    d = M.parse_liberty_pin_directions(
        'library(x){ cell ("C") { pin ("A") { direction : "input"; } '
        'pin ("Z") { direction : "output"; } } }')
    assert d["C"] == {"A": "input", "Z": "output"}


def test_unquoted_direction_values_still_work():
    d = M.parse_liberty_pin_directions(_LIB)
    assert d["NAND2"]["A"] == "input" and d["NAND2"]["Z"] == "output"


def test_a_constant_cell_is_identified_structurally_not_by_name():
    """`TIELO`, `conb_1`, `LOGIC0_X1`, `TIE0` are one thing in four libraries.
    The rule is "declares no input pin"."""
    d = M.parse_liberty_pin_directions(_LIB)
    assert M.constant_cells(d) == {"TIE0"}


def test_the_identity_master_is_not_mistaken_for_a_constant():
    """LOAD-BEARING. Continuous assignments are modelled as a synthetic master
    whose inputs are attached at classify time, so the structural rule read
    every `assign` in the design as a constant source: 6569 of 11385 sha256
    nets came back uncontrollable."""
    d = M.parse_liberty_pin_directions(_LIB)
    d[M._ASSIGN_CELL] = {"Y": "output"}
    assert M._ASSIGN_CELL not in M.constant_cells(d)


# ── the bidirectional soundness control ─────────────────────────────────────
def test_a_fully_testable_design_yields_an_empty_untestable_set(tmp_path):
    """The control the issue asks for. A non-empty set here is over-exclusion,
    which inflates coverage."""
    r = _run(tmp_path, _FULL, extra=["--json", str(tmp_path / "o.json")])
    assert r.returncode == 0, r.stderr
    import json
    got = json.loads((tmp_path / "o.json").read_text())
    assert got["untestable_count"] == 0, got["untestable_nets"]


def test_a_tie_chain_and_a_dangling_output_are_found(tmp_path):
    """The other direction: it must not be empty on a design that has them."""
    import json
    r = _run(tmp_path, _BROKEN, extra=["--json", str(tmp_path / "o.json")])
    assert r.returncode == 0, r.stderr
    got = json.loads((tmp_path / "o.json").read_text())
    assert "k1" in got["uncontrollable"] and "k2" in got["uncontrollable"], (
        "the constant does not propagate through the gate it drives")
    assert "d1" in got["unobservable"], "a net feeding nothing is observable?"


# ── the real-netlist shape the fixture could not see ────────────────────────
_ASSIGN_NL = '''
module m ( a, \\f.d );
  input a;
  output \\f.d ;
  INV g0 ( .A(a), .Z(n1) );
  assign \\f.d  = n1;
endmodule
'''


def test_a_pseudo_po_wired_by_a_continuous_assignment_is_observable(tmp_path):
    """`fault cut` connects every pseudo-PO through an `assign`, not a cell
    pin. Without this edge the module has no reachable outputs and the whole
    cone is excluded — 94 % of sha256, in the coverage-inflating direction."""
    import json
    r = _run(tmp_path, _ASSIGN_NL, extra=["--json", str(tmp_path / "o.json")])
    assert r.returncode == 0, r.stderr
    got = json.loads((tmp_path / "o.json").read_text())
    assert got["untestable_count"] == 0, (
        f"n1 feeds a pseudo-PO through an assign and was excluded anyway: "
        f"{got['untestable_nets']}")


def test_the_module_with_the_most_instances_is_chosen():
    """A cut netlist holds more than one module and the gate-level one is
    neither reliably first nor last. Picking either characterises the file
    wrongly in opposite directions, and both were tried."""
    two = _FULL + "\nmodule wrapper ( q ); output q; assign q = 1'b0; endmodule\n"
    mod = M.parse_module(two)
    assert mod[0] == "m"


# ── an absence must not arrive as an empty set ──────────────────────────────
def test_no_liberty_refuses_rather_than_returning_an_empty_set(tmp_path):
    r = _run(tmp_path, _FULL, lib=None)
    assert r.returncode == M.RC_CANNOT_CLASSIFY, r.stdout + r.stderr


def test_a_liberty_that_matches_nothing_refuses(tmp_path):
    """spm's commercial-PDK netlist against a sky130 liberty: 0 of 20 masters
    resolve, so every set is empty for want of input. The first version counted
    the synthetic identity master as "resolved" and returned a number."""
    other = 'library(y){ cell ("ZZZ") { pin ("A") { direction : "input"; } } }'
    r = _run(tmp_path, _FULL, lib=other)
    assert r.returncode == M.RC_CANNOT_CLASSIFY, r.stdout + r.stderr
    assert "did not resolve" in r.stderr


def test_an_unreadable_netlist_refuses(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), "--netlist", str(tmp_path / "nope.v")],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == M.RC_CANNOT_CLASSIFY


# ── the real artefact ───────────────────────────────────────────────────────
_LIB_REL = ("/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/"
            "sky130_fd_sc_hd__tt_025C_1v80.lib")


def _sky130_liberty(tmp_path):
    """On the host if present, otherwise out of the pinned EDA image.

    Image-gated the same way `test_issue602_asap7_stack_matches_the_shipped_map`
    is, and SKIPPED rather than passed when neither is reachable: "I could not
    look" and "I looked and it is fine" are different claims.
    """
    host = pathlib.Path(_LIB_REL)
    if host.is_file():
        return host
    # The image is RESOLVED, not read out of this repo: the anchor file that
    # used to name it is deleted, because holding vibeic-eda's version number
    # here made every image release need a PR here.
    sys.path.insert(0, str(_PROGRAMS))
    import _eda_image as _img
    judged = _img.judged_image()
    if judged.ref is None:
        return None
    img = judged.ref
    if subprocess.run(["docker", "image", "inspect", img],
                      capture_output=True, text=True).returncode != 0:
        return None
    out = tmp_path / "sky130.lib"
    r = subprocess.run(["docker", "run", "--rm", "--entrypoint", "cat", img,
                        _LIB_REL], capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or len(r.stdout) < 1000:
        return None
    out.write_text(r.stdout, encoding="utf-8")
    return out

def test_the_sha256_cut_netlist_classifies_a_small_minority(tmp_path):
    """Not a golden number — a sanity bound. sha256 has almost no unused I/O,
    so a large untestable fraction means the graph is wrong, which is how both
    earlier bugs presented (94 % unobservable, then 58 % uncontrollable)."""
    nl = (_REPO / "benchmark-data/ic/sha256/clean_run_v1427_20260715"
          / "phase2/stage2/dft/cut_netlist.v")
    if not nl.is_file():
        pytest.skip("corpus cut netlist absent")
    lib = _sky130_liberty(tmp_path)
    if lib is None:
        pytest.skip("sky130 liberty unreachable (host and image) — NOT run")
    import json
    out = tmp_path / "o.json"
    r = subprocess.run(
        [sys.executable, str(PROG), "--netlist", str(nl),
         "--liberty", str(lib), "--json", str(out)],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    got = json.loads(out.read_text())
    frac = got["untestable_count"] / max(got["nets"], 1)
    assert frac < 0.05, (
        f"{got['untestable_count']} of {got['nets']} nets excluded — a large "
        f"fraction on a design with almost no unused I/O means the graph is "
        f"wrong, in the direction that inflates coverage")
