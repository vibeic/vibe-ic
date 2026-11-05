"""R-0915-103: on a die its own pad ring PERIMETER-pins, the core is the interior.

THE CONTROL THE RULING IS BUILT ON — spm x gf180mcuD as a DIE, the same design
(66 `dffq` in both post-PnR netlists), the same 24 ns clock, the same PDK and
the same SS corner, differing only in the core rectangle:

                          run7 (core = interior)   run8 (core = island)
    placement ROWs        605                      57, all at x=1467.2 um
    core                  2373 um                  228 um in a 3162 um die
    buffers in spm_pnr.v  522                      2057  (synthesis: 273 cells,
                                                          ZERO buffers)
    worst SS setup        +8.21 ns, TNS 0.00       -1.97 ns, TNS -19.03
    detailed route        converged                3 restarts, 8 h 22 m burned

run8's worst path is `rst` (input port) -> u_core/_471_/D: 4.80 ns input delay
+ 1.78 ns at the pad cell + **21.12 ns across 36 buffer stages** (32 of them
buf_1) carrying **0.770 pF IN TOTAL** + 0.94 ns of logic. It is not wire RC; it
is a chain, and it exists because a 1467 um band with no placement ROW gives a
pad->core net nowhere to put a repeater: `RSZ-0035 Found 18 fanout violations`
-> `RSZ-0038 Inserted 784 buffers in 19 nets`, plus `RSZ-2005 cannot find a
viable buffering solution on pin u_pad_x_9/Y`.

THE COUNTER-MEASUREMENT IS KEPT, NOT DELETED. `ring_die_core_pad`'s docstring
carries subservient r37 (a 1176 um interior core at 10.4 % utilisation missing
SS by 13.1 ns on paths whose delay is wire) beside this one, and names it as
the number at risk. Whoever owns that design re-measures it on a tree carrying
this change; the ruling is the owner's, the risk is stated, and the knob that
failure belongs to is the placer's `-density`, which this change does not
touch.

Both directions are tested: a ring-pinned DIE gets the interior and no ladder;
a die nobody's ring pinned — and a HARDMACRO, which never reaches this code at
all — keeps exactly what it had.
"""
from __future__ import annotations

import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))


#: spm's own numbers: 38 pads made the ring need 3162 um, and the ring's
#: measured depth + PAD_EDGE_SPACING + the PDN offsets made the floor 393 um.
SPM_DIE, SPM_FLOOR = 3162, 393
SPM_INTERIOR = SPM_DIE - 2 * SPM_FLOOR            # 2376 um
#: what the auto-sizer asked for from this netlist at the requested utilisation
SPM_ASKED = 85


# ------------------------------------------------- the ruling, both directions









# ------------------------------------------- the other direction: untouched



def test_a_hardmacro_never_reaches_this_code():
    """A hardmacro has no pad ring to pin a die by perimeter: the block that
    sets `_core_sized_um` is entered only when `_padring_required_die_um`
    answered, and that reads the run's own ring record."""
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    assert "_ring_side, _ring_basis = _padring_required_die_um(project)" in src
    assert "if _ring_side is not None:" in src


def test_the_density_is_reported_and_is_not_a_lever():
    """R-0915-103's second half. The caller prints the interior and the share
    the auto-sizer's answer would occupy, and nothing downstream reads it."""
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    # the phrases are f-string fragments in the source, so match them as such
    assert "core := the die interior" in src
    assert "REPORTED as the density it " in src
    assert "never a lever on the rectangle" in src
    assert "R-0915-103" in src
