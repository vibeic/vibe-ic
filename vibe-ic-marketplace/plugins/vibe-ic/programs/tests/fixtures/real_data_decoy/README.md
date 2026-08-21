# `real_data_decoy/` — a fixture that MUST NEVER be selected as real data

This tree exists to be **refused**. It is the control for vibe-ic#1037.

## What it is

`phase3/stage3/extracted/chip_top.spef` is a hand-authored fixture that is
deliberately **indistinguishable from published extraction output to any
selector that looks at the filename, the directory shape, or the file size**:

* the directory shape is the published one — `phase3/stage3/extracted/`;
* the filename is the published one — `chip_top.spef`;
* it is non-empty;
* it is **git-tracked**;
* and it **carries a coupling pair** (`pair_cc == 1`), so it satisfies every
  assertion in `test_si_signoff_timing_aware.py::test_real_spef_*` — the two
  tests whose entire premise is "this is production extraction output".

Exactly one thing separates it from real published output: it is not under
`benchmark-data/`. That is the discriminator the fix turns on, and this fixture
is here so that claim is tested rather than asserted.

## Why a decoy had to be planted

Before vibe-ic#1037, `_real_spef()` fell back to an unbounded
`root.rglob("*.spef")` when its three named `benchmark-data/` candidates were
missing — and those candidates sit under run roots being withdrawn from
publication (#1015/#1010). The only `*.spef` files under that walk root are the
suite's own fixtures. The tests went red, but **only by luck**: the nearest
fixture is zero-coupling by construction and the assertion is
`len(pair_cc) > 0`.

That luck was thin, and it was measured: of the six fixture SPEFs the old walk
yielded, the third — `si_mcf_zero_coupling/coupled/design.spef`, `pair_cc == 1`
— passes **every** assertion in both tests. Only `Path.rglob`'s directory-walk
order stood between this suite and a green "real extracted parasitics" claim
over a file it wrote for itself.

A fixture that happens to be unsuitable is not a check. So this one is
suitable, on purpose, and the check is that it is refused anyway.

## The rule that refuses it

`programs/tests/_real_data.py`. Eligibility is an **allow-list of published-run
shapes**, not a deny-list of fixture directory names — a deny-list loses to the
next fixture path somebody invents, and this directory is exactly that next
path. Note that the test-owned-name backstop in that module is *not* what
catches this file: `real_data_decoy` is not in `TEST_OWNED_NAMES`, and the
components that are (`tests`, `fixtures`) are never reached, because the
`benchmark-data/` rule refuses it first.

## Do not

* Do not move this under `benchmark-data/`.
* Do not "fix" it to be zero-coupling — that would silently retire the control
  and restore the coincidence the issue is about.
* Do not delete it without deleting
  `test_real_data_eligibility.py::test_the_planted_decoy_is_refused`, which
  exists to fail if this file ever becomes selectable.
