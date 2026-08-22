# The seal-ring step's two paths disagree about which index is the width

Measured 2026-08-22 in `ghcr.io/vibeic/vibeic-eda:0.3.25` (`b9124fe1778a`).
Found while writing the upstream PIN for the seal-ring mirror — which is what
a pin is for.

## The variable

The flow declares the die rectangle as four corner coordinates:

    "DIE_AREA", Optional[Tuple[Decimal, Decimal, Decimal, Decimal]],
    'Specific die area to be used in floorplanning. Specified as a
     4-corner rectangle "x0 y0 x1 y1".'

So index 2 is an **x** and index 3 is a **y**.

## The two paths of one step

`librelane/steps/klayout.py`, class `SealRing`. The step dispatches on the PDK
name and the two branches pass the same two indices in opposite order:

    run_generic:
        "--die-width",   f"{self.config['DIE_AREA'][2]:f}",     # x1
        "--die-height",  f"{self.config['DIE_AREA'][3]:f}",     # y1

    run_ihp_sg13g2:
        "-rd", f"width={self.config['DIE_AREA'][3]:f}",         # y1
        "-rd", f"height={self.config['DIE_AREA'][2]:f}",        # x1

## And the receiving script says which axis each one is

This is not a naming ambiguity that could be argued either way. The PDK's own
seal-ring generator — the script the step invokes — documents its parameters:

    def generate_sealring(width: float, heigth: float, input, output,
                          offset_x: float, offset_y: float):
        :param width:  Width (X-Axis) of the sealring.
        :param height: Heigth (Y-Axis) of the sealring.

`width` is the X extent. `run_ihp_sg13g2` passes it the **y** coordinate, and
passes the **x** coordinate as the Y extent.

## Why it has survived

The script's own usage example, in its header, is a **square** die:

    -rd width=1300.0 -rd height=1300.0

On any square die the transposition is invisible. It produces a seal ring with
its two extents swapped only on a rectangular one — and it produces it
silently, because both values are valid numbers in valid units and nothing
downstream re-derives the ring's extents from the die.

## Scope of this finding

* MEASURED: the two branches pass opposite indices, and the receiving script
  declares which axis each parameter is. Both read out of the pinned image.
* NOT MEASURED: a generated ring on a rectangular die. Establishing the
  transposition did not require one — the declared parameter semantics settle
  it — and running the generator was out of scope for this lane.
* NOT OURS TO PATCH HERE. Our own producer drives the generic contract, whose
  mapping is the correct one, and it selects its path by the interface the
  script DECLARES rather than by PDK name. The defect is upstream, in a branch
  we do not drive, and the fix belongs in the fork.

## The same class as this lane's other finding

A dimension crossed at a boundary between two layers, invisible under the
symmetric case everybody tests with, and silent when it is wrong. The other
instance in this lane is two option families whose axis vocabulary is inverted
between the flow script and the tool it calls. Neither raises an error;
neither is caught by any single-case test; both need the asymmetric input to
show up at all.
