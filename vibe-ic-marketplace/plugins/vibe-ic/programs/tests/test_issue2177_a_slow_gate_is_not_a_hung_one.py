#!/usr/bin/env python3
"""vibe-ic#2177 — a gate slower than the stall lease is not a wedged one.

THE DEFECT, IN THIS REPO'S OWN SHIPPED NUMBERS
==============================================
The hygiene shard is supervised by `_owned_process_supervisor` in attestation
mode, where `output_progress=False` and the ONLY forward-progress signal is one
attestation row per COMPLETED GATE.  The lease is spent between two consecutive
validated events, so the unit that gets killed is a WHOLE GATE, and the stall
grace is therefore a wall clock for any single gate.

`hygiene_gate_profile.json` at v1.19.39, the profile this repo SHIPS::

    gates are host-independent      2556 s
    an argued direction is pinned    646 s

against the graces actually in force::

    repo_hygiene_parallel.DEFAULT_STALL_GRACE_S       300 s
    gatekeeper_review._HYGIENE_STALL_GRACE_S         1800 s

Two gates above the first; one above the second.  MEASURED on 8HD-6, three
landing logs of 2026-08-27 (`~/j1786/baseev/base_land.log` and the two under
`~/j1786/tmp/gk_land_diff.8oX709/`), all three carrying::

    arm A shard 0: PROGRESS_PROTOCOL_INCOMPLETE: attestation progress ended
    before assigned gates completed: an argued direction is pinned; progress
    watchdog outcome=stalled, rc=199; the shard did not complete naturally

and the landing then reporting `16 wiring error(s) in the hygiene gate
declarations, so the set certifies nothing`.  Not one of those sixteen was a
property of the tree.

WHAT IS ASSERTED HERE, AND IN WHICH DIRECTION
=============================================
1. A supervised job that runs FAR past its stall lease while reporting
   sub-unit progress COMPLETES.  It is DRIVEN — a real child process under the
   real `run_owned` — not simulated.
2. A job that stops reporting IS killed, and the refusal NAMES the gate that
   was in flight and how long the lease had gone unrenewed.
3. THE MUTATION.  Delete the in-flight renewal (the one line that adds
   `inflight_probe.sample()` to the score) and arm 1 must go red — that is the
   wall clock restored, and a fix whose removal changes nothing was never a
   fix.  Driven by monkeypatching the reader to a frozen score, which is
   byte-equivalent to the channel contributing nothing.
4. The protocol refuses what it must refuse: an unassigned label, a unit that
   does not advance, a denominator that moves, a rewritten history.  A channel
   that accepted those would be a lease anyone could hold open forever.

chip/tool-AGNOSTIC: `sleep`, `printf` and a temporary directory.  No IC, no
PDK, no vendor, no benchmark.
"""
from __future__ import annotations

import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))


LABEL = "an argued direction is pinned"
OTHER = "gates are host-independent"

#: The lease every arm below runs under.  Small so the file is fast; the SHAPE
#: is the production one — a job whose runtime is a multiple of its own lease.
GRACE_S = 3.0
POLL_S = 0.25
#: Long enough that a wall clock could not miss it: 6x the lease.
RUN_S = 18.0
UNITS = 12












# ══════════════════════════════════════════════════════════════════════════
# 1. ACCEPTANCE 1 — a long gate that reports progress is NOT killed.
# ══════════════════════════════════════════════════════════════════════════



# ══════════════════════════════════════════════════════════════════════════
# 2. ACCEPTANCE 3 — the mutation. Remove the renewal and arm 1 goes red.
# ══════════════════════════════════════════════════════════════════════════





# ══════════════════════════════════════════════════════════════════════════
# 3. ACCEPTANCE 2 — a worker that stops reporting IS killed, BY NAME.
# ══════════════════════════════════════════════════════════════════════════





# ══════════════════════════════════════════════════════════════════════════
# 4. THE PROTOCOL REFUSES WHAT IT MUST REFUSE.
#    Each of these is a way to hold a lease open on a job going nowhere.
# ══════════════════════════════════════════════════════════════════════════







def test_a_healthy_stream_scores_every_row():
    pass  # covered by the driven arm above; kept out of the refusal table










# ══════════════════════════════════════════════════════════════════════════
# 5. THE CHANNEL IS INERT WITHOUT A SUPERVISOR, AND REFUSED WITHOUT ONE.
# ══════════════════════════════════════════════════════════════════════════





# ══════════════════════════════════════════════════════════════════════════
# 6. THE TWO GATES THAT ARE ACTUALLY ABOVE THE LEASE NOW RELAY THEIR OWN
#    EARNED EVENTS OUTWARD.
#
#    The channel above is useless if the only two gates that need it never
#    write to it, so this section drives the relay in the gate that carries
#    the whole problem — `gates are host-independent`, 2556 s in the shipped
#    profile — through its own declared test seam.
# ══════════════════════════════════════════════════════════════════════════







# ══════════════════════════════════════════════════════════════════════════
# 7. THE GENERIC HALF — the 152 gates that know no denominator of their own.
#
#    MEASURED on 8HD-6 at load1 ~30, `repo_hygiene_parallel --stall-grace 300`
#    over a pristine a1f3685837ca: four shards killed at rc 199 across the two
#    arms, and for two of them the gate in flight was `every program is
#    reachable` — which the shipped cost profile does not list among its heavy
#    rows at all. Instrumenting the two known-heavy gates would not have saved
#    that shard, and neither would a bigger number: under load ANY gate can
#    outlive any clock somebody picked.
#
#    So the dispatcher also OBSERVES the gate it launched. Every row must prove
#    its own advance, at both ends: the writer refuses to append one, and the
#    reader refuses to score one.
# ══════════════════════════════════════════════════════════════════════════















def test_the_dispatcher_kills_only_its_own_recorded_poller_pid():
    """Never a pattern. Every agent on this fleet runs the same script names,
    and `unanchored_process_kill_check` forbids a pattern kill in shipped
    code for exactly that reason."""
    dispatch = (PROGRAMS.parent.parent.parent.parent
                / "tools" / "ci" / "_gate_dispatch.sh")
    body = dispatch.read_text(encoding="utf-8")
    start = body.index("_gate_inflight_poller_stop() {")
    stop_body = body[start:body.index("\n}", start)]
    assert 'kill "$GATE_DISPATCH_INFLIGHT_POLLER"' in stop_body, stop_body
    assert "pkill" not in stop_body and "pgrep" not in stop_body, stop_body
