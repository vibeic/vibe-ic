"""matrix_d7_write_record — the RUN'S OWN RECORD, read as dimension 7 evidence.

WHAT THIS CLOSES, IN ONE SENTENCE
=================================
``matrix_d7_artifact_graph._w2_population`` decides "is this path produced by
the flow" by asking the **AST of** ``programs/*.py``, and when the answer is no
it drops the path with

    producers = writers_of(path)
    if not producers:
        continue  # externally supplied by design — not an emitted artefact

That comment is a CLAIM, and it is decidable. "No Python program in this
plugin writes it" is not "the flow does not produce it": the module's own
:data:`matrix_d7_artifact_graph.RESOLUTION_LIMITS` already says so in writing —

    "A write performed inside a shelled-out tool script (an OpenROAD/KLayout
    TCL heredoc embedded as a Python string) is not a Python write position
    and is invisible to this module."

A run's own write ledger (``programs/step_write_ledger.py``) is the OTHER
oracle for exactly that predicate: one ``lstat`` walk of what the run actually
wrote, residualled against the flow's declaration, which sees a container
tool's write because a bind mount shares the host inode.

THE ONE DIRECTION
=================
This module may only ever make ``_w2_population`` consider MORE paths. It is
the mirror image of the write ledger's role in dimension 3, where the ledger
may only ever SUBTRACT evidence:

* d3 asks "was the DECLARED artefact produced", so a record that says NO must
  be able to take a green away and must never hand one out;
* d7 asks "is the declaration COMPLETE", so a record that says "the run wrote
  this and no step declares it" must be able to add a finding, and must never
  remove one. A path W2 charges today is charged with a record present, with a
  record absent, and with a record that never mentions it.

Nothing else about W2 changes. Not the attribution cascade, not the
``declaring_entry`` relaxation, not the load-bearing class, not the waiver
machinery. Only the PRODUCER ORACLE is widened, from "a Python program writes
it" to "a Python program writes it, OR a run whose record this repository
carries was observed writing it".

MEASURED — WHAT THIS WOULD FIND, AND ON WHICH STEPS
===================================================
Two real, independent run directories, ledger built by the real emitter
(2026-08-06):

    run                                                D7 residual   W2 promotions
    $HOME/_sky130A_r3_run                                      335              12
    $HOME/campaign_v1544/spm/converge_1.5.44_gf180mcuD         264               9

"335 candidates" is NOT 335 findings, and the gap is the point. Of the 335,
328 are captured by no ``required_outputs`` entry at all; of those, 327 can be
attributed to no step by the plugin's own program table, because the one-shot
runners carry no per-step segmentation (:data:`RESOLUTION_LIMITS` entry 2) and
because ``provenance.jsonl`` records EDA BINARIES while the flow declares
plugin program names — MEASURED overlap between the two vocabularies on both
runs: **0 of 164**. So the residual cannot be read per step directly, and this
module does not pretend otherwise: it answers only the narrow question W2 was
already asking and getting wrong, and the step it lands on is chosen by W2's
own cascade, not by the record.

Filtered that way the residual lands on 51 candidate paths (the ones W2 drops
for "no Python producer"), of which the two runs above witness 12 and 9. The
per-step promotion, measured:

    step  path                                              r3   1.5.44
    11    phase2/stage2/dft/dft_atpg_not_run.json            *      *
    21    phase3/stage3/pnr/openroad.log                     *      *
    23    phase3/stage3/sta/sta_mcorner_ocv_hold.tcl         *      *
    23    phase3/stage3/sta/sta_spef_hold.tcl                *      *
    23    reports/phase3/sta/post_route_signoff_corner.json  *      *
    24    reports/phase3/dynamic_ir.json                     *      *
    27    reports/phase3/si_mcf_sta.json                     *      *
    30    phase3/stage3/pnr/<top>_pnr.v                      *      *
    D1    reports/audit/phase1/expert_parse_track.json       *      -
    DT2   phase2/stage2/dft/path_delay_atpg_not_run.json     *      -
    DT3   phase2/stage2/dft/sdd_atpg_not_run.json            *      -
    M2    phase1/generated_docs/L21_POWER_INTENT.json        *      *

    unattributable (no unique owner from W2's cascade): 0 on both runs

Ten of those steps are green in dimension 7 today (step 23 is already red and
waived). The two strongest are not inferences at all: ``openroad.log``
(45559 B / 37696 B) and the post-PnR gate netlist (44826 B / 122582 B) are
recorded in each run's OWN ``provenance.jsonl`` as **openroad's declared
outputs** — ``producer_confidence="provenance_output"``, the strongest rung on
the emitter's ladder — read by the gates of steps 21 and 30, and named by no
step's ``required_outputs``. A rule that calls those "externally supplied by
design" is stating something the run's own log contradicts.

END TO END ON A REAL RUN, WITH THE RECORD ACTUALLY COMMITTED
============================================================
The table above is the residual filtered on paper. Measured for real: a copy
of ``$HOME/_sky130A_r3_run`` (455 files, mtimes preserved,
``mtime_fidelity.top_mtime_share`` 0.165 so nothing is withheld) made into a
git repository, its ledger emitted by ``step_write_ledger`` and COMMITTED, and
this module pointed at it:

    unbound   4 steps carry dimension-7 findings   7, 23, FS1, M1
    bound    13 steps carry dimension-7 findings   + 11, 21, 24, 27, 30, D1,
                                                     DT2, DT3, M2
    findings LOST                                  0
    unattributable                                 0
    residual paths refused on live re-verification 0 of 335

Nine NEW red cells, twelve new findings, and — the direction that had to be
checked — **not one finding removed**. 335 residual paths went in and 12 came
out, because W2's other three conditions (artefact-shaped, gate-read, not a
step-condition input, undeclared) did the filtering they already did.

TRIAGE, DONE NOW RATHER THAN ON THE DAY IT FIRES
------------------------------------------------
"A previously-passing cell fails" is only a finding once somebody has said WHY,
and three different answers hide inside those twelve. Recorded here so the
first reader inherits the measurement instead of re-deriving it:

* **A REAL OMISSION the AST could not see — 4.**
  ``reports/phase3/dynamic_ir.json`` (step 24) is written through
  ``dynamic_ir_vectored_emit.py:567/591/608/634`` as ``out_json.write_text``,
  where ``out_json`` is a function parameter; ``reports/phase3/si_mcf_sta.json``
  (step 27) through ``si_mcf_sta.py:917/1054`` as
  ``_pl.report_path(project, ...)``. Both are :data:`RESOLUTION_LIMITS` entry 1
  exactly — "a write whose path root is a function PARAMETER" — so a Python
  program really does write them and the AST index cannot resolve the path.
  ``phase3/stage3/pnr/openroad.log`` (step 21) is openroad's own declared
  provenance output, read by step 21's gate.
  ``reports/audit/phase1/expert_parse_track.json`` (D1) and
  ``phase1/generated_docs/L21_POWER_INTENT.json`` (M2) are produced, gate-read
  and undeclared. For these the fix is the one W2 always asks for: DECLARE the
  artefact in the step's ``required_outputs``.

* **CONDITIONAL SENTINELS — 3, and declaring them would be WRONG.**
  ``phase2/stage2/dft/{dft,path_delay_atpg,sdd_atpg}_not_run.json`` (steps 11,
  DT2, DT3) exist only when ATPG did NOT run — ``dft_signoff_common.py:19``
  reads one whose ``verdict`` is SKIP/SKIPPED/SKIPPED-CONDITION.
  ``required_outputs`` is UNCONDITIONAL, so declaring a skip sentinel would
  assert a production the flow denies. #537 gave W1 and W4 an exemption for a
  flow-declared-optional producer; **W2 has never had one**, and extending it
  is a change to W2's RULE that would move cells that are red TODAY (7, 23,
  FS1, M1). That is not done here — a binding may not weaken the rule it binds
  to — so these three are recorded as the waiver-shaped subset.

* **A HARDCODED LITERAL, where the declaration is not the bug — 1.**
  ``phase3/stage3/pnr/spm_pnr.v`` (step 30) reaches W2 only because
  ``spice_correlation_check.py:1354`` names it as a literal — a CHIP NAME
  frozen into a plugin program. The right fix is to remove the hardcode, not
  to declare an spm-specific path in a chip-agnostic flow. The finding is
  still true as stated ("read by a gate, declared by no step"); what it points
  at is one layer up.

* The remaining 3 (``phase3/stage3/sta/sta_{mcorner_ocv,spef}_hold.tcl`` and
  ``reports/phase3/sta/post_route_signoff_corner.json``) land on step 23,
  which is ALREADY red and waived, so they change no cell state.

NOT ONE OF THEM FIRES ON THIS CHECKOUT, AND THAT IS BY CONSTRUCTION
===================================================================
Both run directories above live on one machine. A cell whose colour depends on
a tree outside the repository is the disease #527 removed from dimension 3 —
"a verdict that reads the same whether or not the thing it claims actually
happened", in its other direction: a verdict that reads DIFFERENTLY on two
checkouts of one commit. So the admissibility rule here is #527's, stated for
records instead of artefacts, and it is deliberately the strictest form:

    a record is admissible only if THE COMMIT CARRIES IT.

:func:`record_roots` does not search ``$HOME``, does not take an
operator-supplied directory of loose files, and does not consult a manifest of
machine paths. It asks ``git ls-tree -r HEAD`` for every tracked
``*/reports/write_ledger.json`` and takes the run root to be that file's
grandparent.

WHICH REPOSITORY'S ``HEAD``, since #1723
----------------------------------------
The rule above says THE COMMIT CARRIES IT, and until 2026-08-16 there was only
one commit it could mean: the corpus was tracked inside this repository under
``benchmark-data/``. #1723 moved ``benchmark-data`` into ``vibeic/benchmark-
data``, and this function went on asking the PLUGIN checkout — which now tracks
no run tree at all. MEASURED on origin/main 74ac9fa78: **0 roots**, and the
published reason was "no run root in this commit carries a tracked
``reports/write_ledger.json``", which reads as "nobody has published a record
yet" when the truth is "the records moved and this function did not follow".
The two pinned roots were carrying 318 live observations the whole time; the
same probe against the corpus checkout finds both of them and loads both.

So the question is now asked of the repository that TRACKS THE CORPUS, resolved
by :func:`_record_repo` — the plugin checkout when it still carries the cells
in-tree (the pre-#1723 shape, and every checkout of a commit before it), and
otherwise the git checkout named by ``VIBE_IC_BENCHMARK_DATA`` through
``_published_corpus.corpus_root``. This is the same two-shape resolution
``_corpus_repo_view.corpus_repo`` performs for the provenance checks, for the
same reason and with the same precedence.

WHAT THIS DOES NOT RELAX. The pointer names a REPOSITORY, and every rule below
is then asked of that repository's ``HEAD``: an untracked file under it is
still inadmissible, ``git clean -xdf`` still cannot change a colour, and two
checkouts of one corpus commit still agree. What moved is WHICH commit is
asked, not WHETHER a commit is asked. A pointer at a loose directory of files —
no git checkout — is refused by name rather than read, because there is no HEAD
there to make the claim about. A pointer that is set and broken raises out of
``corpus_root`` rather than degrading to "no corpus": #1723 is exactly the
event that would otherwise have turned this binding green-by-silence.

FOUR RULES A RECORD MUST PASS, AND WHY EACH ONE EXISTS
======================================================
1. **Tracked at HEAD** — above. ``git clean -xdf`` must not be able to change
   a cell's colour, and two checkouts of one commit must not disagree. Checked
   TWICE on purpose: :func:`record_roots` narrows the population to tracked
   records, and :func:`_load` re-verifies against the run root's own git tree
   at the point of use, so the rule does not rest on whichever call site
   reached it first.
2. **Schema is** ``step_write_ledger.SCHEMA``, imported rather than restated,
   and the file on disk must be a real regular file (a symlink is a promise
   about a filesystem, not a record).
3. **The emitter must not have WITHHELD the residual.** This is the one that
   is easy to get wrong. ``step_write_ledger`` refuses to report
   ``written_never_declared`` when the run window is unknown, or when
   ``mtime_fidelity.flattened`` — measured, a git checkout stamps every
   tracked file with one mtime, and the published cell
   ``benchmark-data/ic/spm/v1.5.66_gf180mcuD`` has 216 files sharing 3 distinct
   mtimes. A withheld residual is EMPTY, and because this module can only add,
   an empty one is harmless to the verdict — but it would make the printed
   reason a lie ("the run wrote nothing undeclared" when the truth is "the
   record declined to say"). Such a record is refused, by name, so the two
   cannot be confused. The consequence is worth stating plainly: **a record
   published inside a git working tree will normally be refused here**, and
   closing that needs the run to carry its own t0 marker plus mtimes a
   checkout has not flattened — not a relaxation of this rule.
4. **The declaration half must have parsed** (``declaration.ok``). A record
   built when the flow yaml was unreadable has no residual to speak of, and an
   empty record must not read as "every step declared everything".

A record that fails any of these is NOT consulted and the reason is returned
as a SENTENCE, which :func:`binding_notes` publishes onto every dimension-7
cell. Nothing here is ever silent.

THE THREE EVIDENCE RULES ARE RE-APPLIED, LIVE, PER PATH
=======================================================
The record is a claim about the past; it is not evidence about today. So every
residual path it names is re-verified from ``lstat`` at read time before it may
promote anything:

* a **symlink** is not evidence of a write — rejected, whatever the record says
  (the emitter agrees: it classifies an alias ``produced=False``, but this
  module does not take that on trust, it looks);
* a **zero-byte file** is not a produced artefact — rejected;
* an **untracked** path is a property of one working tree — rejected, for the
  same reason the record itself must be tracked.

So a record cannot promote a path whose artefact has since been deleted,
emptied, aliased or was never committed, and :func:`observed_writes` reports
each rejection under its own name rather than folding it into "absent".

WHAT THIS MODULE DELIBERATELY DOES NOT DO
=========================================
* It never attributes a write to a step. The record cannot: see the 0-of-164
  vocabulary measurement above. The owning step comes from W2's cascade.
* It never builds a record. A dimension that emitted its own evidence at audit
  time would be certifying its own output — the defect dimension 3 pins as
  ``SELF_CERTIFYING_AUDIT_PROBE``. ``step_write_ledger`` is imported for its
  schema constant and for nothing else.
* It never removes a finding. See THE ONE DIRECTION.
"""
from __future__ import annotations

import json
import os
import stat as _stat
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from matrix_63x8 import flowref as F

import _plugin_tree
import _published_corpus as _pc

if str(F.PROGRAMS_DIR) not in sys.path:
    sys.path.insert(0, str(F.PROGRAMS_DIR))

#: The record's own module, imported for its schema string and for the two
#: relative paths it publishes. Never called to BUILD anything here.
import step_write_ledger as _swl  # noqa: E402

#: Where ``step_write_ledger.emit()`` puts the run-level record. Under
#: ``reports/`` and not under ``steps/`` because ``benchmark_evidence_publish``
#: excludes ``steps/`` by name, so a record written only there could never
#: reach a published cell — i.e. could never be tracked, i.e. could never be
#: admissible here.
RECORD_REL = "reports/write_ledger.json"

#: Bound for the `git ls-tree` below. NOT a round number picked by feel:
#: `ci_harness_timeout_ceiling_check` (BLOCKING) resolves the pytest harness
#: bound from `tools/gatekeeper-land.sh` — `--timeout=180`,
#: `--timeout-method=thread` — and permits any ONE blocking call at most
#: `180 // 3` = 60 s. Above that the inner bound can never fire: pytest reaches
#: 180 s first and takes the whole SESSION down, so `--maxfail` stops counting
#: and every other file in the subset loses its verdict, including files that
#: had already passed. This module is not a `test_` file but it is scanned and
#: it is spent by five test files, which is exactly why the ceiling applies.
#: The landed value was 120. MEASURED here: `git ls-tree -r HEAD` over this
#: checkout's 21945 tracked entries takes 0.01 s, so 60 s is a hang detector
#: for a hung `git`, which is the only way this call can fail to return.
_LS_TREE_TIMEOUT_S = 60

#: The residual key this dimension reads. Quoted from the emitter's own output
#: shape rather than guessed; :func:`_load` fails loudly if it disappears.
_RESIDUAL_KEY = "written_never_declared"

#: Prefix of every producer label this module hands to W2. It exists so a
#: reader of a dimension-7 failure can tell an AST-derived producer
#: (``cts_quality_check``) from an OBSERVED one at a glance, and so nothing
#: downstream can mistake one for the other.
OBSERVED_PREFIX = "run-record"


@dataclass(frozen=True)
class RecordRoot:
    """A run tree whose write ledger THIS COMMIT carries."""

    #: Repo-relative path of the run root, e.g.
    #: ``benchmark-data/ic/spm/v1.5.99_sky130A``. Used as the label.
    rel: str
    path: Path

    @property
    def label(self) -> str:
        return self.rel


@dataclass(frozen=True)
class Observation:
    """One residual path a record names, after live re-verification."""

    root: str
    rel: str
    size_bytes: int
    producer: Optional[str]
    producer_confidence: str

    @property
    def producer_label(self) -> str:
        who = self.producer or self.producer_confidence or "unattributed"
        return f"{OBSERVED_PREFIX}:{who}"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return (f"{self.rel} ({self.size_bytes} B, {self.producer_label}) "
                f"observed in {self.root}")


@dataclass(frozen=True)
class Rejected:
    """Residual paths a record named that this module refused, kept apart.

    "the record names a path that is gone", "...that is now 0 bytes",
    "...that is a symlink" and "...that no commit carries" are four different
    findings. Folding them into one would make a record's own rot read as a
    flow property.
    """

    absent: Tuple[str, ...] = ()
    empty: Tuple[str, ...] = ()
    symlinked: Tuple[str, ...] = ()
    untracked: Tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.absent or self.empty or self.symlinked
                    or self.untracked)


# ──────────────────────────────────────────────────────────────────────
# Trackedness — "does the COMMIT carry this, or just this machine?"
# ──────────────────────────────────────────────────────────────────────
def _git_tracked(root: Path) -> frozenset:
    """Paths tracked at HEAD under *root*, relative to *root*.

    ``git ls-tree -r HEAD``, not ``git ls-files``: the index can carry a
    staged-but-uncommitted path and the claim made here is about the COMMIT —
    what any OTHER checkout would have. An empty set when *root* is not inside
    a git work tree (a flattened install cache, an unpacked archive), which
    correctly makes nothing there admissible.
    """
    try:
        proc = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "-z", "HEAD"],
            cwd=str(root), capture_output=True, timeout=_LS_TREE_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    if proc.returncode != 0:
        return frozenset()
    return frozenset(
        b.decode("utf-8", "surrogateescape")
        for b in proc.stdout.split(b"\0") if b
    )


@lru_cache(maxsize=8)
def tracked_at_head(root: Path) -> frozenset:
    return _git_tracked(root)


# ──────────────────────────────────────────────────────────────────────
# Discovery — from the commit, never from the machine
# ──────────────────────────────────────────────────────────────────────
def _git_toplevel(start: Path) -> Optional[Path]:
    """The work-tree root *start* belongs to, or None if it is not in one."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(start), capture_output=True, text=True,
            timeout=_LS_TREE_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    out = (proc.stdout or "").strip()
    return Path(out) if out else None


@lru_cache(maxsize=1)
def _record_repo() -> Tuple[Optional[Path], str, str]:
    """``(repo, label_prefix, why)`` — whose ``HEAD`` decides the population.

    ``why`` is ALWAYS a sentence, published through :func:`binding_notes`, so
    a reader of a dimension-7 cell can see which repository was asked. The
    two shapes are the ones ``_corpus_repo_view.corpus_repo`` names, in the
    same precedence:

      * a checkout that still carries the cells under ``benchmark-data/`` —
        asked as itself, so every commit before #1723 answers exactly as it
        always did, with no prefix to add;
      * a clone of ``vibeic/benchmark-data``, which tracks the same cells one
        level up under ``ic/``. Its paths are prefixed with ``benchmark-data/``
        so a label means the same thing in both shapes — the pin, the notes and
        every published finding name cells by that path and must not change
        spelling with the host's checkout layout.
    """
    plugin = _plugin_tree.repo_root()
    if plugin is not None and any(
            rel.endswith("/" + RECORD_REL) for rel in tracked_at_head(plugin)):
        return plugin, "", (
            f"the population was read from this checkout, which still tracks "
            f"the corpus in-tree (the pre-#1723 shape)")

    corpus = _pc.corpus_root()
    if corpus is None:
        return None, "", (
            f"no corpus was offered: this checkout tracks no "
            f"{RECORD_REL} and {_pc.CORPUS_ENV} is unset, so W2's producer "
            f"oracle is the AST alone — exactly as it was before this binding")

    top = _git_toplevel(corpus)
    if top is None:
        return None, "", (
            f"{_pc.CORPUS_ENV} names {corpus}, which is not inside a git work "
            f"tree. This binding judges what a COMMIT carries, never what a "
            f"directory happens to hold (#414/#416/#527), and a loose "
            f"directory has no HEAD to make that claim about — point "
            f"{_pc.CORPUS_ENV} at a clone")

    if (top / "benchmark-data").resolve() == corpus.resolve():
        return top, "", (
            f"the population was read from the corpus checkout at {top}, "
            f"which tracks the cells under benchmark-data/")
    return corpus, "benchmark-data/", (
        f"the population was read from the corpus clone at {corpus}, whose "
        f"cells are labelled under benchmark-data/ so they name the same "
        f"thing they do in a checkout that carries them in-tree")


@lru_cache(maxsize=1)
def record_roots() -> Tuple[RecordRoot, ...]:
    """Every run root whose ``reports/write_ledger.json`` is TRACKED AT HEAD.

    Derived from ``git ls-tree`` over the repository :func:`_record_repo`
    resolves, so the population is a property of a COMMIT and is identical on
    every checkout of it. There is no ``$HOME`` search and no manifest of
    machine paths — #527 removed both from dimension 3 and re-introducing
    either here would make a dimension-7 cell's colour a property of the host.
    The corpus POINTER is not one of those: it names a repository, and the
    claim is still made about that repository's HEAD.

    Empty on a flattened install cache (no repo root, no git work tree, no
    corpus), which is the correct answer there: nothing is admissible,
    everything degrades — and :func:`_record_repo` says which of those it was.
    """
    repo, prefix, _why = _record_repo()
    if repo is None:
        return ()
    out: List[RecordRoot] = []
    for rel in sorted(tracked_at_head(repo)):
        if not rel.endswith("/" + RECORD_REL):
            continue
        root_rel = rel[: -(len(RECORD_REL) + 1)]
        if not root_rel:
            continue
        cand = repo / root_rel
        if cand.is_dir():
            out.append(RecordRoot(rel=prefix + root_rel, path=cand))
    return tuple(out)


# ──────────────────────────────────────────────────────────────────────
# Admissibility of ONE record
# ──────────────────────────────────────────────────────────────────────
def _load(root: RecordRoot) -> Tuple[Optional[Dict], str]:
    """``(document, note)`` for *root*. ``note`` is ALWAYS a sentence.

    The four rules in the module docstring, in order, each returning the
    reason it refused so :func:`binding_notes` can print it.
    """
    p = root.path / RECORD_REL
    try:
        if p.is_symlink():
            return None, (
                f"{root.label}: {RECORD_REL} is a SYMLINK -> "
                f"{os.readlink(p)}; a link is a promise about a filesystem, "
                f"not a record of what a run wrote — NOT consulted")
        if not p.is_file():
            return None, (
                f"{root.label}: {RECORD_REL} is tracked at HEAD but absent "
                f"from this working tree — NOT consulted")
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, (f"{root.label}: {RECORD_REL} is unreadable or does not "
                      f"parse ({type(exc).__name__}) — NOT consulted")
    if not isinstance(doc, dict) or doc.get("schema") != _swl.SCHEMA:
        got = doc.get("schema") if isinstance(doc, dict) else type(doc).__name__
        return None, (f"{root.label}: {RECORD_REL} carries schema {got!r}, not "
                      f"{_swl.SCHEMA!r} — NOT consulted")
    # Trackedness is re-checked HERE and not only at discovery. Discovery
    # NARROWS (it is how the population is found at all); this VERIFIES, at
    # the point of use and against the run root's own git tree. Rule 1 is the
    # one that keeps a cell's colour off the host, so it may not rest on the
    # single call site that happens to reach it first.
    if RECORD_REL not in tracked_at_head(root.path):
        return None, (
            f"{root.label}: {RECORD_REL} exists here but the COMMIT DOES NOT "
            f"CARRY IT — NOT consulted. This record can only make a cell "
            f"redder, so an uncommitted one would turn a verdict on whether "
            f"somebody had run step_write_ledger in their working tree, and "
            f"`git clean -xdf` could change a colour (#527). Commit the run "
            f"tree to admit it.")
    if not (doc.get("declaration") or {}).get("ok"):
        return None, (f"{root.label}: the record's declaration half did not "
                      f"parse, so it has no residual against required_outputs "
                      f"— NOT consulted; an empty record must not read as "
                      f"'every step declared everything'")
    fidelity = doc.get("mtime_fidelity") or {}
    if fidelity.get("flattened"):
        return None, (
            f"{root.label}: the emitter WITHHELD the {_RESIDUAL_KEY} residual "
            f"— mtimes in that tree are flattened "
            f"({fidelity.get('top_mtime_share')} of {fidelity.get('n_files')} "
            f"files share one mtime second), so they record a copy or a git "
            f"checkout rather than the run's writes. Its residual is EMPTY "
            f"BECAUSE IT DECLINED TO ANSWER, not because the run wrote nothing "
            f"undeclared — NOT consulted, so the two cannot be confused")
    if not (doc.get("run_window") or {}).get("known"):
        return None, (
            f"{root.label}: the emitter WITHHELD the {_RESIDUAL_KEY} residual "
            f"— the run window is unknown "
            f"({(doc.get('run_window') or {}).get('t0_detail')}), so a "
            f"pre-existing file cannot be told from this run's write — NOT "
            f"consulted")
    if _RESIDUAL_KEY not in (doc.get("residual") or {}):
        return None, (f"{root.label}: {RECORD_REL} carries no "
                      f"{_RESIDUAL_KEY!r} residual key; the emitter's output "
                      f"shape has changed — NOT consulted")
    total = (doc.get("residual") or {}).get(
        f"{_RESIDUAL_KEY}_total", len(doc["residual"][_RESIDUAL_KEY]))
    return doc, (f"{root.label}: {RECORD_REL} consulted (captured "
                 f"{doc.get('captured_at')}, {total} written-never-declared "
                 f"candidate(s))")


# ──────────────────────────────────────────────────────────────────────
# Live re-verification of ONE residual path
# ──────────────────────────────────────────────────────────────────────
def _still_an_artefact(root: RecordRoot, rel: str,
                       tracked: frozenset) -> Tuple[bool, str, int]:
    """``(admissible, reason, size)`` decided from ``lstat``, right now.

    The record says the run wrote it. That is a claim about the past. These
    are the three rules from this module's docstring, re-applied live so a
    record can never promote a path whose artefact is no longer one.
    """
    p = root.path / rel
    try:
        st = os.lstat(str(p))
    except OSError:
        return False, "absent", 0
    if _stat.S_ISLNK(st.st_mode):
        try:
            target = os.readlink(p)
        except OSError:                                   # pragma: no cover
            target = "?"
        return False, f"symlinked -> {target}", 0
    if not _stat.S_ISREG(st.st_mode):
        return False, "not a regular file", 0
    if st.st_size <= 0:
        return False, "0 bytes", 0
    if rel not in tracked:
        return False, "not tracked at HEAD", int(st.st_size)
    return True, "", int(st.st_size)


# ──────────────────────────────────────────────────────────────────────
# The observation index
# ──────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _index() -> Tuple[Dict[str, Tuple[Observation, ...]],
                      Tuple[str, ...],
                      Dict[str, Rejected]]:
    """``(path -> observations, notes, per-root rejections)``. Built once."""
    by_path: Dict[str, List[Observation]] = {}
    notes: List[str] = []
    rejections: Dict[str, Rejected] = {}

    _repo, _prefix, why_repo = _record_repo()
    roots = record_roots()
    if not roots:
        # WHICH absence it is, in the same breath. Before #1723 there was only
        # one — "nobody has published a record yet" — and that sentence was
        # hard-coded here. There are now three (this checkout carries no
        # corpus and none was offered; the pointer names something that is not
        # a git checkout; the corpus IS readable and genuinely carries no
        # record), and they need opposite responses. `_record_repo` returns the
        # one that applies; a fixed sentence would have described the first
        # while the second was true, which is how this binding sat inert.
        notes.append(
            f"{why_repo}; no run root carries a tracked {RECORD_REL}, so W2's "
            f"producer oracle is the AST alone — exactly as it was before "
            f"this binding")
        return {}, tuple(notes), rejections
    notes.append(why_repo)

    for root in roots:
        doc, note = _load(root)
        notes.append(note)
        if doc is None:
            continue
        tracked = tracked_at_head(root.path)
        absent: List[str] = []
        empty: List[str] = []
        symlinked: List[str] = []
        untracked: List[str] = []
        for rec in (doc["residual"][_RESIDUAL_KEY] or []):
            if not isinstance(rec, dict):
                continue
            rel = str(rec.get("rel") or "").lstrip("./")
            if not rel:
                continue
            ok, why, size = _still_an_artefact(root, rel, tracked)
            if not ok:
                if why == "absent":
                    absent.append(rel)
                elif why == "0 bytes":
                    empty.append(rel)
                elif why.startswith("symlinked"):
                    symlinked.append(f"{rel} {why}")
                else:
                    untracked.append(f"{rel} ({size} B)")
                continue
            by_path.setdefault(rel, []).append(Observation(
                root=root.label,
                rel=rel,
                size_bytes=size,
                producer=rec.get("producer"),
                producer_confidence=str(rec.get("producer_confidence") or "?"),
            ))
        rej = Rejected(tuple(absent), tuple(empty), tuple(symlinked),
                       tuple(untracked))
        if rej:
            rejections[root.label] = rej
            notes.append(
                f"{root.label}: {len(absent) + len(empty) + len(symlinked) + len(untracked)} "
                f"residual path(s) refused on live re-verification "
                f"(absent {len(absent)}, 0-byte {len(empty)}, symlinked "
                f"{len(symlinked)}, untracked {len(untracked)}) — a record is "
                f"a claim about the past, not evidence about today")
    return ({k: tuple(v) for k, v in by_path.items()},
            tuple(notes), rejections)


def observed_writes() -> Dict[str, Tuple[Observation, ...]]:
    """``{repo-run-relative path: observations}`` across every admissible record."""
    return _index()[0]


def observed_producers_of(path: str) -> Tuple[str, ...]:
    """Producer labels for *path*, or ``()`` — the widened half of W2's oracle.

    Matched on the EXACT run-relative path. No basename relaxation and no tail
    matching: ``writers_of`` relaxes because an AST cannot always resolve a
    path's root, but an observation is a concrete path off a concrete
    filesystem and relaxing it would let ``reports/density.json`` promote
    ``reports/phase3/density.json``, which is a different artefact.
    """
    obs = observed_writes().get(path)
    if not obs:
        return ()
    return tuple(sorted({o.producer_label for o in obs}))


def binding_notes() -> Tuple[str, ...]:
    """One sentence per record root, plus the empty-population sentence.

    Published onto every dimension-7 cell. A degrade to the pre-binding
    behaviour must never be silent — that is how a reader stops being able to
    tell "the record said nothing was undeclared" from "there was no record".
    """
    return _index()[1]


def rejections() -> Dict[str, Rejected]:
    """Per root, the residual paths refused by the live evidence rules."""
    return _index()[2]


def clear_caches() -> None:
    """Drop every memo. Paired with the controls, which build a real record.

    Tolerant of a monkeypatched :func:`record_roots`: a control that plants a
    probe replaces the discovery function with a plain callable, and a
    ``clear_caches`` that insisted on ``cache_clear`` would raise inside the
    very test it exists to serve.
    """
    for fn in (tracked_at_head, record_roots, _index):
        clear = getattr(fn, "cache_clear", None)
        if clear is not None:
            clear()


__all__ = [
    "RECORD_REL",
    "OBSERVED_PREFIX",
    "RecordRoot",
    "Observation",
    "Rejected",
    "record_roots",
    "observed_writes",
    "observed_producers_of",
    "binding_notes",
    "rejections",
    "clear_caches",
    "tracked_at_head",
]
