# Patches we owe upstream

Fixes we carry in a `vibeic/` fork that belong to the upstream project, prepared
against upstream `master` and ready to send.

A patch lives here when three things are true: the defect reproduces on **stock**
upstream, the fix is separable from our own doctrine, and sending it has not
happened yet. The middle condition is the one that keeps this directory honest —
most of what our forks carry is policy we chose (abort → warn + continue, extra
DRC coverage, ECO-aware reroute), and upstream has not asked for any of it.
Bundling policy into a defect fix is how a PR stalls, and deserves to.

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
line 167  updateDirtyInsts()   no guard
line 198  (next function)      ThreadException exception;
line 306  (next function)      ThreadException exception;
```

Two of three guarded, and the unguarded one is thirty lines from a guarded one.
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
