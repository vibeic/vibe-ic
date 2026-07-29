# Upstream patches: ones we owe them, and ones we owe ourselves

Two kinds live here, and the direction matters:

* **OUTBOUND** — a fix we carry in a `vibeic/` fork that belongs to the upstream
  project, prepared against upstream `master` and ready to send.
* **INBOUND (backport)** — a fix upstream has already landed that our fork does
  not have, because we are pinned behind their master. A fork that only ever
  moves forward on our own patches silently accumulates crashes upstream fixed
  months ago.

**An OUTBOUND patch lives here** when the defect reproduces on **stock**
upstream, the fix is separable from our own doctrine, and sending it has not
happened yet. The middle condition is what keeps this directory honest — most of
what our forks carry is policy we chose (abort → warn + continue, extra DRC
coverage, ECO-aware reroute), and upstream has not asked for any of it. Bundling
policy into a defect fix is how a PR stalls, and deserves to.

**An INBOUND patch lives here** when upstream has landed a fix our pin predates
and we have not yet rebuilt with it. It leaves when the fork is rebuilt and the
defect is re-tested — a backport recorded but never applied is worse than one
never written, because the file makes it look handled.

## Sending one

These are **outward-facing contributions in this org's name**, so they are not
sent automatically. Each entry below records what is verified and what the
sender still has to do — upstream's `CONTRIBUTING.md` requires DCO sign-off and
a test, and a test for a crash needs a reduced case, not our 22 MB DEF.

---

## `openroad-flexpa-updatedirtyinsts-omp-guard.patch`

**Target** `The-OpenROAD-Project/OpenROAD` `src/drt/src/pa/FlexPA.cpp`

**Defect.** `FlexPA::updateDirtyInsts()` runs `genInstAccessPoints()` inside
`#pragma omp parallel for` with no exception guard. When a pin genuinely yields
zero access points, `logger_->error(DRT, 73)` throws, the throw crosses the
OpenMP boundary, and `std::terminate` kills the process — no diagnostic, no
report, mid-ECO.

**Why it is upstream's, not ours.** That file has three parallel regions, and
the other two already carry `ThreadException`:

```
line 167  updateDirtyInsts()   omp parallel for   NO guard
line 197  updateDirtyInsts()   omp parallel for   ThreadException + try/catch
line 306  (a later function)   omp parallel for   ThreadException + try/catch
```

Two of three guarded — and the corrected reading makes the case stronger, not
weaker: **both of the first two are inside `updateDirtyInsts` itself**, thirty
lines apart, one guarded and one not. This file previously attributed line 198 to
"the next function"; measured against upstream `master`, `updateDirtyInsts` spans
122-209 and the next definition (`FlexPA::deleteInst`) begins at 210, so 197 is
in the same function. The earlier reading came from bounding the function with
the first `^}` after its opening, which lands past the end.

Re-checked after the 2026-07-29 fleet merge took 19 upstream commits into our
fork: the region at 167 is still unguarded upstream, so this is still owed.
Verified against upstream `master` as fetched, not against our fork.

**The patch is the guard only.** Our fork additionally passes
`allow_pin_access_failure=true` so the inaccessible pin degrades to a warning
and the ECO continues. That parameter does not exist upstream — their signature
is `genInstAccessPoints(frInst*)` — and it is a policy change upstream has not
asked for. It stays ours. Guard alone means `DRT-0073` still errors, but as a
reportable error instead of `std::terminate`, which is strictly an improvement
and needs no policy discussion.

**Trigger** (see vibe-ic#551): a repair that follows a route which did not
complete. Six commands over a routed DEF, stock sky130A, deterministic,
reproduces at `set_thread_count 1`.

**Before sending, still to do:**

- reduce the case — six commands over a 22 MB ibex DEF is a report, not a test.
  Upstream asks for one, and the reduction is real work nobody has done.
- confirm the fix on a *stock* build. Ours is verified because we ship it; the
  patch as written has not been compiled against upstream `master`.
- DCO sign-off, per upstream `CONTRIBUTING.md`.

**Not blocking, worth knowing.** Two segfaults sit behind this abort and are
only reachable once it stops terminating: `rsz::Resizer::stitchTrees` (what
stock dies of, via a different path) and `drt::FlexGCWorker::Impl::initPA0`
(what ours dies of). Landing the guard is what lets anyone else see them.


---

## `openroad-rsz-stitchtrees-null-subtree.patch` — INBOUND, SUPERSEDED BY THE MERGE

> **This patch is no longer needed and is kept only until the rebuild is
> re-tested**, per this file's own rule that an inbound row leaves when the fork
> is rebuilt and the defect re-tested — not when someone reads that it should be.
>
> The 2026-07-29 fleet merge (owner ruling: merge ALL new upstream commits) took
> 773 upstream commits into `vibeic/openroad-integration`, and the pin now names
> `483d0cb46`. Verified against that exact ref: the `if (!tree1 || !tree2)` guard
> is present, and our own `allow_pin_access_failure` survived alongside it. So
> the hand-prepared backport below is redundant — taking all of upstream is what
> the ruling changed, and this is the first thing it delivered.
>
> Delete this entry once a build from that pin has run the vibe-ic#551
> six-command case.

## Original entry

**Backport of** `The-OpenROAD-Project/OpenROAD` `5b9e0a371` (2026-07-13),
"rsz: Avoid SIGILL in net tree stitching if subtree can't build",
Signed-off-by: Mike Inouye.

**Why we do not have it.** `vibeic/OpenROAD` is pinned at `1bade74e`, which is
51 commits ahead of the upstream base it forked from and **772 behind** upstream
master. This fix landed in that gap.

**The defect.** `Resizer::estimateSlewsAfterBufferRemoval` calls
`makeBufferedNet` twice and passes both results straight into `stitchTrees`
without checking either. When a buffered net fails to build — logged as
`[WARNING RSZ-0075] makeBufferedNet failed for driver <pin>` and then ignored —
`stitchTrees` dereferences null.

Upstream's own reproduction: "calling `repair_timing` on a pre-placement netlist
where buffered nets can fail to build". Ours (vibe-ic#551) is the same shape
from the other end: `repair_timing` after a `detailed_route` that did not
complete. Three `RSZ-0075` warnings, then Signal 11 in `stitchTrees`.

**Measured on stock `26Q2-2270-g4c26918f5`** — the OpenROAD the iic-osic-tools
base ships, which predates the fix — segfault, `rsz::Resizer::stitchTrees` <-
`estimateSlewsAfterBufferRemoval` <- `UnbufferGenerator::generate`.

**We have not hit it**, and the reason is worth stating: our build crashes
EARLIER, in `FlexPA::initPA0`, on the same command. Two faults race on one path
and ours wins. Fixing either one alone would expose the other.

Applies cleanly to our fork's `Resizer.cc` at line 6670; verified by applying it
to a copy of the file as fetched from the fork.

**Before applying, still to do:** build the fork with it and re-run the #551
six-command case. A three-line null check is about as safe as a change gets, but
"safe-looking" is not "compiled".

### The general point this raises

Nothing in the fork-gatekeeper flow currently asks *what has upstream fixed that
we lack*. It tracks upstream commits for **selective adoption** — should we take
this feature — which is a different question from **are we carrying bugs they
have already fixed**. 772 commits is a lot of room for the second kind, and this
one was found only because a crash walked us into it.
