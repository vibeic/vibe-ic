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
A run root must (a) live INSIDE this repository and (b) carry
``provenance.jsonl`` or ``reports/orchestrator/`` — i.e. be a tree a flow
runner actually wrote. Agent scratch trees are excluded on purpose: the only
``phase3/analog/hardmacro/*/*.gds`` files on the campaign host were written by
a throwaway ``mkgds.py`` seeding INPUTS for a backlog repro, and counting a
seeded input as a produced output would be precisely the adjacent-measurement
disease this campaign exists to remove. Step A8 is waived instead.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
=========================================
* It never reads ``.audit_63x8.json`` verdicts. ``cells_for(3)`` is used only
  to enumerate which cells exist; ``cell.audit_verdict`` is not consulted.
* It never scans program source text for a filename. Production is decided by
  looking at (or creating) the artefact, not by grepping for a string that
  might live in a comment.

FIXTURE ATTESTATION, STATED OUT LOUD — AND NOW UNIFORM
======================================================
**107 of the 126 declared entries are decided live on every host** — 89
archived in in-repo run trees, 5 produced on the spot, 13 searched for and
genuinely absent. The other 19 were only ever proven from run trees outside
this repository (steps 11, 15, 17, 19, 20, 29, 30, 32, M1, M2, M3, M4), so
they fall back to the committed manifest's measured record and every assertion
message says ``[FIXTURE]`` for that entry. Even then the record is
cross-checked against the LIVE yaml — the recorded ``alternative`` must still
be one of the entry's declared alternatives — so a yaml edit reddens the cell
in fixture mode too.

Before #527 that 107/19 split was the *degraded* mode and the campaign host
ran at 126/0, which is precisely why the suite's answer depended on the
machine. It is now the ONLY mode: external trees are not consulted anywhere,
there is no env-var escape hatch, and the live count is 107 on the campaign
host, on CI and on a fresh clone alike.
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

DIM = 3

MANIFEST_PATH = Path(__file__).resolve().parent / "fixtures" / "matrix_d3_output_manifest.json"

#: A run root only counts when a flow runner demonstrably wrote it.
_RUNNER_MARKERS = ("provenance.jsonl", "reports/orchestrator")

#: The manifest's ``kind`` for a run root that lives inside this repository.
#: Every other kind names a tree on some particular machine and is never
#: consulted — see the module docstring (#527).
_IN_REPO_KIND = "repo"

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
#: consulted on ANY host, so these seven cells are decided by the committed
#: manifest rather than by the repository everywhere — the module's one soft
#: spot, named here cell by cell rather than left inside an aggregate floor.
#: Committing those run trees is what would close it. See
#: ``test_d3_fixture_attested_cells_are_named_cell_by_cell``.
EXTERNALLY_ATTESTED_STEPS: Tuple[str, ...] = (
    "17", "20", "29", "30", "M2", "M3", "M4",
)


# ──────────────────────────────────────────────────────────────────────
# Manifest
# ──────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def manifest() -> Dict:
    doc = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    global _IN_REPO_RUN_ROOTS
    _IN_REPO_RUN_ROOTS = tuple(sorted(
        label for label, meta in doc["run_roots"].items()
        if meta.get("kind") == "repo"))
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


@lru_cache(maxsize=1)
def run_roots() -> Dict[str, RunRoot]:
    """Every IN-REPO manifest run root that resolves HERE, keyed by label.

    #527: run roots recorded with any other ``kind`` name a directory on one
    particular machine. They are not searched for — not under ``$HOME``, not
    under an env var, not at all — because a tree the repository does not
    carry cannot make this dimension's answer the same on two hosts. Their
    entries are fixture-attested everywhere instead, which is exactly what
    they already were on every host but one.
    """
    out: Dict[str, RunRoot] = {}
    repo = _plugin_tree.repo_root()
    if repo is None:
        return out
    for label, meta in manifest()["run_roots"].items():
        if meta["kind"] != _IN_REPO_KIND:
            continue
        cand = repo / meta["rel"]
        if cand.is_dir() and _is_flow_run(cand):
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
            cwd=str(root), capture_output=True, timeout=120,
        )
    except FileNotFoundError as exc:  # pragma: no cover - git is always present
        raise AssertionError(
            "git is not on PATH, so this module cannot tell a committed "
            "artefact from a local build product and must not guess: every "
            "verdict below would silently become 'a file with that name "
            "exists on this machine' (#527)"
        ) from exc
    if proc.returncode != 0:
        return frozenset()
    return frozenset(
        b.decode("utf-8", "surrogateescape")
        for b in proc.stdout.split(b"\0") if b
    )


def is_tracked(root: Path, rel: str) -> bool:
    """Is *rel*, relative to run root *root*, carried by the commit?"""
    return rel in tracked_under(root)


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
    """
    empty: Tuple[str, ...] = ()
    symlinked: Tuple[str, ...] = ()
    untracked: Tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.empty or self.symlinked or self.untracked)


def resolve(root: Path, entry: str) -> Tuple[Optional[Hit], Rejected]:
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
    return best, Rejected(tuple(empty), tuple(symlinked), tuple(untracked))


def resolve_anywhere(entry: str) -> Tuple[Optional[Hit], Dict[str, Rejected]]:
    rejected: Dict[str, Rejected] = {}
    for label, rr in run_roots().items():
        hit, rej = resolve(rr.path, entry)
        if rej:
            rejected[label] = rej
        if hit is not None:
            return Hit(label, hit.alternative, hit.path, hit.size_bytes), rejected
    return None, rejected


def _rejected_note(rejected: Dict[str, Rejected]) -> str:
    """The three near-miss categories, named rather than folded into "missing"."""
    bits = []
    for field, label in (("empty", "0-byte matches"),
                         ("symlinked", "symlinked (not produced here)"),
                         ("untracked", "matched but NOT tracked at HEAD — a "
                                       "local build product, not evidence")):
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
        if target.exists():
            return False, (
                f"{writes} is tracked at HEAD in the run root {label!r}; this "
                f"cell claims a LIVE production and cannot prove one against a "
                f"tree that already carries the artefact"
            )
        proc = subprocess.run(
            [sys.executable, str(prog_file), *argv],
            cwd=dst, capture_output=True, text=True, timeout=900,
        )
        if not target.is_file():
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
            return False, (
                f"ran `{program} {' '.join(argv)}` in a copy of {label!r} "
                f"(rc={proc.returncode}) and {writes} was NOT written; "
                f"last output: {tail}"
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
#: (or created) here and now. ``FIXTURE`` = the run tree that carries it is not
#: on this host and the committed measurement stood in. The distinction is
#: surfaced (see :func:`test_d3_evidence_is_live_wherever_the_run_root_exists`)
#: because a module that quietly slid from LIVE to FIXTURE everywhere would
#: still be green while measuring nothing.
LIVE = "LIVE"
FIXTURE = "FIXTURE"


@dataclass(frozen=True)
class EntryVerdict:
    produced: bool
    mode: str
    detail: str


def check_entry(step_id, entry: str, rec: Dict) -> EntryVerdict:
    """The verdict for ONE ``required_outputs`` entry, recomputed live."""
    status = rec.get("status")

    if status == "UNPROVEN":
        hit, rejected = resolve_anywhere(entry)
        if hit is not None:
            return EntryVerdict(True, LIVE, (
                f"recorded UNPROVEN but NOW resolves: {hit.path} "
                f"({hit.size_bytes} B) in {hit.root!r} — the gap has closed and "
                f"the waiver must be removed"
            ))
        return EntryVerdict(False, LIVE, (
            f"no committed non-empty artefact matches {entry!r} in any of the "
            f"{len(run_roots())} admissible run roots"
            f"{_rejected_note(rejected)}"
        ))

    if status == "PRODUCED_LIVE":
        if rec["base_run"] not in run_roots():
            return EntryVerdict(True, FIXTURE, (
                f"[fixture-attested, base run {rec['base_run']!r} absent here] "
                f"live production measured 2026-07-27: `{rec['producer']}` "
                f"wrote {rec['writes']} at {rec['size_bytes']} B"
            ))
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
            hit, rejected = resolve(rr.path, entry)
            if hit is None:
                return EntryVerdict(False, LIVE, (
                    f"the recorded run root {rec['run']!r} resolves at {rr.path} "
                    f"but no longer yields a committed non-empty artefact for "
                    f"{entry!r} (recorded: {rec['path']} at {rec['size_bytes']} B)"
                    f"{_rejected_note({rec['run']: rejected})}"
                ))
            return EntryVerdict(True, LIVE,
                                f"{hit.path} ({hit.size_bytes} B) in {rec['run']!r}")
        hit, _rejected = resolve_anywhere(entry)
        if hit is not None:
            return EntryVerdict(True, LIVE, (
                f"{hit.path} ({hit.size_bytes} B) in {hit.root!r} "
                f"[recorded run {rec['run']!r} absent here]"
            ))
        return EntryVerdict(True, FIXTURE, (
            f"[fixture-attested, run root {rec['run']!r} absent here] "
            f"{rec['path']} at {rec['size_bytes']} B, measured 2026-07-27"
        ))

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
    """The admissibility rule, re-applied live to every resolved root."""
    bad = [
        (label, str(rr.path)) for label, rr in run_roots().items()
        if not _is_flow_run(rr.path)
    ]
    assert not bad, (
        f"these run roots carry neither provenance.jsonl nor "
        f"reports/orchestrator/ and must not be cited as evidence: {bad}"
    )


def test_d3_waived_steps_still_produce_their_unwaived_entries():
    """A waived cell xfails whatever the reason; this keeps the rest honest.

    ``xfail(strict=True)`` swallows the reason a waived cell failed, so a
    regression in one of step A8's three *working* entries would hide behind
    the .gds waiver. Those entries are asserted here, unwaived.
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
    assert (len(enforced), len(waived), len(na)) == (52, 4, 7), (
        f"the ENFORCED/WAIVED/NA split changed to "
        f"({len(enforced)}, {len(waived)}, {len(na)}); it was measured as "
        f"(52, 4, 7) on 2026-07-27. A step moving between states is a real "
        f"change in what dimension {DIM} enforces and must be re-reviewed, not "
        f"absorbed."
    )


def test_d3_evidence_is_live_wherever_the_run_root_exists():
    """No entry may fall back to the fixture while its run root IS present.

    The fixture fallback is the module's one soft spot: it lets a cell go green
    on a machine that cannot see the run tree. That is acceptable only when the
    tree is genuinely absent. If a recorded run root resolves and the entry
    still reads FIXTURE, the resolver has stopped looking and every cell
    downstream of it is hollow.
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
        # #527 — this is now an EQUALITY, not a floor. While external run
        # trees were consulted the number ranged from 107 (CI) to 126 (the
        # campaign host) and the ">=" quietly permitted the whole spread; a
        # host-dependent count is exactly the property this dimension had to
        # lose. 107 is now what every host reports, so a deviation in EITHER
        # direction is a real change: fewer means discovery broke, more means
        # something outside the commit is being counted again.
        assert live == 107, (
            f"{live} of {live + fixture} declared entries were verified live; "
            f"107 are backed by run trees committed to this repo (89 archived "
            f"+ 5 produced on the spot + 13 searched-and-absent) and that "
            f"number is host-independent by construction (#527). More than 107 "
            f"means evidence is coming from outside the commit again."
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
    trees are no longer consulted on any host, so the seven cells are now
    fixture-attested everywhere — worse in absolute terms, and honest, where
    before they were live on exactly one machine and fixture on every other.
    The soft spot is not removed here (the artefacts genuinely are not in the
    repository; committing those run trees is what would remove it), but it is
    SPECIFIC and machine-checkable: the set is pinned, so a cell silently
    joining it reddens.
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

        commit()  # give the repo a HEAD, so `git ls-tree HEAD` is meaningful
        yield root, commit


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
