# Producer identity for the fill and antenna reports (#1119 A3_CROSS_DESIGN)

Branch `jfindings/63x8-producer-identity`, one commit, cut from `78ffef90a`
(the tip of `jfindings/63x8-remaining`, which was not yet landed when this
started — `origin/main` was still at `867de4289` / v1.11.18).

## The finding, reproduced

Two of the thirteen recorded 63x8 adversarial findings were left open by the
preceding branch with a stated reason: their evidence carried nothing that
identified the design, so no gate-side rule could bind it. Reproduced here
before changing anything, over the published corpus:

| artefact | `spm/v1.9.96_gf180mcuD` | `sha256/clean_run_v1427_20260715` | |
|---|---|---|---|
| `reports/phase3/antenna.rpt` | `7c614562baacec12…` | `7c614562baacec12…` | **identical** |
| `reports/density.rpt` | `9c5fa6ff58d32902…` | `c7075af5a2174407…` | differ, but only in numbers |

`antenna.rpt` is byte-identical between two different designs on two different
PDKs: 487 bytes reading `0 net violations, 0 pin violations`, no name anywhere,
citing `phase3/stage3/pnr/openroad.log` as its source — a path typed as a
constant, and a file the published cell does not contain.

Asked with the auditor's own extractor, all four artefacts declare nothing:

```
  cell   reports/phase3/antenna.rpt     declares []
  cell   reports/density.rpt            declares []
  donor  reports/phase3/antenna.rpt     declares []
  donor  reports/density.rpt            declares []
```

## The fix

`phase3_one_shot_runner._measured_subject` records, for a report it is about to
write: the design, and for every input the tool actually read the resolved
project-relative path with its sha256 and byte count, and the tool's own log the
same way. `_emit_antenna_report` (both the in-session and the fallback path) and
`_emit_metal_fill` stamp it into the `.rpt` as `measured_design:` /
`measured_from:` / `tool_log:` and into the `.json` as `measured_subject`.
`antenna.json`'s `"source"` is now the resolved log path rather than the typed
constant.

At the gate: `eda_report_audit` gains one dialect for the runner's stamp, and
`erc_density_check` gains the same binding against the module names the
project's own Verilog declares.

### The two designs' reports are now different bytes

Driven through the real emitters on two fixture designs:

| artefact | `my_top` | `other_top` |
|---|---|---|
| `antenna.rpt` | `9020f6765f90160008fd5c786e2d2f3cbdf6ee0fafb3b6b0772a2ccc5d551be5` | `2275e38a091bcfa2b3f810365cdb534904f2791c7d7c6bed46bf8209e98b456d` |
| `antenna.json` | `82249e73abd8b9913729fb523f0e761fcf3a93bf837d5c038e4c4b4f5830fcac` | `fcd465ad2db003393c0c50ad0b59faa9e0ead5697c64eb5e69eb3688ae41c75f` |
| `density.rpt` | `eacff533399ec248511162c34324e4b015b7ad3eef38076064d23945c1cac4e3` | `41d0a45642a0e1d59e1ad31080461fec97e75b9794ea05f4c90696bb6b294e21` |
| `density.json` | `29c29cb382e46069b7219c13df5092a6b69733d18dde4ab2b380bab155a12743` | `bc4d7af503828f408805e82a425acc71aadc71efd00516f543392beaeb36fc2e` |

Head of `my_top`'s `density.rpt`:

```
measured_design: my_top
measured_from: phase3/stage3/pnr/my_top.def sha256:5a60299f693ceb0e8f501d2b7909…
measured_from: phase3/stage3/pnr/filled.def sha256:0989108641f997a139cdd5037847…
tool_log: phase3/stage3/pnr/metal_fill.log sha256:UNREADABLE
```

The last line is the design working as intended: the log was named and could not
be read, so it is recorded as unreadable rather than omitted. "The input was
absent" and "the input was not looked at" stay different facts.

### The gate separates them

```
[own evidence]     rc=0 binding=True
[foreign evidence] rc=1 binding=False
    ANTENNA_REPORT_IS_ABOUT_ANOTHER_DESIGN — report states it is about other_top,
    which this project's Verilog does not declare.

[own evidence]     rc=0 binding=True
[foreign evidence] rc=1 binding=False
    DENSITY_IS_ABOUT_ANOTHER_DESIGN — Density artefact states it measured
    other_top, which this project's Verilog does not declare.
```

### A stamp is not a measurement

The failure mode this change could have introduced, measured on both gates:

```
  antenna: report ABSENT             -> rc=1   binding=None
  antenna: report EMPTY              -> rc=1   binding=NOT_DETERMINED
  antenna: STAMP ONLY, no result     -> rc=1   binding=True
  density: report ABSENT             -> rc=1   binding=NOT_DETERMINED
  density: report EMPTY              -> rc=1   binding=NOT_DETERMINED
  density: STAMP ONLY, no result     -> rc=1   binding=NOT_DETERMINED
```

The third line is the one that matters: a report whose stamp is present and
correct, carrying no result, is refused with `design_binding: true`. Identity
makes a report attributable; it never makes it a measurement.

## The two recorded findings still read SUCCEEDED

```
[FORGED GREEN] A3_CROSS_DESIGN v1.9.96_gf180mcuD:antenna_report_check
[FORGED GREEN] A3_CROSS_DESIGN v1.9.96_gf180mcuD:erc_density_check
[FAIL] adversarial_agent: 2 of 14 attempted attack(s) produced a forged green.
```

Stated plainly rather than worked around: the recorded subject is a run
**published before the stamp existed**, so its reports carry none, and the gate
correctly reports `NOT_DETERMINED` and passes. The cell cannot be re-measured
either — it carries no `phase3/stage3/pnr/` at all, so the reports cannot be
regenerated from it. The mechanism is in place and guarded; what is missing is a
published run made with it. `adversarial_findings.json` is therefore **not**
regenerated: recording these as closed would be recording the publication
schedule as security progress, which is the one thing the ratchet exists to
prevent.

## A/B against the branch point, by test ID

Same 300 test files, same options, both in `vibeic-eda`:

| | failed | passed | skipped |
|---|---|---|---|
| this branch | 204 | 6927 | 174 |
| `78ffef90a` (branch point) | 205 | 6914 | 174 |

* **Introduced: 0.** `comm -13` over the sorted FAILED test-ID sets is empty.
* One baseline failure is absent from this branch —
  `tests/test_digital_hardmacro_gen.py::test_a_pinless_abstract_is_never_staged`.
  It passes **in isolation on both trees**, so it is order-dependent in the large
  run and is not attributable to this change. Not claimed as a fix.
* The 204 remaining failures are pre-existing at the branch point.

## Guard and its revert

`tests/test_the_fill_and_antenna_producers_name_what_they_measured.py` — 12
assertions, fixtures only, no corpus, because a guard that skips without the
corpus has the defect it guards.

Reverting the three changed programs to `78ffef90a` and re-running: **9 of 12
fail.** The first quotes the published cell's own hash back:

```
E  AssertionError: two different designs produced byte-identical antenna reports
   (7c614562baacec128521fd8751a746cc3b6e1eed2aca1b8a2491cd4aead44e27).
E  assert '7c614562…' != '7c614562…'
```

```
E  AssertionError: antenna_report_check accepted other_top's report in a tree
   whose Verilog declares only my_top:
E    {"program": "eda_report_audit:antenna", "passed": true, "findings": [],
E     "summary": {"design_binding": "NOT_DETERMINED", "clean": true, …}}
```

The 3 that pass on both trees are the vacuous-pass invariants, which must never
fail on either — they are the control, not the finding.

## Footprint on `phase3_one_shot_runner.py`

One helper block plus stamps inside the two emitter functions: **+95 / −1**, in
three regions, all inside or immediately above `_emit_antenna_report` and
`_emit_metal_fill`. No reformatting, no moved code, nothing else touched, so a
rebase over the PPA extraction should apply cleanly or conflict only inside those
two functions.

## REQUESTS TO THE LANDER

1. **Land order.** This branch is cut from `78ffef90a`, the tip of
   `jfindings/63x8-remaining`. It must land **after** that branch. If that branch
   is reworked before landing, this one needs a rebase — the overlap is
   `eda_report_audit.py` (the dialect tuple) and `adversarial_agent.py` (one
   docstring paragraph).
2. **Version.** Not bumped. `plugin.json` is untouched; assign the version.
3. **`adversarial_findings.json` is deliberately unchanged** and still lists the
   two `A3_CROSS_DESIGN` pairs as forging. Please do not regenerate it as part of
   landing: against the published corpus they still forge, for the reason in
   "The two recorded findings still read SUCCEEDED" above.
4. **A published run made with this runner would close them.** Whenever the next
   cell is published from a flow carrying this commit, re-running
   `tools/gen_adversarial_findings.py` against it is what turns these two from
   SUCCEEDED to DEFENDED. That is the acceptance test I could not run here.
5. **Pre-existing red, not mine, not investigated:** 204 failures at the branch
   point across these 300 files, plus
   `tests/test_digital_hardmacro_gen.py::test_a_pinless_abstract_is_never_staged`
   which is order-dependent.
6. **One tracked artefact in the plugin tree is rewritten by the suite** —
   `programs/reports/phase3/antenna.json` — because a test runs a gate with
   `--json` pointing into the source tree. I reverted it before committing rather
   than carry the churn. It is a pre-existing condition the suite write guard
   already reports; flagged, not fixed here.
