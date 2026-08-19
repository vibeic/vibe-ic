# w5_drc_wording — provenance

## What these are

Two synthetic OpenROAD `detailed_route` DRC reports that are byte-identical
except for the WORDING of the router's end-of-iteration violation tally.

    known/reports/phase3/drc_router.rpt
        `[INFO DRT-0199] Number of violations = N`
        — the spelling `_signoff_drc_format.RE_DRT_0199` matches.

    reworded/reports/phase3/drc_router.rpt
        `[INFO DRT-0199] design rule errors remaining = N`
        — a spelling no grammar in this repo matches.

Both end with the SAME twelve unfixed violations, and both carry the same
runner-written summary preamble claiming `total violations: 0`.

## How they were made

Authored, not captured. They are hand-written to the shape of a real OpenROAD
detailed-route transcript (ODB / DRT message-code namespaces, per-iteration
tally trajectory falling 4318 -> 1207 -> 342 -> 61 -> 12, wire-length and via
totals, a DEF write). Nothing here is copied from any run, any design or any
PDK: the file is GRAMMAR, and carries no design name, net name, cell name,
vendor, node or part number.

The reworded variant is produced from the known one by renaming EVERY tally
line, because a tool that renames its tally renames all of them; rewording only
the last would leave the parser reading an earlier iteration and the fixture
would demonstrate nothing. `test_w5_metric_beats_prose` re-derives one from the
other on every run, so the two cannot drift apart in any other respect.

## What they are for

`test_w5_metric_beats_prose` uses them to hold the W5 property: a change in a
tool's log wording must not change a gate's verdict. Measured on origin/main
8e60dd954, with the wording as the only variable:

    known/     drc_report_check . --mode drc --under ...  -> rc=1 FAIL
    reworded/  drc_report_check . --mode drc --under ...  -> rc=0 PASS

The gate is not carrying the tool's own metric in either run there, which is
the state the migration starts from.

## Byte size

Both are padded above `eda_report_audit.MIN_REPORT_BYTES["drc"]` (2048) with
further real-shaped DRT progress lines, because a report under that floor is
rejected as a hand-typed stub before any of this is reached — and being
rejected for the wrong reason would make the demonstration meaningless.
