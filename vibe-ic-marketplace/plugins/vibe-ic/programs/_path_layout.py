#!/usr/bin/env python3
"""_path_layout.py — single source of truth for the project directory tree.

Phase-redesign branch — three Phase buckets defined by deliverable,
not by skill (see docs/architecture/RFC_v2.0_PHASE_REDESIGN.md):

  Phase 1 — structured spec (L1-L23 JSON) ← unified entry for both docs and dialogue
  Phase 2 — verified RTL + gate-level netlist + FPGA SOF
  Phase 3 — sign-off + tapeout + manufacturing (absorbs analog A5-A9, M1-M4, mfg)

  <project>/
  ├── input/                  raw vendor docs / OTP / PDK / prompt原文
  ├── reports/                human-readable summaries
  ├── waivers.json
  ├── provenance.jsonl
  ├── rig_topology.json
  │
  ├── phase1/                 結構化 spec (兩入口統一)
  │   ├── input_doc/          Path A：vendor docs verbatim extracts
  │   ├── input_prompt/       Path B：dialogue + fact-graph workspace
  │   ├── generated_docs/     L1.json … L13.json — UNIVERSAL HANDOFF
  │   ├── human_docs/         L*.md — human review
  │   ├── extraction_patterns.json
  │   ├── extraction_patterns.auto.json
  │   ├── completeness_check_config.json
  │   ├── ai_deep_review_patches.json
  │   └── analog/<block>/     A1 spec.json
  │
  ├── phase2/                 L1-L23 → verified netlist
  │   ├── stage1/             Steps 1-6: RTL gen + verification
  │   │   ├── rtl/
  │   │   ├── rtl.pre_gen_backup/
  │   │   ├── sim/
  │   │   ├── sim_full_stack/
  │   │   ├── formal/
  │   │   ├── tb/
  │   │   └── fpga/           Step 6 early prototype
  │   │       ├── output_files/   Step 6 prototype .sof + .map.rpt
  │   │       └── final/          Step 39 final sign-off bitstream
  │   ├── stage2/             Steps 7-13: synth + DFT + LEC
  │   │   ├── constraints/
  │   │   ├── synth/
  │   │   └── dft/
  │   └── analog/<block>/     A2-A4 (topology / netlist / corner sweep)
  │
  └── phase3/                 sign-off → tapeout → manufacturing
      ├── stage3/             Steps 14-30: physical design + signoff
      │   ├── pnr/
      │   ├── cts/
      │   ├── extracted/      parasitics (SPEF)
      │   ├── postroute_timing_repair/
      │   ├── spice/          post-layout SPICE correlation
      │   ├── sta/            post-route STA
      │   └── sim_postlayout/
      ├── stage4/             Steps 31-36: tapeout
      │   ├── gds/            final GDS
      │   └── foundry_handoff/
      ├── stage5_manufacturing/  Steps 37-40: fab / sort / packaging / final test
      ├── analog/             A5-A9 (layout / PV / resim / hardmacro / cosim)
      │   ├── <block>/        layout.mag / drc_clean.flag / lvs_match.flag / pre_vs_post.json
      │   └── hardmacro/<block>/  A8: lef + lib + gds + v
      └── mixed_signal/       M1-M4
          ├── <reports>       merge / power_domain / level_shifter / ...
          └── cosim/          AMS co-sim outputs

Helpers below take a `project: Path` and return the canonical path. Only
the canonical layout is supported — pre-release plugin, no installed
user base, no migration window. Programs MUST use these helpers (not
hardcoded strings) when reading or writing artefacts in subdirectories.
"""
from __future__ import annotations

import re
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402


# ─── phase1 ──────────────────────────────────────────────────────────────

def phase1_dir(project: Path) -> Path:
    return project / "phase1"


_RTL_INPUT = (None, "structured")


def original_input_sources(project: Path):
    """The complete original prompt and its existing public context sources."""
    import hashlib
    import json
    project = Path(project)
    prompt = project / "input/phase1_prompt.md"
    manifest = project / "input/public_original/manifest.json"
    if any(p.is_symlink() for p in (prompt, *prompt.parents)):
        raise ValueError("original input source is a symbolic link")
    data = prompt.read_bytes()
    if not data.decode("utf-8").strip():
        raise ValueError("original input prompt is empty")
    if manifest.exists() or manifest.is_symlink():
        import benchmark_io_adapter as bio
        if any(p.is_symlink() for p in (manifest, *manifest.parents)):
            raise ValueError("original input manifest is a symbolic link")
        declared = json.loads(manifest.read_bytes().decode("utf-8"))
        public = bio.public_original_input(project, declared["id"],
                                           hashlib.sha256(data).hexdigest())
        context = [manifest.parent / "files" / item["relative_path"]
                   for item in public["files"]]
    else:
        root = project / "input/rtl"
        entries = [root, *sorted(root.rglob("*"))] if root.exists() or root.is_symlink() else []
        if any(p.is_symlink() for p in entries):
            raise ValueError("original input context is a symbolic link")
        context = [p for p in entries if p.is_file()]
    return [prompt, *context]


def select_rtl_input(project: Path, kind: str, entry_step=None, exit_step=None) -> None:
    """Select the existing RTL owner's input for one bounded invocation."""
    global _RTL_INPUT
    if kind not in ("structured", "original"):
        raise ValueError("unknown RTL input contract")
    if kind == "original":
        if str(entry_step) not in ("1", "2") or str(exit_step) not in ("1", "2"):
            raise ValueError("original RTL input requires a bounded Step 1/2 window")
        prompt = Path(project) / "input/phase1_prompt.md"
        if not prompt.is_file() or any(p.is_symlink() for p in
                                      (Path(project), Path(project) / "input", prompt)):
            raise ValueError("original RTL input requires its regular original prompt")
        import task_nature_route as nature
        text = prompt.read_bytes().decode("utf-8")
        if nature.prompt_embeds_rtl(text) or nature.prompt_embeds_partial_rtl(text):
            raise ValueError("original RTL generation cannot replace a supplied RTL transform")
        if any(p.suffix.lower() in (".v", ".sv", ".vhd", ".vhdl")
               for p in original_input_sources(project)[1:]):
            raise ValueError("original RTL generation cannot replace a supplied RTL transform")
        for source in (Path(project) / "input/rtl", Path(project) / "input/vendor_rtl"):
            if source.is_dir() and any(p.suffix.lower() in (".v", ".sv", ".vhd", ".vhdl")
                                       for p in source.rglob("*")):
                raise ValueError("original RTL generation cannot consume supplied RTL as a new specification")
    _RTL_INPUT = (str(Path(project).resolve()), kind)


def rtl_input(project: Path) -> str:
    return _RTL_INPUT[1] if _RTL_INPUT[0] == str(Path(project).resolve()) else "structured"


def active_rtl_input() -> str:
    return _RTL_INPUT[1]


def rtl_input_view(project: Path, kind: str):
    """Carry an already selected owner input into its existing private copy."""
    import contextlib
    @contextlib.contextmanager
    def view():
        global _RTL_INPUT
        previous = _RTL_INPUT
        _RTL_INPUT = (str(Path(project).resolve()), kind)
        try:
            yield
        finally:
            _RTL_INPUT = previous
    return view()


def input_doc_dir(project: Path) -> Path:
    """Path A entry: verbatim extracts from vendor docs (was phase1/input_doc)."""
    return project / "phase1/input_doc"


def input_prompt_dir(project: Path) -> Path:
    """Path B entry: dialogue transcript + fact-graph workspace."""
    return project / "phase1/input_prompt"


def generated_docs_dir(project: Path) -> Path:
    """L1.json … L13.json — universal handoff to Phase 2."""
    return project / "phase1/generated_docs"


def human_docs_dir(project: Path) -> Path:
    """L*.md — human review counterpart to generated_docs/."""
    return project / "phase1/human_docs"


# ─── the design's natural-language spec text ─────────────────────────────
#
# ONE gather, ONE order, ONE denominator (vibe-ic#2086).
#
# WHY THIS LIVES HERE. Two consumers score against "this design's spec": the
# spec-to-rtl WAIVE handoff in `design_one_shot_runner`, which tells the author
# how many staged lesson sections strongly match, and `lesson_consumption_check`
# which the author then runs to VERIFY that number. Measured on 8HD-9 (#2086):
# the runner scored 202 strong matches against the gathered text while the
# command it printed took `--prompt <one spec-file>` and scored 0 of 212 — and
# both exited 0, because the gate had no way to notice it had been handed a
# different, smaller input. Two numbers that must agree cannot be computed by
# two functions; they are computed here, once, and every consumer calls this.

def spec_text_sources(project: Path):
    """The design's natural-language spec sources, in the ONE canonical order.

    Operator prose first (`input_prompt/` then `input_doc/`, `*.md` / `*.txt`),
    then the generated L-doc JSON. Deterministic and total: a consumer that
    reports a denominator over this set can name every file that produced it.
    """
    if rtl_input(project) == "original":
        return original_input_sources(project)
    out = []
    for d in (input_prompt_dir(project), input_doc_dir(project)):
        if d.is_dir():
            for f in sorted(d.rglob("*")):
                if f.is_file() and f.suffix.lower() in (".md", ".txt"):
                    out.append(f)
    gd = generated_docs_dir(project)
    if gd.is_dir():
        for f in sorted(gd.glob("L*.json")):
            out.append(f)
    return out


def gather_spec_text(project: Path, phase1_plain_text=None) -> str:
    """Concatenate the design's spec sources so a spec-PROSE consumer reads the
    SAME text every other consumer read. Best-effort + bounded; returns "" when
    no text source exists.

    ``phase1_plain_text`` is the immutable result of a strict pre-write gather
    (``design_one_shot_runner.step_rtl_gen``). When supplied — including an
    honestly empty string — do not re-read operator prose after that provenance
    check; only append generated L-docs, which live on the separate
    structured-spec side of the boundary.
    """
    chunks = []
    generated = []
    gd = generated_docs_dir(project)
    if rtl_input(project) == "structured" and gd.is_dir():
        generated = sorted(gd.glob("L*.json"))
    if phase1_plain_text is not None:
        if phase1_plain_text:
            chunks.append(phase1_plain_text)
        files = generated
    else:
        files = spec_text_sources(project)
    for f in files:
        try:
            chunks.append(f.read_bytes().decode("utf-8") if rtl_input(project) == "original"
                          else f.read_text(errors="replace"))
        except OSError:
            pass
    return "\n\n".join(chunks)


# ─── phase2 ──────────────────────────────────────────────────────────────

def phase2_dir(project: Path) -> Path:
    return project / "phase2"


def phase2_stage1_dir(project: Path) -> Path:
    return project / "phase2/stage1"


def phase2_stage2_dir(project: Path) -> Path:
    return project / "phase2/stage2"


def rtl_dir(project: Path) -> Path:
    return project / "phase2/stage1/rtl"


def rtl_pre_gen_backup_dir(project: Path) -> Path:
    return project / "phase2/stage1/rtl.pre_gen_backup"


def sim_dir(project: Path) -> Path:
    return project / "phase2/stage1/sim"


def sim_full_stack_dir(project: Path) -> Path:
    return project / "phase2/stage1/sim_full_stack"


def formal_dir(project: Path) -> Path:
    return project / "phase2/stage1/formal"


def tb_dir(project: Path) -> Path:
    return project / "phase2/stage1/tb"


#: Where a testbench is actually written, in the order to look. The flow itself
#: writes `sim_full_stack/`, and MEASURED across the tracked corpus that is where
#: the majority of them are:
#:
#:     sim_full_stack/ holds a testbench   29 project(s)
#:     sim/            holds a testbench   11
#:
#: vibe-ic#599: `l10_tb_conformance_check` carried its own candidate list without
#: `sim_full_stack` and `l12_tb_coverage_check` carried none at all, so step 4 —
#: the simulation step — was credited with no TB conformance or coverage
#: measurement on designs that had four L10 test cases and a real testbench on
#: disk. Two gates answering one question from two independently incomplete
#: views; the answer lives here now so there is one.
_TB_DIR_CANDIDATES = (
    "phase2/stage1/sim/tb",
    "phase2/stage1/sim_full_stack",
    "phase2/stage1/sim",
    "phase2/stage1/tb",
    "sim/tb",
    "sim_full_stack",
    "sim",
)


def _holds_testbench(d: Path) -> bool:
    if not d.is_dir():
        return False
    return any(d.glob("*.v")) or any(d.glob("*.sv")) or \
        any(d.glob("tb_*.v")) or any(d.glob("tb_*.sv"))


def resolve_tb_dirs(project: Path, given: "str | Path | None" = None):
    """Every canonical location under ``project`` that holds a testbench.

    Order is authoritative and duplicates are removed. Consumers that need one
    build root take the first; consumers that audit TB substance use the whole
    set so a trace-only ``sim/tb`` cannot hide a real ``sim_full_stack`` TB (or
    vice versa).
    """
    cands = []
    if given is not None:
        g = Path(given)
        cands.append(g if g.is_absolute() else project / g)
        if g.name == "tb":
            parent = g.parent
            cands.append(parent if parent.is_absolute() else project / parent)
    cands += [project / c for c in _TB_DIR_CANDIDATES]
    seen = set()
    found = []
    for c in cands:
        try:
            k = str(c.resolve())
        except (OSError, RuntimeError):
            k = str(c)
        if k in seen:
            continue
        seen.add(k)
        if _holds_testbench(c):
            found.append(c)
    return tuple(found)


def resolve_tb_dir(project: Path, given: "str | Path | None" = None):
    """The first canonical location that actually HOLDS a testbench.

    ``None`` when none do. Kept as the one-root face for L10/L12 and build
    consumers; the candidate set itself lives in :func:`resolve_tb_dirs`.
    """
    found = resolve_tb_dirs(project, given)
    return found[0] if found else None


def fpga_early_dir(project: Path) -> Path:
    """Step 6: early FPGA prototype + on-board <half-duplex-tester> test (Phase 2)."""
    return project / "phase2/stage1/fpga"


def constraints_dir(project: Path) -> Path:
    return project / "phase2/stage2/constraints"


def synth_dir(project: Path) -> Path:
    return project / "phase2/stage2/synth"


#: Written by phase 3's `step_synth` beside the netlist it mapped
#: (`_write_synth_inputs_sidecar`): `{"netlist": "<top>_synth.v", ...}`.
SYNTH_INPUTS_SIDECAR = "synth_inputs.json"


def mapped_synth_netlist(project: Path) -> Optional[Path]:
    """The technology-MAPPED synthesis netlist -- the one PnR routes.

    Step 9 declares `netlist.v`, the GENERIC pre-map arm (`$_*_` primitives,
    kept for LEC). The netlist `pnr_input_netlist` hands to PnR is the mapped
    `<top>_synth.v` phase 3's `step_synth` writes into the same directory, and
    that step names it in `synth_inputs.json`. The name comes from there;
    when the sidecar is absent or unreadable (step_synth writes it best-effort)
    the directory's ONE `*_synth.v` is it. None when neither names an existing
    file inside the synthesis directory -- i.e. the mapped arm was not
    produced -- or when several `*_synth.v` leave it ambiguous."""
    import json

    d = synth_dir(project)
    try:
        rec = json.loads((d / SYNTH_INPUTS_SIDECAR).read_text())
    except (OSError, ValueError):
        rec = None
    if isinstance(rec, dict):
        name = rec.get("netlist")
        if not isinstance(name, str) or not name or Path(name).name != name:
            return None
        path = d / name
        return path if path.is_file() else None
    found = sorted(p for p in d.glob("*_synth.v") if p.is_file()) if d.is_dir() else []
    return found[0] if len(found) == 1 else None


def phase2_synth_input_identity(project: Path):
    """Content identity of Phase 2's canonical netlist consumed by Phase 3.

    A Phase 3 receipt can only describe the current design while this identity
    matches. Returning None says Phase 2 has not supplied a netlist to bind.
    """
    import hashlib

    path = synth_dir(project) / "netlist_yosys.v"
    if not path.is_file():
        return None
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None
    return {"path": str(path.relative_to(project)), "sha256": digest}


def phase3_signoff_input_identity(project: Path):
    """Content identity of the current inputs to Phase-3 sign-off.

    The netlist is mandatory.  Include the design's L-layer declarations and
    every staged constraint source the backend can consume, including the
    legacy constraint locations and Phase-3 generated SDCs.  Reports are
    deliberately excluded: rewriting a verdict cannot make its own old
    producer receipt current.  A missing or unreadable input fails closed.
    """
    import hashlib

    project = Path(project).resolve()
    netlist = phase2_synth_input_identity(project)
    if netlist is None:
        return None
    roots = (
        "input/constraints", "input/reference_flow", "constraints",
        "phase2/stage2/constraints", "phase3/stage3/constraints",
        "phase3/stage3/cts/constraints",
    )
    paths = [project / "phase3/librelane_switch.json"]
    docs = project / "phase1/generated_docs"
    if docs.is_symlink() and not docs.resolve().is_relative_to(project):
        return None
    if docs.is_dir():
        paths.extend(docs.glob("L*.json"))
    for rel in roots:
        root = project / rel
        if root.is_symlink() and not root.resolve().is_relative_to(project):
            return None
        if root.is_dir():
            paths.extend(path for path in root.rglob("*") if path.is_file())
    files = {}
    for path in sorted(set(paths)):
        if path.is_symlink() and not path.exists():
            return None
        if not path.exists():
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(project) or not resolved.is_file():
            return None
        try:
            files[path.relative_to(project).as_posix()] = hashlib.sha256(
                resolved.read_bytes()).hexdigest()
        except OSError:
            return None
    return {"schema": "vibeic.phase3_signoff_inputs.v1",
            "phase2_synth": netlist, "files": files}


def dft_dir(project: Path) -> Path:
    return project / "phase2/stage2/dft"


# ─── phase3 ──────────────────────────────────────────────────────────────

def phase3_dir(project: Path) -> Path:
    return project / "phase3"


def phase3_stage3_dir(project: Path) -> Path:
    return project / "phase3/stage3"


def phase3_stage4_dir(project: Path) -> Path:
    return project / "phase3/stage4"


def phase3_final_dir(project: Path) -> Path:
    """The run's SIGN-OFF METRICS directory — `phase3/final/`.

    It holds exactly one artefact, `metrics.json`, written by
    `signoff_metrics_aggregate` after the sign-off checkers have run and read
    by every release-document generator (`tapeout_docs_gen`,
    `ic_release_docs_gen`, `_ic_release_artefacts`, `release_docs_check`).

    It exists as a helper because those four readers named the path and NO
    producer wrote it: measured at v1.16.2, `grep -rn "final/metrics.json"`
    over the whole tree returned five readers and zero writers, so step 37.5ic
    could not produce a single one of its six document outputs for ANY design.
    A path a program reads but the layout does not define is a path nothing is
    responsible for creating.
    """
    return project / "phase3/final"


def phase3_stage5_manufacturing_dir(project: Path) -> Path:
    """Steps 37-40: fab / wafer sort / packaging / final ATE."""
    return project / "phase3/stage5_manufacturing"


def phase3_mixed_signal_dir(project: Path) -> Path:
    return project / "phase3/mixed_signal"


def pnr_dir(project: Path) -> Path:
    return project / "phase3/stage3/pnr"


def cts_dir(project: Path) -> Path:
    return project / "phase3/stage3/cts"


# ─── clock-plan provenance: ONE definition of "what the plan is derived from"
#
# The Step-16 clock plan (`cts_dir()/clock_plan.json`) is built by
# `phase3_one_shot_runner.step_canonicalize_artefacts` and audited by
# `clock_plan_check`. They used to answer "which files is this plan derived
# from?" DIFFERENTLY — the producer swept `project.rglob("*.sdc")`, the checker
# swept a fixed directory list — so the checker could call stale a plan the
# producer had just written from a file the checker never looked at. The two
# helpers below are that one definition, and both sides call them.
#
# Only current ASIC constraint locations belong to this input contract.
# Sweeping the project also read Quartus FPGA commands, synthesis-only decks
# and old LibreLane attempts into OpenROAD's ASIC clock plan. The producer,
# freshness check and dropped-clock check all use this same resolved list.
# User constraint directories remain additive, including auxiliary clocks;
# no project-wide fallback admits tool outputs or held/archived constraints.

SDC_PRIORITY_DIRS = (
    "phase3/stage3/constraints",
    "phase3/stage3/cts/constraints",
    "phase3/stage3/pnr",
    "phase2/stage2/constraints",
    "input/constraints",
    "steps/7_constraints",
    "constraints",
)


def clock_plan_input_sdcs(project: Path):
    """Current ASIC SDCs in stable order, shared by producer and consumer."""
    seen = []
    for rel in SDC_PRIORITY_DIRS:
        d = project / rel
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.sdc")):
            if f not in seen:
                seen.append(f)
    return seen


def clock_plan_sdc_digests(project: Path, sdc_files=None) -> dict:
    """`{project-relative path: sha256-of-bytes}` for the plan's input SDCs.

    CONTENT, never mtime. The corpus this plugin ships — and every user project
    — is distributed by `git clone`, copy, rsync or archive extraction, none of
    which preserve mtimes, so an mtime-keyed provenance finding is noise on any
    tree that was not the one that produced the artefact. A digest survives all
    of them and is the only thing that actually answers "was this plan derived
    from the constraints that are here now?".
    """
    import hashlib  # local: only the clock-plan provenance path needs it
    if sdc_files is None:
        sdc_files = clock_plan_input_sdcs(project)
    out = {}
    for f in sdc_files:
        try:
            out[str(f.relative_to(project))] = hashlib.sha256(
                f.read_bytes()).hexdigest()
        except (OSError, ValueError):
            continue
    return out


def extracted_dir(project: Path) -> Path:
    """Parasitic extraction (SPEF)."""
    return project / "phase3/stage3/extracted"


def postroute_timing_repair_dir(project: Path) -> Path:
    return project / "phase3/stage3/postroute_timing_repair"


def spice_dir(project: Path) -> Path:
    return project / "phase3/stage3/spice"


def sta_dir(project: Path) -> Path:
    """Post-route STA. Pre-PnR STA is also written here."""
    return project / "phase3/stage3/sta"


def sim_postlayout_dir(project: Path) -> Path:
    return project / "phase3/stage3/sim_postlayout"


def mixed_signal_dir(project: Path) -> Path:
    return project / "phase3/mixed_signal"


def mixed_signal_cosim_dir(project: Path) -> Path:
    return project / "phase3/mixed_signal/cosim"


def gds_dir(project: Path) -> Path:
    return project / "phase3/stage4/gds"


def foundry_handoff_dir(project: Path) -> Path:
    return project / "phase3/stage4/foundry_handoff"


def fpga_final_dir(project: Path) -> Path:
    """Step 39: final FPGA sign-off bitstream (recompile + on-board re-test).

    THREE paths used to compete for this one concept and none of them agreed:

      * flow/phase1_phase2_phase3.yaml:1839 declares step 39's required output
        as ``phase2/stage1/fpga/final/*.sof``;
      * ``fpga_on_board_attestation_check`` documents ``bitstream_path:
        "phase2/stage1/fpga/final/<name>.sof"`` in its own docstring;
      * this accessor pointed at ``phase3/stage4/fpga``, whose ONLY consumer
        was a bare ``mkdir`` in phase3_one_shot_runner — nothing ever wrote a
        file into it, on any run.

    So the declared artefact was UNPRODUCIBLE: post-#455 (required_outputs is
    ALL-of-N) a genuinely-successful on-board sign-off is reported MISSING.
    Unified onto the path the flow and the attestation checker already name;
    `design_one_shot_runner.step_emit_phase2_manifests` now stages the burned
    bitstream here when — and only when — `fpga_burn` really PASSed.
    """
    return project / "phase2/stage1/fpga/final"


# ─── analog (distributed across phase1/2/3 per Layout P) ────────────────

def phase1_analog_block_dir(project: Path, block: str) -> Path:
    """LEGACY phase-distributed location for A1 spec extraction.

    NOT where A1 writes. `analog_one_shot_runner` and
    `phase1_doc_one_shot_runner` both emit through `analog_dir()` below
    (phase3/analog/), and `analog_a1_spec_extract_check` reads there. This
    helper has ZERO callers in the tree — it is retained only because
    `migrate_to_layout_p` can leave a legacy project-root `analog/` tree at
    this path, which the A-gates accept as a SECOND candidate
    (`_analog_a_check_common.block_artefact_candidates`). Do not route new
    producers here."""
    return project / "phase1/analog" / block


def phase2_analog_block_dir(project: Path, block: str) -> Path:
    """LEGACY phase-distributed location for the A2-A4 analog frontend
    (topology / netlist / corner sweep). NOT where A2-A4 write — see
    `phase1_analog_block_dir` above; same zero-caller status and same
    legacy-tolerance rationale."""
    return project / "phase2/analog" / block


def phase3_analog_block_dir(project: Path, block: str) -> Path:
    """A5-A9 analog backend (layout / PV / resim / hardmacro / cosim)."""
    return project / "phase3/analog" / block


def phase3_hardmacro_dir(project: Path) -> Path:
    """A8 packaged hardmacros (per-block lef/lib/gds/v)."""
    return project / "phase3/analog/hardmacro"


def phase3_hardmacro_block_dir(project: Path, block: str) -> Path:
    return project / "phase3/analog/hardmacro" / block


# CANONICAL analog root. Every analog producer in the tree writes here and
# every A-gate reads here — A1..A9 alike, not just the A5-A9 backend. The
# phase-distributed helpers above are legacy read-side tolerances with no
# callers; the comment that used to sit here told callers to use them for
# A1 / A2-A4, which no producer has ever done.
def analog_dir(project: Path) -> Path:
    """Canonical analog root — phase3/analog (spec, topology, netlist, corner
    sweep, layout, PV, resim, hardmacro, and the block list itself)."""
    return project / "phase3/analog"


def analog_block_dir(project: Path, block: str) -> Path:
    """Canonical per-block analog dir — phase3/analog/<block>, for A1..A9
    outputs. `phase{1,2}_analog_block_dir` are legacy read-side locations
    only; do not send new producers there."""
    return project / "phase3/analog" / block


def hardmacro_dir(project: Path) -> Path:
    """A8 packaged hardmacros — phase3/analog/hardmacro/."""
    return project / "phase3/analog/hardmacro"


# ─── phase1 metadata files (live INSIDE phase1/, not at project root) ────

def phase1_extraction_patterns_file(project: Path) -> Path:
    return project / "phase1/extraction_patterns.json"


def phase1_extraction_patterns_auto_file(project: Path) -> Path:
    return project / "phase1/extraction_patterns.auto.json"


def phase1_completeness_check_config_file(project: Path) -> Path:
    return project / "phase1/completeness_check_config.json"


def phase1_ai_deep_review_patches_file(project: Path) -> Path:
    return project / "phase1/ai_deep_review_patches.json"


# ─── reports ─────────────────────────────────────────────────────────────

def reports_dir(project: Path) -> Path:
    return project / "reports"


# `reports/` is partitioned into phase-aligned subfolders. Programs MUST
# write into the correct subfolder via `report_path()` (auto-routes by
# filename) or via a specific `reports_<phase>_dir()` helper. Top-level
# flat reports/ files are not allowed (except the two whitelisted root
# files); the `reports_subfolder_taxonomy_check` gate enforces this.

def reports_phase1_dir(project: Path) -> Path:
    return project / "reports/phase1"


def reports_phase2_dir(project: Path) -> Path:
    return project / "reports/phase2"


def reports_phase3_dir(project: Path) -> Path:
    return project / "reports/phase3"


def reports_audit_dir(project: Path) -> Path:
    return project / "reports/audit"


def reports_orchestrator_dir(project: Path) -> Path:
    return project / "reports/orchestrator"


def run_logs_dir(project: Path) -> Path:
    """Cross-phase orchestrator logs (full_flow.log, audit_final.log,
    phase{1,2,3,23}.log, etc.). Lives under reports/orchestrator/logs."""
    return project / "reports/orchestrator/logs"


# Category map: filename (or filename glob suffix) → reports subfolder.
# Used by `report_path()` to auto-route a flat report filename into the
# right phase subfolder. Keys are matched in order: exact match first,
# then suffix prefix match, then by-extension default.

_REPORT_CATEGORY: dict = {
    # Phase 1 (was phase1)
    "extraction_coverage_report.json": "phase1",
    "extraction_coverage_report.md": "phase1",
    "phase1_input_vs_generated_completeness.json": "phase1",
    "phase1_input_vs_generated_completeness.md": "phase1",
    # Phase 2 (was phase2)
    "synth_netlist.json": "phase2",
    "sdc_check.json": "phase2",
    "md905_test.json": "phase2",
    "test_cases.json": "phase2",
    "rtl_bugs.json": "phase2",
    "bringup_plan.md": "phase2",
    # Phase 3
    "antenna.rpt": "phase3",
    "antenna.json": "phase3",
    "drc_router.json": "phase3",
    "drc_signoff.json": "phase3",
    "drc_signoff.rpt": "phase3",
    "em.json": "phase3",
    "em.rpt": "phase3",
    "erc.rpt": "phase3",
    "foundry_handoff_audit.json": "phase3",
    "gds_size.json": "phase3",
    "ir_drop.json": "phase3",
    "ir_drop.rpt": "phase3",
    "lvs.json": "phase3",
    "lvs.rpt": "phase3",
    # #203 — netgen `-json` short/open/pin localization for LVS-FAIL triage
    "lvs_localize.json": "phase3",
    "power.json": "phase3",
    "power.rpt": "phase3",
    "si_crosstalk.json": "phase3",
    "si_crosstalk.rpt": "phase3",
    "si_mcf_sta.json": "phase3",
    "si_mcf_sta.rpt": "phase3",
    "si_mcf_sta_check.json": "phase3",
    "si_mcf_repair.json": "phase3",
    "spice_correlation.json": "phase3",
    "density.json": "phase3",
    "density.rpt": "phase3",
    # #198 Branch 1 — which reference_flow QoR knobs phase-3 adopted/rejected
    "reference_flow_knobs.json": "phase3",
    "reference_flow_knobs.md": "phase3",
    # debug_first_pass.py outputs — phase varies per step
    "drc_fix_first_pass.json": "phase3",
    "hold_fix_first_pass.json": "phase3",
    "ir_drop_triage_first_pass.json": "phase3",
    "lvs_triage_first_pass.json": "phase3",
    "ppa_predict_first_pass.json": "phase2",
    "sta_review_first_pass.json": "phase3",
    "synth_doctor_first_pass.json": "phase2",
    # Analog (distributed — default lands in phase3 since most analog
    # artefacts are layout/PV/hardmacro which live in phase3)
    "analog_one_shot.json": "phase3",
    # Audit (cross-phase verdicts + summaries)
    "flow_compliance.json": "audit",
    "flow_compliance_check.log": "audit",
    "fpga_signoff.json": "audit",
    "phase23_completion_audit.json": "audit",
    "tapeout_checklist.json": "audit",
    "FINAL_REPORT.md": "audit",
    # NOTE: `final_summary.md` and `chip_specific_summary.md` are NOT
    # in this map; they are special-cased in `report_path()` below to
    # land at `reports/` root (doctrine rule #3 location + the only
    # files `reports_subfolder_taxonomy_check` whitelists at root).
    # Orchestrator (one-shot runner JSON)
    "phase1_one_shot.json": "orchestrator",
    "phase2_one_shot.json": "orchestrator",
    "phase3_one_shot.json": "orchestrator",
    "phase23_one_shot.json": "orchestrator",
    "vibe_ic_one_shot.json": "orchestrator",
    "analog_flow_compliance.json": "orchestrator",
}

_REPORT_SUBDIR_CATEGORY: dict = {
    # Top-level reports/ subdirs that bucket many files, mapped to a
    # single phase parent.
    "cdc": "phase2",
    "coverage": "phase2",
    "dft": "phase2",
    "fpga": "phase2",
    "gates": "phase2",
    "lint": "phase2",
    "plugin_quality": "phase2",
    "doc_extract": "phase1",
    "pdf": "phase1",
    "phase1_presence.json": "phase1",
    "sta": "phase3",
    "pnr": "phase3",
    "mixed_signal": "phase3",
    "analog": "phase3",
    "signoff": "audit",
    "hardware": "audit",
}


def report_path(project: Path, filename: str) -> Path:
    """Auto-route a report filename into its phase-aligned subfolder.

    Examples:
        report_path(p, "synth_netlist.json")  → reports/phase2/synth_netlist.json
        report_path(p, "drc_signoff.rpt")     → reports/phase3/drc_signoff.rpt
        report_path(p, "final_summary.md")    → reports/final_summary.md       (root)
        report_path(p, "chip_specific_summary.md") → reports/chip_specific_summary.md
        report_path(p, "fpga/on_board_pass.json")
                                              → reports/phase2/fpga/on_board_pass.json

    Unknown filenames default to reports/audit/ (cross-phase fallback)
    so writers don't crash, but the `reports_subfolder_taxonomy_check`
    gate will surface unknowns at audit time.

    `final_summary.md` and `chip_specific_summary.md` are the two
    whitelisted root-level files per doctrine rule #3 +
    `reports_subfolder_taxonomy_check`. They land at `reports/`, not
    `reports/audit/`, which closes the producer-consumer mismatch where
    the auto-router was placing them where the gate could not find them.
    """
    if filename in REPORTS_VALID_ROOT_FILES:
        return reports_dir(project) / filename
    head, _, tail = filename.partition("/")
    if head in _REPORT_SUBDIR_CATEGORY:
        sub = _REPORT_SUBDIR_CATEGORY[head]
        return reports_dir(project) / sub / filename
    if filename in _REPORT_CATEGORY:
        return reports_dir(project) / _REPORT_CATEGORY[filename] / filename
    # Unknown → audit/ as safe default
    return reports_dir(project) / "audit" / filename


#: THE AUDITOR'S PER-STEP OUTPUT RECORD. R-0915-165.
#:
#: One file per step, written by `flow_compliance_check` beside that step's metrics row, naming
#: the declared outputs the step's OWN gate found `missing` or `unusable`, stamped with the
#: invocation that measured them. It exists because no other record can answer "which artefact
#: is this upstream verdict ABOUT":
#:   * `reports/metrics/<sid>.json` cannot -- `step_metrics.emit` refuses a list, "the schema is
#:     flat by design", and a path is not a valid key component;
#:   * this run's compliance report cannot -- it is written after every step, and a step's gate
#:     needs the answer while the run is still going;
#:   * and the step folders' `outputs.json` must NEVER be trusted: it is a restatement of the
#:     declaration and it LIES. Measured on a converged run, the step folders list 90 outputs and
#:     7 of them -- steps 15, 17, 19, 20, 21, 22 and 34, every folder marked `"status": "pass"`
#:     -- name a `rel` that does not exist in the run directory at all.
#:
#: It sits under `reports/audit/`, which the taxonomy whitelist below already allows, and which
#: is the auditor's own directory. Declared here rather than spelled at the write site so the
#: writer and `release_docs_check` cannot come to disagree about where it is.
STEP_OUTPUT_RECORD_DIR: str = "reports/audit/step_outputs"


def step_output_record_path(project: Path, sid) -> Path:
    """The per-step output record for `sid`, named the way `step_metrics` names a step."""
    try:
        import step_metrics as _sm                          # noqa: PLC0415
        name = _sm.normalize_step(sid)
    except Exception:                                       # pragma: no cover
        name = str(sid).replace(".", "_").lower()
    return project / STEP_OUTPUT_RECORD_DIR / f"{name}.json"
#: WHERE A REPORT USED TO BE WRITTEN, by filename. READ SIDE ONLY. R-0915-160.
#:
#: `report_path` above is the ONE answer to "where does this report go", and that is
#: deliberately not negotiable: a producer and its readers disagreeing about a path is the
#: defect R-0915-151 closed, and a reader that enumerates locations for the CURRENT run goes
#: stale the next time a producer moves.
#:
#: Reading a project that ALREADY EXISTS is a different question. `phase1_one_shot_runner`
#: wrote `reports/phase1_one_shot.json` until R-0915-151 moved it onto the router, and every
#: project produced before that still has its pass-1 record there. A reader that cannot see
#: it reports the pass as missing -- measured: `run_second_pass_only` read only the routed
#: path, so on such a project pass 1 was NOT carried forward, the second pass published a
#: record saying so, and the front door halted at phase 1 on a project that had in fact run.
#: `vibe_ic_entry_guard` already tolerated both spellings and called this one "legacy"; this
#: is that tolerance with ONE definition instead of four.
#: MAPS ONE NAME TO EVERY OLDER LOCATION A READER USED TO ACCEPT, in order of preference.
#:
#: It is a TUPLE per name because `analog_one_shot.json` needs two: the router categorises it
#: `phase3`, and `run_status` accepted it at `reports/orchestrator/` and at `reports/` -- neither
#: of which is where the router points.
#:
#: MEASURED, and this table is the shape of a regression I caused. `run_status` had the
#: routed-and-flat pair hand-written three times, for ALL SIX of its phase reports. I replaced
#: those loops with a single call to the resolver below while this table knew ONE name, so five
#: tolerances vanished silently: `test_issue590_auto_picks_the_furthest_phase` stages every report
#: at the flat `reports/<name>.json` and `run_status` answered "UNKNOWN -- no final verdict, no
#: recorded PID and no log or artifact of any kind under this project". Replacing N candidates
#: with a resolver means the resolver must know all N.
LEGACY_REPORT_PATHS: dict = {
    "phase1_one_shot.json": ("reports/phase1_one_shot.json",),
    "phase2_one_shot.json": ("reports/phase2_one_shot.json",),
    "phase3_one_shot.json": ("reports/phase3_one_shot.json",),
    "phase23_one_shot.json": ("reports/phase23_one_shot.json",),
    "vibe_ic_one_shot.json": ("reports/vibe_ic_one_shot.json",),
    "analog_one_shot.json": ("reports/orchestrator/analog_one_shot.json",
                             "reports/analog_one_shot.json"),
}


def report_path_for_reading(project: Path, filename: str):
    """``(path, is_legacy)`` -- where to READ this report from on an existing project.

    The routed path when something is there, else a legacy spelling when one exists and is
    there, else the routed path again so a "not found" message names the canonical place.
    `is_legacy` is returned rather than logged because the caller is the one that must
    DISCLOSE it: a reader silently accepting an old layout is how two layouts survive.

    This never decides where to WRITE. `report_path` is the only answer to that.
    """
    routed = report_path(project, filename)
    try:
        if routed.is_file():
            return routed, False
    except OSError:                                        # pragma: no cover
        pass
    for legacy_rel in (LEGACY_REPORT_PATHS.get(filename) or ()):
        legacy = project / legacy_rel
        try:
            if legacy.is_file():
                return legacy, True
        except OSError:                                    # pragma: no cover
            continue
    return routed, False
#: #505's COVERAGE-ONLY SIDECAR: ONE NAME, AND DELIBERATELY NOT A ROUTED ONE.
#:
#: `phase1_doc_one_shot_runner` writes this file from inside D1 to say that a phase-1 failure was
#: PURELY doc-coverage; `vibe_ic_one_shot_runner` reads it to decide whether to demote instead of
#: halting, and `phase1_one_shot_runner` names its digest in the record it publishes so an expert
#: second pass can carry that name forward (R-0915-160). It is an EXEMPTION, which is why three
#: programs care about it and why they must not disagree about where it is.
#:
#: MEASURED, the spelling count this replaces: FIVE hand-written copies of one path across three
#: programs -- one constant in `phase1_one_shot_runner`, two `project / "reports" / "phase1" /
#: "phase1_exit_reason.json"` chains in `vibe_ic_one_shot_runner` (the coverage predicate and the
#: demotion branch), and the producer's own write and unlink in `phase1_doc_one_shot_runner`. That
#: is the shape R-0915-151 closed for the phase reports and R-0915-168 closed for the auditor's
#: temp and lock, still open for this one file.
#:
#: IT IS NOT `report_path`'s ANSWER, AND THAT IS STATED HERE RATHER THAN LEFT TO BE DISCOVERED.
#: `report_path(project, "phase1_exit_reason.json")` returns `reports/audit/phase1_exit_reason.json`
#: -- the catch-all for an unrecognised report name -- while the producer and both readers have
#: always used `reports/phase1/`. Measured on this tree. So this constant is the LITERAL location,
#: not a routing call, and every project that already has a sidecar keeps working. Moving the file
#: onto the router is a PRODUCER move: it needs its own change, with a read-side tolerance for the
#: old location the way `LEGACY_REPORT_PATHS` carries one, and it is not done here. What is done
#: here is that the five copies become one, so the move -- if it is ever made -- is a one-line move.
COVERAGE_ONLY_SIDECAR_REL: str = "reports/phase1/phase1_exit_reason.json"


def coverage_only_sidecar_path(project: Path) -> Path:
    """#505's coverage-only sidecar in `project`. The one place this path is assembled."""
    return Path(project) / COVERAGE_ONLY_SIDECAR_REL


#: THE AUDITOR'S OWN IN-PROGRESS FILES: ONE DECLARED SHAPE. R-0915-168.
#:
#: The auditor writes temp-then-replace so no reader sees a half-written document, and locks a
#: note so two passes cannot interleave one. Every such mechanism creates a file that is the
#: AUDITOR'S but carries no content a reader could identify it by -- and each was found by a
#: reviewer AFTER it shipped, then patched with its own shape:
#:
#:   R-0915-151  <audit>.json.<pid>.tmp                     the canonical audit's temp
#:   R-0915-152  audit_created/<hex>.json.lock              the note's lock
#:   R-0915-152  audit_created/<hex>.json.<pid>.<tid>.tmp   the note's temp
#:   R-0915-165  step_outputs/<sid>.json.<pid>.tmp          the per-step record's temp
#:
#: Four shapes for one idea, three incidents, and a fifth mechanism would have made a fifth. The
#: shape is now a NAMED MARKER rather than a position: `.fcc-tmp` and `.fcc-lock` are minted by
#: `_auditor_write` and by nothing else, so the digest recognises them ANYWHERE, with no directory
#: list and no path table, and the next auditor mechanism is covered the day it is written.
AUDITOR_TMP_SUFFIX: str = ".fcc-tmp"
AUDITOR_LOCK_SUFFIX: str = ".fcc-lock"

#: `<final>.<pid>.<tid>.fcc-tmp` and `<final>.fcc-lock`. The pid and tid stay because they are
#: what let a human attribute a leftover to the process that abandoned it -- `_atomic_artefact`'s
#: own reason for naming its temps rather than using an opaque `tmpXXXXXX`.
_AUDITOR_TMP_RE_NEW = re.compile(r"\.\d+\.\d+" + re.escape(AUDITOR_TMP_SUFFIX) + r"$")
_AUDITOR_LOCK_RE_NEW = re.compile(re.escape(AUDITOR_LOCK_SUFFIX) + r"$")

#: THE FOUR OLD SHAPES, READ SIDE ONLY. Leftovers in them exist on every tree produced before
#: this change, and a reader that stopped recognising them would let an old leftover move the
#: design hash -- the same mistake as dropping a legacy report location, which cost a round on
#: `next/icslot70`. The helper mints NONE of these; nothing new ever lands here.
_LEGACY_AUDITOR_INPROGRESS_RES = (
    re.compile(r"^reports/audit/phase23_completion_audit\.json\.\d+\.tmp$"),
    re.compile(r"^reports/audit/audit_created/[0-9a-f]+\.json\.lock$"),
    re.compile(r"^reports/audit/audit_created/[0-9a-f]+\.json\.\d+\.\d+\.tmp$"),
    re.compile(r"^reports/audit/step_outputs/[0-9a-z_.]+\.json\.\d+\.tmp$"),
)


def auditor_temp_name(project_final: Path, pid: Optional[int] = None,
                      tid: Optional[int] = None) -> Path:
    """The temp sibling `_auditor_write` publishes `project_final` through.

    A SIBLING, never a file in a temp directory: `os.replace` is atomic only WITHIN a
    filesystem, and a temp elsewhere silently degrades to a copy, reinstating the half-written
    window this exists to close. That is `_atomic_artefact`'s own reasoning, and it is why the
    receipt redirect's `TemporaryDirectory` is a different thing entirely -- that one is not
    publishing into the project at all.
    """
    import os as _os                                        # noqa: PLC0415
    import threading as _threading                          # noqa: PLC0415
    p_ = int(_os.getpid() if pid is None else pid)
    t_ = int(_threading.get_ident() if tid is None else tid)
    return project_final.with_name(
        f"{project_final.name}.{p_}.{t_}{AUDITOR_TMP_SUFFIX}")


def auditor_lock_name(project_final: Path) -> Path:
    """The lock sibling for `project_final`.

    A SIBLING, not a lock on the file itself: locking the document would mean opening the very
    file a concurrent writer is about to replace.
    """
    return project_final.with_name(f"{project_final.name}{AUDITOR_LOCK_SUFFIX}")


def is_auditor_inprogress_name(rel: str) -> bool:
    """Is this project-relative name one the auditor mints WHILE writing something else?

    The one question `design_input_digest` asks, answered from the declaration above so writer
    and reader cannot drift. Deliberately NOT `*.tmp` or `*.lock`: a producer's own partial
    write anywhere in the tree is a design artefact and must keep counting.
    """
    if _AUDITOR_TMP_RE_NEW.search(rel) or _AUDITOR_LOCK_RE_NEW.search(rel):
        return True
    return any(rx.match(rel) for rx in _LEGACY_AUDITOR_INPROGRESS_RES)


# Ordered list of valid reports/ children (for the taxonomy whitelist
# gate). Anything else under reports/ is a violation.
REPORTS_VALID_SUBDIRS: tuple = (
    "phase1", "phase2", "phase3", "audit", "orchestrator",
)

# The only two markdown files allowed at `reports/` root by
# `reports_subfolder_taxonomy_check`. Doctrine rule #3 ("reports/ root
# holds only final_summary.md + chip_specific_summary.md") + the
# attestation gate read them from this canonical location. Used by
# `report_path()` to bypass the bucket router for these two filenames.
REPORTS_VALID_ROOT_FILES: tuple = (
    "final_summary.md",
    "chip_specific_summary.md",
)


# Top-level whitelist (for the canonical-top-level enforcement gate).
#
# `steps/` is the owner's per-STEP publication view
# (`steps/<phase>/<stage>/<id>_<slug>/`, symlinks only — see
# `step_output_collector.py` and `emit_steps_view` below). It is a CANONICAL
# home, not a stray: `flow_compliance_check._glob_first` documents it as "the
# owner's step-folder design", `rtl_scan_scope` excludes it by name as "the
# flow's own PUBLICATION VIEW", and `flow_dashboard_web` serves per-step "open"
# links out of it. It was missing from this tuple only because exactly one
# runner built it, so nobody had measured the collision. MEASURED on
# `campaign_v1578/ibex/converge_1.5.78_sky130A_armA_stock` (a real top-runner
# run that HAS steps/): `top_level_outputs_in_canonical_check` reported
# `[FAIL] ... stray dir(s): sim, steps`. Now that EVERY orchestrator publishes
# the view, leaving it off would turn a hygiene gate red on every run — which
# teaches readers to ignore it. Recording the directory the flow legitimately
# owns is not widening the gate: `sim/`, `run_logs/`, `rtl/`, `synth/`,
# `pnr/`, top-level `*.log` and every other stray are still rejected exactly
# as before (covered by the reverse-case control in
# tests/test_steps_view_every_orchestrator.py).
TOP_LEVEL_VALID_DIRS: tuple = (
    "input", "phase1", "phase2", "phase3", "reports", "steps",
)
TOP_LEVEL_VALID_FILES: tuple = (
    "provenance.jsonl", "rig_topology.json", "waivers.json",
)


# ---------------------------------------------------------------------------
# ORGANIC #525 — SINGLE SOURCE OF TRUTH for audit / gate subprocess timeouts.
#
# The #469 size-adaptive audit timeout lived only inside
# final_report_generate.py while four other call sites kept hand-typed
# 300s/240s caps — so a large SoC (155k+ fillers, multi-GB artifact tree)
# whose flow_compliance legitimately needs 8-9 minutes was killed at 300s
# and the TIMEOUT mis-reported as a plain FAIL with empty detail. Per the
# Step-2.7 single-source doctrine the resolver now lives HERE and every
# consumer (final_report_generate, phase2 step_final_audit,
# phase23_completion_self_audit_check, emit_final_summary, the per-gate
# cap in flow_compliance_check) imports it.
# ---------------------------------------------------------------------------
AUDIT_TIMEOUT_ENV = "VIBE_IC_AUDIT_TIMEOUT_S"
AUDIT_TIMEOUT_DEFAULT_S = 900
AUDIT_SIZE_ADAPT_THRESHOLD_BYTES = 128 * 1024 * 1024   # 128 MiB
AUDIT_SIZE_ADAPT_S_PER_MIB = 4                          # +4 s per MiB over
AUDIT_TIMEOUT_CAP_S = 3600                              # never exceed 1 h
GATE_TIMEOUT_ENV = "VIBE_IC_GATE_TIMEOUT_S"
GATE_TIMEOUT_DEFAULT_S = 900
# Margin the OUTER wrapper adds on top of the child's own adaptive budget
# so the outer cap can never fire first (the #525 emit_final_summary bug:
# a 240s outer cap silently defeated #469's 900-3600s inner budget).
OUTER_TIMEOUT_MARGIN_S = 120


def dir_size_bytes(project, cap: int = 1 << 40) -> int:
    """Best-effort total size (bytes) of the run dir, used to make the
    audit timeout size-adaptive. Walks lazily and stops once `cap` is
    exceeded so this never becomes its own hot spot on huge trees.
    chip-AGNOSTIC: pure filesystem arithmetic, no name inspection."""
    import os
    total = 0
    try:
        for root, _dirs, files in os.walk(project):
            for fn in files:
                fp = Path(root) / fn
                try:
                    total += fp.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
                if total >= cap:
                    return total
    except OSError:
        pass
    return total


def audit_timeout_s(project, explicit=None, size_fn=None) -> int:
    """Resolve the flow_compliance subprocess timeout (seconds) — #469/#525.

    Precedence:
      1. an explicit value (CLI --audit-timeout);
      2. the VIBE_IC_AUDIT_TIMEOUT_S env var (if a positive int);
      3. a size-adaptive default: AUDIT_TIMEOUT_DEFAULT_S, plus
         AUDIT_SIZE_ADAPT_S_PER_MIB for every MiB the run dir exceeds
         AUDIT_SIZE_ADAPT_THRESHOLD_BYTES, capped at AUDIT_TIMEOUT_CAP_S.

    An explicit/env value is honored verbatim (no size adaptation) so a
    test can deliberately shrink it; only the computed default scales.
    Values ≤ 0 are rejected and fall through to the next source."""
    import os
    if explicit is not None and explicit > 0:
        return min(explicit, AUDIT_TIMEOUT_CAP_S)
    env_raw = os.environ.get(AUDIT_TIMEOUT_ENV)
    if env_raw is not None:
        try:
            env_val = int(env_raw)
        except (TypeError, ValueError):
            env_val = 0
        if env_val > 0:
            return min(env_val, AUDIT_TIMEOUT_CAP_S)
    base = AUDIT_TIMEOUT_DEFAULT_S
    size = (size_fn or dir_size_bytes)(project)
    if size > AUDIT_SIZE_ADAPT_THRESHOLD_BYTES:
        over_mib = (size - AUDIT_SIZE_ADAPT_THRESHOLD_BYTES) // (1024 * 1024)
        base += int(over_mib) * AUDIT_SIZE_ADAPT_S_PER_MIB
    return min(base, AUDIT_TIMEOUT_CAP_S)


def gate_timeout_s() -> int:
    """Per-gate subprocess cap for flow_compliance program_exit_zero gates
    (#525). The field measured reset_dependency_check at ~6 min on a 7.5MB
    post-PnR netlist and provenance sha256 over multi-GB GDS in the same
    range — the old 300s killed them mid-run. Default 900s, env-overridable
    (VIBE_IC_GATE_TIMEOUT_S), capped at AUDIT_TIMEOUT_CAP_S."""
    import os
    raw = os.environ.get(GATE_TIMEOUT_ENV)
    if raw is not None:
        try:
            val = int(raw)
        except (TypeError, ValueError):
            val = 0
        if val > 0:
            return min(val, AUDIT_TIMEOUT_CAP_S)
    return GATE_TIMEOUT_DEFAULT_S


# Single shared helper that every one-shot runner calls right before
# its DONE banner. Generates the canonical `reports/final_summary.md`
# (chip-AGNOSTIC) by invoking `final_report_generate.py` as a
# subprocess. Best-effort: failure is logged but does NOT change the
# runner's verdict (the runner's own step audit is the source of truth;
# the summary is a derived view).
# --------------------------------------------------------------------------- #
# "DID THIS INVOCATION PUBLISH THIS FILE?" — ONE implementation, for every
# reader that needs the answer.
#
# WHERE THIS CAME FROM, AND WHY IT MOVED. The question was first asked, and
# answered, inside `vibe_ic_one_shot_runner._published_here` (#2572/#2575): a
# phase report that exists is not this run's account of itself unless this run
# wrote it, and a stale record must never authorise a demotion. That reader
# resolves a phase REPORT NAME through the router, so the predicate lived
# behind that resolution and nothing else could ask it.
#
# A SECOND READER NOW NEEDS THE SAME QUESTION ABOUT AN ARBITRARY PATH. A run
# that declares a window (`--entry-step` / `--exit-step`) deliberately does NOT
# refresh the whole-flow documents — `reports/final_summary.md`,
# `reports/audit/phase23_completion_audit.json` — so a reader of that tree must
# be able to tell "this run wrote it" from "this run left the previous run's
# copy in place". That is the same question, and answering it a second time in
# a second place is how two staleness rules come to disagree about one file.
# So the predicate lives here, the phase-report reader delegates to it, and
# `FRESHNESS_TOLERANCE_S` has one value.
# --------------------------------------------------------------------------- #
FRESHNESS_TOLERANCE_S = 1.0


def published_here(path, started_at, tolerance_s=None) -> bool:
    """Was `path` written at or after `started_at`? `exists AND fresh`.

    `started_at` is the asking invocation's own start (`time.time()` at entry).
    The tolerance absorbs coarse filesystem mtime granularity: a file written
    microseconds after the run started must not read as older than the run.

    Fails CLOSED. An unreadable or absent path returns False — "this
    invocation did not publish it" — because the consequence of a wrong True
    is a stale document quoted as fresh evidence, and the consequence of a
    wrong False is a disclosure nobody needed."""
    from pathlib import Path as _Path
    tol = FRESHNESS_TOLERANCE_S if tolerance_s is None else tolerance_s
    try:
        p = _Path(path)
        return p.is_file() and (p.stat().st_mtime + tol >= started_at)
    except OSError:
        return False


def emit_final_summary(project, programs_dir=None) -> bool:
    """Run `final_report_generate.py` against `project` and return True
    on success, False on any failure (exception, missing tool, non-zero
    exit, stall). Caller logs the True/False; do NOT use the return
    to gate the verdict — final report is a downstream artefact.

    #525 sized an OUTER bound from the child's OWN size-adaptive audit
    budget, because a fixed 240s cap was killing the child before #469's
    900-3600s inner budget could even apply. Sizing a bound better is still
    guessing at one: the child is now supervised by forward progress, so it
    runs as long as it is working and no `timeout` parameter is left to get
    the arithmetic wrong. No caller ever passed one."""
    import sys
    from pathlib import Path
    if programs_dir is None:
        programs_dir = Path(__file__).resolve().parent
    final_gen = Path(programs_dir) / "final_report_generate.py"
    if not final_gen.is_file():
        return False
    try:
        r = _pr.run(
            [sys.executable, str(final_gen), str(project)],
            check=False,
            capture_output=True, text=True,
        )
        return r.returncode == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# The per-STEP output view: `<project>/steps/<phase>/<stage>/<id>_<slug>/`.
#
# WHY THIS HELPER EXISTS. `step_output_collector.materialize` was called from
# exactly ONE place — `vibe_ic_one_shot_runner`'s finalize — so a run driven
# straight at phase2 / phase3 / analog (how most cells are actually driven)
# ended with NO steps tree at all, and its absence was indistinguishable from
# a run that had nothing to show. MEASURED: a top-runner ibex backend run has
# `steps/` with 63 step folders; `AI_IC_design/4th_benchmark/sha256_rerun_e2e`,
# a phase-driven run with a full phase1/phase2/phase3 tree, has none.
#
# BEST-EFFORT, IN BOTH DIRECTIONS. Building the VIEW must never fail a run and
# must never HANG one — hence the subprocess + timeout, the same idiom
# `emit_final_summary` uses, and a blanket except around the whole body. But
# the failure must not be SILENT either: a run that produced artefacts and no
# steps tree used to look exactly like a run whose orchestrator never had the
# feature. So EVERY call writes `reports/audit/steps_view.json` recording what
# happened and why. That is the surfacing decision, and the reasoning is:
#   * raising  — kills a run over bookkeeping. Forbidden.
#   * a gate   — the view is derived, not evidence; failing a run because a
#                convenience view could not be built is the same crime.
#   * a WARN   — scrolls past, survives in no artefact, cannot be queried.
#   * a RECORD — durable, attributable, costs one small file, and INVERTS the
#                default: "no steps tree" is now a written statement with a
#                reason and a runner name instead of an unexplained absence.
# The stderr WARN is kept as well, for the human watching the run.
#
# The record is VERIFIED, NOT REPORTED. After the collector exits 0 this helper
# stats `steps/index.json` itself and counts the folders; a collector that
# claims success and leaves no tree is recorded as a failure. `nested_folders`
# counts entries whose `folder` has the owner-specified two separators
# (phase/stage/step), so a regression back to a flat `steps/<id>_<slug>/` is
# visible in the record rather than having to be re-derived from the tree.
# ---------------------------------------------------------------------------
STEPS_VIEW_REPORT_NAME = "steps_view.json"
# The collector is a pure filesystem walk over the run dir; MEASURED at 0.22 s
# wall (including interpreter start) on an 89 MB / 63-step ibex backend run.
# The cap exists only so a pathological tree cannot wedge a finalize.
STEPS_VIEW_TIMEOUT_S = 300


def steps_view_report_path(project) -> Path:
    """Canonical location of the steps-view status record."""
    return report_path(Path(project), STEPS_VIEW_REPORT_NAME)


def emit_steps_view(project, programs_dir=None, runner=None,
                    timeout=None, only_steps=None) -> dict:
    """Build `<project>/steps/` and record the outcome. NEVER raises.

    Returns the status record (also written to
    `reports/audit/steps_view.json`). `status` is one of:
      OK                — tree present, index.json readable, >=1 step folder
      BUILD_FAILED      — collector errored, or exited 0 with no usable tree
      TIMEOUT           — collector exceeded `timeout`
      COLLECTOR_MISSING — step_output_collector.py not next to this module
    Callers log the record; they must NOT gate on it."""
    import json
    import subprocess          # local imports: helper runs once per run
    import sys
    import time
    from pathlib import Path

    project = Path(project)
    rec: dict = {
        "program": "steps_view",
        "runner": runner or "unknown",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "steps_root": str(project / "steps"),
        "status": "BUILD_FAILED",
        "tree_present": False,
        "n_steps": 0,
        "n_with_outputs": 0,
        "nested_folders": 0,
        "error": None,
    }
    try:
        if programs_dir is None:
            programs_dir = Path(__file__).resolve().parent
        collector = Path(programs_dir) / "step_output_collector.py"
        if not collector.is_file():
            rec["status"] = "COLLECTOR_MISSING"
            rec["error"] = f"not found: {collector}"
        else:
            if timeout is None:
                timeout = STEPS_VIEW_TIMEOUT_S
            proc = None
            try:
                _cmd = [sys.executable, str(collector), str(project)]
                if only_steps:
                    # A run that declared a window refreshes only its own
                    # steps' folders; the collector CARRIES the rest of the
                    # index rather than dropping it. See
                    # step_output_collector.materialize's docstring.
                    _cmd += ["--only-steps",
                             ",".join(sorted(str(s) for s in only_steps))]
                    rec["bounded_to"] = sorted(str(s) for s in only_steps)
                proc = subprocess.run(
                    _cmd, timeout=timeout, check=False,
                    capture_output=True, text=True,
                )
            except subprocess.TimeoutExpired:
                rec["status"] = "TIMEOUT"
                rec["error"] = (f"step_output_collector exceeded {timeout}s "
                                f"on {project}")
            except Exception as exc:
                rec["error"] = f"{type(exc).__name__}: {exc}"
            if proc is not None:
                if proc.returncode != 0:
                    rec["error"] = (
                        f"step_output_collector rc={proc.returncode}: "
                        + (proc.stderr or "").strip()[-600:])
                else:
                    # Do not take the child's word for it — read the tree.
                    idx = project / "steps" / "index.json"
                    try:
                        steps = json.loads(idx.read_text()).get("steps") or []
                    except Exception as exc:
                        rec["error"] = (
                            "collector exited 0 but steps/index.json is "
                            f"unreadable: {type(exc).__name__}: {exc}")
                    else:
                        rec["n_steps"] = len(steps)
                        rec["n_with_outputs"] = sum(
                            1 for s in steps if (s.get("n_outputs") or 0) > 0)
                        rec["nested_folders"] = sum(
                            1 for s in steps
                            if str(s.get("folder") or "").count("/") == 2)
                        rec["tree_present"] = (project / "steps").is_dir()
                        if rec["tree_present"] and rec["n_steps"] > 0:
                            rec["status"] = "OK"
                        else:
                            rec["error"] = ("collector exited 0 but left no "
                                            "step folders")
    except Exception as exc:      # the helper itself must never raise
        rec["error"] = f"{type(exc).__name__}: {exc}"

    try:
        out = steps_view_report_path(project)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
        rec["record_path"] = str(out)
    except Exception as exc:
        rec["record_error"] = f"{type(exc).__name__}: {exc}"

    try:
        if rec["status"] == "OK":
            print(f"steps view: steps/ — {rec['n_steps']} steps, "
                  f"{rec['n_with_outputs']} with outputs "
                  f"({rec['nested_folders']} nested phase/stage/step)")
        else:
            print(f"  [WARN] steps view NOT built ({rec['status']}): "
                  f"{rec.get('error')} — recorded in "
                  f"reports/audit/{STEPS_VIEW_REPORT_NAME}", file=sys.stderr)
    except Exception:
        pass
    return rec


def publish_report_then_steps_view(project, programs_dir, runner, summary,
                                   report_name, only_steps=None):
    """Write `summary` to its report path, THEN build the steps view.

    Returns (steps_view_record, report_path). The caller attaches the record to
    `summary` and re-writes the report -- which is why the report is published
    twice: once so the view can READ it, once so it CARRIES the view's outcome.

    THE ORDER IS THE POINT. `steps/index.json` now takes a step's status from
    the runner's own verdict when its plan attributes one (see
    `flow_dashboard_data._runner_verdict_overrides`), and the collector is a
    SUBPROCESS -- it can only read what is already on disk. Every orchestrator
    used to call `emit_steps_view` BEFORE writing its report, so at view-build
    time this run's verdicts did not exist yet and the view fell back to
    file-existence inference. That is how a step whose runner returned FAIL --
    after the FAIL's own artefacts had already been written -- was published as
    "pass". Publishing first is what makes the two records read the same fact
    instead of two independently-derived guesses about it.

    Never raises: a report that cannot be written must not kill a run, and the
    view is best-effort by construction."""
    import json

    out = report_path(project, report_name)
    try:
        if report_name in {"phase1_one_shot.json", "phase2_one_shot.json", "phase3_one_shot.json"}:
            from benchmark_dispatch import _bind_runner_report
            summary.update(_bind_runner_report(
                summary, project, str(Path(programs_dir) / (runner + ".py")), report_name))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    except Exception:                                     # noqa: BLE001
        pass
    return emit_steps_view(project, programs_dir, runner=runner,
                           only_steps=only_steps), out
