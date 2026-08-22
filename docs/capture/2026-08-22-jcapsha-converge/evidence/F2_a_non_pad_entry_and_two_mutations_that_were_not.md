# The register's first NON-PAD entry — and two mutations that changed bytes without changing the property

## Why this entry exists

The register shipped with two entries and both were `pad_ring.*`. F2's rule is
supposed to be general — "pin a re-implementation against its upstream" has
nothing to do with pads — and the register's own contents were the weakest
evidence for that claim. A rule whose only instances are pads reads as a pad
rule however carefully its docstring is worded. This is the same register,
unchanged, on a subject with no pad in it.

    digital_hardmacro.lef_write_route
      our_module  programs/digital_hardmacro_gen.py
      upstream    librelane/scripts/magic/lef.tcl
      sha256      067772b60a08a2c41fe947ca61ac84cf25272534962e78788acbeabefcf9b4b8
                  (verified equal in ghcr.io/vibeic/vibeic-eda:0.3.24)

## What it pins

Upstream has TWO routes and `MAGIC_LEF_WRITE_USE_GDS` picks between them. Its
default is FALSE — read the views and the DEF, not the GDS alone:

    if { $::env(MAGIC_LEF_WRITE_USE_GDS) } {
        gds read $::env(CURRENT_GDS)
    } else {
        ... read_tech_lef / read_pdk_gds / ... / read_def
    }

That default is load-bearing, and the producer's own docstring records what
the other route cost on a real signed-off run: an abstract with an outline,
obstructions and **zero pins**, because the port labels sit on layers the PDK's
Magic technology does not map. GEOMETRY from the GDS, PORTS from the DEF.

Both halves live in `programs/tests/test_upstream_pin_magic_lef.py`. OURS needs
nothing external and always runs. THEIRS skips — never passes — when no
distribution is reachable.

## Verified

    no distribution reachable        3 passed, 3 skipped
    inside the pinned image          6 passed
    byte-exact copy at a custom root 6 passed

## The reds

    RED A  upstream's default route stops reading the DEF
           -> sha256 test FAILS + two-routes test FAILS   (2 failed, 4 passed)

    RED B  our producer stops emitting `def read`
           -> our-half test FAILS                         (1 failed, 5 passed)

Both sides of the pin are live: upstream drifting and our side drifting each
turn it red, independently.

## TWO MUTATIONS THAT WERE NOT MUTATIONS, AND THIS IS THE SECOND TIME TONIGHT

The first attempt at both reds reported **`1 failed, 5 passed`** and
**`3 passed, 3 skipped`** — i.e. the properties under test survived. Both
readings were false. The mutations were:

    upstream:  "    read_def\n"          -> "    # read_def removed upstream\n"
    ours:      f"def read {def_file}\n"  -> f"# def read {def_file}\n"

Both changed the file. **Neither removed the token the assertion searches
for** — a commented-out line still contains `read_def`. The assertions were
right; my mutations were no-ops with respect to the property, while looking
like real edits in a diff.

This is the same class as the earlier arm that failed to apply at all
(`F2_mutation_sweep.md`), in a new disguise, and it is the more dangerous
disguise: that one raised a `ValueError` I could see, this one ran clean and
produced a green that read as "the test survives the mutation". A mutation
sweep is only evidence if each arm proves the property actually changed.

Both were redone with the proof inside the mutation itself:

    s2 = s.replace("    read_def\n", "    read_views_only\n", 1)
    assert "read_def" not in s2, "TOKEN SURVIVED — this mutation would be a no-op"
    print("MUTATION APPLIED and token verified GONE")

## And a third non-result in the same batch

The first "control" run — unmodified copy at a custom root — reported
`1 failed, 5 passed`, the failure being the sha256. That was not a finding
either: I had built the cached copy by stripping a `sha256sum` header line off
a combined `docker run` output with `sed`/`tail`, and mangled the file. Fixed
by re-extracting with `docker run --rm --entrypoint cat`, which round-trips
byte-exact and matches the recorded digest. **A control that fails is a claim
about the harness until proven otherwise.**

## Register now

    pad_ring.upstream_pad_variables:     ... known_gap=0
    pad_ring.along_the_row_extent:       anchors=2, pin=test
    digital_hardmacro.lef_write_route:   anchors=3, pin=test
    PASS: 3 registered re-implementation(s)

Three entries, two subsystems, one of them with no pad in it, zero open gaps.

## Registering the entry broke three tests, and the helper was the thing at fault

Adding the third entry turned three tests in `test_upstream_contract_parity.py`
red with `assert 2 == 1` — rc 2 NOT DETERMINED, not rc 1. The cause:
`_fake_root` built a distribution containing exactly two hard-coded pad files,
so the new entry's `librelane/scripts/magic/lef.tcl` was not under it and the
checker correctly refused to determine anything.

The tests were right and the checker was right. The helper knew a fixed list.
It now reads the register and materialises every registered entry's upstream
file from that entry's own anchors, so the NEXT entry costs nothing here and no
test has to be touched to add one.

Proof the repair did not hollow them out — the checker's sha-comparison guard
disabled, with the message deliberately left in the source so the mutation
could not pass by deleting the string the test greps for:

    MUTATION APPLIED (guard disabled, message left in place)
    FAILED ...::test_a_changed_upstream_file_is_a_finding
    1 failed, 21 passed

    restored -> 22 passed, checker byte-identical

That is the third fixture in this file to have been borrowed from live data
rather than constructed — after `sorted(known_gap)[0]` and
`sorted(omitted_by_design)[0]`. The pattern is worth naming: **a test that
reaches into the shipped artefact for its fixture asserts today's contents, and
fails the day the artefact legitimately changes** — which is precisely the day
the register is doing its job.

## Checked and clean: the gate does not contradict its producer

F1's fix established, for the pad ring, that "the gate cannot contradict its own
producer over which file it opened". `digital_hardmacro_check.py` cites the SAME
upstream file as the producer this entry registers, so the same question is
live here. Checked:

| | says |
|---|---|
| upstream `lef.tcl` | `lef write … {*}$lefwrite_opts`; `-hide` appended unless `MAGIC_WRITE_FULL_LEF`; `-pinonly` when `MAGIC_WRITE_LEF_PINONLY` |
| producer (`:372`) | "`-hide` unless `MAGIC_WRITE_FULL_LEF`, plus `-pinonly` when `MAGIC_WRITE_LEF_PINONLY`" |
| gate (`:1012`) | "`lef write … [-hide] [-pinonly]`, and `MAGIC_WRITE_LEF_PINONLY` decides whether a labelled port PLUS the connected metal is the pin, or only the labelled patch" |

They agree with each other and with the file. **No finding.** The one
imprecision is a comment at the gate's `:359` writing `lef write … -hide
[-pinonly]`, which reads as unconditional where upstream conditions it; the
producer's docstring has it right and the gate's own `:1012` has it right. Not
worth a record.

No second register entry was added for the gate. It consumes the same upstream
facts as the producer, and those facts are already asserted by this entry's pin;
a second entry would duplicate the upstream assertions and give a false
impression that two independent things are pinned.

Recorded because a check that came back clean is a result, and the register's
value is partly that it makes this question cheap to ask.
