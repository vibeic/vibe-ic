# `fixtures/ppa/` — the shared PPA fixtures

These are for **every** PPA lane. Use them instead of inventing your own: when
two lanes disagree about what a number means, they should at least be arguing
about the same bytes.

Spec §17.3 (real-benchmark fixtures), §17.2 (negative/mutation), §17.5 (no
vacuous pass). Contract: `docs/PPA_INTERFACES.md`.

## Why this is a lane and not an afterthought

Spec §22.1: fixture capacity is reserved separately and is not something added
after the features are done. The reason is narrow and specific — under time
pressure the fixture that gets skipped is always the **negative** one, and a
suite of only positive fixtures is a gate that is always green.

So the tree is weighted the other way. Most of what is here is designed to be
**red**, and `test_ppa_fixture_integrity.py` exists to make sure it stays red:
it fails if a negative fixture is quietly repaired into a positive one.

## What is here

| fixture | proves | the short version |
|---|---|---|
| `sta/known_answer/` | positive + vacuous | Two views with known answers (+14.56 ns setup, +0.57 ns hold) and a **third view that is declared and deliberately not shipped**, so `NOT_MEASURED` has something to be about. |
| `power/activity_basis_pair/` | negative | Same design, same netlist, same liberty, same SDC, same tool. **Only the activity basis differs** — and the number moves 49.2%. |
| `area/stage_pair/` | negative | Same design, same run. **Only the stage differs** — synthesis vs post-route. Both artefacts say 262 cells, which is the trap. |
| `drc/zero_three_ways/` | positive + negative + vacuous | Three DRC runs, all reporting zero violations. Only one is entitled to say the design is clean. |
| `waiver/no_owner/` | negative | Three waivers, one owner. |
| `vacuous/` | vacuous | "I could not read it" and "I read it and it was empty" — the pair that must not collapse into one verdict. |

Every fixture directory carries an `expected.json`: the **known answer**, in the
canonical metric shape where one applies, plus an explicit `must_not` list. You
should not have to reverse-engineer what a fixture is for.

## The three things worth knowing before you use these

**1. Two DRC reports that mean opposite things are byte-identical.** Measured,
not asserted:

```
0abbbf4dc0b2639b0db3735290135e331b55bb1816a99f4cc8009a242ce74a28  ran_and_found_none/drc.xml
0abbbf4dc0b2639b0db3735290135e331b55bb1816a99f4cc8009a242ce74a28  ran_on_empty_layout/drc.xml
```

One is a real deck over real geometry. The other is the same deck over a layout
with no shapes in it. They are the same 702 bytes. **No parser of the report can
ever tell them apart**, because the answer is not in the report. If your gate
decides "DRC clean" from the report alone, it is reading the wrong document —
measure the layout. `drc/zero_three_ways/expected.json` carries the
four-row discriminator table; please implement that one rather than an
eleventh near-miss of it.

**2. The activity-basis pair moves the number by half.** 1.6496e-03 W
vectorless against 2.4617e-03 W from a VCD, for the same silicon. A lane that
compares across the basis and declares a winner is reporting a 49% power
improvement that is entirely an artefact of how activity was assumed. Under
contract §2 that comparison is `UNDETERMINED`.

Related, and worth checking for in real runs: three `vector_vcd` reports in the
published corpus print `Annotated 0 pin activities` — they *declare* a VCD basis
while carrying vectorless numbers. The label is not the basis.

**3. The area pair is deceptive on purpose.** Both artefacts report 262 cells,
because it is the same netlist. That invites the conclusion that the two area
figures are one measurement seen twice. They are not, and they cannot be
reconciled from what is shipped — the only bridge is the core box, and it is in
neither file.

## Provenance

`MANIFEST.json` lists every file with its sha256, where it came from, and what
property it carries. Slices of real published runs name the source path and the
source file's own sha256; they are trimmed by removing whole lines only, never
by editing a value. Files generated with real tools name the tool, the image and
the exact command.

Fixtures sourced from real runs come from the `vibeic benchmark-data`
repository, which left this repo at v1.10.56 (commit `e23d0be5e`). Those paths
are relative to *that* repository.

## Checking and changing

```
python3 programs/tests/test_ppa_fixture_integrity.py            # 0 / 1 / 2 / 3
python3 -m pytest programs/tests/test_ppa_fixture_integrity.py
```

Exit codes follow `docs/PPA_INTERFACES.md` §1: `0` intact, `1` a property no
longer holds, `2` the tree or manifest could not be read (`[CANNOT CHECK]`),
`3` bad invocation.

If you deliberately change a fixture, say in your commit message **what property
the new bytes preserve**, then run `--regen` to update the hashes. `--regen` will
not invent provenance: a file with no manifest entry is refused, because only
you know where it came from.

**Do not "fix" a negative fixture.** If one looks broken — a missing report, an
empty layout, a waiver with no approver — that is the fixture working. Check
`expected.json` before you conclude otherwise.
