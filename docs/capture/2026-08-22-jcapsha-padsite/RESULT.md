# Capture lane `jcapsha` — the ladder for three findings, and the one that was refuted

Cut from `origin/main` @ `a4caccefe` (v1.11.69). Branch `jcapsha/capture-padsite-recovery`.
Source report: the `jpadsite` lane's `RESULT.md` (1987 lines) and its `evidence/`.

Deliverable: `recoveries.json` + `candidates/`, emitted by `enhancement_emit.py`.
Six records: **A, A, A, A, C, D**. No Bucket T — and the absence of a Bucket T is
this lane's main finding.

## The ladder, per finding, and where each one stopped

### F1 — the step read the wrong PDK view → **Bucket A**

Stopped at A. The input a program sees is the refusal's own payload; the
decision is "does this negative verdict name the source CLASSES it consulted,
or only count items inside one of them". No judgement is required.

It is not a duplicate of the denominator family, and I checked before
claiming that. `gate_discloses_denominator_check` scopes to a **PASS** ("a PASS
must say how much it looked at"). `gate_zero_denominator_refuses_check` scopes
to **rc 0 over an empty population**. The refusal here would pass BOTH: it said
`0 site(s) from 1 LEF(s)`, so it disclosed a denominator, and it exited
non-zero. It was still the defect, because the denominator ranged over one of
the **two** view classes that can declare the thing. Disclosing a denominator
and disclosing the population that denominator covers are different properties.

General core: the logic reads no pad and no PDK literal. "Not found" and "not
looked for" are different verdicts, in any step, over any resource.

### F2 — the extent was measured from the oriented footprint → **Bucket A**

Stopped at A. Input: a module that cites an upstream file as the thing it
mirrors. Decision: does a test open that file and go red when ours drifts. Both
halves are mechanical.

This is the strongest of the three, and its value was demonstrated three times
in one night rather than argued:

1. the original drift (our sum used the master's height on vertical sides);
2. **the source report's own supporting citation was overstated.** It states
   "There is no `getHeight` in its side arithmetic at all". Measured
   (`evidence/measured_pad_cfg.txt`): `getHeight` is at lines 100 and 163 of
   upstream's `pad_cfg.tcl`, inside the side loop, twice. It is never
   *consumed* — the accumulator takes `$width` and the step takes `$width` —
   so the SUBSTANCE of the finding holds and the wording does not. A human
   read the file and reported something stronger than the file supports;
   a pin reads the file every time.
3. the rotation-semantics misreading below, which is the same failure again.

### F3 — the config variable the tool "ignores" → **Bucket A, and the tool half is REFUTED**

The brief asked me to think hardest here and to say which half is which. Both
halves turned out to be ours.

**The tool half does not exist.** I drafted it as Bucket T, measured it, and
withdrew it. Measured on a *second* image and a *newer* build than the source
report used — `ghcr.io/vibeic/vibeic-eda:0.3.26`, OpenROAD `26Q3-1666-ge29ae70ad4`
(the report used `:0.3.16` / `26Q3-1165`):

* sweeping the vertical rotation over `R0/R90/R180/MX` leaves the east and west
  pads at `MXR90`/`R90`, 350 um along the row — **identical in all four**, which
  reproduces the source report exactly (`evidence/rotation_reprobe_0326.txt`);
* sweeping the *other* argument moves those same pads
  (`evidence/rotation_reprobe_horizontal_0326.txt`);
* a row-level dump with two distinguishable sites shows `IO_EAST`/`IO_WEST`
  taking the **horizontal** site and `IO_NORTH`/`IO_SOUTH` the **vertical** one
  (`evidence/rotation_rowdump_0326.txt`).

That reads as a transposition, and I was ready to file it as one. It is not.
The tool's own option table documents `-horizontal_site` as "the site for the
horizontal pads (**east and west**)" and `-vertical_site` as "the site for the
vertical pads (**north and south**)", and documents the vertical rotation's
default as belonging to "the southern (bottom) row". Every number measured is
documented behaviour of a tool that is self-consistent with its own contract.
**A plugin-side rule here would not be papering over a tool defect, because
there is no tool defect.** Filed as Bucket D with the refutation recorded, so
it is not filed again.

**So the variable is not inert.** It is live, and it governs the north and
south rows. The source report's sweep varied the knob for one row family while
observing the other, and read "no effect on the sides I measured" as "no effect".
That is F1's rule with the population swapped: *no effect* and *not varied for
the part that responds* are different verdicts.

The general rule captured is therefore **not** "this variable is inert" but
"a published no-effect claim must state the population it varied AND the
population it observed" — Bucket A, deterministic, and it names no variable.

The loud-degradation ruling itself still stands, and I did not touch it. A run
that deliberately sets the variable should still get rc 2 NOT DETERMINED: this
step genuinely cannot honour "rotate the vertical side" through an option that
rotates the other two. Only the stated REASON is wrong.

## A live defect this converge produced — Bucket C

`main` ships that wrong reason. `pad_ring_gen.py` carries
`ROTATION_VERTICAL_INERT` with `"honoured": False` and
`"reason": "the placer does not read it..."`, written into **every** report.
The placer does read it. The measurement quoted beside it is correct and
reproduces; the sentence drawn from it is false.

Filed Bucket C, not A, and the `why_not_bucket_a` is stated in the record: the
input is a free-text reason beside a correct table, and deciding whether the
inference is sound requires reading which part of the layout the option is
documented to govern — prose in the tool's option table that no deterministic
rule in this repo can adjudicate. The F1/F3 rules make the gap **visible** by
requiring the observed population beside the varied one; they cannot decide the
claim. I did not weaken the record to make it fit Bucket A.

## What I did NOT write, and why

The brief says: check for the existing one; if the rule exists, the deliverable
is a one-line reference, not a near-duplicate checker.

I checked `programs/` on main first — 1163 files — and the two rules do not
exist there. They **do** exist, already implemented with tests, on a concurrent
lane's unlanded branch `jcapsha/capture-sha256-recovery`:

    programs/absence_verdict_names_its_search_space_check.py   (F1)
    programs/upstream_mirror_is_pinned_check.py                (F2)

Those are the same two rules I would have written, reached independently. I did
not write a second copy. This lane's added value is that their conclusions are
now **replicated on a different image and a newer tool build**, and that the
Bucket-T question is settled against the tool's documentation rather than by
measurement alone.

## What was run

    enhancement_emit.py --records recoveries.json --out-dir candidates/   rc 0
      A=3 C=1 D=1 T=0, Bucket A routed (no unrouted records)
    backlog_sanitize_check.py --file <the emitted YAML>                   rc 0
      findings: []

The sanitize rc was captured **directly**, not through a pipe. A concurrent
lane published "the YAMLs pass" on the strength of `checker | tail -4; echo $?`,
which reports `tail`'s status and is 0 whatever the checker said. On the first
run mine genuinely did fail (`component` must be `program:<name>`); it was fixed
in the record and re-emitted, not waived.

`CAPTURE_ROUTING.json` gains one entry: step `15.5ic` ships two programs and had
**no routing entry at all**, so a Bucket-A capture taken there was reported
unrouted and its sketch silently skipped. Nine added lines, nothing else touched.

## I verified the other lane's guards rather than re-writing them, and one has a hole

Both were run against their own tree, in a detached worktree at `0c1a7b4c8`:

    absence_verdict_names_its_search_space_check   rc 0
      1278 files parsed, 31 absence verdicts, 31 naming a locus
    upstream_mirror_is_pinned_check                rc 0
      1278 files parsed, 3 declared mirrors, 0 undeclared candidates
    their five test files                          31 passed, 7 skipped

I checked what the 7 skips ARE rather than reporting the count, because an
uncharacterised skip is the same shape this lane is about. They decline BY
NAME and they name the missing input — "upstream ... is not on this host:
$VIBEIC_LIBRELANE_ROOT is unset or does not carry it and `librelane` is not
importable. The question could not be put here; it is put in the container
image that ships the flow." That is an honest decline, not a vacuous pass,
and it is the one thing a skip count alone cannot tell you.

Real denominators on both, so neither is a gate that walked nothing. Load was
92 on 32 cores throughout, so no timing conclusion is drawn from any of it.

Then the check that fixtures cannot make: does the guard fire on the REAL tree.
I stripped both path literals out of a shipped refusal in `erc_density_check.py`
— the entire content that says where it looked — and re-ran.

**It stayed green.** 31 of 31, PASS. Reproduced in isolation one word apart:
`No density artefact was found` passes, `No widget was found` fails. `artefact`
is in the guard's locus vocabulary, and a bare locus WORD anywhere in the
message prose satisfies the predicate.

The vocabulary mixes words that disclose a PLACE (`path`, `dir`, `tree`,
`where`, `searched` — the code comment's own example, "no LEF view was opened",
is one of these and is rightly accepted) with words that merely name the MISSING
THING (`artefact`, `file`, `report`, `manifest`). An absence message can hardly
avoid containing the second kind, so for that population the check cannot fail.

This is NOT the generosity the guard discloses. Its docstring waives
imprecision; this passes a verdict that says nothing, which is the state it
exists to refuse. Filed as the sixth record, Bucket A — partitioning a word list
is deterministic. I did NOT make the change: the guard belongs to the lane that
wrote it, and the partition has to be measured against the existing 31 first,
because a guard that reddens on what we just shipped is a bug not a guard.

**Where that lane was right, and I checked before saying so.** Its scope section
states plainly that it does not check the locus is COMPLETE, and names the exact
decision it cannot make from its input — that whether both declaring views were
opened is a property of the distribution, not of our Python. That is the ladder
applied correctly, and it means the guard does not claim to catch the original
defect. My finding is about the half it DOES claim.

Evidence: `evidence/absence_guard_prose_noun_is_not_a_locus.md`,
`evidence/absence_guard_mutation_stayed_green.txt`. The mutation was reversed by
a reverse edit and `git status` re-verified clean; `__pycache__` was cleared
before the run.

## Not done

No version bumped, nothing pushed to main. No pad was placed, no GDS touched,
no assertion relaxed, no regex widened, no test deleted, no baseline written,
`--write-baseline` never used. The full `programs/tests` suite was not run.
