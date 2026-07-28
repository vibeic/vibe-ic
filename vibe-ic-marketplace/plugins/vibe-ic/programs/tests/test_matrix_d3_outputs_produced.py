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
Agent scratch trees are excluded on purpose: at the time of the first
measurement the only ``phase3/analog/hardmacro/*/*.gds`` files on the campaign
host were written by a throwaway ``mkgds.py`` seeding INPUTS for a backlog
repro, and counting a seeded input as a produced output would be precisely the
adjacent-measurement disease this campaign exists to remove.

That is still the rule, and step A8 now satisfies it rather than being waived
past it — as ``PRODUCED_LIVE``, which is the only status that is TRUE of it.

A8 declares four artefacts and archived runs carry three: the ``.gds`` had no
producer anywhere in the plugin (``magic_port_extract_emit
.build_gds_write_tcl`` shipped in v0.1.114 with a unit test and no caller), so
by construction no run ever wrote one. ``programs/analog_hardmacro_gds_emit
.py`` is that producer. It is declared in A8's ``programs:`` and invoked by
``analog_one_shot_runner.step_for_block("A8_hardmacro_gen")`` — and
deliberately NOT by A8's gate, because ``flow_compliance_check`` is the
acceptance AUDITOR and an auditor that writes a declared ``required_output``
into the project it audits certifies its own output
(``test_d3_the_compliance_audit_does_not_create_declared_outputs``).

Nothing is committed as evidence. The cell copies
``benchmark-data/ic/u_hawaii_adc`` to a throwaway tree, checks that the tree
carries no hardmacro ``.gds`` to begin with, runs the producer, and requires
the artefact to land — with real geometry, at the size and record count the
producer's OWN run record claims, streamed from a ``layout.mag`` that already
existed in the archived tree. That binding is the point: without it any file
matching ``phase3/analog/hardmacro/*/*.gds`` that parses as GDS would have been
accepted as A8's output, and a 1.18 MB chip-top GDS from a different design and
a different PDK measurably was.

THIS ENTRY IS THE ONE THAT NEEDS AN EDA CONTAINER. Magic writes the stream; the
producer's rc=2 names the gap (``A8GDS_NO_STAGE`` / ``A8GDS_NO_MAGIC`` /
``A8GDS_NO_TECH``). Where the container is unreachable this module goes RED for
A8 and says the entry is UNMEASURED — not absent, not produced. Unmeasured is
not zero, and a green there would be a claim about a tool that never ran.

AND BE PRECISE ABOUT WHAT A8's GREEN DOES NOT MEAN. This dimension asks whether
the declared outputs are PRODUCED, not whether they are CONSISTENT. Step A8's
own gate still FAILs on the analog reference run, and once a real run produces
the ``.gds`` the failure moves from ``analog_hardmacro_check``
(``HARDMACRO_INCOMPLETE`` — the layout is missing) to
``analog_lef_gds_outline_check`` (``A8_LEF_GDS_OUTLINE_MISMATCH`` — the hand
authored LEF ``SIZE`` and the streamed bounding box disagree by two orders of
magnitude). That is a sharper finding, not a softer one, and it belongs to the
criteria dimension. A green cell here means the fourth artefact now exists and
is a real layout; it does NOT mean step A8 passes.

TOOLCHAIN-GATED CELLS (steps 6 and 39) ARE NA, NOT WAIVED
=========================================================
Both declare an Intel Quartus bitstream. No program in this plugin synthesises
one, and the flow's own locator — ``design_one_shot_runner
._find_host_quartus_sh`` (six search paths) plus ``_container_has_quartus_sh``
— finds nothing on this host or in the container the runner would use, which
is precisely when ``step_fpga_compile`` returns its documented SKIP. That is a
LIVE, self-invalidating precondition rather than a standing admission, so the
cells assert it instead of xfailing:

  * the toolchain probe must still come back empty — install Quartus, or set
    ``$QUARTUS_ROOTDIR``, and both cells go RED and must be re-measured;
  * no admissible run root may have acquired one of the gated artefacts;
  * and every entry of those steps that is NOT toolchain-gated
    (``quartus_map_audit.json``, ``on_board_pass.json``) must still pass the
    FULL production predicate, in the cell body — so the NA narrows what the
    cell claims without narrowing what it enforces.

BE PRECISE ABOUT WHAT THAT GREEN PROVES. Not "the bitstream exists"; it proves
that the tool which alone could write one is unreachable from here, that no
run tree has one anyway, and that everything else the step declares IS
produced.

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
126 declared entries are decided live** — 89 archived in in-repo run trees, 6
produced on the spot, 12 searched for and genuinely absent (2026-07-28: A8's
``.gds`` moved from the third bucket to the SECOND when it acquired a producer;
the live total is unchanged). The other 19 are
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

# The flow's OWN vendor-toolchain locator, for the same reason: steps 6 and 39
# are NA because the tool that alone writes their bitstream is unreachable, and
# the only honest definition of "unreachable" is the one the runner itself uses
# to decide its SKIP (design_one_shot_runner.step_fpga_compile). Re-implementing
# a `shutil.which` here would let the two disagree — the NA would keep holding
# on a host where the runner WOULD have found Quartus under $QUARTUS_ROOTDIR.
import design_one_shot_runner as _dosr  # noqa: E402

# ONE parser for "does this GDS carry geometry", shared with the A5 layout gate,
# analog_hardmacro_check and the A8 producer, so this module cannot accept a
# hardmacro layout its own consumers reject.
from analog_a5_layout_check import _gds_geometry_count  # noqa: E402

# ONE parser for "which cells does this GDS define" — the plugin's own GDSII
# record walk, imported rather than re-implemented. It is what binds A8's
# streamed layout to the BLOCK it claims to be: geometry alone cannot tell a
# hardmacro apart from any other design's chip-top.
from gds_topcell_name_check import parse_structures  # noqa: E402

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

#: The ONLY entries an ``NA_TOOLCHAIN_ABSENT`` cell may excuse, pinned HERE and
#: not read from the manifest it validates. The cell's own three assertions
#: already stop a *producible* entry being hidden in this bucket (a gated entry
#: must resolve NOWHERE, an ungated one must be PRODUCED), but they cannot stop
#: someone moving a genuinely-missing entry that Quartus has nothing to do with
#: into it. Pinning the set means growing it reddens
#: ``test_d3_toolchain_gated_entries_are_the_pinned_set`` and has to be argued
#: for, exactly as ``EXTERNALLY_ATTESTED_STEPS`` above.
TOOLCHAIN_GATED_ENTRIES: Dict[str, Tuple[str, ...]] = {
    "6": ("phase2/stage1/fpga/output_files/*.map.rpt",
          "phase2/stage1/fpga/output_files/*.sof"),
    "39": ("phase2/stage1/fpga/final/*.sof",),
}

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
    # A digital run, kept in the probe precisely because it is NOT empty: a
    # guard that can only ever measure zero cannot be shown to work.
    "benchmark-data/ic/spm/v1.5.66_gf180mcuD": (
        "24::reports/phase3/ir_drop_signoff.json",
        "25::reports/phase3/em_signoff.json",
        "26::reports/phase3/antenna_signoff.json",
    ),
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
        # A LIVE production must be proved against a tree that does not
        # already hold the artefact. The COPY is ours, so clear it HERE.
        # Corrected 2026-07-28: returning False when the source root carried
        # one made this cell go red exactly when the flow produced the output
        # it is supposed to be measuring — measured on the analog reference
        # run after `analog_one_shot_runner`'s own A8 producer had written it.
        # A dimension called "outputs produced" must not fail on production.
        if target.exists():
            try:
                target.unlink()
            except OSError as exc:
                return False, (
                    f"{writes} was present in the copied run root {label!r} "
                    f"and could not be cleared before the live production "
                    f"probe ({exc.__class__.__name__})"
                )
        proc = subprocess.run(
            [sys.executable, str(prog_file), *argv],
            cwd=dst, capture_output=True, text=True, timeout=900,
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
# Vendor-toolchain reachability — the NA precondition for steps 6 / 39
# ──────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=8)
def toolchain_sites(container: str) -> Tuple[str, ...]:
    """Every place THE FLOW would find its FPGA compiler, asked live.

    Returns the reachable sites, so an empty tuple is the precondition
    "unreachable" and a non-empty one names exactly what invalidated it. Both
    probes are the runner's own (`design_one_shot_runner`), never a local
    `shutil.which`: the cell must go red on precisely the hosts where
    `step_fpga_compile` would stop returning its SKIP.

    A probe that RAISES is not treated as "absent". Unmeasured is not zero —
    the exception is re-raised so the cell fails loudly instead of going green
    on a broken instrument.
    """
    sites: List[str] = []
    host = _dosr._find_host_quartus_sh()
    if host:
        sites.append(f"host:{host}")
    if container and _dosr._container_has_quartus_sh(container):
        sites.append(f"container:{container}")
    return tuple(sites)


def toolchain_record(step_id) -> Dict:
    rec = step_record(step_id)
    tc = rec.get("toolchain")
    if not tc:
        raise AssertionError(
            f"step {step_id} is recorded {rec['verdict']!r} but carries no "
            f"`toolchain` record naming the tool, the probe and the gated "
            f"entries — an NA nobody can check is a skip in disguise"
        )
    return tc


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
        step_id="M1", dim=DIM,
        reason=(
            "NARROWED 2026-07-28. The producer is NOT missing: "
            "mixed_signal_top_lvs_run.py writes phase3/mixed_signal/"
            "top_merged.gds (KLayout merge), ships, and is invoked twice — "
            "M1's own advisory gate clause and vibe_ic_one_shot_runner:813. "
            "What is unreachable is an INPUT SET: the merge needs a digital "
            "sign-off GDS and analog hardmacro GDS in the SAME project, and "
            "no admissible run root is a mixed-signal project that got that "
            "far, so the producer returns its documented rc=2 'inputs "
            "missing' skip everywhere it can run. Closing this needs a "
            "published mixed-signal run tree, not a code change."
        ),
        evidence=(
            "programs/mixed_signal_top_lvs_run.py:184-199 writes top_merged."
            "gds; :152-161 returns SKIP rc=2 naming the absent inputs. Asked "
            "DIRECTLY (mixed_signal_top_lvs_run.run, tool probe stubbed) on "
            "all 12 admissible run roots, 2026-07-28: 12/12 return 'inputs "
            "missing'. Three lack only 'hardmacro GDS (A8)' (the spm-class "
            "digital runs, which have a sign-off GDS and no analog blocks at "
            "all) and the one root with hardmacro GDS lacks 'digital GDS, "
            "gate netlist' — intersection empty. The 2026-07-27 evidence for "
            "this waiver quoted 'Top-level GDS merge tool not shipped.' from "
            "an ARCHIVED merge.json; that string exists nowhere in the plugin "
            "today (mixed_signal_merge_check.py:57 now reads 'Top-level "
            "merge+LVS not runnable in this environment'), so the old reason "
            "was stale. Re-measured live by "
            "test_d3_m1_merge_inputs_are_absent_from_every_run_root."
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

    # ---- NA: a vendor toolchain no reachable host advertises ---------
    # Narrower than a waiver in every direction: three live assertions, and
    # the entries the toolchain does NOT gate keep the full ENFORCED
    # predicate. See the module docstring for what a green here does and
    # does not prove.
    if verdict == "NA_TOOLCHAIN_ABSENT":
        tc = toolchain_record(sid)
        gated = list(tc["gated_entries"])
        live_entries = list(F.required_outputs(sid))

        # (0) Drift. A renamed or deleted entry must not slip behind the NA.
        assert set(live_entries) == set(rec["entries"]), (
            f"step {sid}'s required_outputs drifted from the measured "
            f"manifest: +{sorted(set(live_entries) - set(rec['entries']))} "
            f"-{sorted(set(rec['entries']) - set(live_entries))}"
        )
        missing_gated = [g for g in gated if g not in live_entries]
        assert not missing_gated, (
            f"step {sid} is NA because {missing_gated} are produced only by "
            f"{tc['label']}, but the flow yaml no longer declares them — the "
            f"NA names entries that no longer exist"
        )

        # (1) The toolchain is still unreachable, asked with the runner's own
        #     locator. The moment it resolves, this cell must be re-measured.
        sites = toolchain_sites(tc.get("container", ""))
        assert not sites, (
            f"step {sid} is recorded NA because {tc['label']} is reachable "
            f"from nowhere this suite can run, but it IS reachable now: "
            f"{list(sites)}. The flow's own locator ({tc['probe']}) would "
            f"stop returning its SKIP, so {gated} can be produced and this "
            f"cell must be enforced for real."
        )

        # (2) No run root acquired one anyway (a bitstream compiled
        #     elsewhere and copied in would close the gap without the tool).
        appeared = [
            (e, h.root, h.path, h.size_bytes)
            for e in gated
            for h in [resolve_anywhere(e)[0]]
            if h is not None
        ]
        assert not appeared, (
            f"step {sid} is recorded NA because nothing reachable produces "
            f"{gated}, yet an admissible run root now carries one: "
            f"{appeared} — the NA is stale"
        )

        # (3) EVERYTHING ELSE THE STEP DECLARES IS STILL ENFORCED. Without
        #     this the NA would quietly stop measuring the entries that ARE
        #     produced, which is how a narrowed claim becomes a smaller test.
        ungated_missing = []
        for entry in live_entries:
            if entry in gated:
                continue
            v = check_entry(sid, entry, rec["entries"][entry])
            if not v.produced:
                ungated_missing.append(f"{entry!r}: {v.detail}")
        assert not ungated_missing, (
            f"step {sid} is NA only for the {len(gated)} entry(ies) "
            f"{tc['label']} alone can write; its remaining "
            f"{len(live_entries) - len(gated)} required_outputs are enforced "
            f"and {len(ungated_missing)} are NOT produced:\n  "
            + "\n  ".join(ungated_missing)
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
    assert (len(enforced), len(waived), len(na)) == (53, 1, 9), (
        f"the ENFORCED/WAIVED/NA split changed to "
        f"({len(enforced)}, {len(waived)}, {len(na)}); it was measured as "
        f"(52, 4, 7) on 2026-07-27 and re-reviewed to (53, 1, 9) on "
        f"2026-07-28: A8 became ENFORCED once its .gds got a producer "
        f"(programs/analog_hardmacro_gds_emit.py), and steps 6 and 39 became "
        f"NA_TOOLCHAIN_ABSENT — a live, self-invalidating precondition — "
        f"instead of standing waivers. A step moving between states is a real "
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
            f"archived + 6 produced on the spot + 12 searched-and-absent) and "
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


def test_d3_toolchain_gated_entries_are_the_pinned_set():
    """Which entries an NA may excuse is pinned, not taken from the manifest.

    ``NA_TOOLCHAIN_ABSENT`` is the one state in this module where a declared
    output is allowed to be absent. The cell's own assertions make that
    airtight for the entries listed — but the LIST comes from the manifest, and
    a manifest is editable. This test is the second key: the set of excused
    entries must equal what is written down here, so widening it is a visible,
    argued change rather than a JSON edit.
    """
    measured = {
        F.normalize_id(cell.step_id): tuple(sorted(
            (step_record(cell.step_id).get("toolchain") or {})
            .get("gated_entries") or ()))
        for cell in cells_for(DIM)
        if step_record(cell.step_id)["verdict"] == "NA_TOOLCHAIN_ABSENT"
    }
    pinned = {k: tuple(sorted(v)) for k, v in TOOLCHAIN_GATED_ENTRIES.items()}
    assert measured == pinned, (
        f"the toolchain-excused entry set changed: measured {measured}, "
        f"pinned {pinned}. Every entry in this bucket is a declared output "
        f"this dimension stops requiring, so the population must not grow "
        f"without review."
    )
    # And each of them must still be declared by the live yaml, or the NA is
    # excusing something that no longer exists.
    for sid, entries in pinned.items():
        declared = set(F.required_outputs(sid))
        assert set(entries) <= declared, (
            f"step {sid}: pinned toolchain-gated entries "
            f"{sorted(set(entries) - declared)} are no longer declared by the "
            f"flow yaml")


A8_GDS_ENTRY = "phase3/analog/hardmacro/*/*.gds"


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

    ADDED 2026-07-28. The cell's live-production probe resolves the producer
    from the manifest and runs it by hand, so it stayed green with the
    producer disconnected from every flow path — the exact state the retired
    A8 waiver described ("declared and produced by nothing"). Measured:
    patching ``analog_one_shot_runner``'s A8 dispatch to ``if False:`` AND
    deleting the producer from A8's ``programs:`` left this module
    ``76 passed`` / rc 0.

    Since the producer clause was deliberately withdrawn from A8's GATE (the
    acceptance auditor must not create what it certifies), the runner is the
    SOLE production site, so this asserts the DISPATCH, not the source text:
    ``analog_one_shot_runner.subprocess`` is replaced with a recorder and the
    A8 step is driven for one block.
    """
    prog_name = step_record("A8")["entries"][A8_GDS_ENTRY]["producer"]
    assert prog_name in F.declared_programs("A8"), (
        f"A8 no longer declares {prog_name!r} in its `programs:` list")

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


def test_d3_a8_hardmacro_gds_is_produced_live_and_bound_to_its_producer():
    """The whole A8 closure, measured: produce it, then check WHAT was produced.

    Three separate ways to be wrong are covered, because the first two were
    each shipped once:

    1. *Not produced at all.* The producer is run for real on a throwaway copy
       of an archived analog run and the artefact has to land.
    2. *Produced, but hollow.* Every artefact is re-parsed with the shared
       record walk (BOUNDARY / PATH / SREF / AREF / BOX) that
       ``analog_hardmacro_check`` and the A5 layout gate use — the predicate
       that 500 bytes of non-GDS noise once got past.
    3. *Some OTHER file that merely matches the glob.* Measured 2026-07-28:
       dropping a 1.18 MB chip-top GDS from a different design and a different
       PDK into the run tree kept this dimension fully green. Three bindings
       close that: the size and the geometry record count are recomputed from
       disk and must equal what the producer's own run record claims; the
       record's declared source input must be a file that ALREADY existed in
       the archived tree, i.e. the run's own A5 layout; and the stream must
       DEFINE a structure named after the block, so a real layout belonging to
       some other cell is not interchangeable with this one (that foreign
       chip-top defines 42 structures, none of them the block name).

    There is no skip. rc=2 means the EDA container is unreachable and the
    entry is UNMEASURED; this fails and says so rather than going green on a
    tool that never ran.
    """
    rec = step_record("A8")["entries"][A8_GDS_ENTRY]
    assert rec["status"] == "PRODUCED_LIVE", rec
    prog = F.PROGRAMS_DIR / f"{rec['producer']}.py"
    assert prog.is_file(), (
        f"A8's declared producer programs/{rec['producer']}.py is gone; the "
        f"cell's evidence can no longer be produced at all")

    rr = run_roots().get(rec["base_run"])
    assert rr is not None, (
        f"A8's base run root {rec['base_run']!r} is in this repository and "
        f"must always resolve; it did not")
    src_input = rr.path / rec["source_input"]
    assert src_input.is_file() and src_input.stat().st_size > 0, (
        f"the archived run does not carry {rec['source_input']}, the A5 "
        f"layout this producer streams; without it a produced .gds could "
        f"only have come from somewhere else")

    with tempfile.TemporaryDirectory(prefix="d3_a8_") as td:
        dst = Path(td) / "proj"
        shutil.copytree(rr.path, dst, symlinks=True)
        # A LIVE production must be proved against a tree that does NOT
        # already have the artefact. The COPY is ours, so clear it there
        # rather than demanding the repository never carry one — that demand
        # was a false alarm on the very output the flow now produces.
        removed_first = [str(q.relative_to(dst))
                         for q in sorted(dst.glob(A8_GDS_ENTRY))]
        for q in sorted(dst.glob(A8_GDS_ENTRY)):
            q.unlink()
        assert not sorted(dst.glob(A8_GDS_ENTRY)), removed_first

        proc = subprocess.run(
            [sys.executable, str(prog), *rec["argv"]],
            cwd=dst, capture_output=True, text=True, timeout=1800)
        blob = (proc.stdout or "") + (proc.stderr or "")
        produced_files = sorted(dst.glob(A8_GDS_ENTRY))

        assert proc.returncode != 2, (
            f"`{rec['producer']}` returned its disclosed capability gap "
            f"(rc=2) on a copy of {rec['base_run']!r}, so A8's fourth "
            f"declared output is UNMEASURED here — not absent and not "
            f"produced. This cell needs Magic in the EDA container; the "
            f"producer names what is missing:\n{blob[-800:]}")
        assert proc.returncode == 0, (
            f"`{rec['producer']}` failed on a copy of {rec['base_run']!r} "
            f"(rc={proc.returncode}):\n{blob[-1200:]}")
        assert produced_files, (
            f"`{rec['producer']}` returned 0 and wrote no "
            f"{A8_GDS_ENTRY!r}:\n{blob[-800:]}")

        # ---- bind the bytes to the record that claims to have made them ----
        record_path = dst / rec["production_record"]
        assert record_path.is_file(), (
            f"the producer wrote {[p.name for p in produced_files]} but no "
            f"run record at {rec['production_record']}; an artefact with no "
            f"provenance is exactly what this cell must stop accepting")
        report = json.loads(record_path.read_text(encoding="utf-8"))
        assert report["program"] == rec["producer"], report.get("program")

        claimed = [r for r in report["results"] if r.get("status") == "PRODUCED"]
        assert claimed, (
            f"the run record claims nothing was PRODUCED yet "
            f"{[p.name for p in produced_files]} are on disk:\n{report}")
        assert {str(Path(r["gds"])) for r in claimed} == {
            str(p.relative_to(dst)) for p in produced_files}, (
            f"the run record names {[r['gds'] for r in claimed]} but the tree "
            f"carries {[str(p.relative_to(dst)) for p in produced_files]}")

        problems = []
        for r in claimed:
            p = dst / r["gds"]
            size = p.stat().st_size
            records = _gds_geometry_count(p.read_bytes())
            if size != r["size_bytes"]:
                problems.append(
                    f"{r['gds']}: the run record claims {r['size_bytes']} B, "
                    f"the file on disk is {size} B — the bytes counted are "
                    f"not the bytes this producer says it wrote")
            if records != r["geometry_records"]:
                problems.append(
                    f"{r['gds']}: the run record claims "
                    f"{r['geometry_records']} geometry records, the file "
                    f"carries {records}")
            if records <= 0:
                problems.append(
                    f"{r['gds']} ({size} B) carries NO "
                    f"BOUNDARY/PATH/SREF/AREF/BOX record — padding or an "
                    f"empty library, not a layout")
            # The input must have been in the ARCHIVED tree, not created here.
            if not (rr.path / r["source"]).is_file():
                problems.append(
                    f"{r['gds']}: streamed from {r['source']}, which the "
                    f"archived run root does not carry — the producer's input "
                    f"appeared during this test instead of coming from the run")
            # And the stream must BE this block. Geometry proves it is a
            # layout; only the structure name proves it is THIS layout, and
            # without that any real GDS from any design would satisfy the
            # cell. Chip-agnostic: the name comes from the producer's own
            # per-block record, which comes from the project's block list.
            defined, _referenced, valid_header = parse_structures(
                p.read_bytes())
            if not valid_header:
                problems.append(
                    f"{r['gds']}: does not start with a GDSII HEADER record")
            # The expected name comes from the artefact's OWN declared path,
            # not from `r["block"]`. Corrected 2026-07-28: `block` is a field
            # the PRODUCER writes, so a producer that emitted a foreign GDS and
            # recomputed size, geometry_records AND block from the substituted
            # bytes satisfied all three bindings — measured, module fully green
            # at `76 passed` / rc 0 with a 1,180,456 B chip-top from another
            # design and another PDK landed at the block's path. The path is
            # the flow's statement about what belongs there; the record is the
            # producer's. They must agree, and the path wins.
            expected_block = Path(r["gds"]).parent.name
            if str(r.get("block")) != expected_block:
                problems.append(
                    f"{r['gds']}: the run record calls this block "
                    f"{r.get('block')!r} while the declared path says "
                    f"{expected_block!r} — the producer is describing a "
                    f"different block from the one it wrote to")
            if expected_block not in defined:
                problems.append(
                    f"{r['gds']}: defines structures {defined[:6]} and none of "
                    f"them is {expected_block!r} — the bytes counted as A8's "
                    f"hardmacro layout are some other cell's layout")
        assert not problems, "\n  ".join(problems)


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
                capture_output=True, text=True, timeout=1800)
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
    if rec["verdict"] == "NA_TOOLCHAIN_ABSENT":
        tc = rec.get("toolchain") or {}
        gated = list(tc.get("gated_entries") or ())
        if not gated or any(g not in F.required_outputs(step_id)
                            for g in gated):
            return None
        if toolchain_sites(tc.get("container", "")):
            return None
        if any(resolve_anywhere(g)[0] is not None for g in gated):
            return None
        return (f"{tc.get('label', 'the declared toolchain')} is the sole "
                f"producer of {', '.join(gated)} and no host or container "
                f"this suite can reach advertises it ({tc.get('probe')} "
                f"returns nothing); every other declared output of this step "
                f"is enforced in the cell body")
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
