"""63x8 matrix — DIMENSION 3 (``outputs_produced``).

    Are the declared ``required_outputs`` genuinely PRODUCED?

One parametrized cell per flow step (63 of them). For a step that declares
outputs the predicate is:

    every entry of ``required_outputs`` resolves, on a real run, to an
    artefact that exists and is **larger than zero bytes**.

THE ZERO-BYTE RULE IS LOAD-BEARING
==================================
A 0-byte ``drc.rpt`` is equally consistent with "0 violations" and with "the
tool never wrote anything". Presence alone therefore does not answer this
dimension's question, and every resolver in this module rejects an empty file
before it counts as evidence.

SO IS THE SYMLINK RULE
======================
``Path.is_file()`` and ``Path.stat()`` FOLLOW a symlink and report the
target's bits, so a canonical output path that is only an ALIAS for a file
produced somewhere else — most damagingly for one of the project's own INPUTS
— reads as produced. Two shipped gates already ban exactly this
(``chip_gds_canonical_real_file_check.py``: "gds_size_check follows symlinks
transparently and reports the target's size, so a symlink masking a missing
tape-out artefact passes audit"; ``canonical_path_symlink_forbid_check.py``,
whose forbidden trees include ``analog/hardmacro/**`` and
``phase3/stage4/**``), and this module was reproducing the disease it was
written to catch: step A8's ``phase3/analog/hardmacro/*/*.gds`` resolved to a
37 MB hit that is a symlink into ``design_data/gds/`` — the design's INPUT
layout, aliased under the hardmacro output tree.

A symlink is therefore never evidence of production, anywhere in this module,
and is reported as its own category rather than folded into "missing".
Measured across all 63 steps and every admissible run root on the campaign
host (2026-07-28): 107 entries resolve to real files and 6 candidate matches
are rejected as aliases, all of them under three steps — A5, A8 and 37 — and
all pointing at the same two files in that project's ``design_data/gds/``.
Only A8's ``.gds`` changes verdict: A5 and 37 record an in-repo run root that
carries the real artefact, so they resolve there instead.

EVIDENCE MUST BE REPRODUCIBLE FROM THIS REPOSITORY (#527)
=========================================================
This dimension answers a question about a FLOW STEP, and its answer must be
the same on every host. Before #527 it was not: two mechanisms let a file that
happens to sit on one particular machine decide a cell.

* **A run tree outside the repository.** Run roots recorded ``kind: "home"``
  were looked up under ``$HOME`` (and under an env-var list). On the campaign
  host ``~/AI_IC_design/4th_benchmark/cv32e40p_e2e/phase2/stage1/fpga/
  output_files/*.map.rpt`` resolves; on CI nothing does. Same commit, two
  answers.
* **An UNTRACKED artefact inside an in-repo run tree.** ``benchmark-data/ic/
  sha256/phase2/stage1/fpga/output_files/*.{sof,map.rpt}`` exist in the
  maintainer's working tree and are tracked by NO commit (``git ls-files``
  reports zero ``.sof`` and zero ``.map.rpt`` in the whole repository). They
  made step 6 — waived ``xfail(strict=True)`` because no reachable host can
  build an FPGA bitstream — XPASS on that checkout and xfail everywhere else.
  Emptying ``$HOME`` did not move it: the file was inside the repository
  directory, just not inside the repository.

Both are the same defect: *a verdict that reads the same whether or not the
thing it claims actually happened*. So evidence is now admitted from exactly
three sources, and all are reproducible from tracked repository records:

``PRODUCED_BY_RUN``
    An archived run tree **inside this repository** contains a non-empty,
    non-symlink artefact matching the entry **that is tracked at HEAD**.
    Every checkout of this commit has that file, byte for byte. Re-resolved
    with ``flow_compliance_check._glob_first`` — the flow's OWN resolver,
    imported rather than re-implemented, so this module cannot drift away
    from the semantics the real gate uses (the ``reports/<subdir>`` and
    canonical-analog-dir fallbacks included).

``PRODUCED_LIVE``
    No archived run has the artefact, but running the entry's declared
    producer NOW, in a throwaway **tracked-only** copy of an in-repo run
    tree, makes it land non-empty. This is the strongest available evidence —
    an actual production event, this second, by this checkout's code — and
    the copy is tracked-only so the producer sees exactly what a fresh clone
    would give it. (Measured 2026-07-28: all five live-produced entries still
    land from a tracked-only copy, so nothing was resting on a local
    leftover; and a stale untracked copy of the target in the working tree
    can no longer make ``produce_live`` report "already present".)

    For steps 10 / 23 / 24 / 26 the producer is not guessed: the flow's own
    gate clause names the declared output as its ``--json`` argument, so the
    command is derived from the yaml. (Step 9's producer,
    ``synth_area_stats_emit``, is named explicitly because that step's gate
    does not name it; the program's own module docstring states it exists
    precisely because "nothing ever wrote either one".)

``RECORDED_UNPUBLISHED``
    The real publisher resolved the declared run-relative path while staging a
    converged cell and committed a tracked ``STEP_RECORD.json`` row carrying
    positive byte size, a real sha256, ``in_cell: false`` and the explicit
    ``OUT_OF_PUBLISHED_SCOPE`` decision.  The digest is evidence that the run
    produced named bytes; it is not a claim that those bytes are present in the
    cell.  A missing row, missing/placeholder digest, skipped step, symlink, or
    any other decision remains a negative verdict.  This is the publisher's
    existing policy seam for engineering output deliberately withheld from the
    published tree, not a second baseline written by this test.

Anything else — a file under ``$HOME``, a build product in the working tree
that no commit carries, an operator-supplied directory of run trees — is a
property of the machine, not of the repository, and is not evidence here.
An UNTRACKED match is therefore rejected and reported as its own category,
exactly like a 0-byte match and a symlinked match: "a local build product
nobody committed" and "absent" are different findings and conflating them is
how a machine's history reads as a flow's behaviour.

WHY UNTRACKED IS THE RIGHT LINE, STATED EXPLICITLY
==================================================
It is deliberately NOT "the file exists". A produced artefact that matters to
this dimension is one the repository can show to anyone: `git clean -xdf`
must not be able to change a verdict, and two checkouts of one commit must not
disagree. An untracked build product fails both. It may well be genuine — the
``.sof`` above really was compiled by Quartus once — but genuineness is not the
property under test; *reproducibility of the claim* is. The correct way to
promote such an artefact to evidence is to commit it (or its run tree), at
which point every host agrees again.

In the case that prompted this, the repository had in fact already said so in
writing: ``git check-ignore -v`` attributes both files to ``.gitignore:96``
(``output_files/``). The repository declares that directory to hold build
products it does not carry, and this dimension was reading production evidence
out of it anyway. "Ignored" is a stronger statement than "untracked", but the
admissibility rule needs only the weaker one — a path the commit does not
carry is not evidence — so that is what is implemented, and the ignore rule is
recorded here as corroboration rather than relied upon.

ADMISSIBLE RUN ROOTS
====================
A run root must (a) live INSIDE this repository and (b) prove it is evidence
rather than a directory. There are two ways to prove that, one per manifest
``kind``, and they are kept apart on purpose (:data:`_ADMISSIBILITY`):

``repo`` (:func:`_is_flow_run`)
    carries ``provenance.jsonl`` or ``reports/orchestrator/`` — a tree a flow
    runner actually wrote. Agent scratch trees are excluded on purpose: the
    only ``phase3/analog/hardmacro/*/*.gds`` files on the campaign host were
    written by a throwaway ``mkgds.py`` seeding INPUTS for a backlog repro, and
    counting a seeded input as a produced output would be precisely the
    adjacent-measurement disease this campaign exists to remove.

``published`` (:func:`_is_published_cell`)
    a ``benchmark-data/ic/<IC>/v<version>_<PDK>/`` cell that
    ``benchmark_evidence_publish.py`` staged from a CONVERGED run. A published
    cell is a curated COPY of a run tree, so it does not carry the runner's
    marker; it carries instead the machine verdict the publisher REFUSES to
    stage without. Added 2026-08-06 for A8, and added as a second predicate
    rather than as two more strings in :data:`_RUNNER_MARKERS`, because
    loosening one rule for all thirteen roots on the strength of one root is
    how an admissibility rule stops admitting anything.

STEP A8: THE PRODUCER LANDED, THE EVIDENCE DID NOT
==================================================
A8 declares four artefacts and archived runs carry three. The ``.gds`` had no
producer anywhere in the plugin (``magic_port_extract_emit
.build_gds_write_tcl`` shipped in v0.1.114 with a unit test and no caller), so
by construction no run ever wrote one. ``programs/analog_hardmacro_gds_emit.py``
is now that producer: declared in A8's ``programs:`` and invoked by
``analog_one_shot_runner.step_for_block("A8_hardmacro_gen")`` — and
deliberately NOT by A8's gate, because ``flow_compliance_check`` is the
acceptance AUDITOR and an auditor that writes a declared ``required_output``
into the project it audits certifies its own output
(``test_d3_the_compliance_audit_does_not_create_declared_outputs``).

Between 2026-07-28 and 2026-08-06 the cell was nonetheless still WAIVED, with
the reason narrowed from "nothing produces this" to "nothing can EVIDENCE it
here". Magic writes the stream inside the EDA container, the producer's
documented rc=2 names the gap (``A8GDS_NO_STAGE`` / ``A8GDS_NO_MAGIC`` /
``A8GDS_NO_TECH``), and neither CI — a plain runner with pytest and no docker
— nor a fresh clone has that container. Marking the entry ``PRODUCED_LIVE``
would have made the cell green on hosts with an EDA container and red
everywhere else, which is the property #527 removed from this module.

2026-08-06 — THE WAIVER IS GONE AND THE CELL IS ENFORCED, because the thing
the waiver said it was waiting for happened. Its evidence field asserted that
``git ls-tree -r --name-only HEAD`` matched ZERO paths against
``phase3/analog/hardmacro/*/*.gds``; commit b1665ec8 published
``benchmark-data/ic/u_hawaii_adc/v1.9.86_sky130A/phase3/analog/hardmacro/
{delta_sigma,ldo}/*.gds`` (111096 B and 641262 B), the premise went false and
``test_d3_waived_unproven_entries_have_no_committed_artefact`` turned the suite
red on it. That is the anti-rot mechanism, not a nuisance: the waiver's own
closing condition read "a published analog run whose A8 actually streamed the
layout", and this is one.

Reading a COMMITTED artefact needs no container, so the cell is now green on
every checkout and red on none — the #527 property holds in the direction it
is meant to. The entry is recorded ``PRODUCED_BY_RUN`` against the published
cell, which this module admits as an evidence root under its own kind
(:func:`_is_published_cell`) rather than by widening
:data:`_RUNNER_MARKERS`. What was NOT done, and is worth stating because the
2026-07-28 text refused it in these words: no ``.gds`` was written into a run
tree to turn a test green. The artefacts were published by the benchmark
publisher, from a converged run, in a commit that is not this one.

What IS asserted, on every host: the producer exists and a FLOW PATH dispatches
it (``test_d3_a8_producer_is_reachable_from_a_flow_path``, with
``analog_one_shot_runner.subprocess`` recorded); the emitter behaves
(``programs/tests/test_analog_hardmacro_gds_emit.py``); and whatever a run root
does carry at that path must BE a hardmacro layout — real GDSII header, real
geometry records, defining a structure named after its own block directory
(``test_d3_a8_gds_in_a_run_root_is_a_real_hardmacro_layout``). That last one
matters because a 1.18 MB chip-top GDS from a different design and a different
PDK, dropped under the glob, measurably satisfied every weaker predicate.

BE PRECISE ABOUT WHAT CLOSING THIS WOULD AND WOULD NOT MEAN. This dimension
asks whether the declared outputs are PRODUCED, not whether they are
CONSISTENT. Step A8's own gate still FAILs on the analog reference run, and
once a real run produces the ``.gds`` the failure moves from
``analog_hardmacro_check`` (``HARDMACRO_INCOMPLETE`` — the layout is missing)
to ``analog_lef_gds_outline_check`` (``A8_LEF_GDS_OUTLINE_MISMATCH`` — the hand
authored LEF ``SIZE`` and the streamed bounding box disagree by two orders of
magnitude). That is a sharper finding, not a softer one, and it belongs to the
criteria dimension.

TOOLCHAIN-GATED CELLS (steps 6 and 39) STAY WAIVED — AND WHY THE NA WAS WRONG
=============================================================================
Both declare an Intel Quartus bitstream that no program in this plugin
synthesises. A proposal moved them out of the waiver registry and into a new
``NA_TOOLCHAIN_ABSENT`` state whose precondition was asserted live through the
flow's own locator (``design_one_shot_runner._find_host_quartus_sh`` plus
``_container_has_quartus_sh``): a "self-invalidating NA" that would go red the
day Quartus appeared.

It went red immediately. Re-measured 2026-07-28 on the maintainer host, that
locator returns a real, executable ``quartus_sh`` under an external mount, so
both cells failed their own NA assertion. The design of the NA was sound; its
premise was a property of ONE MACHINE, which is precisely the host-dependence
#527 took out of this module. The waivers are back, and their premises are
statements about the COMMIT (``git ls-tree -r HEAD`` finds no tracked ``.sof``
or ``.map.rpt`` anywhere) that every checkout answers the same way. The NA
machinery is removed rather than left unused: a pinned set nothing populates
asserts ``{} == {}``.

THE WRITE LEDGER — "DID THIS STEP WRITE IT", NOT "DOES A FILE EXIST"
====================================================================
Everything above resolves a PATTERN. ``flow_compliance_check._glob_first`` —
the resolver this module imports on purpose — answers *does something matching
this glob exist under this root*, and for a ``reports/`` pattern it will answer
YES out of ``reports/<subdir>/`` when the declared path itself was never
written. It is not able to answer *did THIS STEP produce it*: it is handed a
pattern and nothing else.

``programs/step_write_ledger.py`` records the other half — one ``lstat`` walk
of what the run ACTUALLY wrote, residualled against the declaration, per step,
with producer attribution from the run's own ``provenance.jsonl`` — and until
2026-08-06 NO GATE READ IT (``grep -rl 'write_ledger' programs/*.py
flow/*.yaml`` returned only the two programs that write it). D3 now does.

THE RULE, AND ITS ONE DIRECTION. When an admissible run root carries a write
ledger, :func:`resolve` consults the ledger's row FOR THE STEP BEING ASKED
ABOUT, and the ledger may only ever SUBTRACT:

* the ledger records the spec as ``declared_output_not_produced`` -> whatever
  the glob found is refused, under :attr:`Rejected.unwritten`, quoting the
  ledger's own reason and — where the run's provenance log claims a digest for
  a path that is now empty or broken — the CONTRADICTION and the tool that
  claimed it;
* the glob's hit is not one of the paths the ledger records that step as
  having written -> refused under :attr:`Rejected.unattributed`.

It may never ADD. A path the ledger calls produced still has to be non-empty,
non-symlink and tracked at HEAD; those rules run FIRST and unchanged
(``test_d3_the_write_ledger_can_only_subtract_evidence`` asserts all three
against a ledger that records the path as produced). The ledger is also not
consulted where the question is about the PROJECT rather than about a step —
the NA-dormancy probe and the waiver-premise guards pass no step id, so a
ledger can never suppress the artefact that falsifies an NA.

The ledger must itself be TRACKED AT HEAD. It can only redden a cell, so an
untracked one would let ``git clean -xdf`` change a colour and two checkouts of
one commit disagree — #527's defect arriving from the other direction.

MEASURED 2026-08-06, AND THE ANSWER IS ZERO — WHICH IS THE POINT
----------------------------------------------------------------
On THIS checkout: **0 of the 63 cells change state.** No admissible run root
carries a tracked ledger (``step_write_ledger`` landed the same day and no run
tree has been re-published since), so every cell degrades to the pre-ledger
behaviour. That is not silent: every verdict detail now ends with a
``[write ledger — <root>: not bound (<reason>) ...]`` clause naming each root
and why, and :func:`ledger_population` DERIVES the bound set from the commit so
the first published ledger is a loud, named event rather than a discovery.

AND NO LEDGER IS COMMITTED TO CLOSE THAT ZERO — MEASURED 2026-08-06
------------------------------------------------------------------
The obvious way to make the binding fire on the repository's own evidence is to
run the emitter over a published cell and commit the result. It was measured
first, and it is the wrong kind of evidence twice over.

1. **A committed ledger tells this dimension nothing it cannot recompute.** The
   ledger's INTERESTING half — the D5 unwitnessed writes, the D7 residual, the
   ``provenance.jsonl`` window attribution and the contradictions built on it —
   is derived from mtimes, and ``step_write_ledger.mtime_fidelity`` WITHHOLDS
   all of it on any tree a checkout produced. Re-emitted over
   ``$HOME/_sky130A_r3_run`` (455 files, 44 distinct mtimes, top share
   0.165 — a live run) and then over the same tree with its mtimes flattened as
   a clone flattens them, the totals fall ``D5 40 -> 0``, ``D7 335 -> 0``,
   window attributions ``17 -> 12`` — and **the D3 residual is identical, step
   for step, spec for spec, reason for reason**. What survives publication is
   exactly the half D3 consults, and that half is a pure function of the
   tracked tree and the flow declaration, both of which are already in the
   commit. Two independent checkouts of one commit emit ledgers whose D3
   projection is identical and which differ only in ``project``,
   ``mtime_fidelity.under_vcs``, ``capture.walk_ms``, ``captured_at`` and the
   280 ``mtime`` fields that record when each checkout happened — five kinds of
   field about the machine that ran the emitter, and none about the run.

2. **A committed ledger can state a falsehood about the commit that carries
   it, and this module would believe it.** Staged from the published
   ``spm/v1.5.66_gf180mcuD``, ledger emitted and committed, then a follow-up
   commit lands ``phase2/stage1/formal/results.json`` — 620 B, a regular file,
   tracked at HEAD, at exactly step 5's declared path. Unbound, ``resolve``
   finds it. Bound, ``resolve`` returns ``None`` and refuses it under
   :attr:`Rejected.unwritten`, quoting the ledger's ``absent: no path on disk
   matches this spec`` — a sentence that is false of the commit both files sit
   in. Nothing re-checks a committed snapshot; the binding only subtracts, so
   a stale ledger reddens silently and quotes itself as the authority. That is
   the fixture attestation this module threw out the same morning, arriving
   from the red side instead of the green.

So the ledger is DERIVED, never committed.
``test_d3_the_ledger_binding_is_exercised_by_the_repos_own_evidence`` stages a
tracked-only copy of every admissible in-repo run root, runs the REAL emitter
over it, commits the ledger there and resolves all 133 declared entries twice —
1064 ledger-bound resolutions per run, on every host, out of the repository's
own trees rather than a synthetic probe. :func:`ledger_staleness` is the guard
for the day somebody commits one anyway, and
``test_d3_a_committed_ledger_can_be_refuted_by_its_own_commit`` is the control
that it can find a stale one, because a guard that can only measure zero has
not been shown to work.

On FIVE REAL RUN DIRECTORIES with a ledger emitted by the real emitter and
committed — ``$HOME/_sky130A_r3_run``, ``$HOME/_r6_sky130A/run``
and copies of the in-repo ``spm/v1.5.66_gf180mcuD``,
``sha256/clean_run_v1427_20260715`` and ``u_hawaii_adc/v1.9.86_sky130A`` — all
133 declared entries were resolved twice, ledger-bound and unbound:

    run root                              produced  not produced  CHANGED
    _sky130A_r3_run                             88            45        0
    _r6_sky130A/run                             97            36        0
    spm v1.5.66_gf180mcuD                       66            67        0
    sha256 clean_run_v1427                      64            69        0
    u_hawaii_adc v1.9.86_sky130A                29           104        0

665 comparisons, zero differences. The two answers agree because both sides
implement the same doctrine — a symlink is not evidence, a 0-byte file is not
an artefact — and that agreement is the blast-radius measurement, not a null
result: binding to the ledger reddens nothing that was green on real data.

WHAT DOES CHANGE ON A REAL RUN IS THE ATTRIBUTION. Re-measured with
``phase2/stage2/synth/netlist.v`` truncated to 0 bytes on
``_sky130A_r3_run`` (the corruption the ledger's own docstring records):
steps 9 and 14 both declare that path and both were ALREADY red, by the
zero-byte rule. Unbound, the whole message is
``0-byte matches: {...netlist.v}``. Bound, it also carries

    the run's own write ledger records this declared output as NOT WRITTEN by
    this step (zero_byte: ...); and the run's provenance log CONTRADICTS the
    filesystem — provenance claims sha256:ed70a5226c9be057... for a file that
    is now 0 bytes, claimed producer 'yosys'

— a contradiction against yosys's OWN recorded digest, decidable from lstat
with nothing hashed, that no glob could ever have stated.

AND THE HOLE THE BINDING CLOSES IS LATENT, NOT IMAGINARY. Counted across the
same five roots: entries served ONLY by a ``_glob_first`` fallback probe are
0, 0, 0, 0 and 4. The four are ``u_hawaii_adc``'s A1-A4, and each of them ALSO
matches directly through the other side of its ``OR``, which is why none of
them moved. So today no cell rests on a path its own spec does not name — and
``test_d3_the_write_ledger_binds_production_to_the_step`` shows what happens
the day one does: a run that wrote ``reports/phase3/lec.json`` and never wrote
step 13's declared ``reports/lec.json`` is credited with producing it by the
pre-change file, and is not by this one.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
=========================================
* It never reads ``.audit_63x8.json`` verdicts. ``cells_for(3)`` is used only
  to enumerate which cells exist; ``cell.audit_verdict`` is not consulted.
* It never scans program source text for a filename. Production is decided by
  looking at (or creating) the artefact, not by grepping for a string that
  might live in a comment.

A FIXTURE ATTESTATION IS NOT EVIDENCE, AND NO LONGER COUNTS AS ONE
=================================================================
**114 of the 133 declared entries are decided live on every host** — 95
archived in in-repo run trees, 6 produced on the spot, 13 searched for and
genuinely absent. The other 19 name a run tree outside this repository. Until
2026-08-06 those 19 FELL BACK TO THE COMMITTED MANIFEST AND WERE REPORTED
PRODUCED, which is the defect this section now records:

    hit, _rejected = resolve_anywhere(entry)     # <- searched all 7 run roots
    if hit is not None:
        return EntryVerdict(True, LIVE, (...))
    return EntryVerdict(True, FIXTURE, (         # <- ...found nothing: GREEN
        f"[fixture-attested, run root {rec['run']!r} absent here] ...")

A search that comes back EMPTY returned ``produced=True``. Measured on this
checkout: step 17's ``phase3/stage3/pnr/placed.def`` matches nothing
(``find benchmark-data -name placed.def`` = 0; ``git ls-tree -r --name-only
HEAD | grep -c 'placed\\.def'`` = 0) and its cell was green. Because no
lookup could change the answer, SEVEN cells marked ENFORCED with no waiver —
17, 20, 29, 30, M2, M3, M4 — were unfalsifiable: nothing anyone did to the run
tree could move their colour. That is the same disease #527 removed, in its
purest form: *a verdict that reads the same whether or not the thing it claims
actually happened*.

A record dated 2026-07-27 is a claim about the past. It is not evidence that
the artefact exists today, and it is now reported as what it is: the entry is
UNEVIDENCED and NOT produced. The measurement is still printed — the reader
sees the path, the size and the date it was taken — but it decides nothing.

WHY A FAILURE AND NOT A WAIVER
==============================
The alternative was to move those cells to WAIVED, and it was rejected:

* For steps 11 and 29 a waiver would be FALSE. Their declared artefacts ARE
  tracked by this commit — ``benchmark-data/ic/caravel_user_project/
  v1.9.43_sky130A/phase2/stage2/dft/*`` and ``benchmark-data/evaluation/
  phase1_parity/*/phase3/stage3/sim_postlayout/pass.flag`` — merely in trees
  the manifest never registered as run roots, so ``resolve_anywhere`` does not
  look there. ``test_d3_waived_unproven_entries_have_no_committed_artefact``
  would reject the premise, correctly.
* For the other ten the gap is closed by ONE COMMIT — publish the run tree.
  A waiver is a public admission that a gap is *accepted*; granting ten of
  them would convert a one-commit fix into a standing excuse.
* This module's own history is the argument. Its two FPGA waivers rested on a
  ``find ~ -name '*.sof'`` count that was true on one day on one machine and
  false a fortnight later; its A8 waiver existed in two copies telling two
  different stories. A red cell cannot rot. A waiver can, and did.

So the seven cells stop CLAIMING ENFORCED-and-green: they stay ENFORCED and
they FAIL, with a message naming the entry, the run root that is missing and
the one action that closes it. Twelve cells are red for this reason (the
eleven above plus M1, whose waiver covers a different entry) and they are
pinned in :data:`UNEVIDENCED_CELLS` so the population cannot grow quietly.
Falsifiability is restored in BOTH directions and is asserted, not described:
``test_d3_an_entry_that_resolves_nowhere_is_not_reported_as_produced`` plants
step 17's ``placed.def`` in an admissible run root and the cell goes green
again.

Even in the unevidenced state the record is still cross-checked against the
LIVE yaml — the recorded ``alternative`` must still be one of the entry's
declared alternatives — so a yaml edit is caught before the entry is even
searched for.

Before #527 the fixture fallback was the *degraded* mode and the campaign host
decided every entry live, which is precisely why the suite's answer depended
on the machine. External trees are not consulted anywhere, there is no env-var
escape hatch, and the live count is the same on the campaign host, on CI and
on a fresh clone.

2026-07-28: the count moved from 107/126 to 114/133. Every one of the seven
new entries is a dimension-7 declaration that the in-repo run trees ALREADY
carry — six archived, one (``reports/phase3/em_signoff.json``) produced on the
spot by its own declared producer. A8's ``.gds`` did NOT move then: it stayed
in the searched-and-absent bucket, waived, because its producer's evidence
needed an EDA container this dimension may not depend on. The counts above are
re-measured, not carried forward.

2026-08-06: the count is UNCHANGED at 114/133 and A8's ``.gds`` did move — from
searched-and-absent to resolved, out of the ``UNPROVEN`` bucket (13 -> 12) and
into ``PRODUCED_BY_RUN`` (95 -> 96). Both buckets are decided LIVE, so the
total is flat; what changed is that the live search now finds a 641262 B
artefact instead of nothing. Re-measured composition: 96 + 6 + 12 = 114 live,
19 fixture, 133 declared.
``test_d3_evidence_is_live_wherever_the_run_root_exists`` forbids the fallback
whenever an admissible run root actually resolves and holds the live count at
its floor; ``test_d3_the_verdict_does_not_depend_on_the_host`` plants a
complete fake run tree — marker file, matching artefact and all — under a
redirected ``$HOME`` and asserts not one cell moves.
"""
from __future__ import annotations

import contextlib
import fnmatch
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest

from matrix_63x8 import flowref as F
from matrix_63x8 import waivers
from matrix_63x8.cells import cells_for

import _plugin_tree

# WHERE THIS DIMENSION'S EVIDENCE WENT.
#
# Every admissible run root this module cites is a PUBLISHED CELL or a run tree
# that was staged beside one — `benchmark-data/ic/<IC>/v<version>_<PDK>/` and
# friends. Those moved to https://github.com/vibeic/benchmark-data, so in this
# checkout `run_roots()` resolves NOTHING and `audit_step` reports every
# declared artefact as "NOT produced".
#
# That report would be a LIE of a specific and expensive kind: it names a defect
# in the flow ("this step does not produce what it declares") when the truth is
# that the evidence is in another repository and could not be read. A check that
# cannot measure must never report that it measured — the same rule vibe-ic#1357
# fixed for an absent TOOL (skip naming the tool, not a failure about a missing
# artefact). So: corpus absent -> SKIP naming the corpus; corpus present -> run
# exactly as before, and still able to fail.
#
# NOTE ON THE ENV POINTER. `VIBE_IC_BENCHMARK_DATA` is read here ONLY to answer
# "is there a corpus at all". It is deliberately NOT wired into `run_roots()`:
# #527 removed every $HOME search, env override and machine-path manifest from
# this dimension precisely so a cell's colour could not become a property of the
# host, and re-introducing one to make cells green again would undo that.
import _published_corpus as _pc  # noqa: E402
from _published_corpus import SKIP_REASON, corpus_root, needs_corpus  # noqa: E402

# The flow's OWN glob resolver. Imported, never re-implemented: it carries two
# non-obvious fallbacks (reports/<category>/<rest> and the canonical analog
# dir) whose absence would make this module report FALSE NEGATIVES against a
# real run tree.
if str(F.PROGRAMS_DIR) not in sys.path:
    sys.path.insert(0, str(F.PROGRAMS_DIR))
import flow_compliance_check as _fcc  # noqa: E402

#: Resolved once so a rename of the private helper is a loud, named failure
#: rather than a collection-time ImportError two screens away from the cause.
_GLOB_FIRST = getattr(_fcc, "_glob_first", None)

# ONE parser for "does this GDS carry geometry", shared with the A5 layout gate,
# analog_hardmacro_check and the A8 producer, so this module cannot accept a
# hardmacro layout its own consumers reject.
from analog_a5_layout_check import _gds_geometry_count  # noqa: E402

# ONE parser for "which cells does this GDS define" — the plugin's own GDSII
# record walk, imported rather than re-implemented. It is what binds A8's
# streamed layout to the BLOCK it claims to be: geometry alone cannot tell a
# hardmacro apart from any other design's chip-top.
from gds_topcell_name_check import parse_structures  # noqa: E402

# The PUBLISH CONTRACT's own two programs, imported rather than re-stated, so a
# published evidence cell is recognised here by exactly the rule that made it
# publishable. `_audit_verdict` is what `benchmark_evidence_publish.publish`
# calls before it will stage anything and `_CONVERGED` is the set it demands;
# `_NAME_RE` is the canonical `v<version>_<PDK>` folder name that
# `benchmark_evidence_structure_check` enforces afterwards.
import benchmark_evidence_publish as _bep  # noqa: E402
from benchmark_evidence_structure_check import _NAME_RE as _PUBLISHED_NAME_RE  # noqa: E402

# The WRITE LEDGER's own module, imported for its schema string and for
# nothing else. This module READS a ledger a run left behind; it never builds
# one — a dimension that manufactured its own evidence at audit time would be
# the self-certification defect `SELF_CERTIFYING_AUDIT_PROBE` exists to pin.
import step_write_ledger as _swl  # noqa: E402

# THE HALF OF THIS DIMENSION'S QUESTION EVERYTHING ABOVE CANNOT ASK.
#
# Every resolver in this file reads an ARTEFACT: a non-empty, non-symlink,
# HEAD-tracked file in an archived run tree, or one produced live into a
# throwaway copy of one. Not one of them asks whether anything in the SOURCE
# still WRITES the declared path. So a producer can be deleted outright and no
# verdict here moves. MEASURED 2026-08-29 on this checkout, by deleting the
# sole `.sby` write in `programs/crc_vector_gen.py` — the only writer of step
# 5's declared `phase2/stage1/formal/*.sby`:
#
#     clean    54 passed, 66 skipped in 136.23s
#     mutated  54 passed, 66 skipped in  49.95s
#
# Identical, because 53 of the 68 cells SKIP for want of a corpus and the
# remaining 15 answer an NA question about the flow yaml. The dimension whose
# published question is "are the declared outputs PRODUCED" could not see its
# producer die.
#
# `declared_output_has_a_live_producer_check` owns that predicate and is
# IMPORTED here, never restated. It carries an AST write-site scan, a
# glob-vs-glob matcher that runs in both directions, a `_flow_commands` filter
# so a declaration cannot prove itself, and a venue list from which
# `gate_fixtures` is EXCLUDED because a mutation fixture writing 23 declared
# paths measurably read as their producer. A second copy of that in this file
# would drift away from the shipped gate within a release, and this repository
# has paid for that before.
import declared_output_has_a_live_producer_check as _producer  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

DIM = 3

MANIFEST_PATH = Path(__file__).resolve().parent / "fixtures" / "matrix_d3_output_manifest.json"

#: A run root only counts when a flow runner demonstrably wrote it.
_RUNNER_MARKERS = ("provenance.jsonl", "reports/orchestrator")

#: The manifest's ``kind`` for a run root that lives inside this repository.
#: Every other kind names a tree on some particular machine and is never
#: consulted — see the module docstring (#527).
_IN_REPO_KIND = "repo"

#: The manifest's ``kind`` for a PUBLISHED EVIDENCE CELL —
#: ``benchmark-data/ic/<IC>/v<version>_<PDK>/`` (``benchmark-data/PUBLISHING.md``).
#: Also inside this repository, and admitted on a DIFFERENT proof of provenance
#: from a run tree; :func:`_is_published_cell` states which and why.
_PUBLISHED_KIND = "published"

#: Both kinds live in the commit, so both are decided live on every checkout.
#: Everywhere the question is "does the repository carry this root" rather than
#: "how was its provenance proved", this pair is what is meant.
_IN_REPO_KINDS: Tuple[str, ...] = (_IN_REPO_KIND, _PUBLISHED_KIND)

#: Manifest run roots that live INSIDE this repository, so every checkout has
#: them and their entries are always decided live. Derived from the manifest's
#: own ``kind`` field at import; written down here so the split between
#: "in the repo" and "on the campaign host" is stated rather than implied.
#:
#: 2026-08-15 (vibe-ic#1266) — the LIST below is unchanged and the records that
#: cite it are not. Five entries recorded ``PRODUCED_BY_RUN`` against three of
#: these roots were being answered, on every host, by an admissible in-repo
#: root instead, so their citations were provenance-shaped blanks: green cells
#: whose only stated source was a directory nobody carries, one of them a run
#: whose own label says it ABORTED. They are re-pointed at the roots that
#: actually hold the bytes, and
#: ``test_d3_no_record_cites_an_absent_run_this_commit_can_answer`` keeps the
#: repair from being undone. The registry itself is deliberately untouched:
#: retiring a root nothing cites is a separate change with its own pin to move,
#: and the entries were the defect.
_IN_REPO_RUN_ROOTS: Tuple[str, ...] = ()
_EXTERNAL_RUN_ROOTS_AS_MEASURED: Tuple[str, ...] = (
    "AI_IC_design/4th_benchmark/U_Hawaii_EE628_DeltaSigma_ADC_e2e",
    "AI_IC_design/4th_benchmark/cv32e40p_e2e",
    "AI_IC_design/4th_benchmark/ibex_e2e",
    "campaign_pdk/spm/_aborted_tmpplugin_run",
    "campaign_pdk/spm/pdk_portability_ihp-sg13g2_20260721",
)

#: Steps whose EVERY declared entry is evidenced only by a run tree outside
#: this repository, measured 2026-07-27. Since #527 those trees are not
#: consulted on ANY host. Until 2026-08-06 that made these seven cells green on
#: the committed manifest and unfalsifiable from the repository; they are now
#: RED (see :data:`UNEVIDENCED_CELLS` and the "WHY A FAILURE AND NOT A WAIVER"
#: section above), and committing those run trees is what closes them. The set
#: is still pinned so a cell joining it is a loud, named event. See
#: ``test_d3_fixture_attested_cells_are_named_cell_by_cell``.
#:
#: 2026-08-11 — step 29 LEAVES this set (7 -> 6), the shrinking direction
#: (vibe-ic#983 ruling 2). Its sole entry until now was evidenced only by
#: ``AI_IC_design/4th_benchmark/cv32e40p_e2e``, a tree outside this repository
#: that no host consults, so the cell could not be decided from the commit at
#: all. It now also declares ``reports/phase2/gates/post_layout_sim.json``,
#: which resolves inside the repo against a registered root, so step 29 has
#: in-repo evidence for the first time. The test's own report confirms the
#: direction: "Newly external: []" — nothing joined. The entry that WAS
#: external is still external and still unevidenced from the commit; this
#: records that step 29 is no longer evidenced ONLY from outside, which is a
#: strictly weaker and strictly true statement.
#: 2026-08-12: M2, M3 and M4 LEFT this set, and the set only ever SHRINKS
#: honestly — "Newly external: []". They were here because the manifest
#: recorded their entries `PRODUCED_BY_RUN` against an out-of-repo tree; they
#: are now `NA_DORMANT_CONDITION`, which carries no run reference at all, so
#: there is no external tree left to be attested from. See the note on
#: :data:`UNEVIDENCED_CELLS` for why dormancy is the true reading and why for
#: M4 the external attribution was additionally wrong in its own terms.
EXTERNALLY_ATTESTED_STEPS: Tuple[str, ...] = (
    "17", "20", "30",
)

#: How many of the declared entries are decided LIVE on every host. An
#: EQUALITY, not a floor (#527): while external run trees were consulted the
#: number ranged with the machine and a ``>=`` permitted the whole spread.
#: Asserted by ``test_d3_evidence_is_live_wherever_the_run_root_exists``.
#:
#: 2026-08-06 — RE-MEASURED and UNCHANGED at 114, which is worth writing down
#: because A8's ``.gds`` did move that day. It went from ``UNPROVEN`` to
#: ``PRODUCED_BY_RUN``, and both of those are decided LIVE: the UNPROVEN branch
#: searches every admissible root and the PRODUCED_BY_RUN branch resolves one.
#: What changed is the ANSWER (a live search that came back empty now comes
#: back with a 641262 B artefact), not the MODE, so the count is flat. The
#: number is re-derived here rather than carried forward: 96 PRODUCED_BY_RUN +
#: 6 PRODUCED_LIVE + 12 UNPROVEN-and-searched = 114 live, 19 fixture, 133
#: declared.
# 2026-08-10: 114 -> 119. Two run roots this commit ALREADY TRACKS were
# registered (caravel_user_project/v1.9.43_sky130A and phase1_parity/espi), so
# five previously unsearchable entries now resolve against committed bytes.
# The property this number guards -- "no evidence from outside the commit" --
# is intact and was checked rather than assumed: both roots are kind="repo"
# with repo-relative paths, 351 and 253 files tracked at HEAD respectively, and
# nothing here resolves through $HOME.
# 2026-08-11: 119 -> 120, and 133 -> 134 declared (vibe-ic#983 ruling 2). Step
# 29 now declares `reports/phase2/gates/post_layout_sim.json`, the BLOCKING
# "Substance gate" report its own gate clause already wrote and no entry named.
# The new entry is decided LIVE like the other 119 -- PRODUCED_BY_RUN resolved
# against phase1_parity/espi, which is kind="repo", already a registered root,
# and carries the file non-empty and tracked at HEAD (569 B).
#
# This baseline MOVED, so it is stated rather than absorbed: +1 declared, +1
# live, +1 PRODUCED_BY_RUN (116), fixture-attested unchanged at 19. The guarded
# property -- "no evidence from outside the commit" -- is intact: the entry
# resolves inside the repo and nothing here reaches $HOME. What this number
# must NOT be read as is an increase in independently-produced evidence: the
# report's only producer is step 29's own gate (no runner invokes
# post_layout_sim_check), which is recorded in the manifest entry's `note` and
# is why the same declaration is NOT made for FS1, where it was measured to
# stop the producer from running at all.
# 2026-08-12: 120 -> 126, and the direction is the one this constant exists to
# protect. M2/M3/M4's six entries stopped being FIXTURE and became LIVE — not
# because new evidence arrived, but because the fixture attestation was
# WITHDRAWN: their records are now `NA_DORMANT_CONDITION` with status UNPROVEN,
# which the UNPROVEN branch decides by SEARCHING every admissible root. The
# search comes back empty on every host, and there is no longer any recorded
# run reference for a fallback to consult, so the count is host-independent by
# construction in the way #527 requires — more strongly than before, since the
# fixture branch was precisely the host-dependent one.
#
# Read the increase as "six fewer entries decided by a committed JSON", never
# as "six more artefacts found". Composition, re-measured: 96 PRODUCED_BY_RUN +
# 6 PRODUCED_LIVE + 24 UNPROVEN-and-searched = 126 live, 8 fixture, 134
# declared.
# 2026-08-12 (same change): 126 -> 127. M1 moved WAIVED -> NA, so its
# `merge.json` stopped being FIXTURE and became UNPROVEN-and-searched. Its
# other entry, `top_merged.gds`, was already searched live. Same reading as
# the 120 -> 126 move above: one fewer entry decided by a committed JSON, not
# one more artefact found.
# 2026-08-12 (same change): 127 -> 128. D1 declared
# `phase1/generated_docs/L21_POWER_INTENT.json`, which dimension 7 was
# reporting as produced-by-the-flow / read-by-a-gate / declared-by-nobody and
# charging to M2 (the CONSUMER) for want of a producer to charge. The entry
# resolves in an admissible run root (caravel_user_project, 531 B) and is
# recorded PRODUCED_BY_RUN, so it is decided LIVE like the other 127 and adds
# no fixture attestation. Declaring an artefact d3 could NOT evidence would
# have moved the finding from d7 to d3 rather than closing it -- which is what
# the first attempt did, and is why the manifest record is measured by asking
# `resolve_anywhere`, never typed.
# 2026-08-12 (same change): 128 -> 129. Step 11's
# `phase2/stage2/dft/coverage.yml`, declared for the same d7 W2 reason as L21
# above and recorded PRODUCED_BY_RUN at spm/v1.9.96_gf180mcuD (28797 B). It is
# decided LIVE like the other 128 and adds no fixture attestation.
# 2026-08-14 (#1215): 129 -> 133. The write-record tripwire's four surviving
# W2 promotions, declared in the flow yaml on the steps that PRODUCE them --
# D1 `reports/audit/phase1/expert_parse_track.json`, 23
# `reports/phase3/sta/post_route_signoff_corner.json`, 24
# `reports/phase3/dynamic_ir.json`, 27 `reports/phase3/si_mcf_sta.json`. Same
# reading as the L21 and coverage.yml moves above: four fewer entries decided
# by nothing, not four more artefacts found. Every one is recorded
# PRODUCED_BY_RUN at `benchmark-data/ic/spm/v1.9.96_gf180mcuD` (7399 / 393 /
# 1887 / 2750 B), and each was checked `git ls-files`-TRACKED at HEAD in that
# root before the record was written -- which is the per-path check this pin
# exists to force (#527): an entry live-verified from an untracked working-tree
# file would raise this number on one host and not another.
# 2026-08-15 (#1348): 133 -> 134. D1 `phase1/extraction_patterns.json`, the
# LAST surviving W2 promotion, declared in the flow yaml on the step that
# PRODUCES it. Same reading as the L21, coverage.yml and #1215 moves above: one
# fewer entry decided by nothing, not one more artefact found. It is recorded
# PRODUCED_BY_RUN at `benchmark-data/ic/spm/v1.9.96_gf180mcuD` (7608 B), and it
# was checked `git ls-files`-TRACKED at HEAD, non-empty and not a symlink in
# NINE of the ten admissible run roots before the record was written -- the
# per-path check this pin exists to force (#527). Its verdict is therefore LIVE
# and it adds no fixture attestation: fixture stays at 7, as it was.
# 2026-08-28 (#1785): 134 -> 135. Step 31 `reports/phase3/perc_sweep.json`, the
# sixth artefact dimension 7 charged on that step and the first since the PERC
# sweep clause was re-homed there on 2026-08-25. It is the OTHER reading of
# this pin's two directions: not one fewer entry decided by nothing, but one
# MORE entry now decided — and decided UNPROVEN, because `find -name
# perc_sweep.json` over the published corpus returns nothing in any of the ten
# admissible run roots and the producer postdates every published cell. An
# UNPROVEN entry is LIVE by construction (the branch re-searches every root on
# each call), so it lands on this side of the count and not in the fixture
# figure, which stays where it was. Same class and same arithmetic as
# `magic_illegal_overlap.json` on the same step; the number rose because the
# POPULATION rose, which is exactly what this equality exists to make a human
# say out loud.
_LIVE_ENTRY_COUNT = 135

#: Run roots the compliance-audit self-certification probe drives, and the
#: declared ``required_outputs`` each audit CREATES in the tree it audits.
#: Both are in this repository, both audit in ~1-2 s, and one is the analog
#: reference run A8's evidence comes from.
#:
#: An auditor may never accept as evidence an artefact it caused to exist
#: during its own run. Three entries in this pin violate that TODAY and are
#: recorded rather than endorsed. They are NOT the same kind of violation and
#: the difference is what a reader needs:
#:
#:   * steps 24 and 26 name their own declared ``required_output`` as the
#:     ``--json`` argument of their blocking gate command, so the audit writes
#:     the file whose presence it then reports, on EVERY tree. That is a flow
#:     defect, it predates this dimension, and it is out of this cell's scope.
#:   * step 25's ``reports/phase3/em_signoff.json`` is a STALE-ROOT artefact,
#:     not a flow defect. It entered this pin on 2026-07-28 when dimension 7
#:     declared it, and it appears here only because THIS root predates the
#:     runner wiring that produces it: ``phase3_one_shot_runner`` carries
#:     ``("em_signoff", "em_report_check.py",
#:     "reports/phase3/em_signoff.json", ("--mode","em"))`` in
#:     ``_DECLARED_SIGNOFF_GATES`` and plans it via
#:     ``step_declared_signoff_gates(project)``. On a root published after that
#:     wiring the artefact pre-exists the audit and this entry MUST disappear.
#:     Re-publishing the root is the one thing that closes it; until then the
#:     step-25 verdict on this root rests on the audit's own output and
#:     ``--strict-audit-evidence`` refuses it.
#:
#: Pinning all three means the POPULATION cannot grow silently, which is the
#: part A8 tried to grow.
SELF_CERTIFYING_AUDIT_PROBE: Dict[str, Tuple[str, ...]] = {
    # The analog reference run — A8's own base_run. MUST stay empty.
    "benchmark-data/ic/u_hawaii_adc": (),
    # 2026-08-07 — v1.5.66_gf180mcuD (the former non-empty control here) was
    # retired and replaced by v1.9.96_gf180mcuD. RE-MEASURED against the new
    # cell, not carried forward: it is published AFTER the em_signoff wiring
    # this probe's own comment predicted would make the entry disappear
    # ("on a root published after that wiring the artefact pre-exists the
    # audit and this entry MUST disappear") — `reports/phase3/{ir_drop_signoff,
    # em_signoff,antenna_signoff}.json` all pre-exist in the published cell, so
    # a `flow_compliance_check` run against a copy creates 0 files there of any
    # kind. Verified empirically (copytree + real subprocess run + before/after
    # file-list diff) before pinning, not assumed from the prediction alone.
    # The probe's "not empty" side is currently uncovered by any pinned entry —
    # disclosed here rather than silently dropped; a future root published
    # BEFORE the step-25 wiring reaches this file would restore it.
    "benchmark-data/ic/spm/v1.9.96_gf180mcuD": (),
    # 2026-08-06 — the published cell that carries A8's hardmacro GDS. It is in
    # the probe for the reason A8 is the reason the probe exists: this root is
    # now an evidence source, so "could the auditor have written the artefact
    # it then reports" has to be asked of it too. MEASURED empty — a
    # `flow_compliance_check` run creates 0 files there of any kind — and
    # pinned empty so it cannot start creating one silently.
    "benchmark-data/ic/u_hawaii_adc/v1.9.86_sky130A": (),
}


# ──────────────────────────────────────────────────────────────────────
# Manifest
# ──────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def manifest() -> Dict:
    doc = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    global _IN_REPO_RUN_ROOTS
    _IN_REPO_RUN_ROOTS = tuple(sorted(
        label for label, meta in doc["run_roots"].items()
        if meta.get("kind") in _IN_REPO_KINDS))
    return doc


def step_record(step_id) -> Dict:
    rec = manifest()["steps"].get(F.normalize_id(step_id))
    if rec is None:
        raise AssertionError(
            f"step {step_id!r} is declared in {F.FLOW_YAML} but has no record in "
            f"{MANIFEST_PATH.name}: a step was added to the flow without "
            f"measuring whether its required_outputs are produced"
        )
    return rec


# ──────────────────────────────────────────────────────────────────────
# Run-root discovery — live, every time
# ──────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RunRoot:
    label: str
    kind: str
    path: Path


def _is_flow_run(path: Path) -> bool:
    return any((path / m).exists() for m in _RUNNER_MARKERS)


def _is_published_cell(path: Path) -> bool:
    """A cell ``benchmark_evidence_publish.py`` staged from a CONVERGED run.

    ADDED 2026-08-06, and the reason it is a SECOND predicate rather than two
    more strings in :data:`_RUNNER_MARKERS` is the whole point. A run tree is
    admitted because a flow runner demonstrably wrote it — it dropped a marker
    file. A published cell is a curated COPY of such a tree, made by a program
    (``benchmark-data/PUBLISHING.md``), and the copy does not carry the
    runner's marker: the analog reference cell has no ``provenance.jsonl`` and
    no ``reports/orchestrator/``. Widening the marker list to let it in would
    have loosened the rule for all thirteen roots on the strength of one, which
    is how an admissibility rule stops admitting anything.

    So the provenance is proved POSITIVELY, by the publish contract's own
    precondition, using the contract's own two programs:

    * the folder is named canonically, ``v<version>_<PDK>``
      (``benchmark_evidence_structure_check._NAME_RE``), and
    * it carries the machine verdict that made it publishable —
      ``reports/audit/phase23_completion_audit.json``, read with
      ``benchmark_evidence_publish._audit_verdict`` and required to be in
      ``_CONVERGED`` — which is exactly what ``publish()`` reads before it will
      stage a single file, and it REFUSES a FAIL or a missing one.

    That is strictly stronger than "a marker file exists": a hand-assembled
    directory, an agent scratch tree, or a cell staged from a run whose own
    audit said FAIL is refused here, and refused for a stated reason rather
    than by accident of naming.
    ``test_d3_a_published_cell_must_show_a_converged_verdict`` asserts both
    directions.
    """
    if not _PUBLISHED_NAME_RE.match(path.name):
        return False
    try:
        verdict, _src = _bep._audit_verdict(path, None)
    except Exception:
        # `_audit_verdict` raises `Refuse` for "no audit artifact" and for an
        # unparseable or verdict-less one. Both mean the same thing here: this
        # directory cannot show the verdict that would have made it
        # publishable, so it is not evidence.
        return False
    return verdict in _bep._CONVERGED


#: How each in-repo ``kind`` proves it is evidence rather than a directory.
#: One entry per kind, so a manifest ``kind`` nobody has taught this module
#: about resolves to nothing instead of silently defaulting to admitted.
_ADMISSIBILITY = {
    _IN_REPO_KIND: _is_flow_run,
    _PUBLISHED_KIND: _is_published_cell,
}


#: The directory every manifest ``rel`` for an in-repo run root is written
#: under. It is also the name of the repository the published cells moved to
#: (``vibeic/benchmark-data``), which is what makes the rewrite below a plain
#: prefix swap rather than a lookup table.
_CORPUS_DIR = "benchmark-data"


def _offered_corpus() -> Optional[Path]:
    """A corpus a caller EXPLICITLY offered that is not this repo's own tree.

    ``corpus_root()`` answers two different questions with one path: "does this
    checkout still carry cells" (``<repo>/benchmark-data``) and "did the
    operator point ``VIBE_IC_BENCHMARK_DATA`` at a clone". Only the second is
    new information for discovery — the first is already reached by the
    in-repo candidate — so it is separated here rather than yielded twice.

    It raises rather than returning ``None`` on a broken pointer, because
    ``corpus_root()`` does; a named-but-unreadable corpus is a wrong path, not
    an absent one (``_published_corpus.CorpusPointerBroken``).
    """
    corpus = corpus_root()
    if corpus is None:
        return None
    repo = _plugin_tree.repo_root()
    if repo is not None and corpus.resolve() == (repo / _CORPUS_DIR).resolve():
        return None
    return corpus


def _corpus_candidate(rel: str, corpus: Path) -> Optional[Path]:
    """Where manifest *rel* lands inside an external corpus clone, if anywhere.

    Every in-repo run root is recorded ``benchmark-data/<something>``, and the
    split moved exactly that subtree out to its own repository root. So the
    corpus path is *rel* with the one prefix removed, and a *rel* that does not
    carry the prefix has no corpus form at all rather than a guessed one.
    """
    prefix = _CORPUS_DIR + "/"
    if not rel.startswith(prefix):
        return None
    return corpus / rel[len(prefix):]


@lru_cache(maxsize=1)
def run_roots() -> Dict[str, RunRoot]:
    """Every manifest run root READABLE HERE, keyed by label.

    #527: run roots recorded with any other ``kind`` name a directory on one
    particular machine. They are not searched for — not under ``$HOME``, not
    under an env var, not at all — because a tree the repository does not
    carry cannot make this dimension's answer the same on two hosts. Their
    entries are fixture-attested everywhere instead, which is exactly what
    they already were on every host but one.

    Two in-repo kinds, each with its OWN proof of provenance (``repo`` ->
    :func:`_is_flow_run`, ``published`` -> :func:`_is_published_cell`). Neither
    weakens the other: a ``repo`` root still has to carry a runner marker, and
    a ``published`` root still has to carry a converged verdict.

    THE PUBLISHED CELLS LEFT THIS REPOSITORY, AND THE POINTER DID NOT REACH
    HERE (vibe-ic#1703)
    ======================================================================
    Every one of those roots is recorded ``benchmark-data/<...>``, and that
    subtree moved to ``vibeic/benchmark-data``. ``_published_corpus`` already
    established the seam for that — set ``VIBE_IC_BENCHMARK_DATA`` to a clone
    and the corpus checks run — and the skip in the cell predicate quotes it
    verbatim: *"Point VIBE_IC_BENCHMARK_DATA at a clone to run this check
    against them."*

    This function never read it, so the pointer switched the skip OFF without
    switching discovery ON. Measured on ``origin/main`` at ``ee849c19e`` with
    ``VIBE_IC_BENCHMARK_DATA`` set to a clone of ``vibeic/benchmark-data``::

        50 failed, 11 passed, 2 xfailed in 3.63s

    and every one of the 50 read ``[0 admissible run roots searched: []]``
    while the cells sat unread on disk. That is not a stricter answer, it is a
    confident wrong one: "N required_outputs are NOT produced" asserted by a
    function that opened no file. The documented remedy was worse than the
    skip it replaced.

    So an EXPLICITLY OFFERED corpus is now a second place a manifest root may
    resolve, and #527 still holds in the direction it was written for:

    * it is never SEARCHED for — the operator names it, exactly as
      ``_published_corpus`` requires, and an unset pointer changes nothing;
    * trackedness is still decided by ``git ls-tree -r HEAD`` in the tree that
      holds the root (:func:`tracked_under`), so it is the CORPUS COMMIT that
      answers, ``git clean -xdf`` still cannot move a verdict, and two clones
      of one corpus commit still agree;
    * a corpus that cannot answer that question is REFUSED rather than read as
      "nothing is tracked" — see :func:`_refuse_an_unanswerable_corpus`.

    What it does NOT restore is a single answer for all hosts: two different
    corpus commits may legitimately differ. That is a property of the split,
    not of this function, and the honest rendering of it is that the verdict
    now names the corpus it read.
    """
    out: Dict[str, RunRoot] = {}
    repo = _plugin_tree.repo_root()
    corpus = _offered_corpus()
    if corpus is not None:
        _refuse_an_unanswerable_corpus(corpus)
    if repo is None and corpus is None:
        return out
    for label, meta in manifest()["run_roots"].items():
        admits = _ADMISSIBILITY.get(meta["kind"])
        if admits is None:
            continue
        candidates = []
        if repo is not None:
            candidates.append(repo / meta["rel"])
        if corpus is not None:
            cand = _corpus_candidate(meta["rel"], corpus)
            if cand is not None:
                candidates.append(cand)
        for cand in candidates:
            if cand.is_dir() and admits(cand):
                out[label] = RunRoot(label=label, kind=meta["kind"], path=cand)
                break
    return out


def _refuse_an_unanswerable_corpus(corpus: Path) -> None:
    """An offered corpus must be able to say what its own commit carries.

    :func:`tracked_under` returns the EMPTY SET for a tree that is not a git
    work tree, and every caller reads that as "not tracked at HEAD — a local
    build product, not evidence". Inside this repository that is the right
    answer, because the only way to be here and not be a checkout is to be a
    flattened install cache that genuinely carries no commits.

    An offered corpus can be neither: an unpacked release tarball, a `cp -r` of
    somebody's clone, a docker COPY of the cells. Every artefact in it is real
    and published, and reading the whole tree as untracked would report all of
    them NOT PRODUCED — the same confident wrong answer #1348 measured from the
    other direction, arriving through the door this change opens. So it is
    refused here, at the seam, with the reason named.
    """
    if _claims_to_be_a_checkout(corpus):
        return
    raise AssertionError(
        f"{_pc.CORPUS_ENV}={str(corpus)!r} is not a git checkout, so this "
        f"module cannot ask which of its files the corpus COMMIT carries. "
        f"Every artefact under it would read as 'not tracked at HEAD — a local "
        f"build product, not evidence' and every cell would report its declared "
        f"outputs NOT PRODUCED, which is a confident wrong answer, not a strict "
        f"one (#527, #1348). Point {_pc.CORPUS_ENV} at a clone of "
        f"vibeic/benchmark-data rather than at an unpacked copy of one."
    )


# ──────────────────────────────────────────────────────────────────────
# Trackedness — "does the repository carry this file, or just this machine?"
# ──────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=64)
def tracked_under(root: Path) -> frozenset:
    """Paths tracked at HEAD under *root*, relative to *root*.

    ``git ls-tree -r HEAD`` rather than ``git ls-files``: the index can carry
    a staged-but-uncommitted path, and the claim this module makes is about
    the COMMIT — what any other checkout would have. An empty set when *root*
    is not inside a git work tree (a flattened install cache, an unpacked
    archive), which correctly makes nothing there admissible as evidence.
    """
    try:
        proc = _pr.run(
            ["git", "ls-tree", "-r", "--name-only", "-z", "HEAD"],
            cwd=str(root), capture_output=True, text=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - git is always present
        raise AssertionError(
            "git is not on PATH, so this module cannot tell a committed "
            "artefact from a local build product and must not guess: every "
            "verdict below would silently become 'a file with that name "
            "exists on this machine' (#527)"
        ) from exc
    if proc.returncode != 0:
        # git RAN and FAILED. Two very different worlds produce this, and the
        # empty set is the honest answer to only one of them:
        #
        #  * *root* is genuinely not a git work tree (a flattened install
        #    cache, an unpacked archive) — nothing there is committed, so
        #    nothing there is admissible as evidence. Empty is correct.
        #
        #  * *root* IS a checkout whose git metadata this process cannot
        #    reach — a worktree whose gitdir lives outside a container mount,
        #    a bad GIT_DIR, a permissions failure. The artefacts ARE committed;
        #    git simply could not say so. Returning empty here does not report
        #    "unknown", it reports "NOT TRACKED AT HEAD" for every path in the
        #    tree, which this module's callers read as "the artefact is not
        #    produced" — a confident wrong answer, indistinguishable from a
        #    real finding.
        #
        # MEASURED (#1348 / #1356): mounting this repo's worktree into a
        # container, where `.git` points at a host path that does not exist
        # there, turned 16 d3 contradictions into 54. The extra 38 were
        # artefacts that ARE committed and ARE present — the failure message
        # listed each one WITH ITS SIZE and still called it "matched but NOT
        # tracked at HEAD — a local build product, not evidence".
        #
        # The discriminator is whether anything CLAIMS to be a checkout here.
        # If a `.git` exists at or above *root* and git still cannot answer,
        # the environment is broken and this module must refuse — exactly as
        # it already refuses when the git binary is missing, and for the same
        # reason: it cannot tell a committed artefact from a local build
        # product and must not guess (#527).
        if _claims_to_be_a_checkout(root):
            raise AssertionError(
                f"`git ls-tree -r HEAD` exited {proc.returncode} under {root}, "
                f"which DOES carry git metadata — so this is a broken "
                f"environment, not a tree without commits. Refusing to read "
                f"that as 'nothing is tracked at HEAD': every artefact below "
                f"would be reported NOT PRODUCED while it sits committed on "
                f"disk. git said: "
                f"{(proc.stderr or b'').decode('utf-8', 'replace').strip()[:200]!r}"
            )
        return frozenset()
    return frozenset(
        b.decode("utf-8", "surrogateescape")
        for b in proc.stdout.split(b"\0") if b
    )


def _claims_to_be_a_checkout(root: Path) -> bool:
    """Does anything at or above *root* claim this is a git checkout?

    A directory (normal clone) or a file (`git worktree`, submodule) named
    ``.git``. Deliberately a filesystem question, not a git one: it has to
    stay answerable when git itself is the thing that is failing.
    """
    for d in (root, *root.parents):
        if (d / ".git").exists():
            return True
    return False


def is_tracked(root: Path, rel: str) -> bool:
    """Is *rel*, relative to run root *root*, carried by the commit?"""
    return rel in tracked_under(root)


@lru_cache(maxsize=512)
def _head_record_blob(root: Path, rel: str) -> bytes:
    """Exact immutable ``HEAD`` bytes for one tracked publisher record."""
    try:
        proc = subprocess.run(
            ["git", "cat-file", "blob", f"HEAD:./{rel}"],
            cwd=str(root), capture_output=True, timeout=60,
        )
    except FileNotFoundError as exc:  # pragma: no cover - git is always present
        raise AssertionError(
            "git is not on PATH, so publisher-record bytes cannot be bound "
            "to the commit and must not be trusted"
        ) from exc
    if proc.returncode != 0:
        raise AssertionError(
            f"`git cat-file blob HEAD:./{rel}` exited {proc.returncode} under "
            f"{root}; trackedness was established but the exact HEAD blob "
            f"cannot be read, so refusing mutable record bytes. git said: "
            f"{(proc.stderr or b'').decode('utf-8', 'replace').strip()[:200]!r}"
        )
    return proc.stdout


def _head_bound_record_bytes(root: Path, path: Path, rel: str
                             ) -> Tuple[Optional[bytes], str]:
    """Return record bytes only when the worktree exactly matches ``HEAD``.

    ``tracked_under`` proves that a pathname exists in the commit.  It does not
    prove that mutable filesystem bytes at that pathname are the blob the
    commit carries.  Read both channels and require byte identity before JSON
    parsing, so modified, deleted, symlinked, or in-memory-substituted records
    cannot change a cell computed for one commit.
    """
    if path.is_symlink():
        return None, "worktree record is a symlink, not the HEAD blob"
    try:
        worktree = path.read_bytes()
    except OSError as exc:
        return None, f"worktree record cannot be read ({exc})"
    if worktree != _head_record_blob(root, rel):
        return None, "worktree bytes differ from the exact HEAD blob"
    return worktree, ""


# ──────────────────────────────────────────────────────────────────────
# The run's OWN write ledger — "did THIS STEP write it", per step
# ──────────────────────────────────────────────────────────────────────
#: Where `step_write_ledger.emit()` puts the record. Under `reports/` and not
#: under `steps/` on purpose: the publisher excludes `steps/` by name, so a
#: ledger written only there would never reach a published cell.
LEDGER_REL = "reports/write_ledger.json"

#: The ledger's D3 rule name, quoted from the emitter rather than guessed.
_LEDGER_D3_RULE = "declared_output_not_produced"


@dataclass(frozen=True)
class Ledger:
    """One run's write ledger, reduced to what this dimension may consult."""
    rel: str
    captured_at: str
    project: str
    rows: Dict[str, Dict]          # step id -> the ledger's row for that step


@lru_cache(maxsize=64)
def write_ledger(root: Path) -> Tuple[Optional[Ledger], str]:
    """``(ledger, note)`` for run root *root*. ``note`` is ALWAYS a sentence.

    Four admissibility rules, and the second is the one that matters.

    1. The file must be a real regular file at :data:`LEDGER_REL`. A symlink is
       refused for the same reason a symlinked artefact is: it is a promise
       about a filesystem, not a record.
    2. **It must be TRACKED AT HEAD.** The ledger can only ever make a cell
       REDDER, so an untracked one is a lever that turns a verdict on whether
       somebody happened to run ``step_write_ledger`` in their working tree.
       ``git clean -xdf`` would then change a colour and two checkouts of one
       commit would disagree — the exact host-dependence #527 took out of this
       module, arriving from the other direction. Publishing the run tree (the
       ledger with it) is what admits it, on every host at once.
    3. The schema must be the one this module knows
       (``step_write_ledger.SCHEMA``), imported rather than restated.
    4. It must carry step rows. A ledger built when the flow yaml was
       unreadable has none, and an empty record must not read as "every step
       wrote nothing".

    A ledger that fails any of these is NOT consulted and the reason is
    returned so it can be printed. Nothing here is ever silent: :func:`resolve`
    puts the note in the verdict detail, and
    ``test_d3_the_write_ledger_population_is_derived_from_the_commit`` reports
    the population root by root — including, and this is the case a pinned
    population could not see, a root whose COMMIT carries a ledger that lands
    on the wrong side of rules 1, 3 or 4 and is therefore refused in silence.
    """
    p = root / LEDGER_REL
    try:
        if p.is_symlink():
            return None, (f"{LEDGER_REL} is a SYMLINK -> {os.readlink(p)}; a "
                          f"link is a promise about a filesystem, not a record "
                          f"of what this run wrote — NOT consulted")
        if not p.is_file():
            return None, (f"no {LEDGER_REL} — this run left no write ledger, "
                          f"so production is decided exactly as before")
    except OSError as exc:
        return None, f"{LEDGER_REL} is unreadable ({exc}) — NOT consulted"
    if not is_tracked(root, LEDGER_REL):
        return None, (f"{LEDGER_REL} exists here but is NOT tracked at HEAD — "
                      f"NOT consulted. A ledger can only redden a cell, so an "
                      f"untracked one would make this verdict a property of "
                      f"one working tree (#527). Commit the run tree to admit "
                      f"it.")
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"{LEDGER_REL} does not parse ({exc}) — NOT consulted"
    if not isinstance(doc, dict) or doc.get("schema") != _swl.SCHEMA:
        return None, (f"{LEDGER_REL} carries schema "
                      f"{(doc or {}).get('schema') if isinstance(doc, dict) else None!r}, "
                      f"not {_swl.SCHEMA!r} — NOT consulted")
    rows = {str(r["id"]): r for r in (doc.get("steps") or [])
            if isinstance(r, dict) and r.get("id") is not None}
    if not rows:
        return None, (f"{LEDGER_REL} carries no step rows (its `declaration` "
                      f"reads {doc.get('declaration')}) — NOT consulted; an "
                      f"empty record must not read as 'every step wrote "
                      f"nothing'")
    return (Ledger(rel=LEDGER_REL,
                   captured_at=str(doc.get("captured_at") or "?"),
                   project=str(doc.get("project") or "?"),
                   rows=rows),
            f"{LEDGER_REL} consulted ({len(rows)} step rows, captured "
            f"{doc.get('captured_at')})")


@dataclass(frozen=True)
class LedgerSay:
    """What the run's ledger says about ONE step's ONE declared spec."""
    consulted: bool
    note: str
    #: The ledger's own `declared_output_not_produced` finding, or None.
    unwritten: Optional[Dict] = None
    #: The paths the ledger records THIS STEP as having produced for the spec.
    produced_rels: Tuple[str, ...] = ()
    #: Producer attribution for those paths, as the ledger recorded it.
    producers: Tuple[str, ...] = ()


def _ledger_reason(finding: Dict) -> str:
    """A ledger D3 finding rendered as one sentence, contradiction included."""
    bits = [f"the run's own write ledger records this declared output as "
            f"NOT WRITTEN by this step ({finding.get('reason')}: "
            f"{finding.get('detail')})"]
    if finding.get("provenance_contradiction"):
        bits.append(
            f"and the run's provenance log CONTRADICTS the filesystem — "
            f"{finding['provenance_contradiction']}"
            + (f", claimed producer {finding['claimed_producer']!r}"
               if finding.get("claimed_producer") else ""))
    return "; ".join(bits)


def ledger_says(root: Path, step_id, entry: str) -> LedgerSay:
    """The ledger's verdict for (*step_id*, *entry*) in run root *root*.

    Degrades to ``consulted=False`` — today's behaviour — at three named
    points, because each of them means the ledger cannot answer FOR THIS CELL
    and a ledger that answered anyway would be inventing:

    * the root carries no admissible ledger (:func:`write_ledger`);
    * the ledger has no row for this step (it predates the step, or the step
      declared no ``required_outputs`` when it was captured);
    * the ledger's row does not mention this spec — the flow yaml has drifted
      since the run, and a record about a different string is not a record
      about this one.
    """
    led, note = write_ledger(root)
    if led is None:
        return LedgerSay(False, note)
    row = led.rows.get(F.normalize_id(step_id))
    if row is None:
        return LedgerSay(False, (
            f"{LEDGER_REL} (captured {led.captured_at}) records no row for step "
            f"{step_id} — it predates this step, or the step declared no "
            f"required_outputs when the run happened; decided as before"))
    findings = {f.get("spec"): f for f in (row.get("findings") or [])
                if isinstance(f, dict) and f.get("dimension") == "D3"
                and f.get("rule") == _LEDGER_D3_RULE}
    produced: Dict[str, List[str]] = {}
    attributed: Dict[str, List[str]] = {}
    for rec in (row.get("produced") or []):
        if not isinstance(rec, dict):
            continue
        produced.setdefault(str(rec.get("spec")), []).append(str(rec.get("rel")))
        if rec.get("producer"):
            attributed.setdefault(str(rec.get("spec")), []).append(
                f"{rec['producer']} ({rec.get('producer_confidence')})")
    if entry not in findings and entry not in produced:
        return LedgerSay(False, (
            f"{LEDGER_REL} (captured {led.captured_at}) covers step {step_id} "
            f"but not the spec {entry!r} — the flow yaml has drifted since the "
            f"run; decided as before"))
    return LedgerSay(
        True,
        f"{LEDGER_REL} captured {led.captured_at}",
        unwritten=findings.get(entry),
        produced_rels=tuple(sorted(set(produced.get(entry, ())))),
        producers=tuple(sorted(set(attributed.get(entry, ())))),
    )


# ──────────────────────────────────────────────────────────────────────
# Live resolution of one required_outputs entry
# ──────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Hit:
    #: Run-root label. :func:`resolve` searches ONE root and leaves this empty
    #: because it does not know the label; :func:`resolve_anywhere` fills it in.
    root: str
    alternative: str
    path: str
    size_bytes: int


@dataclass(frozen=True)
class Rejected:
    """Matches that were looked at and refused, kept apart by REASON.

    "the only match is 0 bytes", "...is a symlink to an input", "...is a build
    product no commit carries" and "there is nothing at all" are four different
    findings. Folding them together is how a never-ran tool reads as a clean
    run and how one machine's history reads as a flow's behaviour.

    Two more since the write ledger was wired in, and they are the two the
    project-wide glob could never state:

    ``unwritten``
        the run's own ledger records this step's declared output as NEVER
        WRITTEN — with the reason (absent / zero_byte / dangling_symlink /
        symlink_alias) and, where the run's provenance log claims a digest for
        a path that is now empty or broken, the contradiction and the tool
        that claimed it.
    ``unattributed``
        a file matching the glob exists and passes every evidence rule, but
        the ledger does not record THIS STEP as having written that path. "A
        file matching this pattern exists somewhere in the project" and "this
        step produced it" are different claims; this is where they separate.
    """
    empty: Tuple[str, ...] = ()
    symlinked: Tuple[str, ...] = ()
    untracked: Tuple[str, ...] = ()
    unwritten: Tuple[str, ...] = ()
    unattributed: Tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.empty or self.symlinked or self.untracked
                    or self.unwritten or self.unattributed)


def resolve(root: Path, entry: str,
            step_id=None) -> Tuple[Optional[Hit], Rejected]:
    """Largest NON-EMPTY, NON-SYMLINK, COMMITTED match for *entry* under *root*.

    ``" OR "`` inside an entry is any-of (``F.split_any_of`` reproduces the
    consumer's split exactly); the ALL-of-ness across entries is the caller's
    job.

    #527 — the trackedness rule. A match that the commit does not carry is a
    property of this working tree, not of the repository: ``git clean -xdf``
    deletes it and a second checkout of the same commit never had it. Such a
    match is refused and reported under :attr:`Rejected.untracked`, so the
    message says "a build product nobody committed" instead of implying the
    step produced something reproducible.

    THE WRITE LEDGER — WHAT *step_id* IS FOR
    ----------------------------------------
    Everything above answers "does a file matching this glob exist under this
    root, and is it real". It never answers "did THIS STEP produce it": the
    resolver takes a pattern, not a step, and ``_glob_first`` will happily
    serve a hit from the ``reports/<subdir>/`` fallback or from anywhere else
    the pattern reaches. When a *step_id* is given AND the root carries an
    admissible write ledger, the ledger's row FOR THAT STEP is consulted and
    can only ever SUBTRACT:

    * the ledger records the spec as never written -> the hit is refused,
      whatever the glob found, under :attr:`Rejected.unwritten`;
    * the ledger records the step as having written some paths and the hit is
      none of them -> refused under :attr:`Rejected.unattributed`.

    It CANNOT add. A path the ledger records as produced still has to pass the
    non-empty, non-symlink and tracked-at-HEAD rules above, which are applied
    first and unchanged — otherwise the ledger would become a way around them,
    which is precisely what it must not be. And with no *step_id*, or no
    admissible ledger, this function behaves exactly as it did before: callers
    that ask a question ABOUT THE PROJECT rather than about a step (the
    dormancy probe, the waiver-premise guards) pass no *step_id* on purpose.
    """
    assert _GLOB_FIRST is not None, (
        "flow_compliance_check._glob_first is gone; this module resolves "
        "required_outputs with the flow's own resolver on purpose and must not "
        "silently fall back to a re-implementation"
    )
    best: Optional[Hit] = None
    empty: List[str] = []
    symlinked: List[str] = []
    untracked: List[str] = []
    for alt in F.split_any_of(entry):
        for rel in _GLOB_FIRST(root, alt):
            p = root / rel
            if p.is_symlink():
                # `is_file()` and `stat()` FOLLOW the link, so an aliased
                # artefact would be credited with its target's bits. See the
                # module docstring: a symlink is not evidence of production.
                symlinked.append(f"{rel} -> {os.readlink(p)}")
                continue
            if not p.is_file():
                continue
            size = p.stat().st_size
            if size <= 0:
                empty.append(rel)
                continue
            if not is_tracked(root, rel):
                untracked.append(f"{rel} ({size} B)")
                continue
            if best is None or size > best.size_bytes:
                best = Hit(root="", alternative=alt, path=rel, size_bytes=size)

    unwritten: List[str] = []
    unattributed: List[str] = []
    if step_id is not None:
        say = ledger_says(root, step_id, entry)
        if say.consulted and say.unwritten is not None:
            # THE BINDING. The glob may have found something; this step's own
            # run says it did not write it. A file that exists is not the same
            # fact as a step that produced one.
            unwritten.append(
                (f"{best.path} ({best.size_bytes} B) matched the glob, but "
                 if best is not None else "")
                + _ledger_reason(say.unwritten))
            best = None
        elif say.consulted and best is not None \
                and best.path not in say.produced_rels:
            unattributed.append(
                f"{best.path} ({best.size_bytes} B) matches the pattern, but "
                f"the run's own write ledger records step {step_id} as having "
                f"written {list(say.produced_rels)} for this spec — not that "
                f"path. 'A matching file exists' is not 'this step produced "
                f"it'.")
            best = None
    return best, Rejected(tuple(empty), tuple(symlinked), tuple(untracked),
                          tuple(unwritten), tuple(unattributed))


def resolve_anywhere(entry: str,
                     step_id=None) -> Tuple[Optional[Hit], Dict[str, Rejected]]:
    """First admissible root that evidences *entry*, ledger-bound per root.

    The ledger binds PER RUN. A root whose ledger records this step as having
    written nothing cannot evidence the entry, and the search moves on to the
    next root — because "this run did not write it" is not "no run ever did",
    and a root that carries no ledger keeps answering exactly as before.
    """
    rejected: Dict[str, Rejected] = {}
    for label, rr in run_roots().items():
        hit, rej = resolve(rr.path, entry, step_id)
        if rej:
            rejected[label] = rej
        if hit is not None:
            return Hit(label, hit.alternative, hit.path, hit.size_bytes), rejected
    return None, rejected


def _rejected_note(rejected: Dict[str, Rejected]) -> str:
    """The five near-miss categories, named rather than folded into "missing"."""
    bits = []
    for field, label in (("empty", "0-byte matches"),
                         ("symlinked", "symlinked (not produced here)"),
                         ("untracked", "matched but NOT tracked at HEAD — a "
                                       "local build product, not evidence"),
                         ("unwritten", "the run's own write ledger says THIS "
                                       "STEP never wrote it"),
                         ("unattributed", "matched, but the run's write ledger "
                                          "attributes that path to no write by "
                                          "this step")):
        per_root = {k: list(getattr(v, field)) for k, v in rejected.items()
                    if getattr(v, field)}
        if per_root:
            bits.append(f"{label}: {per_root}")
    return ("; " + "; ".join(bits)) if bits else ""


# ──────────────────────────────────────────────────────────────────────
# Live PRODUCTION of one entry (the PRODUCED_LIVE proof)
# ──────────────────────────────────────────────────────────────────────
def gate_command_writing(step_id, entry: str) -> Optional[List[str]]:
    """The step's own gate command that names *entry* as an argument.

    Derived from the yaml, not from a hand table: for steps 10/23/24/26 the
    gate clause is literally ``<program> . --mode X --json <the declared
    required_output>``, so the flow itself states who produces it.
    """
    for clause in F.gate_clauses(step_id):
        if not clause.command:
            continue
        toks = clause.command.split()
        if entry in toks[1:]:
            return toks
    return None


def _copy_tracked(src: Path, dst: Path) -> int:
    """Copy only what the commit carries, preserving symlinks. Returns the count.

    #527 — the producer must be handed the tree a FRESH CLONE would give it.
    A ``shutil.copytree`` drags along every local build product, which makes
    the live-production proof depend on the operator's working tree twice
    over: a leftover copy of the target reads as "already present" and kills
    the proof, and a leftover input can make a producer succeed that would
    fail for anyone else.
    """
    n = 0
    for rel in sorted(tracked_under(src)):
        s = src / rel
        if not (s.is_symlink() or s.is_file()):
            continue
        d = dst / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        if s.is_symlink():
            os.symlink(os.readlink(s), d)
        else:
            shutil.copy2(s, d)
        n += 1
    return n


def produce_live(step_id, entry: str, rec: Dict) -> Tuple[bool, str]:
    """Run the declared producer in a throwaway TRACKED-ONLY copy of
    *rec['base_run']*.

    Returns ``(produced, detail)``. ``detail`` always names a measured value.
    """
    label = rec["base_run"]
    rr = run_roots().get(label)
    if rr is None:
        return False, f"base run root {label!r} does not resolve on this host"

    writes = rec["writes"]
    program = rec["producer"]
    argv = list(rec["argv"])

    from_gate = gate_command_writing(step_id, entry)
    if from_gate is not None:
        # The yaml is the authority when it names the producer.
        if from_gate[0] != program or from_gate[1:] != argv:
            # Some steps name a PRODUCER and a JUDGE separately.  Step 0.5ic's
            # producer writes the JSON record; its gate then merges a verdict
            # into that same path.  In that shape the gate command names the
            # output without being its only producer.  The exception is
            # explicit in the measured record and remains bound to the live
            # flow's declared program list; an arbitrary helper cannot claim
            # it writes a step output.
            declared_before_gate = rec.get("producer_is_declared_before_gate") is True
            if not declared_before_gate or program not in F.declared_programs(step_id):
                return False, (
                    f"the gate clause that names {entry!r} is {from_gate!r} but the "
                    f"manifest recorded producer {[program, *argv]!r} — the flow's "
                    f"declared producer changed and the manifest is stale"
                )

    prog_file = F.PROGRAMS_DIR / f"{program}.py"
    if not prog_file.is_file():
        return False, f"declared producer programs/{program}.py does not exist"

    with tempfile.TemporaryDirectory(prefix="d3_live_") as td:
        dst = Path(td) / "proj"
        copied = _copy_tracked(rr.path, dst)
        if not copied:
            return False, (
                f"the run root {label!r} carries no file tracked at HEAD, so "
                f"there is nothing a fresh clone could hand the producer"
            )
        target = dst / writes
        # A LIVE production must be proved against a tree that does not
        # already hold the artefact.
        #
        # The PR that closed A8 hit this as a false alarm and proposed
        # unlinking the target from the copy instead. That repair is not
        # needed here and is strictly weaker: `_copy_tracked` (#527) hands the
        # producer only what the COMMIT carries, so a local build product left
        # behind by an earlier run of the producer is never copied in the first
        # place. What remains reachable is the case the message names — the
        # artefact is TRACKED AT HEAD — and in that case the entry is not a
        # live production at all; it should be recorded PRODUCED_BY_RUN.
        # Unlinking it would let a committed artefact be re-created and
        # counted as freshly produced.
        if target.exists():
            return False, (
                f"{writes} is tracked at HEAD in the run root {label!r}; this "
                f"cell claims a LIVE production and cannot prove one against a "
                f"tree that already carries the artefact"
            )
        # A LIVE production must also be proved against a tree the producer
        # can actually READ.
        #
        # `--under <rel>` is the `eda_report_audit` family's declaration of
        # WHICH artefacts the producer was told to summarise, and the program
        # itself already states what happens when none of them is there:
        # `SCOPE_NOT_FOUND` — "discovery was structurally impossible, so
        # whatever this verdict says about reports is about the scope, not
        # about the project" (`eda_report_audit._main`). Such a run still
        # writes a non-empty JSON, and until this guard existed the only test
        # applied to it was `size > 0`, so an auditor writing "I found nothing
        # to summarise" into an empty tree counted as the step having PRODUCED
        # its declared output.
        #
        # MEASURED on this commit, driving the real producer over all eight
        # admissible run roots for step 10's
        # `reports/phase3/sta/pre_pnr_summary.json`: four roots that carry no
        # STA report at all each wrote a 969-BYTE record with
        # `passed: false`, findings `[STA_REPORT_EXISTS, SCOPE_NOT_FOUND]`,
        # `files_found: 0` and both declared scopes in
        # `scoped_under_missing` — and 969 is exactly the size this entry's
        # manifest record cited as its live production. The proof was of the
        # auditor's ability to report an absence, not of the step's ability to
        # produce a summary.
        #
        # The bar is AT LEAST ONE declared scope present, not all of them,
        # and that limit is disclosed rather than hidden: no admissible run
        # root carries `phase3/stage3/sta/per_corner`, so requiring all would
        # be unsatisfiable by this corpus today and would redden a cell over
        # evidence nobody can supply. One present scope is what separates "the
        # producer read the step's own report" from "the producer read
        # nothing", which is the distinction this guard exists to draw.
        #
        # A producer that declares no `--under` scope (step 9's
        # `synth_area_stats_emit .`) is not covered by this rule at all. Said
        # out loud because a rule that silently applies to one record out of
        # six is not a rule a reader can rely on.
        scopes = [argv[i + 1] for i, tok in enumerate(argv)
                  if tok == "--under" and i + 1 < len(argv)]
        if scopes and not any((dst / s).exists() for s in scopes):
            return False, (
                f"none of the producer's declared --under scope(s) {scopes} "
                f"exists in a tracked-only copy of {label!r}, so "
                f"`{program}` can discover nothing there: whatever it writes "
                f"is a record OF THE SCOPE, not a summary of this step's "
                f"outputs (the program's own SCOPE_NOT_FOUND finding says so "
                f"in those words). A non-empty absence record is not a "
                f"produced artefact"
            )
        proc = _pr.run(
            [sys.executable, str(prog_file), *argv],
            cwd=dst, capture_output=True, text=True)
        if not target.is_file():
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
            # rc=2 is the plugin-wide "the capability itself is absent" code.
            # Say so in those words: an entry nothing could measure is
            # UNMEASURED, and reporting it as "not produced" would be as
            # wrong as reporting it as produced.
            unmeasured = (
                " — rc=2 is this plugin's disclosed capability gap, so the "
                "entry is UNMEASURED here rather than absent; install/start "
                "the tool the producer names above and re-run"
                if proc.returncode == 2 else ""
            )
            return False, (
                f"ran `{program} {' '.join(argv)}` in a copy of {label!r} "
                f"(rc={proc.returncode}) and {writes} was NOT written; "
                f"last output: {tail}{unmeasured}"
            )
        size = target.stat().st_size
        if size <= 0:
            return False, (
                f"ran `{program} {' '.join(argv)}` in a copy of {label!r} and "
                f"{writes} landed at 0 bytes — a zero-byte artefact is not a "
                f"produced artefact"
            )
        return True, f"{writes} produced live at {size} B in a copy of {label!r}"


# ──────────────────────────────────────────────────────────────────────
# The per-entry verdict
# ──────────────────────────────────────────────────────────────────────
#: How an entry's verdict was reached. ``LIVE`` = the artefact was looked at
#: (or created) here and now. ``FIXTURE`` = the run tree the manifest recorded
#: is not on this host.
#:
#: ``FIXTURE`` NO LONGER MEANS "the committed measurement stood in" (2026-08-06)
#: — a standing-in measurement is exactly the green that no measurement could
#: move. It now means the entry could not be decided here, and every ``FIXTURE``
#: verdict carries ``produced=False``. The mode is still surfaced (see
#: :func:`test_d3_evidence_is_live_wherever_the_run_root_exists`) because a
#: module that quietly slid from LIVE to FIXTURE everywhere would be measuring
#: nothing — it would now be loudly red rather than quietly green, but the
#: cause would still be discovery, not production, and the two must not be
#: confused.
LIVE = "LIVE"
FIXTURE = "FIXTURE"

#: The date every manifest record was measured on. Quoted in the UNEVIDENCED
#: message so the reader sees how old the standing-in observation is.
_MANIFEST_MEASURED_ON = "2026-07-27"


@dataclass(frozen=True)
class EntryVerdict:
    produced: bool
    mode: str
    detail: str


@dataclass(frozen=True)
class RecordedOutput:
    """A publisher-authored proof for bytes deliberately absent from a cell."""

    root: str
    record: str
    rel: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class RecordedSearch:
    """The result of searching tracked per-step publisher records.

    ``candidates`` distinguishes "the publisher never recorded this output"
    from "it recorded a row, but the row is not evidence".  That distinction
    is load-bearing: a missing or placeholder digest must not collapse into an
    ordinary absence.
    """

    hit: Optional[RecordedOutput]
    candidates: int
    rejected: Tuple[str, ...]


_RECORDED_UNPUBLISHED = "OUT_OF_PUBLISHED_SCOPE"
_SHA256_PLACEHOLDERS = frozenset({
    "0" * 64,
    "f" * 64,
    "deadbeef" * 8,
    "0123456789abcdef" * 4,
})


def _normalise_record_rel(value: object) -> Optional[str]:
    """Return a safe run-relative POSIX path, or ``None``."""
    if not isinstance(value, str) or not value:
        return None
    rel = value
    while rel.startswith("./"):
        rel = rel[2:]
    parts = Path(rel).parts
    if not rel or rel.startswith("/") or ".." in parts:
        return None
    return Path(rel).as_posix()


def _real_record_digest(value: object) -> bool:
    """The publisher's digest shape, excluding explicit placeholder values."""
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(c in "0123456789abcdef" for c in value)
        and value not in _SHA256_PLACEHOLDERS
    )


def _recorded_output_from_doc(step_id, entry: str, doc: object, *,
                              root: str, record: str) -> RecordedSearch:
    """Validate one tracked ``STEP_RECORD.json`` against one declaration.

    The schema is the publisher's actual output, not a second manifest format:
    a passing step, a matching run-relative path, non-zero measured bytes, a
    real sha256, and the explicit decision that the bytes were deliberately
    excluded from the published cell.  ``in_cell`` must be exactly ``False``;
    a record may not stand in for bytes it says should be present locally.
    """
    if (not isinstance(doc, dict) or doc.get("id") is None
            or F.normalize_id(doc.get("id")) != F.normalize_id(step_id)):
        return RecordedSearch(None, 0, ())
    outputs = doc.get("declared_outputs")
    if not isinstance(outputs, list):
        return RecordedSearch(None, 0, ())

    alts = tuple(_normalise_record_rel(a) for a in F.split_any_of(entry))
    candidates = 0
    rejected: List[str] = []
    for row in outputs:
        if not isinstance(row, dict):
            continue
        rel = _normalise_record_rel(row.get("rel"))
        if rel is None or not any(a is not None and fnmatch.fnmatchcase(rel, a)
                                  for a in alts):
            continue
        candidates += 1
        why = []
        size = row.get("bytes")
        digest = row.get("sha256")
        if doc.get("status") != "pass":
            why.append(f"step status is {doc.get('status')!r}, not 'pass'")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            why.append(f"bytes is {size!r}, not a positive integer")
        if not _real_record_digest(digest):
            why.append("sha256 is missing, malformed, or a placeholder")
        if row.get("decision") != _RECORDED_UNPUBLISHED:
            why.append(f"decision is {row.get('decision')!r}, not "
                       f"{_RECORDED_UNPUBLISHED!r}")
        if row.get("in_cell") is not False:
            why.append(f"in_cell is {row.get('in_cell')!r}, not false")
        if row.get("symlink") is not False:
            why.append(f"symlink is {row.get('symlink')!r}, not false")
        if why:
            rejected.append(f"{record}: {rel}: " + "; ".join(why))
            continue
        return RecordedSearch(
            RecordedOutput(root, record, rel, size, digest),
            candidates, tuple(rejected))
    return RecordedSearch(None, candidates, tuple(rejected))


def recorded_unpublished_output(step_id, entry: str) -> RecordedSearch:
    """Search only tracked records in cells the real publisher could admit."""
    candidates = 0
    rejected: List[str] = []
    record_name = _bep._STEP_RECORD_FILENAME
    for label, rr in run_roots().items():
        # Some legacy roots are registered as ``repo`` because they retain the
        # runner provenance as well as the published view.  Ask the publisher's
        # own admission predicate instead of trusting that older label.
        if not _is_published_cell(rr.path):
            continue
        steps = rr.path / "steps"
        if not steps.is_dir():
            continue
        for path in sorted(steps.rglob(record_name)):
            rel_record = path.relative_to(rr.path).as_posix()
            if not is_tracked(rr.path, rel_record):
                rejected.append(f"{label}:{rel_record}: record is not tracked at HEAD")
                continue
            raw, binding_error = _head_bound_record_bytes(
                rr.path, path, rel_record)
            if raw is None:
                rejected.append(
                    f"{label}:{rel_record}: record bytes are not HEAD-bound "
                    f"({binding_error})")
                continue
            try:
                doc = json.loads(raw)
            except (UnicodeError, json.JSONDecodeError) as exc:
                rejected.append(f"{label}:{rel_record}: record is unreadable ({exc})")
                continue
            one = _recorded_output_from_doc(
                step_id, entry, doc, root=label, record=rel_record)
            candidates += one.candidates
            rejected.extend(one.rejected)
            if one.hit is not None:
                return RecordedSearch(one.hit, candidates, tuple(rejected))
    return RecordedSearch(None, candidates, tuple(rejected))


def _recorded_or(step_id, entry: str, mode: str, detail: str) -> EntryVerdict:
    """Prefer a valid publisher record to an otherwise-negative verdict."""
    found = recorded_unpublished_output(step_id, entry)
    if found.hit is not None:
        h = found.hit
        return EntryVerdict(True, LIVE, (
            f"recorded as deliberately unpublished: {h.rel} ({h.size_bytes} B, "
            f"sha256={h.sha256}) in {h.record} under {h.root!r}; the tracked "
            f"publisher record proves production without claiming the bytes "
            f"are present in this cell"
        ))
    record_note = (
        f"; publisher record search found {found.candidates} matching row(s)"
        + (f" but rejected them: {list(found.rejected)}" if found.rejected else
           "; the output is absent from the publisher records entirely")
    )
    return EntryVerdict(False, mode, detail + record_note)


def _record_control_doc() -> Dict:
    """One synthetic publisher row used only by the paired schema controls."""
    return {
        "id": "15",
        "status": "pass",
        "declared_outputs": [{
            "rel": "phase3/stage3/pnr/floorplan.def",
            "symlink": False,
            "bytes": 42195,
            "sha256": "bfe53501cdebf896b368b80f1e86274b9c6b8d4f9482704823093adc0f9898c4",
            "in_cell": False,
            "decision": _RECORDED_UNPUBLISHED,
        }],
    }


def test_d3_a_real_recorded_unpublished_digest_is_production_evidence():
    found = _recorded_output_from_doc(
        "15", "phase3/stage3/pnr/floorplan.def", _record_control_doc(),
        root="published/control", record="steps/15/STEP_RECORD.json")
    assert found.hit is not None, found
    assert found.hit.size_bytes == 42195
    assert found.hit.sha256.startswith("bfe53501")


@pytest.mark.parametrize(
    "mutate, phrase",
    (
        (lambda row: row.pop("sha256"), "sha256"),
        (lambda row: row.__setitem__("sha256", "0" * 64), "placeholder"),
        (lambda row: row.__setitem__("decision", "ABSENT_IN_RUN"), "decision"),
        (lambda row: row.__setitem__("in_cell", True), "in_cell"),
    ),
    ids=("digest-missing", "digest-placeholder", "not-recorded-unpublished",
         "claims-bytes-in-cell"),
)
def test_d3_a_hollow_record_does_not_replace_the_missing_bytes(mutate, phrase):
    doc = _record_control_doc()
    mutate(doc["declared_outputs"][0])
    found = _recorded_output_from_doc(
        "15", "phase3/stage3/pnr/floorplan.def", doc,
        root="published/control", record="steps/15/STEP_RECORD.json")
    assert found.hit is None
    assert found.candidates == 1, (
        "the malformed matching row was folded into 'absent from the record'")
    assert phrase in " ".join(found.rejected), found.rejected


def test_d3_absent_from_the_record_is_distinct_from_a_rejected_record():
    doc = _record_control_doc()
    found = _recorded_output_from_doc(
        "17", "phase3/stage3/pnr/placed.def", doc,
        root="published/control", record="steps/15/STEP_RECORD.json")
    assert found == RecordedSearch(None, 0, ())


# ──────────────────────────────────────────────────────────────────────
# DOES THIS COMMIT CARRY A PRODUCER FOR THE ENTRY? (vibe-ic#1452)
# ──────────────────────────────────────────────────────────────────────
#: The exact promise :func:`_unevidenced_detail` used to make about EVERY
#: unevidenced entry, quoted so the guard below tests the sentence a reader
#: actually gets rather than a paraphrase of it.
_RUN_TREE_REMEDY = (
    "Commit (or register in the manifest) a run tree that carries it and this "
    "cell answers live again."
)


@dataclass(frozen=True)
class ProducerEvidence:
    """Which oracle, if any, names something in this COMMIT that writes *entry*.

    ``producers`` is the union over the entry's ``" OR "`` alternatives: an
    any-of entry is produced if ANY alternative is, because that is how
    :func:`resolve` resolves it.

    ``limit`` is never empty and is the load-bearing half. An oracle that
    answers "nothing" has said *I found no producer*, NOT *nothing produces
    this*, and the difference decides which remedy is true. Dimension 7's own
    ``RESOLUTION_LIMITS`` states the gap in writing — a write performed inside
    a shelled-out tool script (an OpenROAD/KLayout TCL heredoc embedded as a
    Python string) is not a Python write position and is invisible — so an
    empty answer is reported WITH the reach of what was asked and is never
    rendered as a zero.
    """
    entry: str
    producers: Tuple[str, ...]
    limit: str

    def __bool__(self) -> bool:
        return bool(self.producers)


@lru_cache(maxsize=None)
def producer_evidence(entry: str) -> ProducerEvidence:
    """Programs this COMMIT carries that write any alternative of *entry*.

    Dimension 7's two oracles are IMPORTED rather than re-implemented, for the
    same reason ``_glob_first`` is: a second opinion about "does the flow
    produce this path" that could drift from the one d7 enforces is worse than
    no opinion at all. Both are pure functions of the COMMIT, which is the only
    kind this module may consult (#527) — the first parses the AST of every
    ``programs/*.py``, the second reads run write-ledgers TRACKED AT HEAD — so
    a maintainer's untracked build product cannot name a producer that a fresh
    clone would not also name.

    Imported lazily and cached: ``writers_of`` builds an AST index over the
    whole program tree on first call, and no cell that never reaches an
    UNEVIDENCED verdict should pay for it.
    """
    import matrix_d7_artifact_graph as _graph
    import matrix_d7_write_record as _record

    found = set()
    for alt in F.split_any_of(entry):
        found |= set(_graph.writers_of(alt))
        found |= set(_record.observed_producers_of(alt))
    # Called, not reached through getattr: a rename in d7 must be a loud, named
    # failure here rather than a silently narrower oracle answering "none".
    n_records = len(_record.record_roots())
    return ProducerEvidence(
        entry=entry,
        producers=tuple(sorted(found)),
        limit=(
            f"asked both of dimension 7's commit-derived oracles: the AST of "
            f"every programs/*.py, and {n_records} observation set(s) from run "
            f"write-ledgers tracked at HEAD. Neither can see a write performed "
            f"inside a shelled-out tool script (an OpenROAD/KLayout TCL heredoc "
            f"embedded as a Python string) — "
            f"matrix_d7_artifact_graph.RESOLUTION_LIMITS says so in writing — "
            f"so 'no producer found' is the reach of the question, not a proof "
            f"that nothing writes it"
        ),
    )


#: The remedy an UNEVIDENCED verdict may honestly state (vibe-ic#1452).
#:
#: WHY THIS IS NOT :data:`_RUN_TREE_REMEDY` ANY MORE. That sentence was
#: appended unconditionally to every unevidenced entry, and it is a claim about
#: PRODUCIBILITY that the module never checked. It was acted on: #1452 read it
#: off its red cells, concluded "the fix is repo content, not code", and
#: proposed committing the external run trees the message names — a proposal a
#: later measurement showed to be unsafe on disclosure grounds, and which for
#: the no-producer entries could not have closed the cell even had it been
#: safe. Committing a run tree that carries an artefact THIS COMMIT CANNOT
#: PRODUCE is not evidence that the flow produces it; admitting one would be
#: the A8 defect this module's own docstring refused in those words ("no
#: ``.gds`` was written into a run tree to turn a test green").
#:
#: WHY THE GAP IS NAMED HERE RATHER THAN DECIDED HERE. Deciding it per entry
#: means asking :func:`producer_evidence`, which builds an AST index over every
#: ``programs/*.py`` — MEASURED at 128.5 s on this checkout at loadavg 174, and
#: main's d3 file carries no dimension-7 reference at all today, so that whole
#: cost would be NEW and would land inside a parametrised cell that runs in
#: about two seconds now. The harness bound is 180 s per test with
#: ``--timeout-method=thread``, and crossing it kills the SESSION rather than
#: the test, taking every other result down unnamed. So the verdict names BOTH
#: gaps and neither is a promise, and the split is measured once, in
#: :func:`test_d3_the_unevidenced_population_is_split_by_which_gap_it_has`,
#: where the index cost is paid by a test that exists to pay it.
_TWO_GAPS_REMEDY = (
    " Two different gaps produce this verdict and they need OPPOSITE remedies. "
    "If this commit carries a producer for the entry, the gap is EVIDENCE and "
    "committing (or registering in the manifest) a run tree that carries it "
    "closes the cell. If it carries none, the gap is the PRODUCER and no run "
    "tree closes it — importing an artefact this commit cannot be shown to "
    "produce is not evidence of production, which is the defect refused for "
    "step A8's .gds. Which gap THIS entry has is measured from the commit by "
    "test_d3_the_unevidenced_population_is_split_by_which_gap_it_has; do not "
    "assume it is the first one."
)


# ──────────────────────────────────────────────────────────────────────
# CAN THE PUBLISH CONTRACT EVER CARRY THE ENTRY? (vibe-ic#1349)
# ──────────────────────────────────────────────────────────────────────
#: The one destination `benchmark_evidence_publish.publish` writes that is NOT
#: in its `_COPY_SUBTREES`: the signoff GDS is staged by an explicit branch of
#: `publish()` into `dest/phase3/stage4/gds/`, so a scope built from the
#: subtree list alone would report the one artefact the GDS manifest is about
#: as unpublishable. Written down here because that branch computes the path
#: inline and exports no constant to import; it is BOUND TO OBSERVED BEHAVIOUR
#: by `test_d3_the_publish_scope_is_what_the_publisher_actually_stages`, which
#: runs the real program and refuses a scope that does not match what landed.
_PUBLISH_GDS_DEST = "phase3/stage4/gds"


def publish_scope() -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """``(destination prefixes, exact files)`` a published cell can contain.

    Read from ``benchmark_evidence_publish``'s OWN constants, never re-stated,
    for the same reason ``_audit_verdict`` and ``_CONVERGED`` already are: a
    second opinion about what the publish contract carries could drift from the
    contract, and this module would then tell a reader to perform a publish
    that does not do what the message says.

    A rename of either constant is an ``AttributeError`` here — loud, named,
    at the site that depends on it — rather than a silently narrower scope
    that reports every entry as publishable.
    """
    subtrees = tuple(Path(str(s)).as_posix() for s in _bep._COPY_SUBTREES)
    return (subtrees + (_PUBLISH_GDS_DEST,),
            tuple(_bep._COPY_FILES) + ("RESULT.md",))


@lru_cache(maxsize=None)
def publishable(entry: str) -> bool:
    """Can any alternative of *entry* land inside a program-published cell?

    Any-of, matching :func:`resolve`: an entry is publishable when ANY of its
    ``" OR "`` alternatives falls inside the staged scope, because that is the
    alternative a publish would carry and the one the entry would resolve on.
    """
    prefixes, files = publish_scope()
    for alt in F.split_any_of(entry):
        rel = alt.lstrip("./")
        if rel in files:
            return True
        if any(rel == p or rel.startswith(p + "/") for p in prefixes):
            return True
    return False


#: vibe-ic#1349 — the clause an UNEVIDENCED entry gets when the run-tree half of
#: :data:`_TWO_GAPS_REMEDY` is not a thing this repository can do.
#:
#: WHY THIS IS THE SAME DEFECT #1452 FIXED, ONE STEP FURTHER IN. #1452 removed
#: an UNCHECKED promise ("commit a run tree and this cell answers live again")
#: and replaced it with two gaps, of which the first still says a run tree
#: closes the cell. For an entry whose declared path lies outside every
#: destination `benchmark_evidence_publish` stages, that first half is
#: unreachable through the repository's own publish contract — and it was acted
#: on three times: #1349, #1452 and #1457 were each filed within hours of each
#: other, each concluding "the remedy is corpus publication", and none of them
#: could have been performed by running the publisher.
#:
#: It states a STRUCTURAL fact and no count, deliberately. A number measured on
#: one day is the shape this module refuses everywhere else; the population is
#: pinned instead, in :data:`UNEVIDENCED_OUTSIDE_THE_PUBLISH_CONTRACT`.
_PUBLISH_GAP = (
    " REMEDY CHECK (vibe-ic#1349): the run-tree half of that choice is NOT "
    "AVAILABLE for this entry. No alternative of it lands inside the scope "
    "`benchmark_evidence_publish` stages, so no cell that program publishes "
    "can carry it, whether or not a run produces it — the tracked artefacts "
    "under this prefix all come from pre-program hand-staged trees. Widening "
    "the publish scope is the evidence-policy and repo-size call that "
    "program's own docstring defers ('Widening it is an evidence-policy call, "
    "not a size call, and is deliberately left alone here'); it is not a fix "
    "to improvise from a red cell. Staged scope: "
)


def _publish_gap_note(entry: str) -> str:
    """The publish-contract clause for *entry*, or "" when it is publishable."""
    if publishable(entry):
        return ""
    prefixes, files = publish_scope()
    return (_PUBLISH_GAP + f"{sorted(prefixes)} + files {sorted(files)}.")


def _unevidenced_detail(entry: str, rec: Dict, which_root: str,
                        rejected: Dict[str, "Rejected"]) -> str:
    """The message for an entry NOTHING on this checkout can resolve.

    It states three things a reader needs and the old fixture message stated
    none of: that the search happened and came back empty, what the manifest
    record actually is (a dated observation of a tree that is not here), and
    the ONE action that turns the cell green again.

    vibe-ic#1452 — THE THIRD OF THOSE WAS NOT TRUE. "Commit a run tree" was
    appended unconditionally, including to entries this commit carries no
    producer for, where following it cannot work. It is replaced by
    :data:`_TWO_GAPS_REMEDY`, which names both gaps and promises neither.

    vibe-ic#1349 — AND THE SURVIVING HALF OF THAT REMEDY IS NOT ALWAYS
    REACHABLE EITHER. :data:`_TWO_GAPS_REMEDY` still tells the EVIDENCE-gap
    reader that committing a run tree closes the cell. For an entry outside
    the scope :func:`publish_scope` derives, running the flow and publishing
    the result cannot produce a cell that carries it, so
    :data:`_PUBLISH_GAP` says so at the point the reader is deciding what to
    do. Nothing about the VERDICT changes: the entry is still unevidenced and
    the cell is still red.
    """
    return (
        f"UNEVIDENCED: {which_root} is not carried by this repository, and "
        f"nothing matching {entry!r} resolves in any of the "
        f"{len(run_roots())} admissible run roots {sorted(run_roots())}"
        f"{_rejected_note(rejected)}. The manifest records "
        f"{rec.get('path') or rec.get('writes')!r} at "
        f"{rec.get('size_bytes')} B measured on {_MANIFEST_MEASURED_ON} — that "
        f"is a claim about a tree on one machine on one day, not evidence that "
        f"this commit produces the artefact, and it must not be reported as "
        f"produced." + _TWO_GAPS_REMEDY + _publish_gap_note(entry)
    )


def _ledger_state(step_id, entry: str) -> str:
    """One clause naming the ledger state of EVERY admissible root, for the
    verdict detail.

    Backward compatibility is not allowed to be silent. A run that carries no
    ledger degrades to the pre-ledger behaviour, and the record has to SAY
    which roots those are — otherwise a reader of a green cell cannot tell
    "this step's own run recorded the write" from "nobody ever asked".
    """
    roots = run_roots()
    if not roots:
        return ""
    says = {label: ledger_says(rr.path, step_id, entry)
            for label, rr in roots.items()}
    bound = {k: v for k, v in says.items() if v.consulted}
    if not bound:
        # The common case today, and it must stay READABLE or nobody will read
        # it: one clause, the reasons de-duplicated, the roots counted.
        reasons = sorted({v.note.split(" — ")[0].split(";")[0]
                          for v in says.values()})
        return (f" [write ledger: none of the {len(roots)} admissible run "
                f"roots carries one this dimension may consult ({'; '.join(reasons)})"
                f" — this entry is decided exactly as it was before the "
                f"ledger existed]")
    return (" [write ledger — "
            + "; ".join(f"{k}: BOUND ({v.note})" for k, v in bound.items())
            + (f"; not bound: {sorted(set(says) - set(bound))}"
               if len(bound) != len(says) else "")
            + "]")


def check_entry(step_id, entry: str, rec: Dict) -> EntryVerdict:
    """The verdict for ONE ``required_outputs`` entry, recomputed live.

    Every ``resolve``/``resolve_anywhere`` call below is passed *step_id*, so
    each root answers "did THIS STEP write it" whenever it left a write ledger
    and "does a matching artefact exist here" whenever it did not. The two are
    told apart in the detail rather than blurred.
    """
    status = rec.get("status")

    if status == "UNPROVEN":
        hit, rejected = resolve_anywhere(entry, step_id)
        if hit is not None:
            return EntryVerdict(True, LIVE, (
                f"recorded UNPROVEN but NOW resolves: {hit.path} "
                f"({hit.size_bytes} B) in {hit.root!r} — the gap has closed and "
                f"the waiver must be removed" + _ledger_state(step_id, entry)
            ))
        return _recorded_or(step_id, entry, LIVE, (
            f"no committed non-empty artefact matches {entry!r} in any of the "
            f"{len(run_roots())} admissible run roots"
            f"{_rejected_note(rejected)}{_ledger_state(step_id, entry)}"
        ))

    if status == "PRODUCED_LIVE":
        if rec["base_run"] not in run_roots():
            # Same rule as the PRODUCED_BY_RUN fall-through below: the run tree
            # the live production was measured in is not here, so this checkout
            # cannot re-run the producer, and a record of somebody else having
            # run it is a claim about the past, not an artefact.
            hit, rejected = resolve_anywhere(entry, step_id)
            if hit is not None:
                return EntryVerdict(True, LIVE, (
                    f"{hit.path} ({hit.size_bytes} B) in {hit.root!r} "
                    f"[recorded base run {rec['base_run']!r} absent here]"
                    + _ledger_state(step_id, entry)
                ))
            return _recorded_or(
                step_id, entry, FIXTURE,
                _unevidenced_detail(
                    entry, rec, f"the recorded base run {rec['base_run']!r}",
                    rejected) + _ledger_state(step_id, entry))
        ok, detail = produce_live(step_id, entry, rec)
        if ok:
            return EntryVerdict(True, LIVE, detail)
        return _recorded_or(step_id, entry, LIVE, detail)

    if status == "PRODUCED_BY_RUN":
        alts = F.split_any_of(entry)
        if rec["alternative"] not in alts:
            return EntryVerdict(False, LIVE, (
                f"the manifest resolved this entry via alternative "
                f"{rec['alternative']!r}, which the flow yaml no longer declares "
                f"(current alternatives: {list(alts)}) — the entry changed and "
                f"the evidence no longer refers to it"
            ))
        rr = run_roots().get(rec["run"])
        if rr is not None:
            hit, rejected = resolve(rr.path, entry, step_id)
            if hit is not None:
                return EntryVerdict(True, LIVE,
                                    f"{hit.path} ({hit.size_bytes} B) in {rec['run']!r}"
                                    + _ledger_state(step_id, entry))
            # THE RECORDED ROOT IS HERE AND NO LONGER CARRIES IT. Until now
            # that ended the search, while the ABSENT-root branch below asked
            # every admissible root — so an entry was strictly LESS likely to
            # be evidenced when the manifest happened to name a root that
            # exists. Measured on this checkout: steps 21 and 22 recorded
            # `phase3/stage3/pnr/routed.def` and `phase3/stage3/extracted/
            # *.spef` against `spm/v1.9.96_gf180mcuD` — a PUBLISHED CELL, i.e.
            # a curated subset of the run the manifest was measured on, which
            # never carried either path in any commit — while
            # `spm/v1.5.58_ihp-sg13g2`, an admissible root already registered
            # in this same manifest, carries both non-empty and tracked at
            # HEAD. Both cells read "not produced" with the artefact sitting in
            # the repository.
            #
            # This only ADDS the search the sibling branch already performs,
            # through the identical `resolve_anywhere`, so nothing becomes
            # evidence here that is not non-empty, non-symlink, tracked at HEAD
            # and un-refused by that root's own write ledger. What it removes
            # is a verdict decided by WHICH root the manifest names rather than
            # by what the commit carries. The stale record is reported, not
            # swallowed: a reader is told the recorded root lost the artefact
            # and which root answered instead, so the manifest gets repaired
            # rather than quietly relied upon.
            elsewhere, rej_all = resolve_anywhere(entry, step_id)
            if elsewhere is not None:
                return EntryVerdict(True, LIVE, (
                    f"{elsewhere.path} ({elsewhere.size_bytes} B) in "
                    f"{elsewhere.root!r} — STALE MANIFEST RECORD: the recorded "
                    f"run root {rec['run']!r} resolves at {rr.path} but no "
                    f"longer yields a committed non-empty artefact for "
                    f"{entry!r} (recorded: {rec['path']} at "
                    f"{rec['size_bytes']} B). Re-point the record at "
                    f"{elsewhere.root!r}"
                    f"{_rejected_note({rec['run']: rejected})}"
                    + _ledger_state(step_id, entry)
                ))
            return _recorded_or(step_id, entry, LIVE, (
                f"the recorded run root {rec['run']!r} resolves at {rr.path} "
                f"but no longer yields a committed non-empty artefact for "
                f"{entry!r} (recorded: {rec['path']} at {rec['size_bytes']} B), "
                f"and nothing matching it resolves in any of the "
                f"{len(run_roots())} admissible run roots either"
                f"{_rejected_note(rej_all or {rec['run']: rejected})}"
                f"{_ledger_state(step_id, entry)}"
            ))
        hit, rejected = resolve_anywhere(entry, step_id)
        if hit is not None:
            return EntryVerdict(True, LIVE, (
                f"{hit.path} ({hit.size_bytes} B) in {hit.root!r} "
                f"[recorded run {rec['run']!r} absent here]"
                + _ledger_state(step_id, entry)
            ))
        return _recorded_or(
            step_id, entry, FIXTURE,
            _unevidenced_detail(
                entry, rec, f"the recorded run root {rec['run']!r}", rejected)
                + _ledger_state(step_id, entry))

    return EntryVerdict(False, LIVE, f"unrecognised manifest status {status!r}")


def audit_step(step_id) -> Tuple[List[str], List[str]]:
    """``(missing, details)`` over ALL declared entries — ALL-of-N."""
    rec = step_record(step_id)
    live_entries = list(F.required_outputs(step_id))
    recorded = rec["entries"]

    drift = []
    if set(live_entries) != set(recorded):
        added = sorted(set(live_entries) - set(recorded))
        gone = sorted(set(recorded) - set(live_entries))
        drift.append(
            f"required_outputs drifted from the measured manifest: "
            f"+{added} -{gone}"
        )

    missing: List[str] = list(drift)
    details: List[str] = []
    for entry in live_entries:
        if entry not in recorded:
            missing.append(f"{entry!r}: never measured")
            continue
        v = check_entry(step_id, entry, recorded[entry])
        details.append(f"[{v.mode}] {entry!r} -> {v.detail}")
        if not v.produced:
            missing.append(f"{entry!r}: {v.detail}")
    return missing, details


# ──────────────────────────────────────────────────────────────────────
# The one class of citation the corpus skip may NOT cover
# ──────────────────────────────────────────────────────────────────────
# WHAT THE CORPUS SKIP PROMISES, AND WHERE THAT PROMISE IS FALSE.
#
# `SKIP_REASON` tells the reader the result cells live in another repository
# and that pointing the corpus pointer at a clone runs this check against them.
# That is true for every entry whose recorded run root is a kind this module
# SEARCHES: those roots were `benchmark-data/<...>` here, `_corpus_candidate`
# rewrites them into the clone, and the cell answers live again.
#
# It is FALSE for an entry whose recorded root is any OTHER kind. #527 removed
# every off-repository search from this dimension, so such a root is consulted
# on no host, with or without the pointer — and MEASURED against a clone of the
# published-corpus repository at its own HEAD, neither those roots nor the
# artefacts they cite resolve there under any root either. Setting the pointer
# does not move these entries: they come back unevidenced with the corpus
# present, exactly as they do without it.
#
# So for those entries the absent corpus is not the reason the answer is
# missing, and letting the skip cover them drops them out of the denominator
# altogether: on a fresh checkout the whole dimension reported no failure while
# these citations went unexamined, which reads as a clean run over a population
# nobody looked at. A check that could not look has not looked — but a citation
# NOTHING can look at is a stronger statement than that, and it has to be made
# here rather than deferred to a corpus that cannot settle it.
#
# The carve-out only ever NARROWS the skip. It adds no evidence, admits no new
# root, and changes nothing at all when the corpus is present.


def unanswerable_citations(step_id) -> Tuple[Tuple[str, str, str], ...]:
    """``(entry, cited run root, the path the citation wanted)`` for the
    declared entries of *step_id* that NO corpus can answer.

    An entry is unanswerable when the run root it records is outside
    :data:`_ADMISSIBILITY` — either the manifest gives that root a ``kind`` this
    module never searches, or the manifest registers no such root at all. Both
    are properties of the RECORD, decided without opening a file, which is what
    makes the answer identical on a host that has a corpus and on one that does
    not.

    An entry that records NO root is not unanswerable: it cites nothing, so a
    corpus carrying the artefact resolves it and the skip is the honest verdict.
    """
    recorded = (step_record(step_id).get("entries") or {})
    roots = manifest()["run_roots"]
    out: List[Tuple[str, str, str]] = []
    for entry in F.required_outputs(step_id):
        er = recorded.get(entry)
        if not er:
            continue
        # A tracked publisher record is itself the missing measurement: it
        # says this run produced the named bytes, records their digest, and
        # says explicitly that publish policy withheld them.  Such an entry is
        # answerable even when the older matrix manifest cites a machine-local
        # source run, so it must not be moved into NOT_MEASURED first.
        if recorded_unpublished_output(step_id, entry).hit is not None:
            continue
        for field in ("run", "base_run"):
            label = er.get(field)
            if not label:
                continue
            meta = roots.get(label)
            if meta is not None and meta.get("kind") in _ADMISSIBILITY:
                continue
            out.append((entry, label,
                        str(er.get("path") or er.get("writes") or entry)))
    return tuple(out)


def _corpus_skip_would_hide(step_id, cites: Tuple[Tuple[str, str, str], ...]) -> str:
    """The NOT DETERMINED message for citations the skip would have swallowed.

    It names, per entry, the path the record wanted and the root it wanted it
    from, because "not determined" without those two is a shrug rather than a
    finding.
    """
    roots = manifest()["run_roots"]
    lines = [
        f"{entry!r}: NOT DETERMINED — the record wants {wanted!r} from run "
        f"root {label!r} (kind "
        f"{(roots.get(label) or {}).get('kind', 'NOT REGISTERED')!r}), which "
        f"this dimension searches on no host"
        for entry, label, wanted in cites
    ]
    return (
        f"step {step_id} ({F.step_name(step_id)}): {len(cites)} declared "
        f"output(s) cite a run root NO corpus can supply, so the corpus-absent "
        f"skip must not cover them:\n  " + "\n  ".join(lines) + "\n\n"
        f"The skip says the result cells live in another repository and that "
        f"the corpus pointer reaches them. That holds for a record whose root "
        f"is one of the kinds this module searches "
        f"({sorted(_ADMISSIBILITY)}); it does not hold for these. Setting the "
        f"pointer leaves them exactly as they are, so they are NOT DETERMINED "
        f"rather than not-yet-looked-at, and they may not leave the "
        f"denominator in silence.\n"
        f"This is NOT a claim that the flow fails to produce these artefacts — "
        f"nothing here measured that. It is a refusal to report a clean run "
        f"over a citation nothing can resolve. Close it by re-pointing the "
        f"record at a root that carries the artefact, by publishing a run tree "
        f"that does, or by waiving the cell through the one waiver registry "
        f"with the disclosure — never by widening the skip."
    )


# ──────────────────────────────────────────────────────────────────────
# Waivers — ONE registry, the one that is consumed
# ──────────────────────────────────────────────────────────────────────
# This module used to carry a `_LOCAL_WAIVERS` mirror of its four dimension-3
# waivers, added while eight agents shared one worktree and concurrent edits to
# `matrix_63x8.waivers.WAIVERS` lost entries. Its docstring said the mirror
# "becomes inert the moment the orchestrator lands it" — and the orchestrator
# did land it, so `waiver_for` had been reading the central copy and ignoring
# the local one for some time.
#
# Nothing noticed, and the two copies had drifted: at v1.7.83 step A8's central
# waiver said every matching .gds was "a stub written by a throwaway seeding
# script into an agent scratch tree" while the local one said both were
# "SYMLINKS pointing back at the design\'s own input layout". Two different
# stories for one accepted gap, and `or` silently picked one. Editing the
# inert copy — which is what a #527 fix attempt did first — changes nothing a
# reader ever sees.
#
# So the mirror is deleted rather than re-synchronised. A waiver is a public
# admission; it can have exactly one text.



# ──────────────────────────────────────────────────────────────────────
# The SOURCE arm — "does anything still write it", per step
# ──────────────────────────────────────────────────────────────────────
#: The tree the producer scan walks. It is the REPOSITORY, not the plugin: the
#: program's own ``VENUE_RELS`` includes a top-level ``tools/`` that sits above
#: :data:`flowref.PLUGIN_ROOT`, and handing it the plugin root would silently
#: drop a venue and turn real producers into TOKEN-TRACE.
#: NOT `F.PLUGIN_ROOT.parents[2]`. That climbs three levels looking for a
#: repository, and the mutation ledger replays cells inside a `cp -al` mirror
#: of the PLUGIN ALONE -- MEASURED 2026-08-29: it climbed out to `/`, where the
#: producer audit raised an uncaught FileNotFoundError and took every
#: dimension-3 cell with it. The plugin root is what this module actually
#: holds, so it is what gets named; the program was taught to accept it.
SOURCE_ROOT: Path = F.PLUGIN_ROOT


class ProducerRegression(AssertionError):
    """The source arm's failure, distinguishable from every other one here.

    It is an ``AssertionError``, so a cell reports it exactly like every other
    predicate in this module and no reader has to learn a new shape. It is a
    SUBCLASS because
    ``test_d3_the_corpus_skip_covers_exactly_the_cells_it_can_explain`` INVOKES
    the cell body and reads a bare ``AssertionError`` as "the cell refused over
    a citation no corpus can answer". MEASURED 2026-08-29: without the subclass,
    deleting ``crc_vector_gen``'s ``.sby`` write made that guard report step 5
    as a predicate/cell disagreement about the CORPUS -- a false attribution of
    a true finding, and the sort of noise that gets a real defect triaged as a
    test bug. The guard is not weakened by the distinction: every
    ``AssertionError`` it could see before, it still sees.
    """



@lru_cache(maxsize=1)
def producer_rows() -> Dict[str, Dict]:
    """``{declared path: producer state}`` for the whole flow, measured NOW.

    One scan per session (~12 s), shared by all 68 cells. The rows are keyed by
    the flow's declared path with alternates split out, and each carries the
    ``steps`` that declare it — which is how a cell asks about ITS OWN outputs
    without this module re-deriving the step→path mapping the program already
    computed from the same yaml.
    """
    return _producer.audit(SOURCE_ROOT,
                           flow=Path(F.FLOW_YAML),
                           plugin_root=F.PLUGIN_ROOT)["rows"]


@lru_cache(maxsize=1)
def write_site_baseline() -> frozenset:
    """Declared paths this repository HAS resolved to a real write site.

    Read from the program's own inventory file, not recomputed: it is the same
    record ``declared_output_has_a_live_producer_check --strict`` blocks on, so
    a cell here and the shipped gate cannot disagree about what a regression
    is. Missing or unreadable is refused rather than treated as empty — an
    empty baseline would make :func:`producer_regressions` unable to fire, and
    a guard that degrades to "off" reports success.
    """
    # `SHIPPED_INVENTORY`, not the program's `--root`-relative default: this
    # module audits `SOURCE_ROOT` (= `F.PLUGIN_ROOT`) in-process, so the
    # baseline it must agree with is the one shipped beside the program.
    inv = _producer.SHIPPED_INVENTORY
    assert inv.is_file(), (
        f"{inv} is missing. It is the shrink-only record of declared outputs "
        f"this tree resolves to a write site, and without it the source arm of "
        f"this dimension cannot fire at all"
    )
    data = json.loads(inv.read_text(encoding="utf-8"))
    paths = data.get("write_site")
    assert paths, f"{inv} records no write site; the source arm could not fire"
    return frozenset(paths)


def producer_regressions(step_id, rows: Optional[Dict[str, Dict]] = None
                         ) -> Tuple[Tuple[str, str], ...]:
    """This step's declared paths whose producer the SOURCE can no longer find.

    Two arms, and together they are exactly the program's own ``--strict``
    verdict restricted to one step. Neither is invented here.

    ``NO-TRACE``
        the declared path appears nowhere in the source that runs — not as a
        write destination, not even as a name. Nothing could write it.

    ``LOST WRITE SITE``
        the path is in the shrink-only baseline — this repository HAS resolved
        it to a real write call — and no longer resolves to one. This is the
        arm that fires when a producer is deleted, and the program's own
        docstring records WHY the strong arm alone cannot: measured
        2026-08-29, simulating deletion of the entire sole producer of all 34
        single-producer paths, not one reached NO-TRACE. Every one landed in
        TOKEN-TRACE, because the path's name still appears in the source —
        written there by its READERS. A rule that blocked only on NO-TRACE
        would be a rule that cannot fire.

    NOT asserted: that every declared output HAS a write site. Measured on this
    tree, 18 of 197 declared paths do; the other 179 are written to destinations
    assembled at runtime (``f"L{n}_{name}.json"``) that no scanner can resolve.
    Demanding WRITE-SITE per cell reddens 62 of the 68 cells and reports the
    ordinary way this repository writes files, not a defect.

    ``rows`` is injectable for ONE purpose: a can-fail test needs to hand this
    function an audit taken with a producer excluded, and a predicate that
    cannot be shown a deleted producer cannot be shown to notice one.
    """
    sid = F.normalize_id(step_id)
    rows = producer_rows() if rows is None else rows
    baseline = write_site_baseline()
    out: List[Tuple[str, str]] = []
    for decl, row in sorted(rows.items()):
        if sid not in row["steps"]:
            continue
        state = row["state"]
        if state == "NO-TRACE":
            out.append((decl, "NO-TRACE — nothing in the running source writes "
                              "or even names this path"))
        elif decl in baseline and state != "WRITE-SITE":
            out.append((decl, f"LOST WRITE SITE — demoted to {state}"
                              f"{' (evidence: ' + row['evidence'] + ')' if row['evidence'] else ''}"
                              f"; this repository resolved this path to a real "
                              f"write call and no longer does"))
    return tuple(out)


@lru_cache(maxsize=1)
def producer_arm_coverage() -> Tuple[str, ...]:
    """The cells the source arm can currently speak about, DERIVED.

    A step is covered when at least one of its declared paths is in the
    baseline, because that is the only arm measured able to fire. Derived from
    the commit rather than pinned to a literal: the baseline may GROW freely
    (that is the program's own rule) and a pinned count would turn growth into
    a failure. What must never happen is the set going EMPTY, and
    :func:`test_d3_the_source_arm_covers_a_named_and_non_empty_set_of_cells`
    is what says so.
    """
    baseline = write_site_baseline()
    rows = producer_rows()
    covered: set = set()
    for decl, row in rows.items():
        if decl in baseline:
            covered |= set(row["steps"])
    return tuple(sorted(covered, key=str))


def dim_waivers() -> Tuple[waivers.Waiver, ...]:
    """This dimension's waivers, from the one registry that is consumed."""
    return tuple(waivers.waivers_for_dim(DIM))


def waiver_for(step_id) -> Optional[waivers.Waiver]:
    """The waiver for this cell, or ``None``. Single source: the registry."""
    return waivers.waiver_for(step_id, DIM)


def _params():
    out = []
    for cell in cells_for(DIM):
        w = waiver_for(cell.step_id)
        marks = [pytest.mark.xfail(strict=True, reason=w.xfail_reason)] if w else []
        out.append(pytest.param(cell, marks=marks))
    return out


# ──────────────────────────────────────────────────────────────────────
# The 63 cells
# ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("cell", _params(), ids=lambda c: f"step{c.step_id}")
def test_d3_required_outputs_are_produced(cell):
    sid = cell.step_id
    rec = step_record(sid)
    verdict = rec["verdict"]

    # ---- THE SOURCE ARM: does anything still WRITE what this declares? ----
    #
    # Asked FIRST, and asked of every cell — NA, waived and enforced alike —
    # because it is the only question in this body that dies when a producer
    # dies. Everything below it reads an artefact, and an artefact committed in
    # 2026-07 answers the same whether or not this checkout still writes it.
    #
    # AHEAD OF THE NA RETURNS on purpose. Step 37.5ip is NA_DORMANT_CONDITION
    # and carries a baseline-anchored write site; "this step has not run" is a
    # statement about a run tree and cannot excuse a deleted writer in the
    # source. Ahead of the corpus skip for the same reason in the other
    # direction: this question is about THIS checkout, so no corpus can supply
    # it and no absent corpus can be a reason not to ask it.
    #
    # LIMIT, STATED RATHER THAN HIDDEN. A cell with a waiver carries
    # `xfail(strict=True)`, so on those two cells (6 and 39) a failure here is
    # absorbed as an expected failure. Neither waived step has a
    # baseline-anchored path today, and `test_d3_a_waived_cell_does_not_absorb
    # _the_source_arm` is the guard that makes the day one does a named event
    # rather than a silent one.
    lost = producer_regressions(sid)
    if lost:
        raise ProducerRegression(
            f"step {sid} ({F.step_name(sid)}) declares required_outputs whose "
            f"PRODUCER this source tree can no longer find:\n  "
            + "\n  ".join(f"{path} \u2014 {why}" for path, why in lost)
            + f"\n[measured by declared_output_has_a_live_producer_check.audit("
            + f"{SOURCE_ROOT}) \u2014 the flow may still be able to SHOW you "
            + f"this artefact out of a committed run tree, which is exactly why "
            + f"this arm exists: a file in the corpus is not proof the flow "
            + f"still writes it]"
        )

    # ---- NA: the step declares nothing to produce -------------------
    if verdict == "NA_NO_REQUIRED_OUTPUTS":
        # Live precondition. If anyone adds required_outputs to this step the
        # NA self-invalidates and this cell must be re-evaluated.
        assert not F.declares_required_outputs(sid), (
            f"step {sid} is recorded NA for dimension {DIM} because it declares "
            f"no required_outputs, but the flow yaml now declares "
            f"{list(F.required_outputs(sid))} — the NA is stale"
        )
        return

    # ---- NA: the step is dormant behind an unmet condition ----------
    if verdict == "NA_DORMANT_CONDITION":
        cond = F.step_condition(sid)
        assert cond is not None, (
            f"step {sid} is recorded NA for dimension {DIM} because a step-level "
            f"`condition` keeps it dormant until silicon comes back, but the "
            f"flow yaml no longer declares any condition for it"
        )
        declared = [str(x) for x in (cond.get("files_exist") or [])]
        for want in rec["condition_files"]:
            assert want in declared, (
                f"step {sid}'s dormancy condition changed: expected "
                f"{want!r} in condition.files_exist, measured {declared}"
            )
        satisfied = {
            label: want
            for label, rr in run_roots().items()
            for want in rec["condition_files"]
            if (rr.path / want).is_file()
        }
        assert not satisfied, (
            f"step {sid}'s dormancy condition IS satisfied in {satisfied} — the "
            f"step is no longer inapplicable and its required_outputs must now "
            f"be measured for real"
        )
        # DELIBERATELY NOT ledger-bound (no step_id). This probe asks "does
        # anything at all exist at the declared paths", because an NA that
        # claims the step never ran must be falsified by an artefact HOWEVER
        # it got there. Passing step_id here would let a ledger saying "this
        # step wrote nothing" SUPPRESS the artefact that disproves the NA —
        # the ledger being used as a way around a rule instead of to sharpen
        # one, which is the one thing it must never become.
        found = [
            (e, h.path, h.size_bytes)
            for e in F.required_outputs(sid)
            for h in [resolve_anywhere(e)[0]]
            if h is not None
        ]
        assert not found, (
            f"step {sid} is recorded NA (never ran: no run root has "
            f"{rec['condition_files']}) yet its declared outputs DO exist: "
            f"{found} — the NA is wrong"
        )
        return

    # ---- ENFORCED / WAIVED: the real predicate ----------------------
    # ...but only where there is something to read it against. With no
    # admissible run root AND no published corpus to point at, `audit_step`
    # cannot look at a single byte, and reporting "N required_outputs are NOT
    # produced" would charge the flow with a defect this tree has no evidence
    # for. The two conditions are BOTH required on purpose: a discovery bug that
    # emptied `run_roots()` while the corpus IS present must still redden here,
    # and `test_d3_run_root_discovery_is_live` is the test that says so.
    # THE FOURTH STATE, DECLINING TO LOOK (owner ruling 2026-08-21). A record
    # citing a root this module searches on NO host is not waiting on the
    # corpus pointer and never will be. It used to be REFUSED here by name —
    # `assert not cites` — which charged the flow with a failure on evidence
    # this tree does not hold, and left the cell reported ENFORCED while its
    # predicate was red. Six cells sat in that contradiction.
    #
    # Now the cell says NOT_MEASURED on the configuration axis and this body
    # declines to look, so both axes agree and the census counts it as the
    # absence of a measurement rather than as either colour. NOTHING IS
    # EXCUSED: `matrix_not_measured_reason` names the exact citations, the
    # state counts as nothing in every enforcement figure, and it
    # self-invalidates the moment the record resolves.
    _unmeasured = matrix_not_measured_reason(sid)
    if _unmeasured is not None:
        pytest.skip(f"NOT_MEASURED: {_unmeasured}")

    if not run_roots() and corpus_root() is None:
        pytest.skip(SKIP_REASON)

    missing, details = audit_step(sid)
    assert not missing, (
        f"step {sid} ({F.step_name(sid)}) declares {len(F.required_outputs(sid))} "
        f"required_outputs; {len(missing)} are NOT produced:\n  "
        + "\n  ".join(missing)
        + f"\n[{len(run_roots())} admissible run roots searched: "
        + f"{sorted(run_roots())}]"
    )


# ──────────────────────────────────────────────────────────────────────
# Guards — these keep the 63 above from going quietly hollow
# ──────────────────────────────────────────────────────────────────────
def test_d3_the_source_arm_goes_red_when_a_real_producer_is_deleted():
    """MUT: delete the sole writer of a declared output; the cell must move.

    Not a synthetic probe — the producer excluded here is one this repository
    really ships, chosen because it is the ONLY write site for its declared
    path, and the exclusion is the program's own `exclude_modules` hook rather
    than a hand-built rows dict. Before the wiring, the real deletion of this
    same line left the whole module at `54 passed, 66 skipped`.
    """
    clean = producer_rows()
    singles = sorted((p, r["producers"][0], r["steps"])
                     for p, r in clean.items()
                     if r["state"] == "WRITE-SITE"
                     and len(r["producers"]) == 1
                     and p in write_site_baseline())
    assert singles, (
        "no baseline-anchored declared output has a single producer, so this "
        "module cannot show its source arm noticing one being deleted"
    )
    path, producer, steps = singles[0]
    assert not producer_regressions(steps[0]), (
        f"step {steps[0]} is already regressed on the clean tree; the "
        f"mutation below would prove nothing"
    )
    mutated = _producer.audit(SOURCE_ROOT, exclude_modules=[producer],
                              flow=Path(F.FLOW_YAML),
                              plugin_root=F.PLUGIN_ROOT)["rows"]
    lost = producer_regressions(steps[0], rows=mutated)
    assert any(p == path for p, _ in lost), (
        f"{producer} is the only writer of {path}, declared by step "
        f"{steps[0]}; removing it left that cell green — the source arm is "
        f"reading something other than the producer"
    )


def test_d3_the_source_arm_covers_a_named_and_non_empty_set_of_cells():
    """Say which cells this arm can speak about, and refuse an empty answer.

    The coverage is DERIVED from the baseline and the flow, never pinned to a
    literal: the baseline may grow freely and a pinned count would turn growth
    into a failure. Measured 2026-08-29 it is 15 of the 68 cells — every cell
    whose declared outputs include at least one path this repository resolves
    to a real write call. The other 53 cells carry only paths written to
    runtime-assembled destinations, where the strong arm cannot resolve a site
    and the weak arm (NO-TRACE) is measured unable to fire; those cells are
    asked the question and it is vacuously satisfied, which is a limit of the
    scanner and is recorded as one here rather than presented as a clean bill.
    """
    covered = producer_arm_coverage()
    assert covered, (
        "the source arm covers NO cell: every baseline path has left the flow "
        "declaration, so nothing on the 68 cells can ever fire this arm"
    )
    known = {F.normalize_id(c.step_id) for c in cells_for(DIM)}
    stray = sorted(set(covered) - known)
    assert not stray, (
        f"the baseline anchors declared outputs to steps that are not cells "
        f"of this dimension: {stray}"
    )


def test_d3_a_waived_cell_does_not_absorb_the_source_arm():
    """A waiver is about EVIDENCE; it must not silently swallow a dead writer.

    Waived cells carry `xfail(strict=True)`, so an assertion failing inside one
    reports as an expected failure. That is the module's idiom and is not
    changed here — but it means the source arm is only genuinely enforceable on
    unwaived cells. Measured 2026-08-29: the two waived steps (6 and 39, both
    Intel Quartus bitstreams no program in this plugin synthesises) anchor NO
    baseline path, so no cell is currently in that shadow. The day one is, this
    test names it instead of leaving it to be discovered.
    """
    shadowed = sorted(
        F.normalize_id(c.step_id) for c in cells_for(DIM)
        if waiver_for(c.step_id) is not None
        and F.normalize_id(c.step_id) in producer_arm_coverage()
    )
    assert not shadowed, (
        f"steps {shadowed} are WAIVED (xfail strict) and also carry a "
        f"baseline-anchored declared output, so a deleted producer there "
        f"would report as an expected failure rather than as a defect. Move "
        f"the source arm out of the waived cell body for these steps, or "
        f"retire the waiver"
    )


def test_d3_manifest_covers_exactly_the_flow_steps():
    """The ledger is 63 cells; the manifest must cover 63 steps, no more."""
    live = {F.normalize_id(s) for s in F.step_ids()}
    recorded = set(manifest()["steps"])
    assert recorded == live, (
        f"manifest/flow step-set mismatch: only in flow {sorted(live - recorded)}, "
        f"only in manifest {sorted(recorded - live)}"
    )
    # 69 -> 68: step `37.5self` (General Precheck) is RETIRED, and the census
    # goes back DOWN. The owner's 2026-08-20 decision: the general precheck was
    # never a third ROUTE, it is a second ARM of `37.5ic` — our ladder runs on
    # every design that reaches that step, and the operator's container runs IN
    # ADDITION wherever the PDK ships a precheck and its template was fetched.
    # A PDK with no shuttle precheck is the same step with one fewer arm, not a
    # different route. Re-stated by hand, as the census comments here require:
    # a step LEAVING must force a human to say the number just as loudly as one
    # arriving. RE-DERIVED from the live yaml, never decremented by hand.
    # 2026-08-21, 68 -> 69: step 1.6x. The note above is CORRECT about its own
    # change and wrong about the base it applied it to. Measured by driving
    # `flowref` at each revision's yaml through
    # `VIBE_IC_MATRIX_FLOW_YAML`, the matrix population is:
    #
    #     ff5071caa (this pin last set)   68   no 1.6x, no 37.5self
    #     7fcbc7397~1                     69   no 1.6x, 37.5self PRESENT
    #     7fcbc7397 (adds 1.6x)           70
    #     867de4289 (retires 37.5self)    69
    #
    # So the population moved THREE times across three commits, not once: 37.5self
    # arrived after this pin was set and was never credited, 1.6x arrived and was
    # never credited, and only the removal was. Subtracting one from a base that
    # was already two behind is how a hand-moved census drifts while every
    # individual edit to it looks careful.
    assert len(cells_for(DIM)) == len(live) == 68


@needs_corpus
def test_d3_run_root_discovery_is_live():
    """Discovery must actually find the evidence trees it is offered.

    Both branches assert. Where there is no tree to look in at all — the
    flattened install cache has no monorepo ancestor, and no corpus was
    pointed at — the manifest's repo-kind roots are legitimately unreachable
    and this asserts that IS the cause, rather than skipping and letting a
    discovery bug read as an environment.

    vibe-ic#1703 — THE FAILURE MESSAGE HAD TO MOVE WITH THE SEARCH. It named
    one tree, ``under {repo}``, and offered one pair of causes ("the checkout
    is partial or a run tree was deleted"). Once :func:`run_roots` also reads
    an operator-named corpus, both were wrong in the case that matters most:
    the published cells left this repository, so the tree to go and look at is
    the corpus, and the likeliest cause is neither of the two offered — it is
    that the corpus does not publish that root. A red test that sends the
    reader to the wrong directory costs more than it saves, so the message now
    names every tree it searched.
    """
    sources = [(p, why) for p, why in (
        (_plugin_tree.repo_root(), "this repository"),
        (_offered_corpus(), f"the corpus named by {_pc.CORPUS_ENV}"),
    ) if p is not None]
    repo_labels = [
        label for label, meta in manifest()["run_roots"].items()
        if meta["kind"] == "repo"
    ]
    resolved = run_roots()
    if not sources:
        assert not any(label in resolved for label in repo_labels), (
            "no monorepo ancestor was found and no corpus was pointed at, yet "
            "repo-kind run roots resolved — the two-tree detection in "
            "_plugin_tree.repo_root() disagrees with what is on disk"
        )
        return
    searched = ", ".join(f"{why} ({path})" for path, why in sources)
    unresolved = [label for label in repo_labels if label not in resolved]
    assert not unresolved, (
        f"these run roots are recorded as evidence but resolve in none of the "
        f"trees searched — {searched}: {unresolved}. Three causes produce this "
        f"and they are not the same repair: the checkout is partial; a run "
        f"tree was deleted while this dimension still cites it; or the "
        f"published corpus does not carry that root, in which case the "
        f"manifest cites a run that is no longer published and the record — "
        f"not the corpus — is what has to move (vibe-ic#1703)."
    )
    assert resolved, "no admissible run root resolved at all"


#: The manifest labels the corpus-routing probe below drives, one per
#: admissibility kind, so the new path is exercised against BOTH proofs of
#: provenance rather than against whichever one happens to be first in the
#: manifest. Written down here rather than picked at runtime: a probe that
#: chooses its own subject can quietly stop covering a kind.
_CORPUS_ROUTE_PROBES: Tuple[Tuple[str, str], ...] = (
    ("benchmark-data/ic/spm/v1.5.58_ihp-sg13g2", _IN_REPO_KIND),
    ("benchmark-data/ic/u_hawaii_adc/v1.9.86_sky130A", _PUBLISHED_KIND),
)


def _seed_corpus_root(corpus: Path, rel: str, kind: str) -> Path:
    """Make *rel* (a manifest ``benchmark-data/...`` path) admissible in *corpus*.

    Seeds the minimum each kind's own predicate demands and nothing else, so a
    probe cannot pass by having built something richer than the rule requires.
    """
    root = _corpus_candidate(rel, corpus)
    assert root is not None, f"{rel!r} has no corpus form; the probe is wrong"
    root.mkdir(parents=True, exist_ok=True)
    if kind == _IN_REPO_KIND:
        (root / _RUNNER_MARKERS[0]).write_text("{}\n", encoding="utf-8")
    elif kind == _PUBLISHED_KIND:
        audit = root / "reports" / "audit"
        audit.mkdir(parents=True, exist_ok=True)
        (audit / "phase23_completion_audit.json").write_text(
            json.dumps({"verdict": _bep._CONVERGED[0]}), encoding="utf-8")
    else:  # pragma: no cover - a kind nobody taught this probe about
        raise AssertionError(f"unknown admissibility kind {kind!r}")
    return root


def test_d3_an_offered_corpus_is_where_the_published_run_roots_are_found(
        monkeypatch):
    """vibe-ic#1703 — the pointer the skip message names must actually route.

    The published cells moved to ``vibeic/benchmark-data``. The cell predicate
    skips when they are absent and its reason tells the reader exactly what to
    do about it — *"Point VIBE_IC_BENCHMARK_DATA at a clone to run this check
    against them"* — but :func:`run_roots` did not read that pointer, so doing
    what the message said switched the SKIP off without switching DISCOVERY on.

    Measured on ``origin/main`` at ``ee849c19e``, with the pointer set to a
    clone of ``vibeic/benchmark-data``::

        $ VIBE_IC_BENCHMARK_DATA=<clone> pytest -q \\
              test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced
        50 failed, 11 passed, 2 xfailed in 3.63s

    every one of them reading ``[0 admissible run roots searched: []]`` — 50
    cells asserting "N required_outputs are NOT produced" from a function that
    had opened no file, while the artefacts sat on disk one directory away.
    That is not strictness, it is fabrication, and it is strictly worse than
    the skip it replaced.

    THIS TEST IS THE CONTROL FOR ALL THREE WAYS OF BEING WRONG, because the
    green half alone would be satisfied by a function that returns every
    manifest label unconditionally:

    ROUTES     the root is seeded in the corpus -> it resolves, at the corpus
               path, for BOTH admissibility kinds.
    READS      the same root with its own proof of provenance REMOVED -> it
               does not resolve. Discovery still measures the directory; the
               pointer is where to look, never permission to assume.
    IS OPT-IN  with the pointer unset, nothing resolves that did not resolve
               before. The corpus is named, never searched for (#527).
    """
    declared = manifest()["run_roots"]
    wrong = [(rel, kind) for rel, kind in _CORPUS_ROUTE_PROBES
             if declared.get(rel, {}).get("kind") != kind]
    assert not wrong, (
        f"the probe drives manifest labels that are gone or have changed kind: "
        f"{wrong}. Re-point _CORPUS_ROUTE_PROBES at one label per "
        f"admissibility kind rather than deleting the coverage")
    assert {kind for _rel, kind in _CORPUS_ROUTE_PROBES} == set(_ADMISSIBILITY), (
        "a new admissibility kind exists and the corpus route is not probed "
        "for it; every kind must be shown to route, or the untested one "
        "silently stops resolving through the pointer")

    run_roots.cache_clear()
    try:
        baseline = set(run_roots())
        with _probe_run_root("d3-corpus-route-") as (corpus, commit):
            # `_has_cells` looks for a published cell, not merely a directory.
            # Both probe labels ARE `ic/<design>/v<version>_<PDK>` cells, so
            # seeding them is what makes this a corpus at all.
            seeded = {rel: _seed_corpus_root(corpus, rel, kind)
                      for rel, kind in _CORPUS_ROUTE_PROBES}
            commit(".")

            # IS OPT-IN — the corpus exists on disk and nothing has been said
            # about it. Discovery must not have found it.
            run_roots.cache_clear()
            assert set(run_roots()) == baseline, (
                "a corpus nobody pointed at changed discovery; it must be "
                "named, never searched for (#527)")

            monkeypatch.setenv(_pc.CORPUS_ENV, str(corpus))

            # ROUTES
            run_roots.cache_clear()
            resolved = run_roots()
            for rel, kind in _CORPUS_ROUTE_PROBES:
                assert rel in resolved, (
                    f"{_pc.CORPUS_ENV} was set to a corpus carrying {rel!r} "
                    f"({kind} kind) and discovery still did not find it — the "
                    f"pointer switches the skip off without switching "
                    f"discovery on, which is the #1703 defect")
                assert resolved[rel].path == seeded[rel], (
                    f"{rel!r} resolved to {resolved[rel].path}, not to the "
                    f"corpus copy at {seeded[rel]}")

            # READS — same pointer, same labels, provenance removed.
            for rel, kind in _CORPUS_ROUTE_PROBES:
                if kind == _IN_REPO_KIND:
                    (seeded[rel] / _RUNNER_MARKERS[0]).unlink()
                else:
                    (seeded[rel] / "reports" / "audit"
                     / "phase23_completion_audit.json").unlink()
            commit(".")
            run_roots.cache_clear()
            still = run_roots()
            leaked = [rel for rel, _kind in _CORPUS_ROUTE_PROBES
                      if rel in still]
            assert not leaked, (
                f"these corpus roots resolved with their own proof of "
                f"provenance deleted: {leaked}. The pointer says WHERE to "
                f"look; the admissibility rule still has to be satisfied "
                f"there, or a corpus is a way around the rule instead of a "
                f"place to apply it")
    finally:
        run_roots.cache_clear()


def test_d3_a_corpus_that_cannot_name_its_own_commit_is_refused(monkeypatch):
    """An offered corpus that is not a checkout must REFUSE, not read empty.

    :func:`tracked_under` returns the empty set for a tree it cannot ask git
    about, and every caller reads that as "not tracked at HEAD — a local build
    product, not evidence". Inside this repository that is correct. For an
    offered corpus it is not: an unpacked tarball, a ``cp -r`` of a clone or a
    docker ``COPY`` of the cells holds published artefacts that ARE tracked
    somewhere, and reading the whole tree as untracked would report every one
    of them NOT PRODUCED.

    That is the same confident wrong answer #1348 measured from the other
    direction — 16 contradictions became 54 when git could not answer inside a
    container — so the door this change opens is closed on it at the seam.
    """
    run_roots.cache_clear()
    try:
        with tempfile.TemporaryDirectory(prefix="d3-corpus-nogit-") as td:
            corpus = Path(td) / "corpus"
            for rel, kind in _CORPUS_ROUTE_PROBES:
                _seed_corpus_root(corpus, rel, kind)
            assert not _claims_to_be_a_checkout(corpus), (
                f"{td} is inside a git work tree, so this probe cannot show "
                f"what a non-checkout corpus does")
            monkeypatch.setenv(_pc.CORPUS_ENV, str(corpus))
            run_roots.cache_clear()
            with pytest.raises(AssertionError, match=_pc.CORPUS_ENV):
                run_roots()
    finally:
        run_roots.cache_clear()


def test_d3_every_admissible_run_root_is_a_real_flow_run():
    """The admissibility rule, re-applied live to every resolved root.

    Each root is re-checked against the predicate for ITS OWN kind, never
    against a union of the predicates. A union would mean every root only has
    to satisfy the loosest rule in the table: a ``repo`` root that stopped
    carrying a runner marker would be carried by the published-cell rule, and a
    ``published`` cell whose verdict went FAIL would be carried by the marker
    rule. Both must still fail, and they do.
    """
    bad = []
    for label, rr in run_roots().items():
        admits = _ADMISSIBILITY.get(rr.kind)
        if admits is None:
            bad.append((label, str(rr.path), f"unknown kind {rr.kind!r}"))
        elif not admits(rr.path):
            bad.append((label, str(rr.path), f"fails the {rr.kind!r} rule"))
    assert not bad, (
        f"these run roots no longer prove their own provenance and must not be "
        f"cited as evidence: {bad}. A {_IN_REPO_KIND!r} root must carry one of "
        f"{list(_RUNNER_MARKERS)}; a {_PUBLISHED_KIND!r} root must be a "
        f"canonical v<version>_<PDK> cell whose "
        f"reports/audit/phase23_completion_audit.json verdict is in "
        f"{list(_bep._CONVERGED)}."
    )


@needs_corpus
def test_d3_waived_steps_still_produce_their_unwaived_entries():
    """A waived cell xfails whatever the reason; this keeps the rest honest.

    ``xfail(strict=True)`` swallows the reason a waived cell failed, so a
    regression in a working entry of a waived step would hide behind the one
    entry the waiver is about. Those entries are asserted here, unwaived —
    today that is M1's ``reports/analog/mixed_signal/merge.json``, which IS
    produced while ``top_merged.gds`` is not.
    """
    problems = []
    for cell in cells_for(DIM):
        sid = cell.step_id
        if waiver_for(sid) is None:
            continue
        rec = step_record(sid)
        unproven = set(rec.get("unproven") or ())
        live = list(F.required_outputs(sid))
        # Drift has to be caught HERE too. A renamed entry disappears from the
        # manifest's key set, and `continue`-ing past it would let a waived
        # step's yaml be edited freely behind the xfail.
        if set(live) != set(rec["entries"]):
            problems.append(
                f"step {sid}: required_outputs drifted from the measured "
                f"manifest: +{sorted(set(live) - set(rec['entries']))} "
                f"-{sorted(set(rec['entries']) - set(live))}"
            )
        for entry in live:
            if entry in unproven or entry not in rec["entries"]:
                continue
            v = check_entry(sid, entry, rec["entries"][entry])
            if not v.produced:
                problems.append(f"step {sid} {entry!r}: {v.detail}")
    assert not problems, (
        "entries of a WAIVED step that are NOT part of its waiver have "
        "regressed:\n  " + "\n  ".join(problems)
    )


def test_d3_waived_unproven_entries_have_no_committed_artefact():
    """Re-execute every waiver's premise against git, on every run (#527).

    Both FPGA waivers used to rest on ``find ~ -maxdepth 10 -name '*.sof'`` ->
    0 hits, measured on one day on one machine. That claim was true when
    written and false a fortnight later — 203 hits, none of them tracked, one
    of them in the user's Trash — and nothing in the repository could notice,
    because the repository was never what the claim was about.

    The premise is now: *no artefact matching this entry is carried by this
    commit*. That is a question git answers in milliseconds, the answer is the
    same for everyone who has the commit, and the day somebody commits a run
    tree containing one, this reddens and the waiver has to be re-argued
    instead of quietly continuing to assert a stale count.

    Checked repo-wide, not merely under the admissible run roots: a run root
    can be added to the manifest later, and the interesting fact is whether
    the artefact exists in the commit AT ALL.
    """
    repo = _plugin_tree.repo_root()
    if repo is None:
        pytest.skip(f"waiver premise needs the repo: {_plugin_tree.NOT_SHIPPED_REASON}")
    tracked = tracked_under(repo)
    assert tracked, (
        f"`git ls-tree -r HEAD` reported no tracked path under {repo}; the "
        f"waiver premises below would then be vacuously true"
    )
    problems = []
    for w in dim_waivers():
        rec = manifest()["steps"].get(F.normalize_id(w.step_id), {})
        unproven = list(rec.get("unproven") or ())
        if not unproven:
            problems.append(f"{w.label}: waived but names no unproven entry")
            continue
        for entry in unproven:
            for alt in F.split_any_of(entry):
                hits = sorted(
                    t for t in tracked
                    if fnmatch.fnmatch(t, alt) or fnmatch.fnmatch(t, f"*/{alt}")
                )
                if hits:
                    problems.append(
                        f"{w.label}: the waiver says {entry!r} has no producer, "
                        f"but this commit tracks {len(hits)} matching artefact(s) "
                        f"({hits[:3]}) — the premise is false and the waiver must "
                        f"be re-argued or removed"
                    )
            # ...and the same question put through the REAL resolver, which is
            # run-root-scoped where the sweep above is repo-wide. The strict
            # xfail only says SOME entry of the cell is unproduced; it does not
            # say the waived one is. Without this a waiver could name an entry
            # that resolves perfectly well while a different entry carried the
            # failure, and the cell would xfail either way.
            erec = rec.get("entries", {}).get(entry)
            if erec is not None and check_entry(w.step_id, entry, erec).produced:
                problems.append(
                    f"{w.label}: {entry!r} is named as the unproven entry but "
                    f"the resolver now finds it — the waiver is about something "
                    f"that no longer needs waiving"
                )
    assert not problems, "\n  ".join(problems)


def test_d3_the_verdict_does_not_depend_on_the_host():
    """Plant a complete fake run tree under $HOME; assert nothing moves (#527).

    This is the property the issue is about, asserted rather than described.
    The planted tree is not a near-miss: it carries a runner marker file, it
    sits at exactly the relative path the manifest records for an
    outside-the-repository run root, and it contains a non-empty artefact for
    every entry any cell declares. Under the pre-#527 resolution ``$HOME`` was
    a search base, so that tree WOULD be discovered and its files WOULD settle
    entries — including the two Quartus outputs whose absence is the entire
    reason step 6 is waived.

    Deterministic on every host, which the bug itself was not: it does not
    depend on what happens to be lying around in the operator's home
    directory, it puts it there.
    """
    repo = _plugin_tree.repo_root()
    if repo is None:
        pytest.skip(f"needs the source tree: {_plugin_tree.NOT_SHIPPED_REASON}")
    outside = [meta["rel"] for meta in manifest()["run_roots"].values()
               if meta["kind"] != _IN_REPO_KIND]
    assert outside, "manifest records no outside-the-repo run root to plant"

    entries = sorted({
        alt
        for cell in cells_for(DIM)
        for entry in F.required_outputs(cell.step_id)
        for alt in F.split_any_of(entry)
    })

    def snapshot():
        run_roots.cache_clear()
        tracked_under.cache_clear()
        return {
            (F.normalize_id(cell.step_id), entry): check_entry(
                cell.step_id, entry, step_record(cell.step_id)["entries"][entry])
            for cell in cells_for(DIM)
            for entry in F.required_outputs(cell.step_id)
            if entry in step_record(cell.step_id)["entries"]
        }, sorted(run_roots())

    before, roots_before = snapshot()
    with tempfile.TemporaryDirectory(prefix="d3_fake_home_") as td:
        for rel in outside:
            root = Path(td) / rel
            root.mkdir(parents=True, exist_ok=True)
            (root / "provenance.jsonl").write_text('{"planted": true}\n')
            (root / "reports" / "orchestrator").mkdir(parents=True, exist_ok=True)
            for pattern in entries:
                # Turn the declared glob into a concrete file: `*` -> "planted".
                target = root / pattern.replace("*", "planted")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("planted evidence that must not count\n")
        planted = sorted(p for rel in outside
                         for p in (Path(td) / rel).rglob("*.sof"))
        assert len(planted) >= len(outside), (
            f"only {len(planted)} bitstream(s) planted across {len(outside)} "
            f"fake run roots; the probe would be inert")

        old_home = os.environ.get("HOME")
        try:
            os.environ["HOME"] = td
            assert Path.home() == Path(td), "HOME redirection did not take"
            after, roots_after = snapshot()
        finally:
            if old_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = old_home

    moved = sorted(
        f"{sid}::{entry}: {before[k].produced}/{before[k].mode} -> "
        f"{after[k].produced}/{after[k].mode}"
        for k in before
        for sid, entry in [k]
        if (before[k].produced, before[k].mode) != (after[k].produced, after[k].mode)
    )
    restored, roots_restored = snapshot()
    assert roots_after == roots_before, (
        f"redirecting $HOME changed which run roots are admissible: "
        f"{roots_before} -> {roots_after}. A tree outside the repository is "
        f"not evidence about a flow step (#527)."
    )
    assert not moved, (
        f"{len(moved)} entry verdict(s) moved when a fake run tree was planted "
        f"under $HOME:\n  " + "\n  ".join(moved[:12])
    )
    # Round trip: the planted tree is gone and $HOME is back, so the third
    # reading must equal the first. A mismatch here would mean the test left
    # state behind and the "nothing moved" above compared two dirty snapshots.
    assert roots_restored == roots_before, "run-root discovery did not restore"
    assert {k: (v.produced, v.mode) for k, v in restored.items()} == \
           {k: (v.produced, v.mode) for k, v in before.items()}, \
        "verdicts did not return to their pre-plant values"


def test_d3_waivers_meet_the_registry_bar():
    """This dimension's waivers are validated by the shared validator, not by hope."""
    problems = []
    assert dim_waivers(), "dimension 3 declares no waiver at all"
    for w in dim_waivers():
        for p in waivers.validate(w):
            problems.append(f"{w.label}: {p}")
        rec = manifest()["steps"].get(F.normalize_id(w.step_id), {})
        if rec.get("verdict") != "WAIVED":
            problems.append(
                f"{w.label}: waived here but the manifest records verdict "
                f"{rec.get('verdict')!r}"
            )
        if not rec.get("unproven"):
            problems.append(f"{w.label}: waived but no unproven entry recorded")
    assert not problems, "\n".join(problems)


def test_d3_cell_states_partition_all_steps():
    """ENFORCED + WAIVED + NA == 68, computed live, with no cell in two states."""
    enforced, waived, na = [], [], []
    for cell in cells_for(DIM):
        sid = cell.step_id
        rec = step_record(sid)
        w = waiver_for(sid)
        if rec["verdict"].startswith("NA_"):
            na.append(sid)
            assert w is None, f"step {sid} is both NA and waived"
        elif w is not None:
            waived.append(sid)
            assert rec["verdict"] == "WAIVED"
        else:
            enforced.append(sid)
            assert rec["verdict"] == "ENFORCED"
    # 69 -> 68: step `37.5self` (General Precheck) is RETIRED, and the census
    # goes back DOWN. The owner's 2026-08-20 decision: the general precheck was
    # never a third ROUTE, it is a second ARM of `37.5ic` — our ladder runs on
    # every design that reaches that step, and the operator's container runs IN
    # ADDITION wherever the PDK ships a precheck and its template was fetched.
    # A PDK with no shuttle precheck is the same step with one fewer arm, not a
    # different route. Re-stated by hand, as the census comments here require:
    # a step LEAVING must force a human to say the number just as loudly as one
    # arriving. RE-DERIVED from the live yaml, never decremented by hand.
    # 2026-08-21, 68 -> 69: step 1.6x. The note above is CORRECT about its own
    # change and wrong about the base it applied it to. Measured by driving
    # `flowref` at each revision's yaml through
    # `VIBE_IC_MATRIX_FLOW_YAML`, the matrix population is:
    #
    #     ff5071caa (this pin last set)   68   no 1.6x, no 37.5self
    #     7fcbc7397~1                     69   no 1.6x, 37.5self PRESENT
    #     7fcbc7397 (adds 1.6x)           70
    #     867de4289 (retires 37.5self)    69
    #
    # So the population moved THREE times across three commits, not once: 37.5self
    # arrived after this pin was set and was never credited, 1.6x arrived and was
    # never credited, and only the removal was. Subtracting one from a base that
    # was already two behind is how a hand-moved census drifts while every
    # individual edit to it looks careful.
    assert len(enforced) + len(waived) + len(na) == 68, (
        f"enforced={len(enforced)} waived={len(waived)} na={len(na)}"
    )
    # The waived set must equal the registry exactly. This used to union the
    # registry with a module-local mirror; the `or` between them meant a stale
    # entry in either could hide the other, which is how A8's two copies came
    # to tell different stories (see the Waivers section above). One registry,
    # one comparison.
    declared = {F.normalize_id(w.step_id) for w in dim_waivers()}
    assert {F.normalize_id(s) for s in waived} == declared, (
        f"waived cells {sorted(F.normalize_id(s) for s in waived)} do not match "
        f"the registered waivers {sorted(declared)}"
    )
    assert (len(enforced), len(waived), len(na)) == (51, 2, 15), (
        f"the ENFORCED/WAIVED/NA split changed to "
        f"({len(enforced)}, {len(waived)}, {len(na)}); it was measured as "
        f"(51, 2, 15) after folding 1.6x into Step 2. A step moving between states "
        f"is a real "
        f"change in what dimension {DIM} enforces and must be re-reviewed, not "
        f"absorbed.\n"
        f"2026-07-28: a convergence pass proposed (53, 1, 9) — A8 ENFORCED on "
        f"a new producer, steps 6/39 NA_TOOLCHAIN_ABSENT. Both were measured "
        f"and reverted, leaving (52, 4, 7). A8's evidence needed Magic in an "
        f"EDA container that CI does not have, and the 6/39 NA's own "
        f"self-invalidating assertion fires on a host that HAS Quartus. "
        f"Neither survived the host-independence rule (#527).\n"
        f"2026-08-06: (52, 4, 7) -> (53, 3, 7) — A8 alone moved, from WAIVED "
        f"to ENFORCED, and NOT on the 2026-07-28 argument. Commit b1665ec8 "
        f"published benchmark-data/ic/u_hawaii_adc/v1.9.86_sky130A/phase3/"
        f"analog/hardmacro/{{delta_sigma,ldo}}/*.gds, so A8's waiver premise "
        f"('git ls-tree -r --name-only HEAD matches ZERO paths') became false "
        f"and its own stated closing condition ('a published analog run whose "
        f"A8 actually streamed the layout') was met. No container is needed to "
        f"read a committed artefact, so the cell is host-independent in the "
        f"direction #527 requires. Steps 6/39 and M1 are unchanged and still "
        f"waived."
        "\n2026-08-12: (53, 3, 7) -> (50, 3, 10). M2, M3 and M4 moved "
        "ENFORCED -> NA together, on one cause: all four mixed-signal steps "
        "share the condition `phase1/analog/analog_block_list.json`, which "
        "occurs ZERO times in `git ls-tree -r HEAD` over the whole "
        "repository. They have never run here, so there is no run to "
        "publish and `UNEVIDENCED` was the wrong reading. M1 keeps its "
        "waiver (a different entry) and stays in the waived count."
        "\n2026-08-12 (same change): (50, 3, 10) -> (50, 2, 11). M1 joined "
        "them, from WAIVED to NA. Its dimension-3 waiver said 'no admissible "
        "run root is a mixed-signal project, so the producer returns its "
        "documented rc=2 inputs-missing skip everywhere it can run' — which is "
        "dormancy described one artefact at a time, and it covered only ONE of "
        "M1's two entries, which is why "
        "test_d3_waived_steps_still_produce_their_unwaived_entries was red on "
        "merge.json. A per-entry waiver cannot express 'this step never ran'. "
        "M1's dimension-7 waiver is untouched."
        "\n2026-08-20: (50, 2, 11) -> (54, 2, 11). Four steps were ADDED to the "
        "flow; none moved between states. 15.5ic, 26.5ic, 37.5ip and 37.5ic are "
        "the path-specific steps of the cell/IP-vs-chip/IC split. Each declares "
        "required_outputs, carries no step-level condition (so "
        "NA_DORMANT_CONDITION is not derivable for it) and holds no waiver, "
        "which is what ENFORCED means here. Every entry is recorded UNPROVEN: "
        "their producer programs are not written yet, so no admissible run root "
        "has ever produced these paths. The four cells are RED, and that is the "
        "honest reading of a flow declaring an output nothing produces \u2014 not "
        "a state to waive away."
        "\n2026-08-20 (later the same day, R6): (54, 2, 11) -> (51, 2, 15), "
        "and note the first triple sums to 67 while this one sums to 68 \u2014 "
        "it was written before step 0.5ic existed. TWO independent movements, "
        "both from vibe-ic#1744:"
        "\n  (a) +1 step. 0.5ic (Submission Template Ingest) was added. It "
        "declares required_outputs, carries no step-level condition and holds "
        "no waiver, so it lands ENFORCED: 54 -> 55 before (b)."
        "\n  (b) -4 ENFORCED, +4 NA. 15.5ic, 26.5ic, 37.5ip and 37.5ic each "
        "GAINED a step-level `condition` in the same change \u2014 "
        "`files_exist: [input/submission_template/slots/*.yaml]` on 15.5ic, "
        "26.5ic and 37.5ic, `files_exist: "
        "[input/submission_template/NO_TEMPLATE.txt]` on 37.5ip \u2014 each "
        "with `condition_kind: design_dependent`. The sentence three "
        "paragraphs up, 'carries no step-level condition (so "
        "NA_DORMANT_CONDITION is not derivable for it)', is therefore FALSE "
        "against the yaml in this same tree, and is kept above only as the "
        "record of what was true that morning. 55 - 4 = 51 ENFORCED, "
        "11 + 4 = 15 NA."
        "\nWHAT THIS COST, STATED PLAINLY: four cells that were RED \u2014 "
        "'a flow declaring an output nothing produces' \u2014 are now NOT "
        "JUDGED. Nothing about their producers changed; only the reading did. "
        "The dormancy is not self-asserted, though: the NA is guarded live by "
        "test_d3_required_outputs_are_produced, which re-reads the yaml for the "
        "condition and re-checks every run root for the condition file, so the "
        "day any project ships input/submission_template/ the NA "
        "self-invalidates and the four cells return to the denominator."
        "\nv1.11.5: (51, 2, 15) -> (51, 2, 16), and this one is +1 STEP with "
        "NO reclassification \u2014 the triple sums 68 -> 69. 37.5self "
        "(General Precheck \u2014 the tape-out check for a design with NO "
        "operator) was added: the chip/IC route for a design that has no "
        "shuttle operator to refuse it, which until this step passed no "
        "submission check of any kind. It arrives NA rather than ENFORCED for "
        "exactly the reason its three siblings did, and the reading is "
        "re-derived live rather than declared: `condition: {files_exist: "
        "[input/submission_template/SELF_TAPEOUT.txt]}` with `condition_kind: "
        "design_dependent`, and no admissible run root carries that marker. "
        "ENFORCED is unmoved at 51, WAIVED unmoved at 2, NA 15 -> 16. Publish "
        "a run tree carrying SELF_TAPEOUT.txt and this NA self-invalidates "
        "through the same live guard, the cell returns to the denominator, "
        "and this pin reddens naming it."
        "\nsmrg/retire-37p5self: (51, 2, 16) -> (51, 2, 15), and it is the "
        "MIRROR of the entry directly above \u2014 the same step, leaving. The "
        "triple sums 69 -> 68. `37.5self` is RETIRED: the general precheck was "
        "never a third ROUTE out of stage 4, it is a second ARM of 37.5ic, "
        "which now runs our ladder on every design that reaches it and the "
        "operator's container IN ADDITION wherever the PDK ships a precheck and "
        "its template was fetched."
        "\nWHICH CELL MOVED, AND IN WHAT STATE: `37.5self/d3`, and it was NA, "
        "not ENFORCED \u2014 exactly the state the entry above records it "
        "entering the grid in. So this is -1 STEP with NO reclassification, the "
        "mirror image of that +1: ENFORCED unmoved at 51, WAIVED unmoved at 2, "
        "NA 16 -> 15. NOTHING ELSE MOVED, and that is MEASURED rather than "
        "assumed: the live not-ENFORCED inventory was diffed against the pinned "
        "one on this tree and the ONLY difference is `37.5self/d3` "
        "(`matrix_mutation_ledger.LEDGER_CELLS_NOT_ENFORCED`, moved in this "
        "same change). A step removal that had silently reclassified a "
        "neighbouring cell would appear there as a second difference; there is "
        "none."
        "\nWHY THIS IS A STALE PIN AND NOT A BROKEN DERIVATION: everything "
        "above this assertion is recomputed live \u2014 `cells_for(DIM)` reads "
        "the yaml, `step_record` reads the manifest, `waiver_for` reads the "
        "registry \u2014 and all three handled a 68-step flow with no change at "
        "all. Only the hand-restated TRIPLE is a number a human must move, "
        "which is exactly what it is for: a step LEAVING has to force someone "
        "to say the number as loudly as one arriving."
        "\n2026-08-21: (51, 2, 15) -> (52, 2, 15). +1 ENFORCED, no "
        "reclassification, and it is step 1.6x \u2014 the cross-layer "
        "rewrite-fidelity relation, added by `7fcbc7397` FIVE COMMITS BEFORE "
        "the entry above. It lands ENFORCED on the same three live reads its "
        "siblings were classified by: `step_condition('1.6x')` is None, it "
        "declares one required_output "
        "(`reports/crosslayer/rewrite_equivalence_check.json`), and it holds no "
        "dimension-3 waiver. Its unconditionality is deliberate and recorded in "
        "its own yaml comment: a `files_exist` condition was tried first and "
        "refused by `flow_condition_reachability_check` as 'a check disabled by "
        "exactly the situation it was written for'. WAIVED and NA unmoved."
        "\nTHE ENTRY ABOVE IS CORRECT ABOUT ITS OWN CHANGE AND WRONG ABOUT THE "
        "BASE IT APPLIED IT TO, which is the part worth keeping. It moved the "
        "triple 69 -> 68 for a step LEAVING, from a base that had never been "
        "credited with this step ARRIVING. MEASURED, by driving `flowref` at "
        "each revision's yaml through `VIBE_IC_MATRIX_FLOW_YAML` and counting "
        "`step_ids()`: ff5071caa 68, 7fcbc7397~1 69, 7fcbc7397 70, 867de4289 "
        "69. The population moved THREE times across three commits and only the "
        "third was written down \u2014 so 'a human must move it' is the "
        "mechanism AND, twice running, the failure."
    )


@needs_corpus
def test_d3_evidence_is_live_wherever_the_run_root_exists():
    """No entry may read FIXTURE while its run root IS present.

    Since 2026-08-06 a FIXTURE entry is a FAILURE, not a green, so this test no
    longer guards against a hollow pass — it guards against a false RED and
    against a silent collapse of discovery. If a recorded run root resolves and
    the entry still reads FIXTURE, the resolver has stopped looking, and a
    module that reported every entry unevidenced because ``run_roots()`` broke
    would be just as wrong as one that reported every entry produced.  Root
    discovery is pinned against the corpus the caller actually offered; a
    count measured before the corpus split cannot honestly be called
    host-independent once two corpus commits may carry different cells.
    """
    resolved = run_roots()
    wrong = []
    live = fixture = 0
    for cell in cells_for(DIM):
        sid = cell.step_id
        rec = step_record(sid)
        for entry, erec in rec["entries"].items():
            if entry not in F.required_outputs(sid):
                continue
            v = check_entry(sid, entry, erec)
            if v.mode == LIVE:
                live += 1
                continue
            fixture += 1
            root = erec.get("run") or erec.get("base_run")
            if root in resolved:
                wrong.append(
                    f"step {sid} {entry!r}: run root {root!r} resolves at "
                    f"{resolved[root].path} yet the verdict is fixture-attested"
                )
    assert not wrong, "\n  ".join(wrong)
    expected_roots = set()
    repo = _plugin_tree.repo_root()
    offered = _offered_corpus()
    for label, meta in manifest()["run_roots"].items():
        admits = _ADMISSIBILITY.get(meta["kind"])
        if admits is None:
            continue
        candidates = []
        if repo is not None:
            candidates.append(repo / meta["rel"])
        if offered is not None:
            candidate = _corpus_candidate(meta["rel"], offered)
            if candidate is not None:
                candidates.append(candidate)
        if any(p.is_dir() and admits(p) for p in candidates):
            expected_roots.add(label)
    assert set(resolved) == expected_roots, (
        f"run-root discovery disagrees with the repo/corpus actually offered: "
        f"resolved={sorted(resolved)}, independently admissible="
        f"{sorted(expected_roots)}; live={live}, fixture={fixture}"
    )


def test_d3_fixture_attested_cells_are_named_cell_by_cell():
    """Say WHICH cells are decided by the committed manifest instead of the tree.

    2026-07-27, adversarial finding (MEDIUM), accepted: ``check_entry`` falls
    back to the committed manifest whenever a recorded run root does not
    resolve, and 5 of the 12 recorded roots live OUTSIDE the repo, so 19 of the
    126 entries are fixture-attested and SEVEN steps (17, 20, 29, 30, M2, M3,
    M4) have 100% of their entries decided by the committed JSON. Those seven
    cells are labelled ENFORCED while being unfalsifiable from the repository.

    #527 turned that from a *degraded* mode into the only mode: those external
    trees are no longer consulted on any host, so the seven cells were
    fixture-attested everywhere — worse in absolute terms, and honest, where
    before they were live on exactly one machine and fixture on every other.

    2026-08-06 finished the sentence #527 started. Recording the soft spot was
    never a substitute for reporting it: a cell decided by the committed JSON
    was still GREEN, so the pin below said "these seven are unfalsifiable" while
    the cells themselves said "produced". ``check_entry`` now returns
    ``produced=False`` for an entry no admissible run root can evidence, so the
    seven are RED and answer live the moment a run tree carrying their artefact
    is committed. This test's job is unchanged and still needed: the artefacts
    genuinely are not in the repository, and the POPULATION must not grow
    quietly, so the set stays pinned and a cell joining it reddens here as
    well as in its own cell.
    """
    manifest()  # populates _IN_REPO_RUN_ROOTS from the manifest's own `kind`
    assert _IN_REPO_RUN_ROOTS, "manifest declares no in-repo run root"
    assert set(_EXTERNAL_RUN_ROOTS_AS_MEASURED) == (
        set(manifest()["run_roots"]) - set(_IN_REPO_RUN_ROOTS)), (
        f"the manifest's external run-root set changed: measured "
        f"{sorted(set(manifest()['run_roots']) - set(_IN_REPO_RUN_ROOTS))!r}, "
        f"pinned {list(_EXTERNAL_RUN_ROOTS_AS_MEASURED)!r}"
    )
    external: Dict[str, int] = {}
    per_step_total: Dict[str, int] = {}
    for cell in cells_for(DIM):
        sid = cell.step_id
        key = F.normalize_id(sid)
        rec = step_record(sid)
        for entry, erec in rec["entries"].items():
            if entry not in F.required_outputs(sid):
                continue
            per_step_total[key] = per_step_total.get(key, 0) + 1
            root = erec.get("run") or erec.get("base_run")
            if root and root not in _IN_REPO_RUN_ROOTS:
                external[key] = external.get(key, 0) + 1

    fully_external = tuple(sorted(
        k for k, n in external.items() if n == per_step_total.get(k)))
    assert fully_external == EXTERNALLY_ATTESTED_STEPS, (
        f"the set of dimension-3 cells whose every entry is evidenced ONLY by "
        f"a run tree outside this repository changed: measured "
        f"{fully_external!r}, pinned {EXTERNALLY_ATTESTED_STEPS!r}. Those "
        f"cells go green on the committed manifest — not on the repository — "
        f"on any host that cannot see the external trees, so the population "
        f"must not grow silently. Newly external: "
        f"{sorted(set(fully_external) - set(EXTERNALLY_ATTESTED_STEPS))}."
    )
    # #527 — and no external tree may resolve, on ANY host. Before the fix
    # this branch read "if the campaign host CAN see them, none may be
    # degraded", which is the same sentence as "this suite measures something
    # different here than it does in CI". Externally-recorded roots are now
    # unreachable by construction, so the fixture attestation for those cells
    # is uniform rather than conditional.
    resolved = run_roots()
    leaked = sorted(r for r in _EXTERNAL_RUN_ROOTS_AS_MEASURED if r in resolved)
    assert not leaked, (
        f"run roots recorded OUTSIDE this repository resolved anyway: "
        f"{leaked} at {[str(resolved[r].path) for r in leaked]}. Evidence from "
        f"a tree the commit does not carry makes this dimension's answer "
        f"depend on the machine (#527)."
    )
    # ...and no root may resolve anywhere except the two trees a reader can
    # NAME: this repository, or the corpus the operator explicitly pointed at.
    #
    # vibe-ic#1703 — the second alternative is new and it is the whole of what
    # changed. It is not a re-opening of the $HOME search #527 removed, and the
    # difference is the one that mattered there: an operator-named corpus is
    # DECLARED (``VIBE_IC_BENCHMARK_DATA``, refused when it names nothing —
    # ``_published_corpus.corpus_root``), whereas the trees #527 removed were
    # DISCOVERED, so a cell's colour turned on what happened to be lying around
    # on the machine. Nothing is searched for here, and with the pointer unset
    # this assertion is exactly what it was.
    permitted = [p for p in (_plugin_tree.repo_root(), _offered_corpus())
                 if p is not None]
    outside = sorted(
        f"{label} -> {rr.path}" for label, rr in resolved.items()
        if permitted
        and not any(base.resolve() in rr.path.resolve().parents
                    for base in permitted)
    )
    assert not outside, (
        f"these admissible run roots are in neither the repository nor the "
        f"corpus named by {_pc.CORPUS_ENV}: {outside}. Permitted trees: "
        f"{[str(p) for p in permitted]}"
    )


def test_d3_no_record_cites_an_absent_run_this_commit_can_answer():
    """vibe-ic#1266 — a record may not name a tree nobody has when the COMMIT
    evidences the entry.

    THE HOLE THIS CLOSES. ``check_entry``'s absent-root branch does not stop at
    the recorded root: when the recorded run is not on this checkout it asks
    :func:`resolve_anywhere`, and a hit there returns ``produced=True``. That
    fall-through is right — a cell must not go red because the manifest happens
    to name the wrong tree — but it made the citation itself unfalsifiable.
    Five entries were green that way, and the only provenance a reader of the
    fixture had for them was a directory on one machine:

      * step 11's four DFT entries cited ``AI_IC_design/4th_benchmark/ibex_e2e``
        and ``campaign_pdk/spm/_aborted_tmpplugin_run`` — the second of those
        naming a run whose own label says it ABORTED, i.e. the record asserted
        production by a run that did not finish;
      * step 29's post-layout sim entry cited
        ``AI_IC_design/4th_benchmark/cv32e40p_e2e``.

    All five were answered, on every host, by an admissible in-repo root. The
    manifest is the only place a reader can look up WHERE an artefact came
    from, so a citation that no checkout can follow is not a smaller version of
    a provenance — it is a provenance-shaped blank, and #1266 is the issue
    filed because nineteen of them accumulated unnoticed.

    THE DIRECTION THIS RUNS IN, stated because a guard that could green a cell
    would be the wrong tool here. It fires ONLY where ``resolve_anywhere``
    already returns a hit, so it can never turn a red cell green and can never
    manufacture evidence: it demands that a record which is *already* being
    answered by the commit SAY SO. Entries nothing resolves — the six cells
    #1266 leaves to the owner (15, 17, 19, 20, 30, 32) — are untouched by it,
    which is deliberate: those citations cannot be repaired by a fact and
    pretending otherwise is exactly the move that issue refuses.

    The remedy is the one ``check_entry`` already prints in its sibling branch
    for a root that IS present and has gone stale ("Re-point the record at
    ..."). This makes the same repair mandatory in the case where the root is
    absent, which is the case that was silent.
    """
    stale = []
    for cell in cells_for(DIM):
        sid = cell.step_id
        rec = step_record(sid)
        if rec["verdict"].startswith("NA_"):
            continue
        for entry, erec in rec["entries"].items():
            if entry not in F.required_outputs(sid):
                continue
            label = erec.get("run") or erec.get("base_run")
            if not label or label in run_roots():
                continue
            # Ledger-bound, exactly as the verdict binds it: a root whose own
            # write ledger refuses this step is not an answer, so this guard
            # never demands a re-point onto evidence the verdict would reject.
            hit, _rejected = resolve_anywhere(entry, sid)
            if hit is not None:
                stale.append(
                    f"step {sid} {entry!r}: recorded against {label!r}, which "
                    f"this repository does not carry, while the admissible "
                    f"root {hit.root!r} evidences it at {hit.path} "
                    f"({hit.size_bytes} B)"
                )
    assert not stale, (
        f"{len(stale)} manifest record(s) cite a run root no checkout carries "
        f"while THIS COMMIT answers the entry:\n  "
        + "\n  ".join(stale)
        + "\nRe-point each record at the root named above and re-measure its "
          "`path` and `size_bytes` there. The cell is green either way — that "
          "is the point: the verdict falls through to a search, so the wrong "
          "citation costs nothing at verdict time and stays wrong forever. "
          "The manifest is the only record of WHERE an artefact came from, and "
          "a citation a reader cannot follow is not evidence of anything "
          "(vibe-ic#1266)."
    )


@dataclass(frozen=True)
class _Cell:
    """The one attribute the cell test reads, so the guards below can call it
    directly instead of going through the parametrisation."""
    step_id: str


def _synthetic_citation_world(monkeypatch, entries: Dict[str, Dict]) -> str:
    """Drive the cell predicate over a manifest written HERE, corpus absent.

    The population this guard is about is expected to shrink as records are
    repaired, and a guard pinned to today's records would go vacuous the moment
    it did — passing loudest exactly when it has stopped checking anything. So
    the substrate is synthesised: two run roots, one of a kind this module
    searches and one of a kind it never will, and whichever entries the caller
    wants recorded against them. Returns the synthetic step id.
    """
    sid = "SYNTHETIC"
    searched, never = "root-this-module-searches", "root-on-one-machine-only"
    monkeypatch.setattr(sys.modules[__name__], "manifest", lambda: {
        "run_roots": {
            searched: {"kind": _IN_REPO_KIND, "rel": "benchmark-data/probe"},
            never: {"kind": "home", "rel": "somewhere/off/this/repository"},
        },
        "steps": {},
    })
    monkeypatch.setattr(sys.modules[__name__], "step_record",
                        lambda _sid: {"verdict": "ENFORCED", "entries": entries})
    monkeypatch.setattr(F, "required_outputs", lambda _sid: tuple(entries))
    monkeypatch.setattr(F, "step_name", lambda _sid: "synthetic step")
    # The corpus-absent world is FORCED, not inherited from the host: with a
    # clone present the cell would never reach the skip branch at all and this
    # guard would pass without exercising the thing it is named for.
    monkeypatch.setattr(sys.modules[__name__], "run_roots", lambda: {})
    monkeypatch.setattr(sys.modules[__name__], "corpus_root", lambda: None)
    return sid


def _cite(root: str, path: str) -> Dict:
    return {"status": "PRODUCED_BY_RUN", "run": root, "alternative": path,
            "path": path, "size_bytes": 1}


def test_d3_a_citation_no_corpus_can_answer_is_not_dropped_by_the_corpus_skip(
        monkeypatch):
    """vibe-ic#1266 — THE CARVE-OUT, both ways, end to end.

    WHAT WENT WRONG. When the result cells moved to their own repository this
    cell test gained a corpus-absent skip, and the skip is right for what it was
    written for: an entry whose recorded run root is one this module searches
    lives in the corpus now, so reporting it "NOT produced" here would charge
    the flow with a defect whose evidence is simply in another repository.

    It was applied to the whole cell. Entries recording a root of a kind this
    module searches on NO host went with it — and those are not waiting on the
    pointer. #527 removed every off-repository search from this dimension, and
    the published corpus does not carry those trees either, so the pointer moves
    them not at all. Measured on a fresh checkout of this commit before the
    carve-out: the dimension reported no failure at all while seven such
    citations across six cells went unexamined, which is a clean run over a
    population nobody looked at — the silent-omission shape this repository
    exists to refuse.

    BOTH DIRECTIONS, because a carve-out that fires on everything is not a
    carve-out and would simply have deleted the skip:

    * a record citing a root this module SEARCHES still SKIPS. This is the one
      that fails if the fix over-fires, and it is why the skip's own rationale
      survives intact.
    * a record citing a root it never searches REFUSES, naming the path the
      record wanted. This is the one that fails if the fix is reverted.

    Both run against a manifest synthesised in the test, so neither direction
    can go vacuous when the real records are repaired — which is the whole
    intent of #1266.
    """
    SEARCHED, NEVER = "root-this-module-searches", "root-on-one-machine-only"
    ANSWERABLE = "phase3/stage3/probe/answerable.json"
    UNANSWERABLE = "phase3/stage3/probe/unanswerable.json"

    # ---- the predicate itself, on a record carrying one of each -------
    sid = _synthetic_citation_world(monkeypatch, {
        ANSWERABLE: _cite(SEARCHED, ANSWERABLE),
        UNANSWERABLE: _cite(NEVER, UNANSWERABLE),
    })
    cites = unanswerable_citations(sid)
    assert [c[0] for c in cites] == [UNANSWERABLE], (
        f"the predicate must select exactly the citation no corpus can answer, "
        f"and it selected {[c[0] for c in cites]}. Selecting the answerable one "
        f"too would turn the corpus skip off wholesale and report the moved "
        f"cells as a flow defect; selecting neither is the omission this guard "
        f"exists for.")
    assert cites[0][1] == NEVER and cites[0][2] == UNANSWERABLE, (
        f"the finding must carry the root it wanted and the path it wanted, or "
        f"nobody can act on it: {cites[0]}")

    # ---- REVERSE: only answerable citations, the skip is untouched ----
    sid = _synthetic_citation_world(monkeypatch,
                                    {ANSWERABLE: _cite(SEARCHED, ANSWERABLE)})
    assert unanswerable_citations(sid) == ()
    with pytest.raises(pytest.skip.Exception) as skipped:
        test_d3_required_outputs_are_produced(_Cell(sid))
    assert str(skipped.value) == SKIP_REASON, (
        f"a cell whose every citation the corpus could answer must still skip "
        f"with the corpus reason, not refuse: {skipped.value}")

    # ---- FORWARD: the unanswerable citation is NOT_MEASURED, by name ----
    #
    # THIS ARM CHANGED SHAPE ON 2026-08-21 AND GOT STRICTER, not looser. It used
    # to require the cell to REFUSE — raise — because a skip was the only other
    # option and a skip meant the entry left the denominator in silence. That
    # reasoning was right while the grid had three states. The owner's ruling
    # gave it a fourth, so silence is no longer what a skip means HERE: the cell
    # reports NOT_MEASURED on the configuration axis, carrying a REQUIRED reason
    # that names the citation, counting as nothing in every enforcement figure,
    # and self-invalidating when the record resolves.
    #
    # So the arm now demands MORE than it did. A bare skip — the old silent
    # shape, with the plain corpus reason — still fails it. A pass still fails
    # it. And on top of both, the state must say NOT_MEASURED and the reason
    # must name the path and the root, which the refusal version never checked
    # from the state axis at all.
    sid = _synthetic_citation_world(monkeypatch, {
        ANSWERABLE: _cite(SEARCHED, ANSWERABLE),
        UNANSWERABLE: _cite(NEVER, UNANSWERABLE),
    })
    # `matrix_cell_state` is not callable on a SYNTHETIC step — its NA leg looks
    # the id up in the yaml — so the driver is asserted directly. It is the only
    # input to the NOT_MEASURED branch of the state function, so this is the
    # same claim reached one call earlier.
    msg = matrix_not_measured_reason(sid)
    assert msg is not None, (
        f"a cell recording {UNANSWERABLE!r} against run root {NEVER!r} — which "
        f"this module searches on no host — is not NOT_MEASURED. It cannot be "
        f"ENFORCED (nothing looked), and it must not be swept into the corpus "
        f"skip as though the pointer could settle it. vibe-ic#1266.")
    try:
        test_d3_required_outputs_are_produced(_Cell(sid))
    except pytest.skip.Exception as skipped:
        # `Skipped` IS the exception here, not a `pytest.raises` ExceptionInfo,
        # so the message is on `.msg` — `.value` is an AttributeError and would
        # turn this guard into an error instead of a verdict.
        reason = getattr(skipped, "msg", None) or str(skipped)
        assert reason != SKIP_REASON, (
            f"the cell skipped with the plain CORPUS reason over a citation no "
            f"corpus can answer. That reason is not true of it, and the entry "
            f"left the denominator in silence — the exact vibe-ic#1266 defect.")
        assert "NOT_MEASURED" in reason, (
            f"the skip does not say NOT_MEASURED, so a reader cannot tell it "
            f"from the corpus skip: {reason}")
    except AssertionError:
        raise
    else:
        raise AssertionError(
            f"the cell PASSED over a citation no corpus can answer "
            f"({UNANSWERABLE!r} from {NEVER!r}) — a clean run over a "
            f"population nothing looked at."
        )
    for want in (UNANSWERABLE, NEVER):
        assert want in msg, (
            f"the NOT_MEASURED reason must name the path and the root the "
            f"record wanted; {want!r} is missing from:\n{msg}")
    assert ANSWERABLE not in msg, (
        f"the reason named an entry the corpus CAN answer, so it is reporting "
        f"the moved cells as unmeasured rather than carving out the citations "
        f"nothing can settle:\n{msg}")


def test_d3_the_corpus_skip_covers_exactly_the_cells_it_can_explain():
    """The same property over the REAL manifest, as a property not a pin.

    :func:`unanswerable_citations` decides from the RECORD and the cell decides
    from the record plus the tree, so the two could drift apart without either
    being obviously wrong. This asserts they cannot: over every live cell, a
    non-empty finding and a refusal-instead-of-skip are the same set.

    Deliberately not a pinned population. A count would have to be edited every
    time a record is repaired, and #1266's whole direction of travel is that
    the population shrinks — nineteen when it was filed, seven on this commit.
    A property neither goes stale as they are repaired nor goes vacuous if they
    all are.
    """
    disagree = []
    for cell in cells_for(DIM):
        sid = cell.step_id
        if step_record(sid)["verdict"].startswith("NA_"):
            continue
        cites = unanswerable_citations(sid)
        if cites:
            # The message must be constructible and must name every path it
            # found, or the refusal degrades to a bare count.
            msg = _corpus_skip_would_hide(sid, cites)
            for _entry, label, wanted in cites:
                if wanted not in msg or label not in msg:
                    disagree.append(
                        f"step {sid}: the NOT DETERMINED message drops "
                        f"{wanted!r} from {label!r}")
        if run_roots() or corpus_root() is not None:
            # The skip branch is not reached here, so there is nothing to
            # cross-check against; the predicate half above still ran.
            continue
        # 2026-08-21: the cell now CARRIES the unanswerable citation as
        # NOT_MEASURED instead of refusing over it, so the cross-check compares
        # the predicate against that state rather than against a raise. The
        # property is unchanged and the failure mode it guards is unchanged: a
        # cell with an unanswerable citation must not be covered by the plain
        # corpus skip, because that reason is not true of it.
        try:
            test_d3_required_outputs_are_produced(_Cell(sid))
        except ProducerRegression:
            # The SOURCE arm fired: this cell is red because the WRITER of one
            # of its declared outputs is gone from the tree. That is not a
            # question about the corpus, so this cross-check -- whose whole
            # subject is whether the corpus skip can explain a cell -- has no
            # claim to make about it. Nothing is excused: the cell is already
            # red and names the path and the producer.
            continue
        except pytest.skip.Exception as skipped:
            carried = "NOT_MEASURED" in (
                getattr(skipped, "msg", None) or str(skipped))
        except AssertionError:
            carried = True          # a refusal also does not hide the entry
        else:
            carried = False
        if carried != bool(cites):
            disagree.append(
                f"step {sid}: unanswerable_citations() found {len(cites)} but "
                f"the cell "
                f"{'carried it as NOT_MEASURED' if carried else 'did not'} — "
                f"the predicate and the cell disagree about whether the corpus "
                f"skip can explain this cell")
    assert not disagree, (
        f"{len(disagree)} disagreement(s) between the citations no corpus can "
        f"answer and the cells that refuse for them:\n  " + "\n  ".join(disagree)
    )


@contextlib.contextmanager
def _probe_run_root(prefix: str):
    """A throwaway GIT REPOSITORY standing in for an in-repo run root.

    The probes below used to build a plain directory in ``/tmp``. Once
    trackedness became part of admissibility (#527) a plain directory can
    prove only half of each rule — it can show a bad match is refused, never
    that a good one is accepted — so the probe is a real repository and
    ``commit()`` is what moves a file from "exists here" to "the commit
    carries it". That also makes the trackedness rule itself exercisable
    against the same substrate as the zero-byte and symlink rules.

    Yields ``(root, commit)``. ``commit(*rels)`` stages those exact paths —
    never ``-A``, so what is tracked is always stated — and clears the
    trackedness cache so the next ``resolve`` sees the new commit.
    """
    with tempfile.TemporaryDirectory(prefix=prefix) as td:
        root = Path(td) / "probe"
        root.mkdir()
        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull,
               "GIT_CONFIG_SYSTEM": os.devnull}
        subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=env,
                       capture_output=True)
        # Auto-gc DETACHES (`gc.autoDetach` defaults on), so a commit here can
        # leave a `git gc` running after this helper returns. It writes into
        # `.git/objects` while `TemporaryDirectory.__exit__` is deleting the
        # same tree, and `rmtree` dies with `OSError: [Errno 39] Directory not
        # empty: 'objects'`.
        #
        # MEASURED on clean main: the owning test failed 3/3 run ALONE and
        # passed 3/3 inside its full targeted list — the same tree giving
        # opposite answers depending on what ran before it, because the timing
        # of the detached gc changed. It also flipped between two runs of one
        # identical file list. That made it produce a FALSE "new failure" on
        # PRs #1063, #1139 and #1274, none of which touch this code.
        #
        # Turned off rather than retried: a retry loop would hide a race that
        # is not ours to have, and `ignore_cleanup_errors` would delete the
        # evidence that anything went wrong. With no auto-gc there is no
        # second writer, so the cleanup is deterministic.
        for _k, _v in (("gc.auto", "0"), ("gc.autoDetach", "false"),
                       ("maintenance.auto", "false")):
            subprocess.run(["git", "config", _k, _v], cwd=root, check=True,
                           env=env, capture_output=True)

        def commit(*rels: str) -> None:
            if rels:
                subprocess.run(["git", "add", "--", *rels], cwd=root,
                               check=True, env=env, capture_output=True)
            subprocess.run(
                ["git", "-c", "user.email=d3@probe.invalid",
                 "-c", "user.name=d3 probe", "commit", "-q", "-m", "probe",
                 "--allow-empty"],
                cwd=root, check=True, env=env, capture_output=True)
            tracked_under.cache_clear()
            # The ledger's own admissibility depends on trackedness, so its
            # memo has to fall with the same commit. Clearing one and not the
            # other is how a probe silently keeps answering about the previous
            # commit.
            write_ledger.cache_clear()

        commit()  # give the repo a HEAD, so `git ls-tree HEAD` is meaningful
        yield root, commit


A8_GDS_ENTRY = "phase3/analog/hardmacro/*/*.gds"

#: The program A8's waiver names as the (new) producer of the entry above.
#: Written down, not read from the manifest, so the assertion below has an
#: independent statement to check — see that test's docstring.
A8_GDS_PRODUCER = "analog_hardmacro_gds_emit"


def test_d3_a8_gds_in_a_run_root_is_a_real_hardmacro_layout():
    """Any hardmacro GDS already in a run root must BE one — not junk.

    RE-SCOPED 2026-07-28 at the convergence merge, because the assertion that
    stood here was a false alarm on the very artefact the flow now produces.
    It failed outright whenever an admissible run root carried a hardmacro
    GDS, and the remedy its own message prescribed ("record it as
    PRODUCED_BY_RUN with the run that wrote it") could not be applied, because
    the sibling guard opens with a hard ``assert rec["status"] ==
    "PRODUCED_LIVE"``. Measured: running the producer on the analog reference
    run exactly as ``analog_one_shot_runner`` does at A8 (rc 0, Magic streamed
    the run's OWN ``layout.mag``) turned this module ``3 failed``. A dimension
    called "outputs produced" must not go red because an output was produced.

    What the original assertion was protecting is NOT lost: the auditor's own
    residue is caught by ``test_d3_the_compliance_audit_does_not_create_
    declared_outputs``, which pins, per run root, exactly which declared
    outputs a ``flow_compliance_check`` run creates in the tree it audits, and
    reddens when that population grows. That guard measures the property
    directly; this one only ever measured its side effect.

    What remains here, and is the honest form: whatever a run root DOES carry
    at A8's declared path must be a real GDSII stream, with geometry, defining
    a structure named after the block directory it sits in. Junk, padding, or
    another design's chip-top dropped under the glob still fails.
    """
    assert A8_GDS_ENTRY in F.required_outputs("A8"), (
        f"A8 no longer declares {A8_GDS_ENTRY!r}; this guard is stale")
    found = [
        (label, rel, rr.path / rel)
        for label, rr in run_roots().items()
        for alt in F.split_any_of(A8_GDS_ENTRY)
        for rel in _GLOB_FIRST(rr.path, alt)
        if (rr.path / rel).is_file()
    ]
    problems = []
    for label, rel, path in found:
        raw = path.read_bytes()
        block = Path(rel).parent.name
        defined, _referenced, valid_header = parse_structures(raw)
        if not valid_header:
            problems.append(
                f"{label}::{rel} ({len(raw)} B) does not start with a GDSII "
                f"HEADER record")
            continue
        if _gds_geometry_count(raw) <= 0:
            problems.append(
                f"{label}::{rel} ({len(raw)} B) carries no "
                f"BOUNDARY/PATH/SREF/AREF/BOX record — padding or an empty "
                f"library, not a layout")
        if block not in defined:
            problems.append(
                f"{label}::{rel} defines structures {defined[:6]} and none of "
                f"them is {block!r}, the block directory it sits in — the "
                f"bytes filed as this block's hardmacro layout are some other "
                f"cell's layout")
    assert not problems, "\n  ".join(problems)


def test_d3_a8_producer_is_reachable_from_a_flow_path():
    """A8's evidence is only evidence if the FLOW produces it.

    ADDED 2026-07-28. A8's waiver now says the producer EXISTS and only its
    evidence is out of reach, so "the producer exists" has to be worth
    something. A probe that resolves the program and runs it by hand is not:
    it stays green with the producer disconnected from every flow path, which
    is the exact state the waiver used to describe ("declared and produced by
    nothing"). Measured: patching ``analog_one_shot_runner``'s A8 dispatch to
    ``if False:`` AND deleting the producer from A8's ``programs:`` left this
    module green.

    Since the producer clause was deliberately withdrawn from A8's GATE (the
    acceptance auditor must not create what it certifies), the runner is the
    SOLE production site, so this asserts the DISPATCH, not the source text:
    ``analog_one_shot_runner.subprocess`` is replaced with a recorder and the
    A8 step is driven for one block.

    The name is written down here rather than read out of the manifest,
    because the manifest records A8's ``.gds`` as ``UNPROVEN`` — it carries no
    producer field to read, and taking the name from the thing under test
    would make this assert nothing.
    """
    prog_name = A8_GDS_PRODUCER
    assert prog_name in F.declared_programs("A8"), (
        f"A8 no longer declares {prog_name!r} in its `programs:` list")
    assert (F.PROGRAMS_DIR / f"{prog_name}.py").is_file(), (
        f"A8's waiver states programs/{prog_name}.py exists; it does not")

    runner = pytest.importorskip("analog_one_shot_runner")
    seen = []

    class _Recorder:
        def __getattr__(self, name):
            return getattr(runner.subprocess, name)

        def run(self, argv, *a, **kw):
            seen.append([str(x) for x in argv])
            return subprocess.CompletedProcess(argv, 0, "", "")

    saved = runner.subprocess
    with tempfile.TemporaryDirectory(prefix="d3_a8_wire_") as td:
        proj = Path(td)
        try:
            runner.subprocess = _Recorder()
            runner.step_for_block(proj, {"name": "blk_a"},
                                  "A8_hardmacro_gen", None)
        finally:
            runner.subprocess = saved

    hits = [argv for argv in seen
            if any(a.endswith(f"{prog_name}.py") for a in argv)]
    assert len(hits) == 1, (
        f"analog_one_shot_runner dispatched {prog_name} {len(hits)} time(s) "
        f"at A8_hardmacro_gen; A8's declared .gds is PRODUCED_LIVE evidence "
        f"only while a flow path actually runs the producer. Dispatched "
        f"argv: {seen}")


# THE A8 LIVE-PRODUCTION PROOF IS NOT HERE, AND THAT IS THE HONEST PLACE FOR IT.
# A test that ran `analog_hardmacro_gds_emit` on a throwaway copy of the analog
# reference run and bound the produced bytes to the producer's own run record
# was written and is REMOVED: it needs Magic in the EDA container, so it is red
# on CI and on any fresh clone, and this module's whole contract (#527) is that
# its answer does not depend on the machine. Measured 2026-07-28: rc=2
# A8GDS_NO_STAGE, "No such container: vibeic-eda".
#
# The bindings that proof carried are not lost. The producer's own behaviour —
# including that a hollow or foreign GDS is refused — is
# `programs/tests/test_analog_hardmacro_gds_emit.py`; that a flow path
# dispatches it is asserted above; and that whatever lands at A8's declared
# path is a real layout for the right block is asserted by
# `test_d3_a8_gds_in_a_run_root_is_a_real_hardmacro_layout`.
#
# 2026-08-06: what those bindings left unproven — that a RUN produced one — is
# no longer unproven and no longer waived. It is answered by an artefact rather
# than by an execution: commit b1665ec8 published two hardmacro layouts into
# `benchmark-data/ic/u_hawaii_adc/v1.9.86_sky130A/phase3/analog/hardmacro/`,
# they are tracked at HEAD, and `test_matrix_a8_published_gds_control.py`
# re-checks on every run that each one is a real GDSII stream defining a
# structure named after its own block directory. The removed test is still the
# right thing to leave removed: running Magic here would re-introduce exactly
# the host-dependence the published artefact makes unnecessary.


@needs_corpus
def test_d3_the_compliance_audit_does_not_create_declared_outputs():
    """THE SELF-CERTIFICATION GUARD. An audit must not write its own evidence.

    ``flow_compliance_check`` is the sole phase-2+3 acceptance auditor and it
    reports, per step, whether the ``required_outputs`` are present. If one of
    its own gate clauses produces one of those artefacts, the audit has
    certified its own output — and because dimension 3 resolves entries in
    exactly the same admissible run roots, whatever the audit leaves behind
    becomes this dimension's evidence too.

    Measured 2026-07-28 on a copy of the analog reference run: with an
    ``advisory_program_exit_zero: analog_hardmacro_gds_emit`` clause in A8's
    gate the audit created ``delta_sigma.gds`` (2042 B) and ``ldo.gds``
    (1706 B) — the exact files A8's cell was reading. The clause was withdrawn;
    production now happens in ``analog_one_shot_runner``, and this holds the
    line.

    The quantity measured is deliberately narrow: not "the audit wrote
    nothing" (it legitimately writes gate reports) but "the audit created a
    file that satisfies some step's declared ``required_outputs``", resolved
    with the flow's OWN resolver against the LIVE yaml.
    """
    fcc_path = F.PROGRAMS_DIR / "flow_compliance_check.py"
    assert fcc_path.is_file(), fcc_path

    measured: Dict[str, Tuple[str, ...]] = {}
    for label in SELF_CERTIFYING_AUDIT_PROBE:
        rr = run_roots().get(label)
        assert rr is not None, (
            f"the self-certification probe drives {label!r}, which lives in "
            f"this repository and must resolve; it did not")
        with tempfile.TemporaryDirectory(prefix="d3_selfcert_") as td:
            dst = Path(td) / "proj"
            shutil.copytree(rr.path, dst, symlinks=True)
            before = {p.relative_to(dst) for p in dst.rglob("*") if p.is_file()}
            _pr.run(
                [sys.executable, str(fcc_path), str(dst)],
                capture_output=True, text=True)
            after = {p.relative_to(dst) for p in dst.rglob("*") if p.is_file()}
            created = after - before
            hits = set()
            for sid in F.step_ids():
                for entry in F.required_outputs(sid):
                    for alt in F.split_any_of(entry):
                        for rel in _GLOB_FIRST(dst, alt):
                            if Path(rel) in created:
                                hits.add(f"{F.normalize_id(sid)}::{rel}")
            measured[label] = tuple(sorted(hits))

    pinned = {k: tuple(sorted(v)) for k, v in SELF_CERTIFYING_AUDIT_PROBE.items()}
    assert measured == pinned, (
        f"the set of declared required_outputs that a COMPLIANCE AUDIT "
        f"creates in the tree it audits changed.\n"
        f"  measured: {measured}\n"
        f"  pinned:   {pinned}\n"
        f"Newly self-certified: "
        f"{ {k: sorted(set(v) - set(pinned.get(k, ()))) for k, v in measured.items() if set(v) - set(pinned.get(k, ()))} }\n"
        f"A gate clause is now producing an artefact the same audit then "
        f"reports as present. Move the producer to the runner that owns the "
        f"step; the audit must measure a tree it did not touch."
    )


def test_d3_m1_merge_inputs_are_absent_from_every_run_root():
    """M1's waiver, re-measured live rather than believed.

    The waiver says the merge PRODUCER ships and is wired, and that what is
    missing is an input SET no reachable run tree has: a digital sign-off GDS
    and an analog hardmacro GDS in the SAME project. Both halves are asserted
    here, so the waiver cannot outlive its reason — publish one mixed-signal
    run tree with both and this test names it and demands the waiver's removal.
    """
    prog = F.PROGRAMS_DIR / "mixed_signal_top_lvs_run.py"
    assert prog.is_file(), (
        "M1's waiver claims the producer ships; it does not exist")
    cmds = [c.command for c in F.gate_clauses("M1") if c.command]
    assert any(c.split()[0] == "mixed_signal_top_lvs_run" for c in cmds), (
        f"M1's waiver claims the producer is wired into its gate; the gate "
        f"clauses are {cmds}")

    # ASK THE PRODUCER, do not re-glob its inputs. A local re-implementation
    # could report "no inputs" on a tree where the producer would find them.
    # The tool probe is stubbed to "absent" first, purely so this can never
    # launch KLayout/Magic/netgen from inside a test: with that stub the ONLY
    # way `run` can still say "inputs missing" is its real input check, and any
    # root whose inputs ARE satisfied comes back with the tool reason instead
    # and trips the assertion below.
    import mixed_signal_top_lvs_run as _ms

    real_exec = _ms._docker_exec
    _ms._docker_exec = lambda *a, **k: (1, "", "stubbed: tool probe disarmed")
    try:
        verdicts = {
            label: _ms.run(rr.path, "chip_top", "", "")
            for label, rr in run_roots().items()
        }
    finally:
        _ms._docker_exec = real_exec

    runnable = {
        label: v for label, v in verdicts.items()
        if not str(v.get("reason", "")).startswith("inputs missing")
    }
    assert not runnable, (
        f"M1 is waived ONLY because mixed_signal_top_lvs_run's own input "
        f"precondition is unmet on every admissible run root — asked directly, "
        f"it returns its documented rc=2 'inputs missing' skip on all "
        f"{len(verdicts)} of them. These roots got past that check: "
        f"{runnable}. The producer can run there — run it, and remove the "
        f"waiver. (per-root reasons: "
        f"{ {k: v.get('reason') for k, v in verdicts.items()} })")


@needs_corpus
def test_d3_zero_byte_artefacts_are_not_counted_as_produced():
    """The rule that makes this dimension mean anything, exercised directly.

    A 0-byte drc.rpt is equally consistent with "0 violations" and "the tool
    never wrote anything". If ``resolve`` ever counted one, every cell in this
    module would go quietly hollow, so the distinction is asserted rather than
    assumed.
    """
    roots = run_roots()
    if not roots and _plugin_tree.repo_root() is not None:
        # Only a source tree owes us run roots. #527 removed the $HOME search,
        # so on the flattened install cache (no repo ancestor, hence no in-repo
        # run root) an empty set is the correct state and must not read as a
        # discovery bug — the probe below is self-contained either way.
        pytest.fail(
            "no admissible run root resolved on the source tree, so discovery "
            "is broken; see test_d3_run_root_discovery_is_live"
        )
    with _probe_run_root("d3_zero_") as (probe, commit):
        (probe / "reports").mkdir()
        empty = probe / "reports" / "drc.rpt"
        empty.touch()
        commit("reports/drc.rpt")
        hit, rej = resolve(probe, "reports/drc.rpt")
        assert hit is None, f"a 0-byte file was accepted as produced: {hit}"
        assert rej.empty == ("reports/drc.rpt",), rej
        assert rej.symlinked == () and rej.untracked == (), rej
        empty.write_text("x")
        commit("reports/drc.rpt")
        hit, rej = resolve(probe, "reports/drc.rpt")
        assert hit is not None and hit.size_bytes == 1, (hit, rej)
    assert all(rr.path.is_dir() for rr in roots.values())


def _probe_only(monkeypatch, label: str, path: Path) -> None:
    """Make *path* the ONE admissible run root for the duration of a test."""
    monkeypatch.setattr(
        sys.modules[__name__], "run_roots",
        lambda: {label: RunRoot(label, _IN_REPO_KIND, path)})


def test_d3_an_entry_that_resolves_nowhere_is_not_reported_as_produced(monkeypatch):
    """THE CONTROL for "a lookup that returns nothing lights the green light".

    Before this fix ``check_entry``'s ``PRODUCED_BY_RUN`` arm ended:

        hit, _rejected = resolve_anywhere(entry)
        if hit is not None:
            return EntryVerdict(True, LIVE, (...))
        return EntryVerdict(True, FIXTURE, (
            f"[fixture-attested, run root {rec['run']!r} absent here] ...")

    — a search of every admissible run root that came back EMPTY returned
    ``produced=True`` anyway, on the strength of a line in the committed
    manifest. Measured on this checkout: step 17's ``phase3/stage3/pnr/
    placed.def`` matches nothing (``find benchmark-data -name placed.def`` = 0,
    ``git ls-tree -r --name-only HEAD | grep -c 'placed\\.def'`` = 0) and its
    cell was GREEN. 19 of the 133 declared entries took that route.

    THREE CASES, AND THE MIDDLE ONE IS THE POINT.

    * FORWARD — the artefact is in no admissible run root: NOT produced. This
      is the assertion the pre-fix file fails.
    * REVERSE A — the SAME entry, the SAME record whose recorded run root is
      still absent, with the artefact planted and committed in an admissible
      run root: produced, LIVE. This is what stops the fix degenerating into
      "recorded run root absent => always False". It is also the property the
      defect said was missing: the cell's colour now MOVES with the run tree.
    * REVERSE B — the recorded run root itself resolves and carries it:
      produced, LIVE, unchanged.

    Both reverse cases pass against the pre-fix file too, by construction:
    they go through the ``resolve_anywhere``/``resolve`` hit branches, which
    this fix does not touch.
    """
    sid, entry = "17", "phase3/stage3/pnr/placed.def"
    assert entry in F.required_outputs(sid), (
        f"step {sid} no longer declares {entry!r}; this control is stale and "
        f"must be re-pointed at an entry the flow actually declares")
    rec = dict(step_record(sid)["entries"][entry])
    assert rec["status"] == "PRODUCED_BY_RUN", rec
    absent_root = rec["run"]

    with _probe_run_root("d3_unevidenced_") as (probe, commit):
        (probe / "reports" / "orchestrator").mkdir(parents=True)
        (probe / "unrelated.txt").write_text("a run tree without the artefact\n")
        commit("unrelated.txt")
        assert _is_flow_run(probe), "the probe is not admissible as a run root"
        _probe_only(monkeypatch, "probe", probe)
        assert absent_root not in run_roots(), (
            f"the recorded run root {absent_root!r} must NOT resolve for this "
            f"control to exercise the fall-through")

        # ---- FORWARD: nothing resolves anywhere ----------------------
        v = check_entry(sid, entry, rec)
        assert v.produced is False, (
            f"an entry that resolves in NONE of the {len(run_roots())} "
            f"admissible run roots was reported as produced: {v.detail}. A "
            f"fixture attestation dated {_MANIFEST_MEASURED_ON} is a claim "
            f"about the past; it is not evidence that the artefact exists now."
        )
        assert v.mode == FIXTURE and "UNEVIDENCED" in v.detail, v
        assert absent_root in v.detail and entry in v.detail, (
            "the failure must name the run root it wanted and the entry it "
            "could not find, or nobody can act on it: " + v.detail)

        # ---- REVERSE A: plant it, the SAME record must go green ------
        target = probe / entry
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("VERSION 5.8 ;\nDESIGN probe ;\nEND DESIGN\n")
        commit(entry)
        v = check_entry(sid, entry, rec)
        assert v.produced is True and v.mode == LIVE, (
            f"the artefact was committed into an admissible run root and the "
            f"verdict did not move: {v}. A rule that fires on everything is "
            f"not a rule — and this cell would still be unfalsifiable, just "
            f"red instead of green."
        )
        assert "probe" in v.detail, v.detail

        # ---- REVERSE B: the RECORDED run root resolves and carries it -
        rec_here = dict(rec, run="probe")
        v = check_entry(sid, entry, rec_here)
        assert v.produced is True and v.mode == LIVE, (
            f"the ordinary in-repo path regressed: {v}")


def test_d3_a_live_production_record_alone_is_not_evidence(monkeypatch):
    """The same rule on the ``PRODUCED_LIVE`` arm, which had the same hole.

    That arm returned ``EntryVerdict(True, FIXTURE, ...)`` the moment its
    ``base_run`` was absent — without so much as a lookup. It is latent on this
    checkout (all six live-produced entries name an in-repo base run, so the
    branch is not reached today), and it is the identical defect: a recorded
    production EVENT is not the artefact, and a checkout that cannot re-run the
    producer has not observed one.

    Reverse case, which must still pass: with the artefact actually present in
    an admissible run root the entry is produced and LIVE, so this rejects the
    ABSENCE of evidence and not the ``PRODUCED_LIVE`` status.
    """
    entry = "reports/probe/live_only.json"
    rec = {
        "status": "PRODUCED_LIVE",
        "base_run": "a/run/tree/this/repo/does/not/carry",
        "producer": "some_producer",
        "writes": entry,
        "argv": [],
        "size_bytes": 1234,
    }
    with _probe_run_root("d3_liveonly_") as (probe, commit):
        (probe / "reports" / "orchestrator").mkdir(parents=True)
        (probe / "unrelated.txt").write_text("no artefact here\n")
        commit("unrelated.txt")
        _probe_only(monkeypatch, "probe", probe)

        v = check_entry("A8", entry, rec)
        assert v.produced is False, (
            f"a PRODUCED_LIVE record whose base run is absent was reported as "
            f"produced without looking for the artefact: {v.detail}")
        assert v.mode == FIXTURE and "UNEVIDENCED" in v.detail, v

        target = probe / entry
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"planted": true}\n')
        commit(entry)
        v = check_entry("A8", entry, rec)
        assert v.produced is True and v.mode == LIVE, (
            f"the artefact IS in an admissible run root and the entry still "
            f"reads unproduced: {v}")


def test_d3_a_present_artefact_still_reads_as_produced(monkeypatch):
    """THE REVERSE CONTROL, standing alone so it can be run BOTH WAYS.

    The two tests above assert a green that must go red. This one asserts the
    green that must STAY green, and it is deliberately a separate test rather
    than a trailing block inside them: a test whose first assertion has already
    failed never reaches its own reverse case, so on the pre-fix file those
    trailing blocks prove nothing. This one passes against the byte-identical
    pre-fix file AND after, which is the only way to show the fix rejects the
    ABSENCE of evidence rather than "an entry whose recorded run root is not
    here" — the degenerate tightening that would fire on all 19 entries no
    matter what the run tree held.

    Two shapes, each with the artefact genuinely present and committed:

      * ``PRODUCED_BY_RUN`` whose recorded run root is ABSENT, resolved in a
        different admissible root (``resolve_anywhere``);
      * ``PRODUCED_BY_RUN`` whose recorded run root IS the one that has it
        (``resolve``).

    The third obvious shape — ``PRODUCED_LIVE``, base run absent, artefact
    present — is deliberately NOT here: measured against the pre-fix file it
    returns ``EntryVerdict(True, 'FIXTURE', ...)`` because that arm returned
    the fixture attestation without ever looking, so the mode genuinely
    CHANGES with this fix and the assertion belongs in the forward control
    (``test_d3_a_live_production_record_alone_is_not_evidence``) where it is
    the reverse half. Putting it here would have made this "both ways" test
    fail one of the two ways, which is how a reverse control stops being one.
    """
    sid, entry = "17", "phase3/stage3/pnr/placed.def"
    assert entry in F.required_outputs(sid), "control is stale"
    rec = dict(step_record(sid)["entries"][entry])

    with _probe_run_root("d3_present_") as (probe, commit):
        (probe / "reports" / "orchestrator").mkdir(parents=True)
        target = probe / entry
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("VERSION 5.8 ;\nDESIGN probe ;\nEND DESIGN\n")
        commit(entry)
        _probe_only(monkeypatch, "probe", probe)
        assert is_tracked(probe, entry) and target.stat().st_size > 0

        v = check_entry(sid, entry, rec)          # recorded run root absent
        assert v.produced is True and v.mode == LIVE, (
            f"a committed, non-empty artefact sitting in an admissible run "
            f"root was NOT counted as produced: {v}. The rule must reject the "
            f"absence of evidence, not the shape of the manifest record.")

        v = check_entry(sid, entry, dict(rec, run="probe"))
        assert v.produced is True and v.mode == LIVE, (
            f"the recorded-run-root path regressed: {v}")


def test_d3_a_recorded_root_that_lost_the_artefact_still_searches_the_others(
        monkeypatch):
    """THE THIRD SHAPE — recorded root PRESENT, artefact somewhere ELSE.

    ``test_d3_a_present_artefact_still_reads_as_produced`` covers the two
    shapes where the recorded root is either absent or is the one holding the
    artefact. The shape between them had no control and no fall-through: the
    recorded root RESOLVES and no longer carries the entry, while another
    admissible root does. The ``PRODUCED_BY_RUN`` arm stopped at the recorded
    root and reported "not produced", so an entry was strictly LESS likely to
    be evidenced when the manifest happened to name a root that exists than
    when it named one that does not — the absent-root branch has searched
    everywhere since #527.

    It is not hypothetical. Steps 21 and 22 recorded ``phase3/stage3/pnr/
    routed.def`` and ``phase3/stage3/extracted/*.spef`` against
    ``spm/v1.9.96_gf180mcuD``, a PUBLISHED CELL — a curated subset of the run
    the manifest was measured on, which has never carried either path in any
    commit — while ``spm/v1.5.58_ihp-sg13g2``, registered in the same manifest
    and admissible on every host, carries both non-empty and tracked at HEAD.
    Two cells read "not produced" with the artefact in the repository.

    BOTH DIRECTIONS, because a fall-through that always says yes is worse than
    the bug it replaces. The reverse half plants NOTHING and asserts the cell
    stays red: the rule must reject the ABSENCE of evidence, not the shape of
    the manifest record.
    """
    sid, entry = "17", "phase3/stage3/pnr/placed.def"
    assert entry in F.required_outputs(sid), "control is stale"
    rec = dict(step_record(sid)["entries"][entry])

    with _probe_run_root("d3_stale_rec_") as (stale, stale_commit):
        with _probe_run_root("d3_stale_oth_") as (other, other_commit):
            (stale / "reports" / "orchestrator").mkdir(parents=True)
            (other / "reports" / "orchestrator").mkdir(parents=True)
            # The recorded root exists and is admissible; it simply does not
            # carry the entry. Give it an unrelated committed file so it is a
            # real run root rather than an empty directory.
            (stale / "reports" / "orchestrator" / "summary.json").write_text("{}")
            stale_commit("reports/orchestrator/summary.json")
            monkeypatch.setattr(
                sys.modules[__name__], "run_roots",
                lambda: {"stale": RunRoot("stale", _IN_REPO_KIND, stale),
                         "other": RunRoot("other", _IN_REPO_KIND, other)})

            # ---- reverse half FIRST: nothing anywhere, still red ----------
            v = check_entry(sid, entry, dict(rec, run="stale"))
            assert v.produced is False, (
                f"no admissible root carries {entry!r} and the entry was still "
                f"reported produced: {v}. The fall-through must add a SEARCH, "
                f"not an answer.")

            # ---- forward half: the other root has it ---------------------
            target = other / entry
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("VERSION 5.8 ;\nDESIGN probe ;\nEND DESIGN\n")
            other_commit(entry)
            assert is_tracked(other, entry) and target.stat().st_size > 0

            v = check_entry(sid, entry, dict(rec, run="stale"))
            assert v.produced is True and v.mode == LIVE, (
                f"the recorded run root lost the artefact, another admissible "
                f"root carries it committed and non-empty, and the entry still "
                f"reads unproduced: {v}")
            assert "STALE MANIFEST RECORD" in v.detail and "'other'" in v.detail, (
                f"the stale record must be REPORTED, not swallowed — a reader "
                f"has to be told the manifest points at the wrong root and "
                f"which root answered: {v.detail}")


def _live_records() -> List[Tuple[str, str, Dict]]:
    """``(step_id, entry, record)`` for every ``PRODUCED_LIVE`` manifest entry."""
    out: List[Tuple[str, str, Dict]] = []
    for cell in cells_for(DIM):
        rec = step_record(cell.step_id)
        if rec["verdict"].startswith("NA_"):
            continue
        for entry, erec in rec["entries"].items():
            if erec.get("status") == "PRODUCED_LIVE":
                out.append((F.normalize_id(cell.step_id), entry, erec))
    return out


def live_records_the_commit_already_carries(
        records: Optional[List[Tuple[str, str, Dict]]] = None) -> Tuple[str, ...]:
    """Every ``PRODUCED_LIVE`` record whose target its base run already carries.

    ``produce_live`` refuses exactly this case, and says why in its own words:
    a live production cannot be proved against a tree that already holds the
    artefact, and *"in that case the entry is not a live production at all; it
    should be recorded PRODUCED_BY_RUN"*. Nothing ever looked for the condition
    itself, so the drift surfaced as four unexplained cell failures (23, 24,
    25, 26) instead of as the one-line status correction it is. A record and
    the tree it cites are both in the commit, so this is decidable here, on
    every host, without running anything.

    *records* exists so the guard can be pointed at a PLANTED record — an
    invariant that only ever measures zero has not been shown able to measure
    one.
    """
    bad: List[str] = []
    for step_id, entry, erec in (_live_records() if records is None else records):
        rr = run_roots().get(erec.get("base_run"))
        if rr is None:
            continue
        if is_tracked(rr.path, erec["writes"]):
            bad.append(
                f"step {step_id} {entry!r}: recorded PRODUCED_LIVE against base "
                f"run {erec['base_run']!r}, which now carries {erec['writes']} "
                f"tracked at HEAD. `produce_live` cannot prove a live "
                f"production against a tree that already holds the target; "
                f"record it PRODUCED_BY_RUN against that run instead")
    return tuple(bad)


def test_d3_no_live_production_record_names_an_artefact_the_commit_carries(
        monkeypatch):
    """The status drift above, caught at the RECORD instead of at the cell.

    A ``PRODUCED_LIVE`` record is a claim that this checkout can WATCH the
    producer write the artefact. The moment the base run is published carrying
    it, that claim stops being provable — not because production regressed but
    because the evidence got stronger and the record did not follow. Reported
    here as what it is, so the repair is "correct the status" rather than a
    hunt through a cell failure that names neither the record nor the reason.
    """
    bad = live_records_the_commit_already_carries()
    assert not bad, (
        "PRODUCED_LIVE records whose base run already carries the artefact:\n  "
        + "\n  ".join(bad))

    # THE PAIRED GUARD. An invariant that measures zero has not been shown to
    # be able to measure anything, and this one measures zero on a clean tree
    # by construction. Plant the exact violation and require it to be found;
    # then take the artefact out of the commit and require it NOT to be, so the
    # guard is answering "the commit carries it" and not "a record exists".
    entry = "phase3/stage3/pnr/placed.def"
    planted = [("probe-step", entry, {"status": "PRODUCED_LIVE",
                                      "producer": "sta_report_check",
                                      "argv": ["."],
                                      "writes": entry,
                                      "base_run": "probe",
                                      "size_bytes": 1})]
    with _probe_run_root("d3_liverec_") as (probe, commit):
        (probe / "reports" / "orchestrator").mkdir(parents=True)
        _probe_only(monkeypatch, "probe", probe)

        assert not live_records_the_commit_already_carries(planted), (
            "the base run does NOT carry the artefact, so this record is a "
            "legitimate live-production claim and must not be reported")

        target = probe / entry
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("VERSION 5.8 ;\nDESIGN probe ;\nEND DESIGN\n")
        commit(entry)
        assert is_tracked(probe, entry)

        found = live_records_the_commit_already_carries(planted)
        assert any(entry in f for f in found), (
            f"a PRODUCED_LIVE record whose base run carries the artefact "
            f"tracked at HEAD was NOT reported: {found}. The guard measures "
            f"zero on this checkout, so it has to be shown it can measure one.")


#: Every dimension-3 cell that declares at least one entry NO admissible run
#: root can evidence, measured on this checkout. Before the fix all twelve were
#: green — eleven of them ENFORCED with no waiver, and M1 green on the one entry
#: its waiver does NOT cover. They are now RED, and each is closed by committing
#: (or registering) a run tree that carries the entry, NOT by a waiver: see
#: ``test_d3_unevidenced_cells_are_named_cell_by_cell``.
UNEVIDENCED_CELLS: Tuple[str, ...] = (
    # 2026-08-10: "11" and "29" LEFT this set. Neither was waived and no
    # evidence was manufactured for them -- the artefacts they declare were
    # already tracked by this commit, and the manifest simply did not list the
    # trees carrying them as run roots, so `resolve_anywhere` never looked.
    # Registering those two roots is the "manifest staleness" repair this
    # module's own docstring distinguishes from the other ten:
    #   11 <- benchmark-data/ic/caravel_user_project/v1.9.43_sky130A
    #         (phase2/stage2/dft/*, 351 files tracked at HEAD)
    #   29 <- benchmark-data/evaluation/phase1_parity/espi
    #         (phase3/stage3/sim_postlayout/pass.flag, 253 files tracked)
    # The remaining ten declare artefacts NO path in this commit matches. They
    # stay RED here rather than becoming waivers. A red cell cannot rot; a
    # waiver can, and did.
    #
    # 2026-08-15 (vibe-ic#1457) — THE COST OF CLOSING THEM WAS MEASURED ON THE
    # WRONG THING. This paragraph used to end "Only a published run
    # tree closes those, and publishing one costs >1 GB of DEFs against a
    # 2.0 GB .git -- which is why they stay RED". #1457 read that sentence off
    # these cells and escalated the class as "a repository-size decision, not
    # an engineering one", where it has sat while everything about it was
    # re-measured EXCEPT the figure holding it up.
    #
    # The figure is not false about run TREES. It is about run trees, and that
    # is the wrong quantity: a cell is closed by the repository carrying the
    # DECLARED ENTRIES, not by importing the tree they came from. The manifest
    # already records the size of every one of those entries, so the cost never
    # needed estimating at all. Summed from those records by
    # :func:`unevidenced_closing_cost` and was pinned at 386857 B.  The
    # 2026-08-23 publisher-record ruling then removed the four DEFs and the ECO
    # decision from this class without publishing their bytes: their tracked
    # STEP_RECORD rows already carry real digests.  The remaining step-30 rows
    # total 1893 B, re-derived by the same function and pinned at
    # :data:`_UNEVIDENCED_CLOSING_COST_BYTES`.  Whatever keeps this class red,
    # it is not repository size.
    #
    # Nor does closing it need a manifest edit. MEASURED on this commit by
    # committing artefacts at the seven declared paths into that same
    # already-registered root, with this file byte-identical: all six cells
    # answered GREEN and both population pins reddened with "newly evidenced
    # -- delete them from the pin and say which run tree closed them". The
    # `resolve_anywhere` fall-through in :func:`check_entry` already searches
    # every admissible root when the recorded one is absent, so "register in
    # the manifest" is not a step anyone has to take first. (That probe was a
    # CONTROL and its artefacts were never pushed: what it establishes is that
    # the mechanism answers, not that anything is produced. The cells still
    # need a real run to write real ones.)
    #
    # 2026-08-12: "M2", "M3" and "M4" LEFT this set, and NOT by being
    # published. "Publish the run tree" was the wrong prescription for them:
    # all four mixed-signal steps carry the SAME step-level condition,
    #
    #     condition: {files_exist: ["phase1/analog/analog_block_list.json"]}
    #
    # and that path occurs ZERO times in this repository -- not merely absent
    # from the admissible run roots, absent from `git ls-tree -r HEAD` over the
    # whole tree. No project here has ever met the condition, so M2-M4 have
    # never RUN here, so there is no run to publish. They are DORMANT, which
    # this module already has a verdict for and already uses for steps 40-44
    # (dormant on `phase3/stage5_manufacturing/silicon_received.json`).
    #
    # What made them look unevidenced was the manifest recording their entries
    # `PRODUCED_BY_RUN` against `AI_IC_design/4th_benchmark/U_Hawaii_EE628_
    # DeltaSigma_ADC_e2e`, an out-of-repo tree. For M4 that attribution was
    # additionally WRONG in its own terms: the entry it recorded produced,
    # `reports/analog/mixed_signal/signoff.json`, is M4's INPUT --
    # `mixed_signal_signoff_check`'s own docstring line 8 calls it "M4's input"
    # and the gate FAILs when it is missing -- and no program in this
    # repository writes it. The run's own write ledger agrees, independently:
    # `benchmark-data/ic/spm/v1.10.18_sky130A/steps/mixed/stage_mixed_signal/
    # M4_.../written.json` records `n_produced: 0` and a
    # `declared_output_not_produced` finding against that exact spec.
    #
    # The NA is not a softening. `matrix_na_precondition` re-derives it live and
    # it falsifies itself in BOTH directions: publish any tree carrying the
    # condition file and the cell reddens, or let any declared output appear
    # anywhere and the NA branch's own probe reddens.
    # 2026-08-12: "M1" left with M2-M4 and for the same reason — it is dormant,
    # not unpublished. It was the last mixed-signal cell here.
    #
    # 2026-08-17 (vibe-ic#1703) — THE SIX BELOW ARE THE SIX THE SPLIT WAS SAID
    # TO HAVE TAKEN OUT OF SIGHT, AND THE PIN NEVER MOVED. #1703 asked for the
    # census's 7 ENFORCED-CONTRADICTED cells to be enumerated by id "as they
    # stood on the last commit that had the data — 772c31dcb — so they are
    # recorded before the record scrolls away". Measured there, on a worktree
    # of that commit, with the suite's own command:
    #
    #   $ pytest -q programs/tests/test_matrix_d3_outputs_produced.py -rA
    #     FAILED ...test_d3_required_outputs_are_produced[step15]
    #     FAILED ...[step17]  FAILED ...[step19]  FAILED ...[step20]
    #     FAILED ...[step30]  FAILED ...[step32]
    #     6 failed, 101 passed, 2 xfailed in 54.70s
    #
    #   $ pytest -q programs/tests/test_matrix_d7_outputs_list_complete.py
    #     FAILED ...test_d7_required_outputs_list_is_complete[stepD1]
    #     1 failed, 92 passed, 5 xfailed in 68.73s
    #
    # 6 + 1 = the 7. The d3 six are EXACTLY this tuple — the enumeration the
    # issue asked to be written down was already written down, here, and
    # survived the move unedited. The seventh is not a d3 cell at all: it is
    # dimension 7's D1, `phase1/extraction_patterns.json` produced by the flow
    # and read by a gate while no step's required_outputs names it, and it does
    # not reproduce on this commit with or without a corpus.
    #
    # What DID change is whether anything could still ask. Six cells stopped
    # being contradicted and started being SKIPPED, which is honest, and the
    # remedy the skip names — point `VIBE_IC_BENCHMARK_DATA` at a clone — did
    # not work, because `run_roots` never read it. It does now, and with the
    # published corpus offered these six are red again, live, from this
    # repository. So they need no second copy of this suite in benchmark-data:
    # what they needed was the pointer to reach here.
    # 2026-08-23 — five cells LEFT because the publisher records their
    # deliberately unstaged bytes with a real sha256.  That is evidence under
    # the owner ruling implemented by `recorded_unpublished_output`; no bytes
    # moved and the publish scope did not widen.  Step 30 remains because its
    # STEP_RECORD is `status: skipped` with no declared-output rows at all.
    "30",
)


@needs_corpus
def test_d3_unevidenced_cells_are_named_cell_by_cell():
    """Name the cells this dimension cannot answer, and pin the population.

    WHY THESE ARE FAILURES AND NOT NEW WAIVERS. A waiver is a public admission
    that a gap is ACCEPTED, and this module's own history is the argument
    against granting twelve of them: its two FPGA waivers rested on a ``find
    ~ -name '*.sof'`` count that was true on one day on one machine and false a
    fortnight later, and its A8 waiver existed in two copies telling two
    different stories. Every gap named here is closed by a commit — publish the
    run tree, or register the one already in the repository — so waiving it
    would convert a one-commit fix into a standing excuse. A red cell cannot
    rot; a waiver can, and did.

    The two kinds of gap are NOT the same and the difference is actionable:

      * steps 11 and 29 declare artefacts THIS COMMIT ALREADY TRACKS, at
        ``benchmark-data/ic/caravel_user_project/v1.9.43_sky130A/phase2/stage2/
        dft/*`` and ``benchmark-data/evaluation/phase1_parity/*/phase3/stage3/
        sim_postlayout/pass.flag``. Neither tree is a manifest run root, so
        ``resolve_anywhere`` never looks there. That is manifest staleness and
        registering the tree closes it. (Out of this cell's scope: touching the
        manifest to move a cell is the one edit this campaign may not make.)
      * step 30 remains genuinely unevidenced: its publisher STEP_RECORD says
        the step was skipped and carries no declared-output rows.  The other
        five former cells now have tracked, digested unpublished-output rows.

    The pin is what keeps the population from growing quietly: another cell
    joining is a NEW loss of evidence and must be reported as its own finding,
    not absorbed into a set that is already red.
    """
    measured = []
    for cell in cells_for(DIM):
        sid = cell.step_id
        rec = step_record(sid)
        if rec["verdict"].startswith("NA_"):
            continue
        bad = [
            entry for entry, erec in rec["entries"].items()
            if entry in F.required_outputs(sid)
            and not check_entry(sid, entry, erec).produced
            and check_entry(sid, entry, erec).mode == FIXTURE
        ]
        if bad:
            measured.append(F.normalize_id(sid))
    assert tuple(sorted(measured)) == tuple(sorted(UNEVIDENCED_CELLS)), (
        f"the set of dimension-{DIM} cells with an UNEVIDENCED entry changed: "
        f"measured {sorted(measured)!r}, pinned {sorted(UNEVIDENCED_CELLS)!r}. "
        f"Newly unevidenced: {sorted(set(measured) - set(UNEVIDENCED_CELLS))}; "
        f"newly evidenced (delete them from the pin and say which run tree "
        f"closed them): {sorted(set(UNEVIDENCED_CELLS) - set(measured))}."
    )
    # ...and every one of them must be ENFORCED, not quietly waived later. A
    # waiver added to silence one of these would be caught here rather than
    # disappearing behind a strict xfail.
    waived = sorted(s for s in UNEVIDENCED_CELLS if waiver_for(s) is not None)
    assert waived == [], (
        f"these unevidenced cells acquired a waiver: {waived}. Every cell left "
        f"in this set is closed by publishing a run tree, so a waiver here "
        f"would be a standing excuse for a one-commit fix.\n"
        f"2026-08-12: this used to read ``== ['M1']``. M1 was the ONE waiver in "
        f"this set, and it is gone in the direction that makes the set "
        f"stronger, not weaker: M1 left UNEVIDENCED_CELLS entirely because it "
        f"is DORMANT (its condition `phase1/analog/analog_block_list.json` "
        f"occurs zero times in the repository), and its dimension-3 waiver "
        f"went with it. The waiver covered only ``top_merged.gds`` while "
        f"``merge.json`` was unevidenced and unwaived — which is exactly what "
        f"test_d3_waived_steps_still_produce_their_unwaived_entries was red on. "
        f"The set now holds no waived cell at all, which is the invariant this "
        f"assertion was always reaching for."
    )


@lru_cache(maxsize=1)
def unevidenced_entries() -> Tuple[Tuple[str, str], ...]:
    """``[(step, entry), ...]`` for every entry that reaches UNEVIDENCED.

    Derived from the same :func:`check_entry` the cells use, so the guards
    below can never drift onto a population the verdicts do not have.

    Cached because three guards below ask for it and each ask re-runs
    :func:`check_entry` over every declared entry — a git-backed walk, not a
    lookup. The cache is keyed on nothing because the answer is a function of
    the COMMIT alone, which is the same reason the verdicts may be trusted.
    """
    out: List[Tuple[str, str]] = []
    for cell in cells_for(DIM):
        sid = cell.step_id
        rec = step_record(sid)
        if rec["verdict"].startswith("NA_"):
            continue
        for entry, erec in rec["entries"].items():
            if entry not in F.required_outputs(sid):
                continue
            v = check_entry(sid, entry, erec)
            if v.mode == FIXTURE and not v.produced:
                out.append((F.normalize_id(sid), entry))
    # A TUPLE, not the list built above: this answer is cached, and a cached
    # mutable would let one caller edit the population every later caller sees.
    return tuple(out)


#: vibe-ic#1457 — what it would COST this repository, in bytes, to carry the
#: entries the unevidenced cells declare.
#:
#: MEASURED, not asserted. See the 2026-08-15 note in :data:`UNEVIDENCED_CELLS`
#: for the figure this replaces and why an unchecked round number survived long
#: enough to be escalated as an owner decision. Pinned so that the population
#: moving, or a recorded size moving, is a NAMED event rather than a silent
#: change of subject.
_UNEVIDENCED_CLOSING_COST_BYTES = 1893

#: An entry the manifest records with no size. Returned instead of ``0`` so the
#: guard can tell "nobody measured it" from "it costs nothing" — folding the
#: first into the second is how a cost claim stops being falsifiable.
_SIZE_NOT_RECORDED = -1


def unevidenced_closing_cost() -> Tuple[int, Tuple[Tuple[str, str, int], ...]]:
    """``(total_bytes, [(step, entry, recorded_bytes), ...])`` for the class.

    Derived from :func:`unevidenced_entries` and the manifest's own
    ``size_bytes``, through the same :func:`check_entry` the cells use, so this
    can never cost a population the verdicts do not have.

    THE MANIFEST IS THE RIGHT SOURCE HERE, and that is worth stating because
    everything else in this module treats a manifest record as a claim about
    the past rather than evidence about today. It is not being used as evidence
    of production: the question is "how big is the artefact this step writes",
    the record is a real observation of a real file, and no verdict below
    depends on the answer. What the answer decides is whether a reader is
    entitled to call this class a repository-size problem.
    """
    rows: List[Tuple[str, str, int]] = []
    for sid, entry in unevidenced_entries():
        rec = step_record(sid)["entries"][entry]
        size = rec.get("size_bytes")
        rows.append((sid, entry,
                     int(size) if isinstance(size, int) and not isinstance(size, bool)
                     else _SIZE_NOT_RECORDED))
    total = sum(b for _, _, b in rows if b != _SIZE_NOT_RECORDED)
    return total, tuple(rows)


@needs_corpus
def test_d3_the_cost_of_closing_the_unevidenced_class_is_measured():
    """vibe-ic#1457 — the stated reason this class stays red is a NUMBER.

    WHY THIS IS A REAL DEFECT AND NOT BOOKKEEPING. The number was acted on.
    ``UNEVIDENCED_CELLS`` carried ">1 GB of DEFs against a 2.0 GB .git" as the
    reason these cells are not closed; #1457 quoted that reading back and
    escalated the class as "a repository-size decision, not an engineering
    one", where it has sat unresolved across several re-measurements of
    everything EXCEPT the figure holding it up. The measured cost is 386857 B.
    An estimate nobody can move is worse than a red cell, because the red cell
    at least says what would move it.

    THE PROPERTY. The cost of closing this class is a sum over the entries the
    class actually has, every term of it recorded, and it equals the pinned
    figure. Both halves are load-bearing: a total assembled out of terms that
    were never measured would be an estimate wearing a measurement's clothes,
    which is the exact failure this guard exists to end.

    THE DIRECTION IT RUNS IN. It asserts nothing about whether the class SHOULD
    be closed, and closing it does not need this test to pass — it needs a run
    tree. It asserts only that the cost is a measurement, so that the next
    person deciding is deciding on a number that came from the repository.
    """
    total, rows = unevidenced_closing_cost()

    unmeasured = [(sid, entry) for sid, entry, b in rows
                  if b == _SIZE_NOT_RECORDED]
    assert not unmeasured, (
        f"{len(unmeasured)} unevidenced entr(ies) have no recorded size, so "
        f"the cost of closing this class cannot be summed and any figure "
        f"quoted for it is an estimate:\n  "
        + "\n  ".join(f"step {a}: {b}" for a, b in unmeasured)
        + "\nMeasure the artefact on the run it came from and record "
          "`size_bytes`, or say in the record that it was never measured — do "
          "not let a missing measurement read as a zero."
    )

    assert total == _UNEVIDENCED_CLOSING_COST_BYTES, (
        f"the cost of closing the unevidenced class moved: measured {total} B "
        f"over {len(rows)} entr(ies), pinned "
        f"{_UNEVIDENCED_CLOSING_COST_BYTES} B.\n  "
        + "\n  ".join(f"step {s}: {e} = {b} B" for s, e, b in sorted(rows))
        + f"\nRe-pin {total} and say what moved: an entry joined or left the "
          f"class, or an artefact was re-measured. The figure is quoted in "
          f"UNEVIDENCED_CELLS as the reason these cells are not closed, so it "
          f"must not be allowed to drift away from the population it is about."
    )


def test_d3_the_closing_cost_guard_reddens_on_both_ways_of_being_wrong(
        monkeypatch):
    """PAIRED CONTROL: the guard above must be able to fail, twice over.

    A cost guard that cannot redden is the same thing as the round number it
    replaced. Both arms are driven against REAL entries of this commit, not
    synthetic strings, so what is exercised is the path the verdicts take.
    """
    real_entries = unevidenced_entries()
    assert real_entries, (
        "there is no unevidenced entry on this commit, so neither arm below "
        "measures anything — the control cannot be run vacuously")

    # ARM 1 — the population moves. Dropping one entry must move the total and
    # be reported as a moved cost, not absorbed.
    dropped = real_entries[0]
    monkeypatch.setattr(sys.modules[__name__], "unevidenced_entries",
                        lambda: tuple(e for e in real_entries if e != dropped))
    with pytest.raises(AssertionError) as exc:
        test_d3_the_cost_of_closing_the_unevidenced_class_is_measured()
    assert "the cost of closing the unevidenced class moved" in str(exc.value)
    monkeypatch.undo()

    # ARM 2 — a term goes unmeasured. It must be NAMED as unmeasured and must
    # not be quietly summed as zero, which would leave the total looking
    # smaller and still self-consistent.
    real_record = step_record
    blinded_sid, blinded_entry = dropped

    def _without_size(step_id):
        rec = real_record(step_id)
        if F.normalize_id(step_id) != F.normalize_id(blinded_sid):
            return rec
        patched = dict(rec)
        patched["entries"] = {
            k: ({kk: vv for kk, vv in v.items() if kk != "size_bytes"}
                if k == blinded_entry else v)
            for k, v in rec["entries"].items()
        }
        return patched

    monkeypatch.setattr(sys.modules[__name__], "step_record", _without_size)
    with pytest.raises(AssertionError) as exc2:
        test_d3_the_cost_of_closing_the_unevidenced_class_is_measured()
    msg = str(exc2.value)
    assert "have no recorded size" in msg, msg
    assert blinded_entry in msg, msg
    assert "the cost of closing the unevidenced class moved" not in msg, (
        f"an entry with NO recorded size was reported as a changed total — "
        f"the missing measurement was summed as zero, which is the "
        f"conflation this arm exists to prevent:\n{msg}")


def test_d3_the_unevidenced_remedy_is_only_promised_where_a_producer_exists():
    """vibe-ic#1452 — an UNEVIDENCED cell must name the remedy that CLOSES it.

    The verdict for an unevidenced entry ends in an instruction, and until
    #1452 it was the same instruction for all of them: commit or register a run
    tree. That is a claim about PRODUCIBILITY and nothing checked it.

    WHY THIS IS A REAL DEFECT AND NOT A WORDING NIT: it was acted on. #1452
    read this sentence off its red cells, concluded "the fix is repo content,
    not code", and proposed committing the external run trees the message
    names — a proposal a later measurement showed to be unsafe on disclosure
    grounds, and which for the no-producer entries could not have closed the
    cell even had it been safe.

    THE PROPERTY. No unevidenced entry may be told outright that a run tree
    closes it, and none may be left with no remedy at all. Both gaps are named
    and neither is promised — which gap a given entry has is measured by
    :func:`test_d3_the_unevidenced_population_is_split_by_which_gap_it_has`.

    THE DIRECTION THIS GUARD RUNS IN. It never asserts that any entry is
    unproducible: the oracles cannot see a write inside a container tool's TCL
    heredoc and say so. It asserts only that the module does not PROMISE a
    remedy it has no basis for. It deliberately does NOT consult
    :func:`producer_evidence`, so that the cheap guard over every cell stays
    cheap and the AST-index cost is paid once, by the split test that exists
    to pay it.
    """
    promised = []
    for sid, entry in unevidenced_entries():
        rec = step_record(sid)["entries"][entry]
        detail = check_entry(sid, entry, rec).detail
        if _RUN_TREE_REMEDY in detail:
            promised.append((sid, entry))
        elif "OPPOSITE remedies" not in detail:
            promised.append((sid, entry))
    assert not promised, (
        f"{len(promised)} UNEVIDENCED entr(ies) either promise "
        f"{_RUN_TREE_REMEDY!r} outright or name no remedy at all:\n  "
        + "\n  ".join(f"step {a}: {b}" for a, b in promised)
        + "\nCommitting a run tree that carries an artefact this commit cannot "
          "be shown to produce is not evidence of production — it is the A8 "
          "defect this module already refused. Name BOTH gaps instead, and "
          "leave which one applies to the measured split."
    )


#: vibe-ic#1349 — the UNEVIDENCED entries whose declared path lies outside
#: EVERY destination `benchmark_evidence_publish` stages, MEASURED on this
#: commit and pinned in both directions.
#:
#: THIS IS NOT A LIST OF UNPUBLISHABLE ARTEFACTS IN PRINCIPLE. The four
#: hand-staged reference trees DO carry paths under `phase3/stage3/` —
#: `routed.def`, `no_repair_needed.flag`, `clock_tree.rpt`, `pdn.done` — which is
#: exactly why the entries that resolve on them are green while these are not.
#: The claim is narrower and is about the PROGRAM: since the 2026-07-25
#: program-first publish directive, a cell is produced by
#: `benchmark_evidence_publish`, that program stages `_COPY_SUBTREES` plus the
#: signoff GDS, and none of these paths is inside either. So "run the flow and
#: publish the result" — the remedy `_TWO_GAPS_REMEDY` offers and the one #1349,
#: #1452 and #1457 each independently concluded was the fix — cannot close
#: these cells, and no amount of running the flow changes that.
#:
#: A cell LEAVING this pin is the good direction and needs a stated cause: the
#: publish scope widened (an owner call), the flow moved the declaration, or
#: the entry stopped being unevidenced. A cell JOINING it is a NEW declared
#: output the publish contract cannot carry, and is its own finding.
UNEVIDENCED_OUTSIDE_THE_PUBLISH_CONTRACT: Tuple[Tuple[str, str], ...] = (
    ("30", "phase3/stage3/spice/*.sp OR phase3/stage3/spice/*.spice OR "
           "sim_spice/*.sp"),
    ("32", "phase3/stage3/postroute_timing_repair/postroute_timing_repair_decision.json"),
)


@needs_corpus
def test_d3_the_run_tree_remedy_is_withdrawn_where_the_publisher_cannot_stage_it():
    """vibe-ic#1349 — do not offer a publish that cannot carry the artefact.

    :func:`test_d3_the_unevidenced_remedy_is_only_promised_where_a_producer_exists`
    holds the module to naming BOTH gaps. This holds it to the next thing: for
    the EVIDENCE gap the message says committing a run tree closes the cell,
    and for an entry outside the publish contract's staged scope that is a
    publish nobody can perform. Three issues concluded "the remedy is corpus
    publication" off this sentence; running the publisher would not have
    produced a cell carrying any of these six paths.

    BOTH DIRECTIONS, and the second is what stops this becoming a blanket
    clause: an entry INSIDE the scope must NOT carry it. A note appended to
    everything says nothing about anything.
    """
    measured = tuple(sorted(
        (sid, entry) for sid, entry in unevidenced_entries()
        if not publishable(entry)))
    assert measured == tuple(sorted(UNEVIDENCED_OUTSIDE_THE_PUBLISH_CONTRACT)), (
        f"the UNEVIDENCED-outside-the-publish-contract population changed.\n"
        f"  JOINED — a declared output the publish contract cannot carry: "
        f"{sorted(set(measured) - set(UNEVIDENCED_OUTSIDE_THE_PUBLISH_CONTRACT))}\n"
        f"  LEFT — say which: the publish scope widened, the flow moved the "
        f"declaration, or the entry is no longer unevidenced: "
        f"{sorted(set(UNEVIDENCED_OUTSIDE_THE_PUBLISH_CONTRACT) - set(measured))}"
    )

    missing, blanket = [], []
    for sid, entry in unevidenced_entries():
        detail = check_entry(sid, entry, step_record(sid)["entries"][entry]).detail
        says = "NOT AVAILABLE for this entry" in detail
        if not publishable(entry) and not says:
            missing.append((sid, entry))
        if publishable(entry) and says:
            blanket.append((sid, entry))
    assert not missing, (
        f"{len(missing)} UNEVIDENCED entr(ies) are still offered a run-tree "
        f"remedy the publish contract cannot deliver:\n  "
        + "\n  ".join(f"step {a}: {b}" for a, b in missing))
    assert not blanket, (
        f"{len(blanket)} PUBLISHABLE entr(ies) were told the remedy is "
        f"unavailable:\n  "
        + "\n  ".join(f"step {a}: {b}" for a, b in blanket)
        + "\nA clause appended to every entry carries no information.")


def test_d3_the_publish_scope_predicate_answers_both_ways():
    """The control: :func:`publishable` must be able to say YES and NO.

    Asserted against REAL declared entries of this commit rather than
    synthetic strings, so the predicate is exercised the way the verdicts
    exercise it. A classifier with one answer has not been shown to classify.
    """
    assert publishable("reports/phase3/spice_correlation.json")
    assert publishable("phase3/stage4/gds/*.gds"), (
        "the signoff GDS is staged by an explicit branch of publish(); a scope "
        "built from _COPY_SUBTREES alone would call the one artefact the GDS "
        "manifest is about unpublishable")
    assert not publishable("phase3/stage3/pnr/floorplan.def")

    # Any-of matches `resolve`: ONE publishable alternative is enough, because
    # that is the alternative a published cell would carry.
    assert publishable(
        "phase3/stage3/spice/correlation.json OR "
        "reports/phase3/spice_correlation.json")

    # ...and the scope is READ from the publish program, not restated here.
    prefixes, files = publish_scope()
    assert all(Path(str(s)).as_posix() in prefixes
               for s in _bep._COPY_SUBTREES), (prefixes, _bep._COPY_SUBTREES)
    assert all(f in files for f in _bep._COPY_FILES), (files, _bep._COPY_FILES)


#: EVERY declared ``required_outputs`` entry, in a cell this dimension ENFORCES,
#: that no cell ``benchmark_evidence_publish`` produces can carry.
#:
#: WHY THIS IS A SECOND PIN AND NOT A WIDER FIRST ONE.
#: :data:`UNEVIDENCED_OUTSIDE_THE_PUBLISH_CONTRACT` is the subset of THIS that
#: is ALSO unevidenced today, and being unevidenced is a property of whichever
#: corpus is bound — so that pin moves when the corpus does, and it is
#: ``@needs_corpus`` for exactly that reason. Being UNPUBLISHABLE is a property
#: of the flow declaration and the publish contract alone: no run root, no
#: corpus and no host enters it, which is why this one runs on every lane
#: including the blind one, where six of the eight cells it covers are red and
#: nothing tells the reader the other ten are standing on borrowed evidence.
#:
#: THAT IS THE THING THIS PIN EXISTS TO SAY. Measured on this commit, with a
#: corpus bound and every one of the 24 run through :func:`check_entry`:
#:
#:     16  PRODUCED [LIVE]
#:      6  NOT PRODUCED [FIXTURE]   <- exactly UNEVIDENCED_OUTSIDE_THE_PUBLISH_CONTRACT
#:      2  NOT PRODUCED [LIVE]      <- step 0.5ic, recorded UNPROVEN, so FIXTURE
#:                                     never applies and the other pin cannot
#:                                     see them however the corpus moves
#:
#: The SIXTEEN resolve against tracked artefacts under prefixes the publisher
#: does not stage — i.e. the pre-program hand-staged trees :data:`_PUBLISH_GAP`
#: names. Re-publishing those cells with the program instead of by hand does not
#: lose evidence that was merely mislaid; it takes sixteen entries from
#: evidenced to unevidenced in one commit, and the eight not-produced become
#: twenty-four. A population that can triple on a publish is one a reader has to
#: be told about BEFORE the publish, not after.
#:
#: (An earlier revision of this comment said "eighteen" and "twenty-four". Both
#: were arithmetic from the failing-cell list rather than from the entries: two
#: of step 0.5ic's four missing entries are unpublishable and they are not among
#: the six. Corrected against the per-entry measurement above.)
#:
#: It is a pin and not a count: a number measured on one day is the shape this
#: module refuses everywhere else.
DECLARED_OUTSIDE_THE_PUBLISH_CONTRACT: Tuple[Tuple[str, str], ...] = (
    ("0.5ic", "input/submission_template/slots/*.yaml OR "
              "input/submission_template/NO_TEMPLATE.txt OR "
              "input/submission_template/SELF_TAPEOUT.txt"),
    ("0.5ic", "input/submission_template/tapeout_declaration.json"),
    ("10", "phase3/stage3/sta/pre_pnr_timing.rpt"),
    ("15", "phase3/stage3/pnr/floorplan.def"),
    ("15", "phase3/stage3/pnr/pdn.tcl OR phase3/stage3/pnr/pdn.done"),
    ("16", "phase3/stage3/cts/clock_plan.json"),
    ("17", "phase3/stage3/pnr/placed.def"),
    ("18", "phase3/stage3/pnr/spare_cells.json"),
    ("19", "phase3/stage3/cts/clock_tree.rpt"),
    ("19", "phase3/stage3/pnr/post_cts.def"),
    ("20", "phase3/stage3/pnr/post_hold.def"),
    ("21", "phase3/stage3/pnr/routed.def"),
    ("21", "phase3/stage3/pnr/routed.drc.rpt"),
    ("22", "phase3/stage3/extracted/parasitic.spef OR "
           "phase3/stage3/extracted/*.spef"),
    ("23", "phase3/stage3/sta/post_route_timing.rpt"),
    ("29", "phase3/stage3/sim_postlayout/results.log OR "
           "phase3/stage3/sim_postlayout/pass.flag"),
    ("30", "phase3/stage3/spice/*.sp OR phase3/stage3/spice/*.spice OR "
           "sim_spice/*.sp"),
    ("32", "phase3/stage3/postroute_timing_repair/repair_log.json OR "
           "phase3/stage3/postroute_timing_repair/no_repair_needed.flag"),
    ("32", "phase3/stage3/postroute_timing_repair/postroute_timing_repair_decision.json"),
    ("34", "phase3/stage3/pnr/filled.def OR phase3/stage3/pnr/metal_fill.done"),
    ("38", "phase3/stage4/foundry_handoff/corner_test_vectors.json"),
    ("38", "phase3/stage4/foundry_handoff/mask_spec.json"),
    ("38", "phase3/stage4/foundry_handoff/scribe_line_layout.gds OR "
           "phase3/stage4/foundry_handoff/scribe_line_layout.PENDING_FOUNDRY.txt"),
    ("38", "phase3/stage4/foundry_handoff/wat_plan.json"),
)


#: Cell states that are a DETERMINATION about the step rather than an absence of
#: one. `NA` is a fact about the design and `WAIVED` is a registered decision
#: carrying evidence; both are answers. `NOT_MEASURED` is not — see below.
_STATES_THAT_DECIDED = ("NA", "WAIVED")


def _declared_outside_the_publish_contract() -> Tuple[Tuple[str, str], ...]:
    """Re-derived from the live flow yaml and the live publish scope.

    NOT_MEASURED IS NOT AN EMPTY POPULATION, and this filter used to read it as
    one. It said `matrix_cell_state(sid) == "ENFORCED"`, written when the grid
    had three states. The fourth state (owner ruling 2026-08-21) then took
    steps 15, 17, 19, 20, 30 and 32 out of ENFORCED, and nine declarations
    silently left this population with them — measured 15 against a pin of 24,
    with nothing JOINED.

    Every one of those nine is still declared by its step and is still outside
    the publish contract. NOT_MEASURED means WE DID NOT LOOK at whether the
    cell is enforced; it does not mean the step declares no gap. The
    declaration is a property of the STEP, the enforcement state is a property
    of OUR MEASUREMENT of it, and filtering the declared population on the
    second converts "not yet measured" into "nothing there" — the substitution
    this module exists to refuse.

    So the filter now excludes only the states that DECIDED. Owner ruling
    2026-08-22, with the direction MEASURED before it was taken:

        ENFORCED only          15  (the shipped filter: 9 LEFT, 0 JOINED)
        not NA and not WAIVED  24  (this: 0 LEFT, 0 JOINED -- the pin, exactly)
        no filter at all       40  (16 JOINED: NA and WAIVED cells, which ARE
                                    answers, so counting them would report a
                                    gap where a decision was recorded, and
                                    would move the pin to 40)

    Dropping the ENFORCED filter can only ever make this population LARGER, so
    nothing is re-greened by the change, and
    `test_d3_the_unevidenced_publish_gap_is_inside_the_declared_one` keeps its
    subset relation because DECLARED stays a superset.
    """
    return tuple(sorted(
        (F.normalize_id(sid), entry)
        for sid in F.step_ids()
        for entry in F.required_outputs(sid)
        if matrix_cell_state(sid) not in _STATES_THAT_DECIDED
        and not publishable(entry)))


def test_d3_every_enforced_declaration_the_publisher_cannot_stage_is_pinned():
    """No corpus. The declaration side of the publish gap, pinned so it cannot
    grow — or shrink — without somebody saying which.

    A step that declares a new output under a prefix the publisher does not
    stage joins this population the same minute the yaml changes, and a reader
    is told at that point rather than after a publish has taken the cell red.
    The reverse matters as much: an entry LEAVING means the publish scope
    widened, which is the evidence-policy call
    ``benchmark_evidence_publish``'s docstring defers, and it may not happen
    quietly.
    """
    measured = _declared_outside_the_publish_contract()
    pinned = tuple(sorted(DECLARED_OUTSIDE_THE_PUBLISH_CONTRACT))
    assert measured == pinned, (
        f"the ENFORCED-declaration-outside-the-publish-contract population "
        f"changed: measured {len(measured)}, pinned {len(pinned)}.\n"
        f"  JOINED — a step now declares an output no published cell can "
        f"carry: {sorted(set(measured) - set(pinned))}\n"
        f"  LEFT — say WHICH: the publish scope widened (an evidence-policy "
        f"call), the flow moved the declaration, or the cell stopped being "
        f"ENFORCED: {sorted(set(pinned) - set(measured))}"
    )


def test_d3_the_unevidenced_publish_gap_is_inside_the_declared_one():
    """No corpus on the pin side. The two publish-gap pins may not drift apart.

    :data:`UNEVIDENCED_OUTSIDE_THE_PUBLISH_CONTRACT` is by construction the
    subset of :data:`DECLARED_OUTSIDE_THE_PUBLISH_CONTRACT` that is also
    unevidenced. Nothing enforced that: two tuples maintained by hand, one
    corpus-gated and one not, drift, and the drift would show up as a message
    telling a reader an entry is unpublishable while the declaration pin says
    it is fine.

    Checked both ways round, because a subset assertion alone is satisfied by
    an EMPTY subset — which is what a corpus-gated pin decays to if its guard
    stops running.
    """
    declared = set(DECLARED_OUTSIDE_THE_PUBLISH_CONTRACT)
    unevidenced = set(UNEVIDENCED_OUTSIDE_THE_PUBLISH_CONTRACT)
    assert unevidenced <= declared, (
        f"{len(unevidenced - declared)} entr(ies) are pinned UNEVIDENCED-"
        f"outside-the-publish-contract but are not in the declaration pin: "
        f"{sorted(unevidenced - declared)}. One of the two is wrong about the "
        f"same publish scope."
    )
    assert unevidenced, (
        "UNEVIDENCED_OUTSIDE_THE_PUBLISH_CONTRACT is empty, so the subset "
        "assertion above proved nothing"
    )
    for sid, entry in unevidenced:
        assert not publishable(entry), (
            f"step {sid}: {entry!r} is pinned as outside the publish contract "
            f"and publishable() says it is inside it"
        )


#: The synthetic run the live binding below publishes. One artefact per scope
#: prefix so a prefix that has silently stopped being staged is visible, plus
#: one under `phase3/stage3/` — the prefix every entry in
#: :data:`UNEVIDENCED_OUTSIDE_THE_PUBLISH_CONTRACT` lives under.
_PUBLISH_PROBE_FILES = {
    "reports/audit/phase23_completion_audit.json": '{"verdict": "PASS"}',
    "RESULT.md": "# RESULT\n\n## VERDICT\n\n**PASS.** synthetic probe.\n",
    "provenance.jsonl": '{"step": "probe"}\n',
    "phase1/generated_docs/L1.json": '{"a": 1}',
    "phase2/stage2/synth/netlist.v": "module top(); endmodule\n",
    "phase3/reports/drc.rpt": "clean\n",
    "phase3/analog/probe/spec.json": "{}",
    "reports/phase3/sta.json": "{}",
    "phase3/stage4/gds/probe.gds": "GDSII-FAKE-STREAM-",
    # OUT of every staged subtree — the population this guard is about.
    "phase3/stage3/pnr/floorplan.def": "DESIGN probe ;\nEND DESIGN\n",
}


def test_d3_the_publish_scope_is_what_the_publisher_actually_stages(tmp_path):
    """BIND :func:`publish_scope` to what the publish PROGRAM really does.

    ``_PUBLISH_GDS_DEST`` is the one prefix this module writes down instead of
    importing, because ``publish()`` computes it inline and exports no
    constant. A written-down path is exactly the hand-copy this repository
    keeps removing, so it is not left as a claim: the real program is run over
    a synthetic CONVERGED run that carries one artefact per prefix, and the
    staged cell is asked which of them arrived.

    BOTH DIRECTIONS. Every in-scope artefact must be IN the cell — otherwise
    the predicate calls something publishable that the publisher drops, and
    the clause would be withheld from an entry that needs it. And the
    out-of-scope artefact must NOT be in the cell — otherwise the whole
    finding is wrong and the clause is a false statement about the contract.
    """
    run = tmp_path / "run"
    for rel, text in _PUBLISH_PROBE_FILES.items():
        p = run / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    # `benchmark_evidence_publish` REFUSES a run that cannot name the PDK
    # revision it signed off against (W6); this probe needs a STAGED cell to
    # read the contract off, so the run has to be publishable.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _pdk_revision_fixture as _pdk_fixture
    _pdk_fixture.write_run_pdk_revision(run)

    dest_root = tmp_path / "benchmark-data"
    proc = _pr.run(
        [sys.executable, str(F.PROGRAMS_DIR / "benchmark_evidence_publish.py"),
         "--run-dir", str(run), "--ic", "probeic", "--pdk", "probepdk",
         "--plugin-version", "0.0.0", "--dest-root", str(dest_root)],
        capture_output=True, text=True)
    assert proc.returncode == 0, (
        f"the publish probe did not stage a cell (rc={proc.returncode}); this "
        f"guard cannot say what the contract carries from a run it refused.\n"
        f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
    cell = dest_root / "ic" / "probeic" / "v0.0.0_probepdk"
    assert cell.is_dir(), f"no cell at {cell}: {proc.stdout[-2000:]}"

    arrived = {rel: (cell / rel).is_file() for rel in _PUBLISH_PROBE_FILES}
    wrong = {rel: got for rel, got in arrived.items()
             if got != publishable(rel)}
    assert not wrong, (
        f"publish_scope() disagrees with the publisher on {len(wrong)} "
        f"path(s) — {{path: landed_in_cell}} {wrong}. The predicate said "
        f"{ {r: publishable(r) for r in wrong} }. Either the publish contract "
        f"moved and the scope must be re-derived, or "
        f"{_PUBLISH_GDS_DEST!r} is no longer where publish() puts the signoff "
        f"GDS.\nstaged: {proc.stdout[-2000:]}")
    # Belt and braces on the half that carries the finding: the probe DEF is
    # the shape of all six pinned entries, and a cell that carried it would
    # refute the pin outright.
    assert not (cell / "phase3/stage3/pnr/floorplan.def").exists(), (
        "the publisher staged a phase3/stage3 artefact — "
        "UNEVIDENCED_OUTSIDE_THE_PUBLISH_CONTRACT is measuring a contract "
        "that no longer holds and must be re-derived")


#: vibe-ic#1452 — the UNEVIDENCED entries for which NO oracle this commit
#: carries can name a producer. MEASURED on this commit, not assumed, and
#: pinned so that a move in EITHER direction is a named event.
#:
#: THIS IS NOT A LIST OF UNPRODUCIBLE ARTEFACTS and must not be read as one.
#: The two oracles are the AST of ``programs/*.py`` and the run write-ledgers
#: tracked at HEAD, and d7's ``RESOLUTION_LIMITS`` states what neither can see.
#: The four ``*.def`` entries ARE produced — by OpenROAD, inside the EDA
#: container, from a TCL heredoc embedded as a Python string, which is exactly
#: the write position ``RESOLUTION_LIMITS`` names as invisible here. "The
#: oracle cannot see the producer" and "there is no producer" are different
#: findings and this pin exists to keep them apart.
#:
#: Step 32 is deliberately NOT in this list even though it was measured into it
#: before this change: ``phase3_one_shot_runner`` writes
#: ``postroute_timing_repair_decision.json`` through a drop-in atomic helper, a write
#: position the d7 detector could not see until vibe-ic#1452 taught it the
#: shadowing writers. The pin would have recorded a blind spot as a fact.
UNEVIDENCED_WITHOUT_A_NAMED_PRODUCER: Tuple[Tuple[str, str], ...] = (
    ("30", "phase3/stage3/spice/correlation.json OR "
           "reports/phase3/spice_correlation.json"),
)


@needs_corpus
def test_d3_the_unevidenced_population_is_split_by_which_gap_it_has():
    """Pin WHICH unevidenced entries have no producer, in both directions.

    The guard above is satisfied by the implementation choosing its own
    sentence, so on its own it could not tell anyone that the WORLD changed.
    This one measures the world: it recomputes the split from the commit and
    compares it to what was measured, so writing a producer for one of these
    entries and losing a producer for one that had one are both loud, named
    events.

    LEAVING THE PIN HAS TWO EXITS AND THEY NEED DIFFERENT REMEDIES. An entry in
    ``set(pinned) - set(measured)`` either gained a producer, or stopped being
    UNEVIDENCED at all — and a split OF the unevidenced cannot contain something
    that is not unevidenced. Naming only the first exit sends an author looking
    for a program that writes an artefact nothing needs to write any more.
    """
    measured = tuple(sorted(
        (sid, entry) for sid, entry in unevidenced_entries()
        if not producer_evidence(entry)))
    pinned = tuple(sorted(UNEVIDENCED_WITHOUT_A_NAMED_PRODUCER))
    still_unevidenced = set(unevidenced_entries())
    left = set(pinned) - set(measured)
    gained_producer = sorted(x for x in left if x in still_unevidenced)
    no_longer_unevidenced = sorted(x for x in left if x not in still_unevidenced)
    assert measured == pinned, (
        f"the UNEVIDENCED-without-a-producer population changed.\n"
        f"  GAINED A PRODUCER — still unevidenced, but something now writes it. "
        f"Delete from the pin and say which program: {gained_producer}\n"
        f"  NO LONGER UNEVIDENCED AT ALL — the entry left the population this "
        f"pin splits, so it cannot be in the split. Delete from the pin; "
        f"nothing writes it and nothing needs to: {no_longer_unevidenced}\n"
        f"  NEWLY in the no-producer class (a declared output whose producer "
        f"this commit no longer carries): {sorted(set(measured) - set(pinned))}"
    )


def test_d3_the_producer_oracle_answers_both_ways():
    """The control: :func:`producer_evidence` must be able to say YES and NO.

    A classifier that only ever returns one answer has not been shown to
    classify anything, and this one decides which remedy a red cell is told to
    follow. Both arms are asserted against REAL declared entries of this
    commit, not synthetic strings, so the oracle is exercised the way the
    verdicts exercise it.
    """
    yes = producer_evidence("phase3/stage3/postroute_timing_repair/postroute_timing_repair_decision.json")
    assert yes and "phase3_one_shot_runner" in yes.producers, yes
    no = producer_evidence("phase3/stage3/pnr/floorplan.def")
    assert not no.producers, no
    # ...and a NO must still disclose its reach, never read as a proven zero.
    assert "not a proof" in no.limit and "RESOLUTION_LIMITS" in no.limit, no

    # An any-of entry is produced when ANY alternative is, matching `resolve`.
    either = producer_evidence(
        "phase3/stage3/pnr/floorplan.def OR "
        "phase3/stage3/postroute_timing_repair/postroute_timing_repair_decision.json")
    assert either.producers == yes.producers, either


def test_d3_a_departure_from_the_pin_is_routed_to_the_REASON_it_left(monkeypatch):
    """PAIRED GUARD for the split above: the two exits must not be conflated.

    ``set(pinned) - set(measured)`` is silent about WHY an entry left, and the
    two reasons need opposite remedies. Driven by planting a pair that is NOT
    in :func:`unevidenced_entries`, and asserting the message routes it to the
    second exit and NOT the first.
    """
    ghost = ("M4", "reports/analog/mixed_signal/does_not_exist.json")
    assert ghost not in set(unevidenced_entries()), (
        "the planted pair is genuinely unevidenced, so it cannot exercise the "
        "'left the population' exit this test is about")
    monkeypatch.setattr(
        sys.modules[__name__], "UNEVIDENCED_WITHOUT_A_NAMED_PRODUCER",
        tuple(UNEVIDENCED_WITHOUT_A_NAMED_PRODUCER) + (ghost,))

    with pytest.raises(AssertionError) as exc:
        test_d3_the_unevidenced_population_is_split_by_which_gap_it_has()
    msg = str(exc.value)
    head, _, tail = msg.partition("NO LONGER UNEVIDENCED AT ALL")
    assert tail, f"the second exit is not named at all:\n{msg}"
    assert "does_not_exist.json" in tail, (
        f"an entry that LEFT the unevidenced population was not reported under "
        f"the exit it took:\n{msg}")
    assert "does_not_exist.json" not in head, (
        f"an entry that left the population was reported as having GAINED A "
        f"PRODUCER — the conflation this guard exists to prevent:\n{msg}")


def test_d3_untracked_artefacts_are_not_counted_as_produced():
    """#527 — the rule that makes the answer the same on every host.

    A build product the commit does not carry is a fact about one working
    tree. ``git clean -xdf`` deletes it; a second checkout of the same commit
    never had it; CI never sees it. Crediting it answers "does a file with
    this name exist on this machine", which is a different question from the
    one this dimension asks, and it answered that different question in the
    wrong direction: step 6 is waived ``xfail(strict=True)`` precisely because
    no reachable host can build an FPGA bitstream, and two untracked files in
    ``benchmark-data/ic/sha256/phase2/stage1/fpga/output_files/`` made it
    XPASS on the maintainer's checkout while every other host xfailed.

    Both directions are asserted: the untracked file is refused AND the same
    bytes at the same path are accepted once committed, so the rule rejects
    the un-committedness and not the path, the size or the glob.
    """
    with _probe_run_root("d3_untracked_") as (probe, commit):
        (probe / "reports").mkdir()
        art = probe / "reports" / "drc.rpt"
        art.write_text("x" * 4096)

        # Precondition: it is a real, non-empty, non-symlink file, so it clears
        # every OTHER admissibility rule and only trackedness can refuse it.
        assert art.is_file() and not art.is_symlink()
        assert art.stat().st_size == 4096

        hit, rej = resolve(probe, "reports/drc.rpt")
        assert hit is None, (
            f"an untracked build product was accepted as produced: {hit} — no "
            f"other checkout of this commit has that file"
        )
        assert rej.untracked == ("reports/drc.rpt (4096 B)",), rej
        assert rej.empty == () and rej.symlinked == (), rej

        # STAGED is still not carried by the commit. The index is a fact about
        # this working tree too — `git stash`, a reset, a crashed rebase all
        # change it — so admissibility is decided against HEAD, and a path that
        # is only `git add`-ed remains inadmissible.
        subprocess.run(["git", "add", "--", "reports/drc.rpt"], cwd=probe,
                       check=True, capture_output=True)
        tracked_under.cache_clear()
        hit, rej = resolve(probe, "reports/drc.rpt")
        assert hit is None, (
            f"a staged-but-uncommitted artefact was accepted as produced: "
            f"{hit} — no other checkout of HEAD has it either"
        )
        assert rej.untracked == ("reports/drc.rpt (4096 B)",), rej

        commit("reports/drc.rpt")
        hit, rej = resolve(probe, "reports/drc.rpt")
        assert hit is not None and hit.size_bytes == 4096, (hit, rej)
        assert rej.untracked == (), rej


def test_d3_live_production_is_handed_only_what_the_commit_carries():
    """``PRODUCED_LIVE`` must not be decided by the operator's working tree.

    The live proof copies a run root and runs the declared producer in the
    copy. A plain ``copytree`` drags every local build product in with it,
    which makes the proof depend on the machine twice over: a leftover copy of
    the TARGET makes ``produce_live`` report "already present" and kill a
    genuine cell, and a leftover INPUT can make a producer succeed that would
    fail for anyone who only has the commit. Copying the tracked set is what
    makes "this checkout's code produced it" mean the same thing everywhere.

    Measured 2026-07-28: all five live-produced entries still land from a
    tracked-only copy, so no cell was resting on a local leftover.
    """
    with _probe_run_root("d3_copy_") as (probe, commit):
        (probe / "inputs").mkdir()
        (probe / "inputs" / "committed.txt").write_text("in the commit\n")
        commit("inputs/committed.txt")
        (probe / "inputs" / "leftover.txt").write_text("only on this machine\n")
        (probe / "stale_output.json").write_text("{}\n")

        with tempfile.TemporaryDirectory(prefix="d3_copy_dst_") as td:
            dst = Path(td) / "proj"
            n = _copy_tracked(probe, dst)
            assert n == 1, f"copied {n} files, expected exactly the tracked one"
            assert (dst / "inputs" / "committed.txt").is_file()
            assert not (dst / "inputs" / "leftover.txt").exists(), (
                "an untracked input was handed to the producer; the live "
                "production proof would then depend on this working tree"
            )
            assert not (dst / "stale_output.json").exists(), (
                "an untracked leftover of a producer's own output was copied; "
                "produce_live would report 'already present' and lose a cell "
                "that is in fact fine"
            )


def test_d3_produce_live_is_not_decided_by_the_working_tree(monkeypatch):
    """The same rule asserted through ``produce_live`` itself, not its helper.

    Mutation control, 2026-07-28: reverting ``produce_live`` to
    ``shutil.copytree`` while leaving ``_copy_tracked`` correct survived the
    whole suite, because the test above exercises the helper and nothing
    exercised the CALL. A rule that only the unused half of a pair obeys is
    not a rule, so this drives the real entry point against a real producer.

    The probe is a tracked-only clone of an actual base run root, committed,
    plus an UNTRACKED stale copy of the very artefact the producer writes.
    With a whole-tree copy that stale file arrives first and ``produce_live``
    reports "already present", losing a cell that is in fact fine — and, in
    the other direction, an untracked INPUT would let a producer succeed here
    that fails for everyone who only has the commit.
    """
    candidates = [
        (sid, entry, erec)
        for cell in cells_for(DIM)
        for sid in [cell.step_id]
        for entry, erec in step_record(sid)["entries"].items()
        if erec.get("status") == "PRODUCED_LIVE"
        and erec.get("base_run") in run_roots()
    ]
    if not candidates:
        pytest.skip("no live-produced entry has a run root on this tree")
    sid, entry, erec = candidates[0]
    src = run_roots()[erec["base_run"]].path

    with _probe_run_root("d3_prodlive_") as (probe, commit):
        n = _copy_tracked(src, probe)
        assert n, f"{src} carries nothing tracked; probe would be inert"
        # -f because the copied set can itself include a tracked `.gitignore`
        # whose rules would otherwise drop files that ARE in the source commit.
        subprocess.run(["git", "add", "-f", "--", "."], cwd=probe, check=True,
                       capture_output=True)
        commit()

        stale = probe / erec["writes"]
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text("stale local leftover from an earlier run\n")
        assert not is_tracked(probe, erec["writes"]), (
            "the stale artefact ended up tracked; the probe proves nothing")

        monkeypatch.setattr(
            sys.modules[__name__], "run_roots",
            lambda: {erec["base_run"]: RunRoot(erec["base_run"], _IN_REPO_KIND,
                                               probe)})
        produced, detail = produce_live(sid, entry, erec)

    assert produced, (
        f"step {sid} {entry!r} could not be produced live once an UNTRACKED "
        f"leftover of {erec['writes']!r} sat in the working tree: {detail}. "
        f"The producer must be handed the tree a fresh clone would give it."
    )


def test_d3_a_directory_outside_any_repository_yields_no_evidence():
    """The degenerate case of the same rule, stated so it cannot regress.

    An unpacked archive, a scratch copy, a downloaded run tree: a directory
    that is not inside a git work tree carries nothing this repository can
    vouch for, so ``git ls-tree`` fails there and NOTHING in it is admissible
    — rather than everything in it being admissible, which is what a
    permissive fallback would silently do.
    """
    with tempfile.TemporaryDirectory(prefix="d3_norepo_") as td:
        probe = Path(td) / "probe"
        (probe / "reports").mkdir(parents=True)
        (probe / "reports" / "drc.rpt").write_text("x" * 512)
        assert tracked_under(probe) == frozenset(), (
            "a non-repository directory reported tracked paths")
        hit, rej = resolve(probe, "reports/drc.rpt")
        assert hit is None, f"evidence accepted from outside any repo: {hit}"
        assert rej.untracked == ("reports/drc.rpt (512 B)",), rej


def test_d3_symlinked_artefacts_are_not_counted_as_produced():
    """The companion rule, exercised the same way.

    ``Path.is_file()`` and ``Path.stat()`` both FOLLOW a symlink, so a
    canonical output path that is merely an alias for a file produced
    elsewhere — most damagingly for one of the project's own INPUTS — is
    credited with the target's size and reads as produced. That is the exact
    anti-pattern two shipped gates already ban
    (``chip_gds_canonical_real_file_check.py``: "gds_size_check follows
    symlinks transparently and reports the target's size, so a symlink masking
    a missing tape-out artefact passes audit";
    ``canonical_path_symlink_forbid_check.py``, whose forbidden trees include
    ``analog/hardmacro/**`` and ``phase3/stage4/**``), and this module was
    reproducing it: step A8's ``.gds`` resolved to a 37 MB hit that is a
    symlink into ``design_data/gds/``, the design's input layout.

    A symlink is never evidence that THIS step wrote those bits, so it is
    rejected wherever it appears — and reported as its own category, because
    "aliased to an input" and "absent" are different findings.
    """
    with _probe_run_root("d3_symlink_") as (probe, commit):
        (probe / "reports").mkdir()
        (probe / "elsewhere").mkdir()
        real = probe / "elsewhere" / "source.rpt"
        real.write_text("x" * 4096)
        alias = probe / "reports" / "drc.rpt"
        alias.symlink_to(Path("..") / "elsewhere" / "source.rpt")
        # Committed, so trackedness cannot be what refuses it below: a symlink
        # the commit DOES carry is still not evidence that this step wrote
        # those bits.
        commit("reports/drc.rpt", "elsewhere/source.rpt")

        # Precondition: the alias resolves and would be credited 4096 B by any
        # link-following presence check, so the rejection below is load-bearing.
        assert alias.is_file() and alias.stat().st_size == 4096
        assert is_tracked(probe, "reports/drc.rpt")

        hit, rej = resolve(probe, "reports/drc.rpt")
        assert hit is None, (
            f"a symlink was accepted as a produced artefact: {hit} — it would "
            f"have been credited its target's {alias.stat().st_size} bytes")
        assert rej.empty == () and rej.untracked == (), rej
        assert rej.symlinked == ("reports/drc.rpt -> ../elsewhere/source.rpt",), \
            rej

        # ...and a real file at the same path is still accepted, so the rule
        # rejects the aliasing rather than the path.
        alias.unlink()
        alias.write_text("x" * 4096)
        commit("reports/drc.rpt")
        hit, rej = resolve(probe, "reports/drc.rpt")
        assert hit is not None and hit.size_bytes == 4096, (hit, rej)


# ──────────────────────────────────────────────────────────────────────
# THE WRITE LEDGER — controls
# ──────────────────────────────────────────────────────────────────────
#: The step and spec the ledger controls below drive. Step 13 declares a FLAT
#: ``reports/lec.json``, which is what makes it the right subject: a flat
#: ``reports/`` pattern is exactly the shape ``_glob_first`` serves from its
#: ``reports/<subdir>/`` fallback, so "a file of that name exists somewhere
#: under reports/" and "step 13 wrote reports/lec.json" come apart there.
_LEDGER_PROBE_STEP = "13"
_LEDGER_PROBE_ENTRY = "reports/lec.json"
_LEDGER_PROBE_DECOY = "reports/phase3/lec.json"


def _ledger_probe_tree(probe: Path) -> None:
    """A minimal but REAL run tree: runner marker + a provenance log."""
    (probe / "reports" / "orchestrator").mkdir(parents=True, exist_ok=True)
    (probe / "provenance.jsonl").write_text(json.dumps({
        "timestamp": "2026-08-06T00:00:00Z", "tool": "probe_tool",
        "argv": ["probe_tool"], "inputs": {}, "outputs": {},
        "exit_code": 0, "duration_s": 1.0,
    }) + "\n", encoding="utf-8")


def _emit_ledger(probe: Path) -> Dict:
    """Run the REAL emitter over *probe* and return its result dict.

    The ledger under test is never hand-written here. If ``step_write_ledger``
    changes what it records, these controls change with it or they break —
    which is the point: a control that asserts against a fixture of the
    record's shape stops testing the record.
    """
    write_ledger.cache_clear()
    res = _swl.emit(probe)
    assert res.get("ok"), res
    return res


def test_d3_the_write_ledger_binds_production_to_the_step(monkeypatch):
    """THE CONTROL for "nothing reads the per-step output folder".

    ``resolve`` takes a PATTERN. ``_glob_first`` answers "does something
    matching it exist under this root", and for a ``reports/`` pattern it will
    happily answer YES from ``reports/<subdir>/`` when the declared path itself
    was never written. That is the substitution this campaign keeps finding: a
    file that exists standing in for a step that produced one.

    ``step_write_ledger`` records the other half — what the run ACTUALLY
    wrote, per step — and until now no gate read it
    (``grep -rl 'write_ledger' programs/*.py flow/*.yaml`` returned only the
    two programs that WRITE it).

    FORWARD — the run wrote ``reports/phase3/lec.json`` and never wrote step
    13's declared ``reports/lec.json``. The ledger says so, in its own words
    (``declared_output_not_produced`` / ``absent``). The pre-fix ``resolve``
    returns the decoy and the cell reads produced; after, it returns nothing
    and names the ledger. **This assertion fails against the byte-identical
    pre-change file.**

    REVERSE A — the SAME probe with the declared path really written and the
    ledger re-emitted: produced again. A rule that fires on everything is not
    a rule, and this is what stops "has a ledger" degenerating into "always
    red".

    REVERSE B — BACKWARD COMPATIBILITY. Delete the ledger, change nothing
    else: the decoy resolves again, exactly as it did before this change, and
    the reason is stated in the note rather than left silent. Passes against
    the pre-change file too, by construction.

    REVERSE C — the ledger is consulted PER STEP. Asked without a step id (the
    dormancy probe and the waiver-premise guards ask that way on purpose), the
    same call still resolves the decoy: the ledger sharpens a step's question,
    it does not censor the project-wide one.
    """
    assert _LEDGER_PROBE_ENTRY in F.required_outputs(_LEDGER_PROBE_STEP), (
        f"step {_LEDGER_PROBE_STEP} no longer declares {_LEDGER_PROBE_ENTRY!r}; "
        f"this control is stale and must be re-pointed at a flat `reports/` "
        f"entry the flow actually declares")

    with _probe_run_root("d3_ledger_bind_") as (probe, commit):
        _ledger_probe_tree(probe)
        decoy = probe / _LEDGER_PROBE_DECOY
        decoy.parent.mkdir(parents=True, exist_ok=True)
        decoy.write_text('{"equivalent": true}\n')
        commit(_LEDGER_PROBE_DECOY)
        assert not (probe / _LEDGER_PROBE_ENTRY).exists()

        # Precondition: the flow's OWN resolver DOES serve the decoy for the
        # declared pattern. Without this the control would prove nothing.
        assert _GLOB_FIRST(probe, _LEDGER_PROBE_ENTRY) == [_LEDGER_PROBE_DECOY], (
            "the reports/<subdir>/ fallback no longer serves the decoy, so "
            "this control no longer exercises the substitution it exists for")
        hit, _ = resolve(probe, _LEDGER_PROBE_ENTRY)
        assert hit is not None and hit.path == _LEDGER_PROBE_DECOY, hit

        _emit_ledger(probe)
        commit(LEDGER_REL)

        say = ledger_says(probe, _LEDGER_PROBE_STEP, _LEDGER_PROBE_ENTRY)
        assert say.consulted, say
        assert say.unwritten is not None, (
            f"the emitter no longer records step {_LEDGER_PROBE_STEP}'s "
            f"{_LEDGER_PROBE_ENTRY!r} as never written, so there is nothing "
            f"for this control to bind to: {say}")

        # ---- FORWARD ------------------------------------------------
        hit, rej = resolve(probe, _LEDGER_PROBE_ENTRY, _LEDGER_PROBE_STEP)
        assert hit is None, (
            f"a file that step {_LEDGER_PROBE_STEP} never wrote was accepted "
            f"as its produced artefact: {hit}. The run's own write ledger "
            f"records {_LEDGER_PROBE_ENTRY!r} as "
            f"{say.unwritten.get('reason')!r}; 'a matching file exists "
            f"somewhere in the project' is not 'this step produced it'.")
        assert len(rej.unwritten) == 1 and _LEDGER_PROBE_DECOY in rej.unwritten[0], rej
        assert "write ledger" in rej.unwritten[0], rej
        assert rej.empty == () and rej.symlinked == () and rej.untracked == (), (
            "the ledger refusal must be its own category — 'absent', '0-byte', "
            "'aliased' and 'this step never wrote it' are different findings: "
            f"{rej}")

        # ---- REVERSE A: write it for real, re-emit, must go green ----
        (probe / _LEDGER_PROBE_ENTRY).write_text('{"equivalent": true}\n')
        commit(_LEDGER_PROBE_ENTRY)
        _emit_ledger(probe)
        commit(LEDGER_REL)
        hit, rej = resolve(probe, _LEDGER_PROBE_ENTRY, _LEDGER_PROBE_STEP)
        assert hit is not None and hit.path == _LEDGER_PROBE_ENTRY, (
            f"the step's own ledger records the write and the verdict did not "
            f"move: {hit} {rej}. A ledger-bound cell must still be able to go "
            f"green, or it is unfalsifiable in the other direction.")

        # ---- REVERSE B: no ledger at all -> exactly today's behaviour -
        (probe / _LEDGER_PROBE_ENTRY).unlink()
        (probe / LEDGER_REL).unlink()
        commit()
        subprocess.run(["git", "rm", "-q", "--cached", "--",
                        _LEDGER_PROBE_ENTRY, LEDGER_REL],
                       cwd=probe, check=True, capture_output=True,
                       env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull,
                            "GIT_CONFIG_SYSTEM": os.devnull})
        commit()
        write_ledger.cache_clear()
        say = ledger_says(probe, _LEDGER_PROBE_STEP, _LEDGER_PROBE_ENTRY)
        assert not say.consulted and "no " + LEDGER_REL in say.note, say
        hit, rej = resolve(probe, _LEDGER_PROBE_ENTRY, _LEDGER_PROBE_STEP)
        assert hit is not None and hit.path == _LEDGER_PROBE_DECOY, (
            f"a run that left NO write ledger must be decided exactly as it "
            f"was before this change; it was not: {hit} {rej}")

        # ---- REVERSE C: no step id -> the project-wide question ------
        _emit_ledger(probe)
        commit(LEDGER_REL)
        hit, _ = resolve(probe, _LEDGER_PROBE_ENTRY)
        assert hit is not None and hit.path == _LEDGER_PROBE_DECOY, (
            "asked WITHOUT a step id the resolver must still answer the "
            "project-wide question — the NA-dormancy probe and the waiver "
            "premises depend on it, and a ledger that could suppress an "
            "artefact there would be a way around a rule, not a sharpening "
            f"of one: {hit}")
        _probe_only(monkeypatch, "probe", probe)   # keep run_roots() honest


def test_d3_a_write_ledger_the_commit_does_not_carry_is_not_consulted():
    """An untracked ledger may not decide a cell — and must SAY so.

    The ledger can only make a cell redder. An untracked one would therefore
    let ``git clean -xdf`` change a verdict and let two checkouts of one
    commit disagree — #527's defect arriving from the opposite direction, and
    the reason this module refuses an untracked ARTEFACT too.

    Both directions are asserted: untracked -> not consulted and the decoy
    still resolves; committed -> consulted and the decoy is refused. So the
    rule is not "ledgers never bind", it is "a ledger binds once the
    repository carries it".
    """
    with _probe_run_root("d3_ledger_track_") as (probe, commit):
        _ledger_probe_tree(probe)
        decoy = probe / _LEDGER_PROBE_DECOY
        decoy.parent.mkdir(parents=True, exist_ok=True)
        decoy.write_text('{"equivalent": true}\n')
        commit(_LEDGER_PROBE_DECOY)
        _emit_ledger(probe)          # written, NOT committed

        say = ledger_says(probe, _LEDGER_PROBE_STEP, _LEDGER_PROBE_ENTRY)
        assert not say.consulted, say
        assert "NOT tracked at HEAD" in say.note, say
        hit, _ = resolve(probe, _LEDGER_PROBE_ENTRY, _LEDGER_PROBE_STEP)
        assert hit is not None, (
            "an UNTRACKED ledger changed a verdict: the colour of this cell "
            "would then depend on whether somebody had run step_write_ledger "
            "in their working tree")

        commit(LEDGER_REL)
        write_ledger.cache_clear()
        say = ledger_says(probe, _LEDGER_PROBE_STEP, _LEDGER_PROBE_ENTRY)
        assert say.consulted, say
        hit, rej = resolve(probe, _LEDGER_PROBE_ENTRY, _LEDGER_PROBE_STEP)
        assert hit is None and rej.unwritten, (hit, rej)


def test_d3_the_write_ledger_can_only_subtract_evidence():
    """The ledger must never become a way around the evidence rules.

    A ledger is a claim by the run about itself. If a cell could go green
    because a ledger SAYS a step wrote something, the zero-byte rule, the
    symlink rule and the trackedness rule would all be bypassable by writing a
    JSON file. So the ledger is consulted only after those rules have already
    refused, and it is asserted here on all three at once: for each, the
    ledger records the path as PRODUCED (the emitter's own residual is empty
    for that spec) and ``resolve`` still refuses, under the ORIGINAL category
    rather than a ledger one.
    """
    entry = _LEDGER_PROBE_ENTRY
    for label, make in (
        ("zero_byte", lambda p: p.write_text("")),
        ("symlink", lambda p: p.symlink_to(Path("..") / "elsewhere" / "src.json")),
        ("untracked", lambda p: p.write_text('{"equivalent": true}\n')),
    ):
        with _probe_run_root(f"d3_ledger_sub_{label}_") as (probe, commit):
            _ledger_probe_tree(probe)
            (probe / "elsewhere").mkdir()
            (probe / "elsewhere" / "src.json").write_text('{"x": 1}\n')
            target = probe / entry
            target.parent.mkdir(parents=True, exist_ok=True)
            make(target)
            if label != "untracked":
                commit(entry, "elsewhere/src.json")
            else:
                commit("elsewhere/src.json")
            _emit_ledger(probe)
            commit(LEDGER_REL)

            say = ledger_says(probe, _LEDGER_PROBE_STEP, entry)
            assert say.consulted, say
            if label == "untracked":
                # The ledger DOES record this one as produced — it has no
                # notion of trackedness. That is exactly why the rule below
                # has to run first.
                assert entry in say.produced_rels, say
            hit, rej = resolve(probe, entry, _LEDGER_PROBE_STEP)
            assert hit is None, (
                f"the {label} rule was bypassed once a write ledger recorded "
                f"the path: {hit}. The ledger answers 'did this step write "
                f"it', never 'is this evidence'.")
            assert rej.unattributed == (), (
                f"the {label} case must be refused by its OWN rule, not "
                f"re-labelled as an attribution problem: {rej}")


def test_d3_an_artefact_the_run_never_wrote_is_not_attributed_to_the_step():
    """The second half of the binding: a file that appeared AFTER the run.

    The ledger records what the run wrote. An artefact dropped at a declared
    path afterwards satisfies every other rule in this module — it is a real,
    non-empty, committed file at exactly the declared path — and it is still
    not something the step produced. Before the ledger there was no way to
    tell the two apart; ``Rejected.unattributed`` is where they separate.

    The reverse case is the same probe with the ledger RE-EMITTED after the
    file landed: now the run's record does cover it and it counts again. So
    the rule refuses an unattributed path, not a late one.
    """
    entry = _LEDGER_PROBE_ENTRY
    with _probe_run_root("d3_ledger_attr_") as (probe, commit):
        _ledger_probe_tree(probe)
        target = probe / entry
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"equivalent": true}\n')
        commit(entry)
        _emit_ledger(probe)
        commit(LEDGER_REL)
        hit, rej = resolve(probe, entry, _LEDGER_PROBE_STEP)
        assert hit is not None, (hit, rej)   # baseline: the run wrote it

        # Now REMOVE it from the ledger's world by rewriting the ledger from a
        # tree that does not have it, then put the file back. The record is
        # the emitter's own, taken from a real observation — only the order of
        # events is arranged.
        target.unlink()
        _emit_ledger(probe)
        target.write_text('{"equivalent": true}\n')
        commit(entry, LEDGER_REL)
        write_ledger.cache_clear()

        hit, rej = resolve(probe, entry, _LEDGER_PROBE_STEP)
        assert hit is None and rej.unwritten, (
            f"a file the run's own ledger does not record this step as having "
            f"written was still credited to it: {hit} {rej}")

        _emit_ledger(probe)
        commit(LEDGER_REL)
        hit, rej = resolve(probe, entry, _LEDGER_PROBE_STEP)
        assert hit is not None, (
            f"re-emitting the ledger over a tree that HAS the artefact must "
            f"make it count again: {hit} {rej}")


def ledger_population() -> Tuple[Dict[str, str], Dict[str, str]]:
    """``(carried, consulted)`` — the ledger population, DERIVED TWICE.

    ``carried``   run-root label -> the ledger path THE COMMIT carries there.
    ``consulted`` run-root label -> :func:`write_ledger`'s admitting sentence.

    This used to be a hand-written ``LEDGER_BOUND_ROOTS = ()`` compared against
    the measurement. It was true when it was written and it could not stay
    true: a literal population is a statement about the tree on the day
    somebody typed it, and this repository has been bitten by hardcoded
    populations repeatedly. Worse, an empty literal cannot tell the two things
    it most needs to distinguish apart — "no ledger is committed" and "a ledger
    IS committed and this dimension silently refuses it" both measure ``()``
    and both pass ``() == ()``. The second is the binding dying quietly, which
    is the whole failure class the binding was built for.

    So both sides are derived and they are derived from DIFFERENT questions:

    * ``carried`` asks the COMMIT, through :func:`tracked_under`, whether the
      run root carries :data:`LEDGER_REL` at all. It knows nothing about
      schemas, rows or symlinks;
    * ``consulted`` asks :func:`write_ledger`, which applies all four
      admissibility rules and returns a sentence either way.

    Neither can go stale, and a disagreement between them is the event that
    matters: a root in ``carried`` and not in ``consulted`` is a committed
    ledger nothing reads.
    """
    carried: Dict[str, str] = {}
    consulted: Dict[str, str] = {}
    for label, rr in run_roots().items():
        if is_tracked(rr.path, LEDGER_REL):
            carried[label] = f"{rr.path.name}/{LEDGER_REL}"
        led, note = write_ledger(rr.path)
        if led is not None:
            consulted[label] = note
    return carried, consulted


def ledger_staleness(root: Path) -> Tuple[str, ...]:
    """Every claim a COMMITTED ledger at *root* makes that its own commit
    refutes. Empty means the record still describes the tree it ships in.

    A ledger is a SNAPSHOT of a tree, and the tree it snapshots is in the
    commit — where it moves. A follow-up commit lands a missing artefact; a
    re-publish stages a newer run. :func:`resolve` never re-checks the
    snapshot and the binding only ever SUBTRACTS, so a ledger that has gone
    stale refuses a real, non-empty, tracked file at exactly the declared path
    and quotes itself as the reason.

    MEASURED 2026-08-06 on a staged copy of ``spm/v1.5.66_gf180mcuD`` — see
    the module docstring, and
    ``test_d3_a_committed_ledger_can_be_refuted_by_its_own_commit``, which is
    the control that this function finds the stale claim it is written to find
    and reports nothing on a freshly emitted one.

    The check is the LEDGER'S OWN D3 finding put back to the tree: for every
    spec the ledger records as never written, ask :func:`resolve` with NO step
    id — the pre-ledger question, "does the commit carry a real artefact at
    this spec" — and report every YES. That direction only; a ledger that
    records a spec as produced when the file has since been deleted makes the
    cell redder through the unchanged rules and needs no help from here.

    THE REMEDY THIS MESSAGE NAMES — AND THE ONE IT USED TO (#1475)
    --------------------------------------------------------------
    It used to end "re-emit the ledger over the tree as it now is". That is
    true of the probe this function is controlled on, where the probe IS the
    tree the emitter walked, and it is MEASURED FALSE of a published cell.
    A cell is a git checkout, so ``step_write_ledger.mtime_fidelity`` sees one
    flattened mtime, correctly WITHHOLDS the run window and every time-derived
    conclusion, and the "repair" replaces a detectably stale record with an
    empty one. Measured on this repository's own published cell and reverted:

        field                        published    re-emitted over the checkout
        counts.recorded                    513                             366
        counts.in_run_window               489                               0
        residual.written_never_declared    384                               0
        residual.unwitnessed_writes         50                               0

    Three attempts followed the old prescription before it was withdrawn, so
    the message says the working remedy instead: run the SAME emitter against
    the RUN DIRECTORY, whose mtimes are the run's own, and publish the capture
    that POSTDATES every write the cell carries. When that tree is gone there
    is no honest repair from the checkout and the record has to be withdrawn —
    :func:`write_ledger` already announces that degrade, so nothing goes
    silent. Hand-editing rows out of a machine-emitted record is neither, and
    is never the answer: it makes a detectably stale claim undetectably
    fabricated.

    ``test_d3_the_stale_ledger_message_names_a_remedy_the_emitter_can_deliver``
    pins that, because a prescription nothing checks is how this one drifted.
    """
    led, _note = write_ledger(root)
    if led is None:
        return ()
    problems: List[str] = []
    for step_id, row in sorted(led.rows.items()):
        for finding in (row.get("findings") or ()):
            if not isinstance(finding, dict):
                continue
            if finding.get("dimension") != "D3" \
                    or finding.get("rule") != _LEDGER_D3_RULE:
                continue
            spec = str(finding.get("spec"))
            hit, _rej = resolve(root, spec)          # no step id: pure presence
            if hit is not None:
                problems.append(
                    f"step {step_id} spec {spec!r}: the ledger says NOT WRITTEN "
                    f"({finding.get('reason')}) but the commit that carries the "
                    f"ledger also carries {hit.path} ({hit.size_bytes} B, a "
                    f"regular file tracked at HEAD). The record is stale and "
                    f"this dimension would refuse a real artefact on its word "
                    f"— re-emit with the shipped emitter AT THE RUN DIRECTORY, "
                    f"whose mtimes are the run's, and publish the capture that "
                    f"POSTDATES this write. Re-emitting over this checkout is "
                    f"measured to EMPTY the record rather than correct it "
                    f"(flattened mtimes -> the emitter withholds the run "
                    f"window and every time-derived conclusion), and editing "
                    f"the rows by hand makes a detectably stale claim "
                    f"undetectably fabricated. If the run directory is gone, "
                    f"WITHDRAW the record: this dimension then answers exactly "
                    f"as it did before the ledger, and says so")
    return tuple(problems)


def test_d3_the_write_ledger_population_is_derived_from_the_commit():
    """Backward compatibility, stated rather than assumed — and re-derived.

    "A run with no ledger keeps today's behaviour" is only honest if a reader
    can see WHICH runs those are and WHY. Four assertions, and the second is
    the one the old pinned-empty tuple could not make.
    """
    carried, consulted = ledger_population()
    why = {label: write_ledger(rr.path)[1] for label, rr in run_roots().items()}

    # 1. Nothing is consulted that the commit does not carry. This is
    #    `write_ledger` rule 2 asked from the outside: if it ever passed, a
    #    verdict would be a property of one working tree (#527).
    ghost = sorted(set(consulted) - set(carried))
    assert not ghost, (
        f"this dimension consults a write ledger the commit does not carry at "
        f"{ghost}. `git clean -xdf` would change a cell's colour and two "
        f"checkouts of one commit would disagree.\n"
        f"  per root: {json.dumps(why, indent=2)}")

    # 2. Nothing the commit carries is silently refused. THE HOLE THE OLD PIN
    #    HAD: `LEDGER_BOUND_ROOTS = ()` measured `()` both when no ledger was
    #    committed and when one was committed with a schema this module does
    #    not know, and passed either way — the binding dead and nobody told.
    dead = sorted(set(carried) - set(consulted))
    assert not dead, (
        f"the commit carries a write ledger under {dead} and this dimension "
        f"does NOT consult it, so the binding is inert exactly where somebody "
        f"published a record to make it fire.\n"
        f"  reason, from write_ledger itself: "
        + json.dumps({k: why[k] for k in dead}, indent=2)
        + "\nEither fix the record or delete it; a ledger nothing reads is the "
          "failure this binding exists to end.")

    # 3. Every degrade is a sentence. A cell that quietly falls back to the
    #    pre-ledger behaviour is indistinguishable from one that was checked.
    for label, note in why.items():
        assert note and note.strip(), (
            f"run root {label!r} has no stated ledger reason; a degrade to "
            f"the pre-ledger behaviour must never be silent")

    # 4. Any ledger that IS committed must still be TRUE OF ITS OWN COMMIT.
    #    NOT vacuous: a record IS committed, and this assertion has already
    #    caught a real one (#1475) — a mid-run capture published beside the
    #    finished tree, denying four artefacts the same commit carried. The
    #    guard's own bidirectional control is
    #    `test_d3_a_committed_ledger_can_be_refuted_by_its_own_commit`.
    for label in sorted(consulted):
        stale = ledger_staleness(run_roots()[label].path)
        assert not stale, (
            f"the committed write ledger under {label!r} is REFUTED by the "
            f"commit that carries it:\n  " + "\n  ".join(stale))


def _staged_root_with_a_real_ledger(src: Path, probe: Path, commit) -> Ledger:
    """Stage *src*'s COMMITTED tree into probe repo *probe*, emit the REAL
    ledger there, commit it, and return the admitted record.

    Tracked-only, via :func:`_copy_tracked`: the ledger has to describe the
    tree a fresh clone would get, not this operator's build products. The
    emitter is ``step_write_ledger`` itself — a hand-written record here would
    stop testing the record.
    """
    rels = [rel for rel in sorted(tracked_under(src))
            if (src / rel).is_symlink() or (src / rel).is_file()]
    n = _copy_tracked(src, probe)
    assert n == len(rels), (
        f"_copy_tracked staged {n} paths but {len(rels)} of {src}'s tracked "
        f"paths are files or symlinks; the commit below would not match the "
        f"copy")
    commit(*rels)
    _emit_ledger(probe)
    commit(LEDGER_REL)
    led, note = write_ledger(probe)
    assert led is not None, (
        f"the REAL emitter ran over a staged copy of {src} and committed its "
        f"record, and this module still refuses it: {note}")
    return led


@needs_corpus
def test_d3_the_ledger_binding_is_exercised_by_the_repos_own_evidence():
    """The binding runs on THIS REPOSITORY's trees, not only on a probe.

    Every other ledger control here builds a four-file synthetic tree. That
    proves the RULE and proves nothing about the BLAST RADIUS: "binding to the
    ledger reddens nothing that was green" was, until now, a number in a
    docstring measured once by hand on one machine.

    So it is executed. For each admissible in-repo run root: a tracked-only
    copy, the real emitter, the ledger committed, then every declared entry of
    every cell resolved TWICE — with the step id (ledger-bound) and without it
    (the pre-ledger answer) — and any difference reported cell by cell.

    Two ways this could pass while measuring nothing, both closed:

    * the ledger might not be consulted at all (renamed :data:`LEDGER_REL`,
      bumped schema, drifted specs). ``answered`` counts the entries the
      ledger actually decided and must be non-zero;
    * the staged copy might not answer like the root it was copied from.
      Asserted directly — the unbound answer for every entry must match the
      one the real root gives.

    RE-MEASURED 2026-08-13: 10 roots x 134 entries = 1340 bound resolutions,
    1340 answered by the ledger, 0 differences. A difference is not a bug in
    this test — it is the ledger and the glob disagreeing about one artefact,
    which is the finding.

    WAS `2026-08-06: 8 roots x 133 entries = 1064`. The shape of the result did
    not move — every bound resolution is still answered and nothing differs —
    but the population did, and a recorded number that describes a tree the
    repository no longer has is the defect this file elsewhere calls out (see
    the `RECORD_BOUND_ROOTS` note in the d7 module: "re-measure them, then move
    the pin"). Nothing asserts these three numbers, which is exactly why they
    were free to rot: the only thing that would have caught them is somebody
    re-deriving them, so that is what this is.

    WHAT THE POPULATION LOOKS LIKE NOW, so the next reader has the list rather
    than the count: the corpus publishes run trees in TWO shapes and
    `run_roots()` admits both, so three ICs each contribute a pair —
    `ic/sha256` and `ic/sha256/clean_run_v1427_20260715`, `ic/caravel_user_project`
    and `.../v1.9.43_sky130A`, `ic/u_hawaii_adc` and `.../v1.9.86_sky130A` —
    alongside four singletons: `evaluation/phase1_parity/espi`,
    `ic/spm/v1.5.58_ihp-sg13g2`, `ic/spm/v1.9.96_gf180mcuD`, `ic/subservient`.

    Deliberately NOT claiming which additions account for the +2: the 2026-08-06
    list was not written down, only its count, so any decomposition would be
    reconstruction rather than measurement. The list is recorded here precisely
    so the next move can be attributed instead of guessed at.
    """
    roots = run_roots()
    assert roots, (
        "no admissible in-repo run root resolves here, so this measurement "
        "would be vacuous; that is a run-root discovery failure, not a pass")
    entries = [(cell.step_id, entry) for cell in cells_for(DIM)
               if F.declares_required_outputs(cell.step_id)
               for entry in F.required_outputs(cell.step_id)]
    assert entries, "no cell in this dimension declares a required output"

    answered = 0
    changed: List[str] = []
    perturbed: List[str] = []
    for label, rr in sorted(roots.items()):
        real = {(sid, entry): (h.path if h else None)
                for sid, entry in entries
                for h, _ in [resolve(rr.path, entry, None)]}
        with _probe_run_root("d3_repo_ledger_") as (probe, commit):
            led = _staged_root_with_a_real_ledger(rr.path, probe, commit)
            for sid, entry in entries:
                say = ledger_says(probe, sid, entry)
                if say.consulted:
                    answered += 1
                bound, rej = resolve(probe, entry, sid)
                plain, _ = resolve(probe, entry, None)
                if (plain.path if plain else None) != real[(sid, entry)]:
                    perturbed.append(
                        f"{label} step {sid} {entry!r}: staged copy says "
                        f"{plain.path if plain else None}, the root itself says "
                        f"{real[(sid, entry)]}")
                if (bound.path if bound else None) != (plain.path if plain else None):
                    changed.append(
                        f"{label} step {sid} {entry!r}: unbound "
                        f"{plain.path if plain else None} -> ledger-bound "
                        f"{bound.path if bound else None} "
                        f"(ledger captured {led.captured_at}); "
                        f"unwritten={rej.unwritten} unattributed={rej.unattributed}")

    assert not perturbed, (
        "the tracked-only copy does not answer like the run root it was "
        "copied from, so nothing measured against it says anything about the "
        "root:\n  " + "\n  ".join(perturbed[:20]))
    assert answered, (
        f"{len(roots)} roots x {len(entries)} entries were resolved with a "
        f"freshly emitted, committed write ledger in place and the ledger "
        f"decided NONE of them. The binding is inert — LEDGER_REL, the schema "
        f"or the declared specs have drifted apart from what the emitter "
        f"writes — and every control below would still be green.")
    assert not changed, (
        f"binding to the run's own write ledger CHANGES {len(changed)} of "
        f"{len(roots) * len(entries)} resolutions on this repository's own "
        f"evidence. Each one is the ledger and the glob disagreeing about a "
        f"single artefact: measure which is right before moving either.\n  "
        + "\n  ".join(changed[:20]))


@needs_corpus
def test_d3_a_committed_ledger_can_be_refuted_by_its_own_commit():
    """WHY the ledger above is derived and never committed — measured.

    A ledger is a record about a tree at a moment. Commit it and the tree
    keeps moving underneath it: the next commit lands the artefact the ledger
    recorded as never written, and nothing re-reads the snapshot. The binding
    only subtracts, so the stale record REFUSES a real artefact and quotes
    itself as the authority — a fixture attestation about the past, which this
    module rejected the same morning in its green-making direction.

    This drives the whole sequence on the repository's own published cell, and
    doubles as the bidirectional control for :func:`ledger_staleness`: it must
    name the stale claim, and must report nothing once the ledger is re-emitted
    over the tree as it now is.
    """
    src = run_roots().get("benchmark-data/ic/spm/v1.9.96_gf180mcuD")
    assert src is not None, (
        "the published spm cell does not resolve here; this control needs a "
        "real published tree, not a synthetic one")

    with _probe_run_root("d3_stale_ledger_") as (probe, commit):
        _staged_root_with_a_real_ledger(src.path, probe, commit)

        # A spec the ledger records as never written, with no glob in it, so a
        # later commit can land it VERBATIM the way a re-publish would.
        target = None
        for cell in cells_for(DIM):
            sid = cell.step_id
            if not F.declares_required_outputs(sid):
                continue
            for entry in F.required_outputs(sid):
                if "*" in entry or len(F.split_any_of(entry)) > 1:
                    continue
                say = ledger_says(probe, sid, entry)
                if say.consulted and say.unwritten is not None:
                    target = (sid, entry)
                    break
            if target:
                break
        assert target is not None, (
            "no declared spec is both literal and recorded as never written "
            "in this cell's ledger, so the hazard cannot be driven here")
        sid, entry = target

        assert resolve(probe, entry, sid)[0] is None, "baseline: still absent"
        assert resolve(probe, entry, None)[0] is None, "baseline: still absent"
        assert ledger_staleness(probe) == (), (
            "a ledger just emitted over this tree already disagrees with it")

        # A later commit lands the artefact — exactly the declared path, a
        # real non-empty regular file, carried by the commit. Every rule this
        # module applies BEFORE the ledger accepts it.
        landed = probe / entry
        landed.parent.mkdir(parents=True, exist_ok=True)
        landed.write_text(json.dumps({"landed": "by a later commit"}) * 20)
        commit(entry)
        assert not landed.is_symlink() and landed.stat().st_size > 0 \
            and is_tracked(probe, entry)

        plain, _ = resolve(probe, entry, None)
        assert plain is not None and plain.path == entry, (
            f"precondition: the pre-ledger question must say YES, else the "
            f"refusal below proves nothing: {plain}")

        bound, rej = resolve(probe, entry, sid)
        assert bound is None and rej.unwritten, (
            f"THE HAZARD DID NOT REPRODUCE. If a committed ledger no longer "
            f"overrides a real tracked artefact at the declared path, this "
            f"control has outlived its subject and the module docstring's "
            f"reason for deriving the ledger has to be re-argued: {bound} {rej}")

        stale = ledger_staleness(probe)
        assert any(entry in s for s in stale), (
            f"`ledger_staleness` did not find the claim the commit refutes "
            f"({entry!r}); the guard cannot be trusted on a root that DOES "
            f"carry a ledger: {stale}")

        # And the repair, which is the same operation the derivation performs.
        # It is the RUN DIRECTORY's repair: here the probe IS the tree the
        # emitter walked, with the mtimes of the writes above. That is exactly
        # the distinction #1475 turned on — see `ledger_staleness`, and
        # `test_d3_the_stale_ledger_message_names_a_remedy_the_emitter_can_deliver`.
        _emit_ledger(probe)
        commit(LEDGER_REL)
        bound, rej = resolve(probe, entry, sid)
        assert bound is not None and bound.path == entry, (
            f"re-emitting the ledger over the tree that HAS the artefact must "
            f"make it count again: {bound} {rej}")
        assert ledger_staleness(probe) == (), (
            f"a freshly emitted ledger must agree with its own tree: "
            f"{ledger_staleness(probe)}")


def test_d3_the_stale_ledger_message_names_a_remedy_the_emitter_can_deliver():
    """A failure message may only prescribe what the shipped tool can do.

    THE DEFECT THIS PINS (#1475). :func:`ledger_staleness` used to end its
    finding with "re-emit the ledger over the tree as it now is". Read at a
    published cell — the only place this message is ever produced on real data
    — "the tree as it now is" is a git checkout, and ``step_write_ledger``
    correctly refuses to derive write times from one: ``mtime_fidelity`` sees
    the flattened mtimes, WITHHOLDS the run window, and the D5/D7 halves of the
    record go to zero. The prescription therefore replaced a DETECTABLY stale
    record with an EMPTY one, and it was followed and reverted before anyone
    read the emitter's own disclosure.

    A message is part of the check. This one now names the operation that
    works — the same emitter, pointed at the RUN DIRECTORY, publishing the
    capture that postdates the writes — and names withdrawal as the fallback
    when that tree is gone. Both are things the shipped tool can actually do;
    neither is a hand edit.

    Driven through the real function on a real stale record, so the sentence
    asserted here is the sentence an operator gets.
    """
    with _probe_run_root("d3_stale_msg_") as (probe, commit):
        _ledger_probe_tree(probe)
        commit("provenance.jsonl")
        assert not (probe / _LEDGER_PROBE_ENTRY).exists()

        _emit_ledger(probe)
        commit(LEDGER_REL)
        say = ledger_says(probe, _LEDGER_PROBE_STEP, _LEDGER_PROBE_ENTRY)
        assert say.consulted and say.unwritten is not None, (
            f"the emitter no longer records step {_LEDGER_PROBE_STEP}'s "
            f"{_LEDGER_PROBE_ENTRY!r} as never written, so this control has "
            f"no stale claim to make: {say}")
        assert ledger_staleness(probe) == (), (
            "the record agrees with its tree here; a message pinned against a "
            "record that is ALREADY stale would prove nothing")

        # The staleness, made real: a later commit lands the declared path.
        landed = probe / _LEDGER_PROBE_ENTRY
        landed.parent.mkdir(parents=True, exist_ok=True)
        landed.write_text(json.dumps({"landed": "by a later commit"}) * 20)
        commit(_LEDGER_PROBE_ENTRY)

        stale = ledger_staleness(probe)
        assert len(stale) == 1 and _LEDGER_PROBE_ENTRY in stale[0], (
            f"the guard did not report the one claim the commit refutes, so "
            f"the message below is not the message operators see: {stale}")
        msg = stale[0]

        # WHAT IT MUST SAY — the remedy, where to perform it, and the fallback.
        for phrase, why in (
            ("RUN DIRECTORY",
             "the message must say WHERE to re-emit; 'somewhere' is how this "
             "was performed against a checkout three times"),
            ("POSTDATES",
             "a capture taken before the write reproduces the same staleness, "
             "so the message must say which capture to publish"),
            ("WITHDRAW",
             "when the run tree is gone there is no honest repair, and a "
             "message that names none invites a hand-edited record"),
        ):
            assert phrase in msg, f"{why}\n  message: {msg}"

        # WHAT IT MUST NOT SAY — the measured-wrong operation, in any form
        # close enough for a reader to perform it.
        for banned in ("over the tree as it now is",
                       "re-emit the ledger over the tree"):
            assert banned not in msg, (
                f"the message prescribes {banned!r} again. Measured on this "
                f"repository's own cell: re-emitting over the CHECKOUT takes "
                f"counts.recorded 513 -> 366, counts.in_run_window 489 -> 0 "
                f"and the D7 residual 384 -> 0 — it empties the record instead "
                f"of correcting it.\n  message: {msg}")

        # And the guard is still bidirectional with the new wording: a capture
        # of THIS tree, which is the run directory here, clears it.
        _emit_ledger(probe)
        commit(LEDGER_REL)
        assert ledger_staleness(probe) == (), (
            f"a freshly emitted ledger must agree with its own tree: "
            f"{ledger_staleness(probe)}")


# ══════════════════════════════════════════════════════════════════════
# UNIFORM CELL-STATE INTERFACE (read by programs/tests/test_matrix_63x8_coverage.py)
#
# The coverage meta-test must be able to ask every dimension module the same
# question and get an answer the module itself computes. Anything it derived on
# its own would be a second opinion about cells it does not own — the adjacent
# measurement this campaign removes. Both functions are LIVE: they re-derive
# from the current tree on every call, so a cell that changes state changes its
# answer here without anyone editing a table.
# ══════════════════════════════════════════════════════════════════════
def _condition_file_present(root, pattern: str) -> bool:
    """Is a step-level `files_exist` entry satisfied under ``root``?

    A GLOB HAD TO BE ANSWERED WITH A GLOB (measured 2026-08-20)
    ==========================================================
    This was ``(root / pattern).is_file()``. Every `condition_files` value in
    the manifest was a plain path, so the bug was invisible: M1-M4 name
    `phase1/analog/analog_block_list.json`, steps 40-44 name
    `phase3/stage5_manufacturing/silicon_received.json`, and a plain path is
    its own glob.

    The chip/IC steps (15.5ic, 26.5ic, 37.5ic) are gated on
    `input/submission_template/slots/*.yaml` — the first WILDCARD condition in
    the flow. `Path("a/*.yaml").is_file()` is False for every tree that has
    ever existed, so those three cells would have reported NA_DORMANT
    unconditionally: not "the condition is unmet" but "the question cannot be
    asked". A cell that can only answer one way is exactly the vacuous pass
    this dimension exists to catch, and it would have been introduced BY the
    steps whose dormancy it was meant to measure.

    Directory entries count: `files_exist` is satisfied by presence, and one
    existing consumer (step 14, `condition_files_exist: [phase2/stage2/synth]`)
    names a DIRECTORY. `is_file()` was wrong about that too.
    """
    from glob import glob as _glob
    import os
    if any(ch in pattern for ch in "*?["):
        # `.exists()` on each hit, not just a non-empty glob: `glob` returns a
        # DANGLING symlink, and the enforcer this mirrors
        # (`flow_compliance_check._glob_first`) documents the opposite rule --
        # "only paths that RESOLVE are returned" -- because leaving a link to
        # nothing once scored strictly better than deleting the file.
        return any(os.path.exists(h) for h in _glob(str(root / pattern),
                                                    recursive=True))
    return (root / pattern).exists()


def matrix_na_precondition(step_id):
    """Why this cell is NA, re-derived LIVE, or ``None`` when it is answerable."""
    # Re-derived live from the flow yaml and the run trees, NOT read off the
    # manifest's recorded verdict — the manifest is evidence, not authority.
    if not F.declares_required_outputs(step_id):
        return "declares no required_outputs, so there is nothing to produce"
    rec = step_record(step_id)
    if rec["verdict"] != "NA_DORMANT_CONDITION":
        return None
    cond = F.step_condition(step_id)
    if cond is None:
        return None
    wanted = list(rec["condition_files"] or ())
    declared = [str(x) for x in (cond.get("files_exist") or [])]
    if not wanted or any(w not in declared for w in wanted):
        return None
    if any(_condition_file_present(rr.path, w)
           for rr in run_roots().values() for w in wanted):
        return None
    return ("a step-level condition keeps the step dormant: no admissible run "
            "root carries " + ", ".join(wanted))


def matrix_not_measured_reason(step_id):
    """What this cell could not look at, or None if it could look at everything.

    THE FOURTH STATE, by owner ruling 2026-08-21. Six cells of this dimension —
    steps 15, 17, 19, 20, 30 and 32 — declare an output whose manifest record
    cites a run root of a kind this module searches on NO host. Setting
    `$VIBE_IC_BENCHMARK_DATA` does not reach them; publishing the corpus does
    not reach them; they are not waiting on a pointer.

    They were reported ENFORCED, which claims their predicate passed, while the
    predicate FAILED — `test_no_cell_is_counted_enforced_while_its_predicate_is
    _red` named all six. That was the only thing the three-state grid let them
    be, and it was a statement about the DESIGN that no evidence here supports.
    The honest answer is that the measurement is absent, and this is the
    sentence that says which measurement.

    NOT A WAIVER, and it does not close anything. The cell leaves the
    enforcement denominator and enters a state that counts as nothing, carrying
    the citation it could not resolve. It returns to the denominator the moment
    the record is re-pointed at a reachable root or such a run is published —
    `unanswerable_citations` is re-derived live, so this state self-invalidates
    exactly as an NA precondition does.
    """
    cites = unanswerable_citations(step_id)
    if not cites:
        return None
    named = "; ".join(
        f"{rel!r} from run root {root!r}" for rel, root, _ in cites)
    return (
        f"{len(cites)} declared output(s) cite a run root this dimension "
        f"searches on no host, so no corpus can supply them: {named}. "
        f"NOT a claim that the flow fails to produce these artefacts — nothing "
        f"here measured that.")


def matrix_cell_state(step_id) -> str:
    """``ENFORCED`` / ``WAIVED`` / ``NA`` / ``NOT_MEASURED`` for one cell.

    PRECEDENCE, and it is deliberate: NA and WAIVED outrank NOT_MEASURED,
    NOT_MEASURED outranks ENFORCED. NA is a fact about the design and WAIVED is
    a registered decision carrying evidence — neither is unmade by this host
    being unable to read something. ENFORCED is the one claim you cannot make
    without looking, so "could not look" outranks it. That ordering is what
    stops the fourth state quietly eating a waiver.
    """
    if matrix_na_precondition(step_id) is not None:
        return "NA"
    if waiver_for(step_id) is not None:
        return "WAIVED"
    if matrix_not_measured_reason(step_id) is not None:
        return "NOT_MEASURED"
    return "ENFORCED"


# ══════════════════════════════════════════════════════════════════════
# A COMMITTED LEDGER MUST BE A LIVE CAPTURE (vibe-ic#1475, from #1188)
# ══════════════════════════════════════════════════════════════════════
#: What a ledger walked over a git checkout looks like from the outside. The
#: emitter itself sets these — it does not pretend to know write times it
#: cannot know — so the detection is reading its own disclosure, not guessing.
_BLIND_LEDGER_FIELDS = ("mtime_fidelity.flattened is true",
                        "run_window.known is false")


def _committed_write_ledgers():
    """``(label, path, doc)`` for every write ledger THIS COMMIT carries."""
    out = []
    for label, rr in sorted(run_roots().items()):
        p = rr.path / LEDGER_REL
        if not p.is_file():
            continue
        try:
            out.append((label, p, json.loads(p.read_text(encoding="utf-8"))))
        except (OSError, ValueError) as exc:
            # Unreadable is NOT "not blind". It is unmeasured, and it is named.
            out.append((label, p, {"__unreadable__": str(exc)}))
    return out


def _blind_capture_reason(label: str, doc) -> str:
    """Why *doc* is a checkout walk rather than a run capture. ``""`` if it is
    a live capture; a sentence naming the fields if it is not.

    Kept pure so the control below can drive it both directions without
    planting anything in the corpus — a guard whose only falsification is a
    manual experiment is a guard nobody re-runs.
    """
    if not isinstance(doc, dict):
        return f"{label}: the ledger is {type(doc).__name__}, not an object"
    if "__unreadable__" in doc:
        return (f"{label}: the ledger could not be read "
                f"({doc['__unreadable__']}) — UNMEASURED, which is not a pass")
    fid = doc.get("mtime_fidelity") or {}
    win = doc.get("run_window") or {}
    if fid.get("flattened") is not True and win.get("known") is not False:
        return ""
    return (f"{label}: mtime_fidelity.flattened={fid.get('flattened')!r}, "
            f"run_window.known={win.get('known')!r}, in_run_window="
            f"{(doc.get('counts') or {}).get('in_run_window')!r} — this ledger "
            f"was walked over a COPY, not captured during a run, so it "
            f"attributes no write to any step. Restore the live capture; a "
            f"ledger emitted from a checkout is strictly LESS evidence than "
            f"none, because this dimension trusts it")


@needs_corpus
def test_d3_no_committed_ledger_was_captured_from_a_checkout():
    """A ledger walked over a git checkout attributes nothing — refuse it.

    THE TRAP THIS CLOSES (vibe-ic#1475). When a committed ledger records a spec
    as never written and the same commit carries the artefact,
    :func:`ledger_staleness` reports it — and its remediation text used to read
    "re-emit the ledger over the tree as it now is". Following that advice is
    destructive, and it was followed three times before it was withdrawn.
    ``step_write_ledger.py`` run against a git checkout of a published cell
    returns

        mtime_fidelity.flattened   true      (distinct_mtimes 1, share 1.0)
        run_window.known           false     (t0_source withheld_flattened_mtimes)
        counts.in_run_window       0

    because git does not preserve mtimes, so the emitter correctly WITHHOLDS
    every time-derived conclusion. The resulting record is not a fresher
    account of the same run — it is a BLIND one, and committing it would
    replace a real capture with one that can attribute no write to any step.

    The message is now pinned by
    ``test_d3_the_stale_ledger_message_names_a_remedy_the_emitter_can_deliver``.
    This is the other half, and it is the half that BLOCKS: a message can be
    ignored, so the assertion is on the ARTEFACTS this commit carries. It fires
    the moment one is replaced by a checkout walk — exactly when a reviewer
    needs telling, because that diff reads as a routine ledger refresh.

    ``test_d3_the_blind_capture_predicate_fires_on_a_checkout_walk`` is the
    bidirectional control, so this one's green is falsifiable without anyone
    having to plant a file in the published corpus.
    """
    roots = run_roots()
    assert roots, ("no run roots enumerated at all — this guard measured "
                   "NOTHING, which is not the same as finding nothing")

    ledgers = _committed_write_ledgers()
    if not ledgers:
        pytest.skip(f"none of the {len(roots)} enumerated run root(s) carries "
                    f"{LEDGER_REL} — a real zero, not a failed look")

    blind = [r for r in (_blind_capture_reason(lbl, doc)
                         for lbl, _p, doc in ledgers) if r]
    assert not blind, (
        f"{len(blind)} of {len(ledgers)} committed write ledger(s) were "
        f"captured from a checkout rather than during a run:\n  "
        + "\n  ".join(blind))


def test_d3_the_blind_capture_predicate_fires_on_a_checkout_walk():
    """The control. A guard that cannot go red is a comment with a colour.

    Both fields the emitter uses to disclose a checkout walk are driven
    independently, because either one alone is enough to make the record blind
    and a predicate that needed BOTH would pass on half the real cases.
    """
    live = {"mtime_fidelity": {"flattened": False, "distinct_mtimes": 77},
            "run_window": {"known": True, "t0_source": "orchestrator_summary"},
            "counts": {"in_run_window": 489}}
    assert _blind_capture_reason("live", live) == "", \
        "a real capture was called blind — this guard would block every landing"

    flattened = json.loads(json.dumps(live))
    flattened["mtime_fidelity"]["flattened"] = True
    assert "flattened=True" in _blind_capture_reason("f", flattened)

    withheld = json.loads(json.dumps(live))
    withheld["run_window"]["known"] = False
    assert "known=False" in _blind_capture_reason("w", withheld)

    # UNMEASURED is not a pass: an unreadable record must be named, never
    # quietly treated as a live capture.
    assert _blind_capture_reason("u", {"__unreadable__": "boom"})
    assert _blind_capture_reason("n", None)
