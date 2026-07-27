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

WHAT COUNTS AS PROOF OF PRODUCTION
==================================
Exactly two kinds, both recomputed live:

``PRODUCED_BY_RUN``
    An archived run tree contains a non-empty artefact matching the entry.
    Re-resolved here with ``flow_compliance_check._glob_first`` — the flow's
    OWN resolver, imported rather than re-implemented, so this module cannot
    drift away from the semantics the real gate uses (the ``reports/<subdir>``
    and canonical-analog-dir fallbacks included).

``PRODUCED_LIVE``
    No archived run has the artefact, but running the entry's declared
    producer NOW, in a throwaway copy of a real run tree, makes it land
    non-empty. This is the strongest available evidence — an actual
    production event, this second, by this checkout's code.

    For steps 10 / 23 / 24 / 26 the producer is not guessed: the flow's own
    gate clause names the declared output as its ``--json`` argument, so the
    command is derived from the yaml. (Step 9's producer,
    ``synth_area_stats_emit``, is named explicitly because that step's gate
    does not name it; the program's own module docstring states it exists
    precisely because "nothing ever wrote either one".)

ADMISSIBLE RUN ROOTS
====================
Evidence is only accepted from a directory that carries ``provenance.jsonl``
or ``reports/orchestrator/`` — i.e. a tree a flow runner actually wrote.
Agent scratch trees are excluded on purpose: the only
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

DEGRADED MODE, STATED OUT LOUD
==============================
Measured on a plain checkout of this repo (no external corpus): **107 of the
126 declared entries are decided live** — 89 archived in in-repo run trees, 5
produced on the spot, 13 searched for and genuinely absent. The other 19 are
proven only from external run trees on the campaign host (steps 11, 15, 17,
19, 20, 29, 30, 32, M2, M3, M4); where those are absent the cell falls back to
the committed manifest's measured record and every assertion message says
``[FIXTURE]`` for that entry. Even then the record is cross-checked against the
LIVE yaml — the recorded ``alternative`` must still be one of the entry's
declared alternatives — so a yaml edit reddens the cell in degraded mode too.
``test_d3_evidence_is_live_wherever_the_run_root_exists`` forbids the fallback
whenever the run root actually resolves, and holds the live count at its floor.
Point ``$VIBE_IC_MATRIX_D3_RUN_ROOTS`` (os.pathsep-separated) at a directory
holding those trees to restore full live verification; on the campaign host all
126 are live.
"""
from __future__ import annotations

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

#: os.pathsep-separated list of directories under which the manifest's
#: ``kind: "home"`` run roots may be found. Searched before ``$HOME``.
RUN_ROOTS_ENV = "VIBE_IC_MATRIX_D3_RUN_ROOTS"

#: A run root only counts when a flow runner demonstrably wrote it.
_RUNNER_MARKERS = ("provenance.jsonl", "reports/orchestrator")

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
#: this repository, measured 2026-07-27. On a checkout that cannot see those
#: trees these seven cells are decided by the committed manifest rather than by
#: the repository — the module's one soft spot, named here cell by cell rather
#: than left inside an aggregate floor. See
#: ``test_d3_degraded_mode_is_named_cell_by_cell``.
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


def _search_bases() -> Tuple[Path, ...]:
    bases: List[Path] = []
    raw = os.environ.get(RUN_ROOTS_ENV, "")
    for part in raw.split(os.pathsep):
        part = part.strip()
        if part:
            bases.append(Path(part))
    bases.append(Path.home())
    return tuple(bases)


@lru_cache(maxsize=1)
def run_roots() -> Dict[str, RunRoot]:
    """Every manifest run root that resolves HERE, keyed by label."""
    out: Dict[str, RunRoot] = {}
    repo = _plugin_tree.repo_root()
    for label, meta in manifest()["run_roots"].items():
        rel = meta["rel"]
        cands: List[Path] = []
        if meta["kind"] == "repo":
            if repo is not None:
                cands.append(repo / rel)
        else:
            cands.extend(base / rel for base in _search_bases())
        for cand in cands:
            if cand.is_dir() and _is_flow_run(cand):
                out[label] = RunRoot(label=label, kind=meta["kind"], path=cand)
                break
    return out


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


def resolve(root: Path, entry: str) -> Tuple[Optional[Hit], List[str]]:
    """Largest NON-EMPTY match for *entry* under *root*, plus the 0-byte ones.

    ``" OR "`` inside an entry is any-of (``F.split_any_of`` reproduces the
    consumer's split exactly); the ALL-of-ness across entries is the caller's
    job. The second return value exists so a message can say "the only
    matching artefact is 0 bytes" rather than "missing" — those are different
    defects and conflating them is how a never-ran tool reads as a clean run.
    """
    assert _GLOB_FIRST is not None, (
        "flow_compliance_check._glob_first is gone; this module resolves "
        "required_outputs with the flow's own resolver on purpose and must not "
        "silently fall back to a re-implementation"
    )
    best: Optional[Hit] = None
    empties: List[str] = []
    for alt in F.split_any_of(entry):
        for rel in _GLOB_FIRST(root, alt):
            p = root / rel
            if not p.is_file():
                continue
            size = p.stat().st_size
            if size <= 0:
                empties.append(rel)
                continue
            if best is None or size > best.size_bytes:
                best = Hit(root="", alternative=alt, path=rel, size_bytes=size)
    return best, empties


def resolve_anywhere(entry: str) -> Tuple[Optional[Hit], Dict[str, List[str]]]:
    empties: Dict[str, List[str]] = {}
    for label, rr in run_roots().items():
        hit, empty = resolve(rr.path, entry)
        if empty:
            empties[label] = empty
        if hit is not None:
            return Hit(label, hit.alternative, hit.path, hit.size_bytes), empties
    return None, empties


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


def produce_live(step_id, entry: str, rec: Dict) -> Tuple[bool, str]:
    """Run the declared producer in a throwaway copy of *rec['base_run']*.

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
        shutil.copytree(rr.path, dst, symlinks=True)
        target = dst / writes
        if target.exists():
            return False, (
                f"{writes} already present in the copied run root {label!r}; this "
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
        hit, empties = resolve_anywhere(entry)
        if hit is not None:
            return EntryVerdict(True, LIVE, (
                f"recorded UNPROVEN but NOW resolves: {hit.path} "
                f"({hit.size_bytes} B) in {hit.root!r} — the gap has closed and "
                f"the waiver must be removed"
            ))
        zero = f"; 0-byte matches: {empties}" if empties else ""
        return EntryVerdict(False, LIVE, (
            f"no non-empty artefact matches {entry!r} in any of the "
            f"{len(run_roots())} admissible run roots{zero}"
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
            hit, empties = resolve(rr.path, entry)
            if hit is None:
                zero = f"; 0-byte matches: {empties}" if empties else ""
                return EntryVerdict(False, LIVE, (
                    f"the recorded run root {rec['run']!r} resolves at {rr.path} "
                    f"but no longer yields a non-empty artefact for {entry!r} "
                    f"(recorded: {rec['path']} at {rec['size_bytes']} B){zero}"
                ))
            return EntryVerdict(True, LIVE,
                                f"{hit.path} ({hit.size_bytes} B) in {rec['run']!r}")
        hit, empties = resolve_anywhere(entry)
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
# Waivers
# ──────────────────────────────────────────────────────────────────────
#: Reported to the orchestrator in this agent's return value for central
#: application to ``matrix_63x8.waivers.WAIVERS``. Kept here meanwhile because
#: eight agents share one worktree and concurrent edits to that shared registry
#: lose entries. ``waiver_for`` below prefers the central registry, so this
#: table becomes inert the moment the orchestrator lands it.
_LOCAL_WAIVERS: Tuple[waivers.Waiver, ...] = (
    waivers.Waiver(
        step_id=6, dim=DIM,
        reason=(
            "Two of the three entries are Intel Quartus outputs — a .sof "
            "bitstream and a .map.rpt — and Quartus is installed on no host "
            "this suite can reach, so no run can produce them and no program "
            "in the plugin synthesises an FPGA bitstream itself."
        ),
        evidence=(
            "`command -v quartus quartus_sh quartus_map quartus_fit "
            "quartus_asm` -> all absent, and `find ~ -maxdepth 10 -name "
            "'*.sof'` -> 0 hits across 108 candidate run trees (measured "
            "2026-07-27); programs/fpga_board_capability.py:8 names 'no "
            "Quartus on host' as the expected disclosed gap"
        ),
    ),
    waivers.Waiver(
        step_id=39, dim=DIM,
        reason=(
            "The entry phase2/stage1/fpga/final/*.sof is the recompiled Intel "
            "Quartus bitstream for on-board sign-off; the same tool gap as "
            "step 6 applies, so this entry has no producer on any reachable "
            "host while the sibling on_board_pass.json is produced normally."
        ),
        evidence=(
            "`find ~ -maxdepth 10 -name '*.sof'` -> 0 hits (measured "
            "2026-07-27); the sibling entry reports/phase2/fpga/"
            "on_board_pass.json resolves in benchmark-data/ic/spm/"
            "v1.5.66_gf180mcuD"
        ),
    ),
    waivers.Waiver(
        step_id="A8", dim=DIM,
        reason=(
            "Three of A8's four entries (.lef/.lib/.v) are produced by a real "
            "analog run, so the step demonstrably executes; the .gds entry "
            "alone is produced by nothing. Every matching file on the host is "
            "a stub written by a throwaway seeding script into an agent "
            "scratch tree, and admitting a seeded INPUT as a produced OUTPUT "
            "is the false pass this campaign removes."
        ),
        evidence=(
            "`find ~ -maxdepth 10 -path '*analog/hardmacro/*' -name '*.gds'` "
            "-> only backlog_medlow_mixed_scratch/{ba_mixed,ba_pristine,"
            "m1proj}, all written by backlog_medlow_mixed_scratch/mkgds.py "
            "(a 12-line pya script), none carrying provenance.jsonl or "
            "reports/orchestrator; measured 2026-07-27"
        ),
    ),
    waivers.Waiver(
        step_id="M1", dim=DIM,
        reason=(
            "The step's own gate output records that the merge tool which "
            "would write phase3/mixed_signal/top_merged.gds does not ship, so "
            "a run that reaches M1 emits merge.json (the sibling entry, which "
            "IS produced) while the merged GDS is never written. No flow-run "
            "tree on the host carries one."
        ),
        evidence=(
            "AI_IC_design/4th_benchmark/U_Hawaii_EE628_DeltaSigma_ADC_e2e/"
            "reports/analog/mixed_signal/merge.json -> {\"verdict\": \"SKIP\", "
            "\"rationale_when_skipped\": \"Top-level GDS merge tool not "
            "shipped.\", \"missing\": [\"phase3/mixed_signal/top_merged.gds\"]}"
            " (measured 2026-07-27)"
        ),
    ),
)

_LOCAL_BY_KEY = {w.key: w for w in _LOCAL_WAIVERS}


def waiver_for(step_id) -> Optional[waivers.Waiver]:
    """Central registry first, this module's pending table second."""
    return (
        waivers.waiver_for(step_id, DIM)
        or _LOCAL_BY_KEY.get((F.normalize_id(step_id), DIM))
    )


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


def test_d3_waivers_meet_the_registry_bar():
    """Pending waivers are validated by the shared validator, not by hope."""
    problems = []
    for w in _LOCAL_WAIVERS:
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
    # The waived set must equal the union of the two registries exactly — an
    # `or` between them would let a stale central entry hide a missing local
    # one (or the reverse) and quietly shrink what this dimension enforces.
    declared = {
        F.normalize_id(w.step_id)
        for w in (*waivers.waivers_for_dim(DIM), *_LOCAL_WAIVERS)
    }
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
        assert live >= 107, (
            f"only {live} of {live + fixture} declared entries were verified "
            f"live; 107 are backed by run trees checked in to this repo (89 "
            f"archived + 5 produced on the spot + 13 searched-and-absent) and "
            f"must always be re-measured. Set ${RUN_ROOTS_ENV} to restore the "
            f"remaining 19."
        )


def test_d3_degraded_mode_is_named_cell_by_cell():
    """Say WHICH cells lose their live measurement when a run root is absent.

    2026-07-27, adversarial finding (MEDIUM), accepted: ``check_entry`` falls
    back to the committed manifest whenever a recorded run root does not
    resolve, and 5 of the 12 recorded roots live OUTSIDE the repo. Measured
    with ``_search_bases()`` pointed at a nonexistent directory — the CI /
    other-developer shape — 19 of the 126 entries become fixture-attested and
    SEVEN steps (17, 20, 29, 30, M2, M3, M4) have 100% of their entries decided
    by the committed JSON. Those seven cells are labelled ENFORCED while being
    unfalsifiable on any host but the campaign host.

    The ``live >= 107`` floor above PERMITS that fallback (it is calibrated at
    exactly the all-external-roots-absent number), so it cannot catch it. This
    test does not remove the soft spot — the artefacts genuinely are not in the
    repository — but it makes the degradation SPECIFIC and machine-checkable:
    the set of externally-attested steps is pinned, so a cell silently joining
    it reddens here, and the assertion below is the one that fails first on the
    campaign host if an external tree disappears.
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
    # On a host that CAN see the external trees, none of them may be degraded.
    resolved = run_roots()
    if all(r in resolved for r in _EXTERNAL_RUN_ROOTS_AS_MEASURED):
        degraded = []
        for cell in cells_for(DIM):
            sid = cell.step_id
            rec = step_record(sid)
            for entry, erec in rec["entries"].items():
                if entry not in F.required_outputs(sid):
                    continue
                if check_entry(sid, entry, erec).mode != LIVE:
                    degraded.append(f"{F.normalize_id(sid)}::{entry}")
        assert not degraded, (
            f"every recorded run root resolves on this host, so no entry may "
            f"be fixture-attested, yet {len(degraded)} are: {degraded[:8]}"
        )


def test_d3_zero_byte_artefacts_are_not_counted_as_produced():
    """The rule that makes this dimension mean anything, exercised directly.

    A 0-byte drc.rpt is equally consistent with "0 violations" and "the tool
    never wrote anything". If ``resolve`` ever counted one, every cell in this
    module would go quietly hollow, so the distinction is asserted rather than
    assumed.
    """
    roots = run_roots()
    if not roots:
        pytest.fail(
            "no admissible run root resolved, so the zero-byte rule cannot be "
            "exercised; see test_d3_run_root_discovery_is_live"
        )
    root = next(iter(roots.values())).path
    with tempfile.TemporaryDirectory(prefix="d3_zero_") as td:
        probe = Path(td) / "probe"
        probe.mkdir()
        (probe / "reports").mkdir()
        empty = probe / "reports" / "drc.rpt"
        empty.touch()
        hit, empties = resolve(probe, "reports/drc.rpt")
        assert hit is None, f"a 0-byte file was accepted as produced: {hit}"
        assert empties == ["reports/drc.rpt"], empties
        empty.write_text("x")
        hit, empties = resolve(probe, "reports/drc.rpt")
        assert hit is not None and hit.size_bytes == 1, (hit, empties)
    assert root.is_dir()


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
