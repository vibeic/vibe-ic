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
two sources, and both are reproducible from this repository at this commit:

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
_LIVE_ENTRY_COUNT = 133

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


@lru_cache(maxsize=1)
def run_roots() -> Dict[str, RunRoot]:
    """Every IN-REPO manifest run root that resolves HERE, keyed by label.

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
    """
    out: Dict[str, RunRoot] = {}
    repo = _plugin_tree.repo_root()
    if repo is None:
        return out
    for label, meta in manifest()["run_roots"].items():
        admits = _ADMISSIBILITY.get(meta["kind"])
        if admits is None:
            continue
        cand = repo / meta["rel"]
        if cand.is_dir() and admits(cand):
            out[label] = RunRoot(label=label, kind=meta["kind"], path=cand)
    return out


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
        proc = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "-z", "HEAD"],
            cwd=str(root), capture_output=True, timeout=60,
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
        proc = subprocess.run(
            [sys.executable, str(prog_file), *argv],
            cwd=dst, capture_output=True, text=True, timeout=60,
        )
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


def _unevidenced_detail(entry: str, rec: Dict, which_root: str,
                        rejected: Dict[str, "Rejected"]) -> str:
    """The message for an entry NOTHING on this checkout can resolve.

    It states three things a reader needs and the old fixture message stated
    none of: that the search happened and came back empty, what the manifest
    record actually is (a dated observation of a tree that is not here), and
    the ONE action that turns the cell green again.
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
        f"produced. Commit (or register in the manifest) a run tree that "
        f"carries it and this cell answers live again."
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
        return EntryVerdict(False, LIVE, (
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
            return EntryVerdict(False, FIXTURE, _unevidenced_detail(
                entry, rec, f"the recorded base run {rec['base_run']!r}",
                rejected) + _ledger_state(step_id, entry))
        ok, detail = produce_live(step_id, entry, rec)
        return EntryVerdict(ok, LIVE, detail)

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
            return EntryVerdict(False, LIVE, (
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
        return EntryVerdict(False, FIXTURE, _unevidenced_detail(
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
def test_d3_manifest_covers_exactly_the_flow_steps():
    """The ledger is 63 cells; the manifest must cover 63 steps, no more."""
    live = {F.normalize_id(s) for s in F.step_ids()}
    recorded = set(manifest()["steps"])
    assert recorded == live, (
        f"manifest/flow step-set mismatch: only in flow {sorted(live - recorded)}, "
        f"only in manifest {sorted(recorded - live)}"
    )
    assert len(cells_for(DIM)) == len(live) == 63


def test_d3_run_root_discovery_is_live():
    """Discovery must actually find the in-repo evidence trees.

    Both branches assert. On the flattened install cache there is no monorepo
    ancestor at all, so the manifest's repo-kind roots are legitimately
    unreachable and this asserts that IS the cause — rather than skipping and
    letting a discovery bug read as an environment.
    """
    repo = _plugin_tree.repo_root()
    repo_labels = [
        label for label, meta in manifest()["run_roots"].items()
        if meta["kind"] == "repo"
    ]
    resolved = run_roots()
    if repo is None:
        assert not any(label in resolved for label in repo_labels), (
            "no monorepo ancestor was found, yet repo-kind run roots resolved — "
            "the two-tree detection in _plugin_tree.repo_root() disagrees with "
            "what is on disk"
        )
        return
    unresolved = [label for label in repo_labels if label not in resolved]
    assert not unresolved, (
        f"these in-repo run roots are recorded as evidence but do not resolve "
        f"under {repo}: {unresolved} — either the checkout is partial or a run "
        f"tree was deleted while this dimension still cites it"
    )
    assert resolved, "no admissible run root resolved at all"


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


def test_d3_cell_states_partition_all_63_steps():
    """ENFORCED + WAIVED + NA == 63, computed live, with no cell in two states."""
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
    assert len(enforced) + len(waived) + len(na) == 63, (
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
    assert (len(enforced), len(waived), len(na)) == (50, 2, 11), (
        f"the ENFORCED/WAIVED/NA split changed to "
        f"({len(enforced)}, {len(waived)}, {len(na)}); it was measured as "
        f"(50, 2, 11) on 2026-08-12. A step moving between states is a real "
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
    )


def test_d3_evidence_is_live_wherever_the_run_root_exists():
    """No entry may read FIXTURE while its run root IS present.

    Since 2026-08-06 a FIXTURE entry is a FAILURE, not a green, so this test no
    longer guards against a hollow pass — it guards against a false RED and
    against a silent collapse of discovery. If a recorded run root resolves and
    the entry still reads FIXTURE, the resolver has stopped looking, and a
    module that reported 133 unevidenced entries because ``run_roots()`` broke
    would be just as wrong as one that reported 133 produced ones. The
    ``live == _LIVE_ENTRY_COUNT`` equality below is what pins that.
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
    if _plugin_tree.repo_root() is not None:
        # On the source tree the in-repo evidence is always there, so the
        # majority of entries must be measured for real. A number here that
        # collapses means discovery broke, not that the repo changed.
        #
        # #527 — this is an EQUALITY, not a floor. While external run trees
        # were consulted the number ranged from 107 (CI) to 126 (the campaign
        # host) and the ">=" quietly permitted the whole spread; a
        # host-dependent count is exactly the property this dimension had to
        # lose. The number below is what EVERY host reports, so a deviation in
        # either direction is a real change: fewer means discovery broke, more
        # means something outside the commit is being counted again.
        #
        # It moved on 2026-07-28, from 107 to 114, for exactly one reason:
        # dimension 7 declared seven more artefacts and the in-repo run trees
        # already carry all seven (six archived, one produced on the spot).
        # Composition, re-measured: 95 PRODUCED_BY_RUN + 6 PRODUCED_LIVE + 13
        # UNPROVEN-and-searched = 114 live, 19 fixture, 133 declared.
        assert live == _LIVE_ENTRY_COUNT, (
            f"{live} of {live + fixture} declared entries were verified live; "
            f"{_LIVE_ENTRY_COUNT} are backed by run trees committed to this "
            f"repo and that number is host-independent by construction "
            f"(#527). More than {_LIVE_ENTRY_COUNT} means evidence is coming "
            f"from outside the commit again."
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
    outside = sorted(
        f"{label} -> {rr.path}" for label, rr in resolved.items()
        if _plugin_tree.repo_root() is not None
        and _plugin_tree.repo_root().resolve() not in rr.path.resolve().parents
    )
    assert not outside, (
        f"these admissible run roots are not inside the repository: {outside}"
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
            subprocess.run(
                [sys.executable, str(fcc_path), str(dst)],
                capture_output=True, text=True, timeout=60)
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
    # The remaining ten declare artefacts NO path in this commit matches. Only
    # a published run tree closes those, and publishing one costs >1 GB of DEFs
    # against a 2.0 GB .git -- which is why they stay RED here rather than
    # becoming waivers. A red cell cannot rot; a waiver can, and did.
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
    "15", "17", "19", "20", "30", "32",
)


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
      * the other ten declare artefacts no path in this commit matches at all.
        Only a published run tree closes those.

    The pin is what keeps the population from growing quietly: a thirteenth
    cell joining is a NEW loss of evidence and must be reported as its own
    finding, not absorbed into a set that is already red.
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
                    f"this dimension would refuse a real artefact on its word — "
                    f"re-emit the ledger over the tree as it now is")
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
    #    Vacuous today by design — no ledger is committed, and the module
    #    docstring records why — so `ledger_staleness` is exercised for real by
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

        # And the repair, which is the same operation the derivation performs:
        # re-emit over the tree as it now is.
        _emit_ledger(probe)
        commit(LEDGER_REL)
        bound, rej = resolve(probe, entry, sid)
        assert bound is not None and bound.path == entry, (
            f"re-emitting the ledger over the tree that HAS the artefact must "
            f"make it count again: {bound} {rej}")
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
    if any((rr.path / w).is_file()
           for rr in run_roots().values() for w in wanted):
        return None
    return ("a step-level condition keeps the step dormant: no admissible run "
            "root carries " + ", ".join(wanted))


def matrix_cell_state(step_id) -> str:
    """``"ENFORCED"`` / ``"WAIVED"`` / ``"NA"`` for one cell of this dimension."""
    if matrix_na_precondition(step_id) is not None:
        return "NA"
    if waiver_for(step_id) is not None:
        return "WAIVED"
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
