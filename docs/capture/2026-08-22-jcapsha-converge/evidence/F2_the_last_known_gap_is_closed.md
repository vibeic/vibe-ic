# The register's last `known_gap` is closed, and the half that was missing was upstream's

At the previous push the register was green with one honest admission left:

    pad_ring.along_the_row_extent: anchors=2, pin=known_gap

    "nothing compares our along-the-row extent against upstream's. Ours summed
     the ORIENTED footprint, so a vertical side summed the master's height
     instead of its width -- a factor of more than four on the side that was
     measured."

I wrote that this branch would not close it. It closes now, because the image
the snapshot was taken in is ON THIS HOST and the upstream file is readable.

## The gap was more specific than "nothing compares them"

**OUR half was pinned all along**, behaviourally, by
`test_pad_ring.py::test_the_spacing_is_upstreams_arithmetic`. The fixture's pad
master is 75 x 350 and each side is 1_280_000 DEF units: four pads summed by
WIDTH fit with 196_000-unit gaps; four summed by HEIGHT are 1_400_000 against
1_280_000 and do not fit at all. That test goes red the moment the extent
returns to the oriented footprint. Nobody had written down that it was the pin.

**THEIRS was a sentence in a comment.** That is the half this adds.

## Verified against the real distribution

    image   ghcr.io/vibeic/vibeic-eda:0.3.24    (the one the snapshot records)
    file    librelane/scripts/openroad/common/pad_cfg.tcl
    sha256  a3bae7d559e8c8b9f16d8dc5d086cfd217207ed09667263bd8e183a5c5ebd52c
            == the value in the register, byte for byte

Run inside the image with `docker run` (never `exec`), repo bind-mounted:

    4 passed

## The assertion worth stating carefully

A raw count of `getHeight` in that file is **four**, which reads as a flat
contradiction of "upstream measures the width". Two are site dimensions, not
cell measurements. The other two are `set height [expr [[$inst getMaster]
getHeight] / $units]`, once per measuring block. MEASURED, every use of the
resulting `$height` in the whole file:

    102:        puts "$master_name: $width $height"

One diagnostic line. In the second block it is computed and never used at all.
The height is read and discarded; the arithmetic is width-only. That is why our
Python is width-only on all four sides, and the test asserts the USE, not the
count -- a count would have to be explained away, and an explanation in a test
is a comment.

## The reds

Positive control first: unmodified copy at a custom root -> **4 passed**, so
the harness can see the file and the assertions can pass.

Then upstream drifts -- `incr sum_of_cell_widths $width` becomes `$height`,
the exact drift that produced the 4.4x error:

    MUTATION APPLIED: upstream now sums the HEIGHT
    FAILED ...::test_the_file_is_the_one_the_register_snapshotted
    FAILED ...::test_the_fit_sum_and_the_row_step_both_accumulate_the_width
    FAILED ...::test_the_masters_height_is_read_and_then_never_used_in_arithmetic
    3 failed, 1 passed

And with no distribution reachable at all: **4 skipped**, naming the missing
input and the environment variable that supplies it. It does not pass. A pin
that turns green when it cannot see the thing it pins is the failure this
register exists to prevent.

## The status is not a rubber stamp either

Control -- point `pin_test` at a test that was never written:

    FAIL: pin_test names test_that_was_never_written in
          programs/tests/test_upstream_pin_pad_cfg.py and no such test is
          defined there.

## Register now

    pad_ring.upstream_pad_variables: ... known_gap=0
    pad_ring.along_the_row_extent:   anchors=2, pin=test
    PASS: 2 registered re-implementation(s); every upstream name and every
          registered computation is accounted for.

Zero open gaps, and every green in it now has something behind it.
