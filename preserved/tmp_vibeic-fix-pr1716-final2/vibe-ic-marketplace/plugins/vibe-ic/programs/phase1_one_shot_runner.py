#!/usr/bin/env python3
"""phase1_one_shot_runner.py — Phase 1 unified dispatcher.

Phase 1 produces structured L1-L23 JSON from one of two input modes:

  - input_doc : vendor docs under `input/docs/` or `phase1/input_doc/`,
                processed by the 17-skill doc-extraction track that
                lives in `phase1_doc_one_shot_runner.py`.
  - input_prompt : free-text prompt under `input/phase1_prompt.md` or
                structured YAML under `input/phase1_structured.yaml`,
                processed by `tools/phase1_engine/cli.py run-all`
                (IC Expert Agent dialogue path, plain-language register).

Both modes write to `phase1/generated_docs/L*.json` + `phase1/human_docs/L*.md`.

The runner auto-detects the mode by probing for input files, and dispatches
to the appropriate backend. Callers may force the mode via `--mode`.

Outputs:
  - <project>/phase1/generated_docs/L1..L13.json
  - <project>/phase1/human_docs/L*.md
  - <project>/reports/phase1_one_shot.json

chip-AGNOSTIC. Detection logic uses path existence only; no chip-specific
strings.

Usage:
    python3 phase1_one_shot_runner.py <project_dir> [--ic-name <name>]
    python3 phase1_one_shot_runner.py <project_dir> --mode docs
    python3 phase1_one_shot_runner.py <project_dir> --mode prompt
    python3 phase1_one_shot_runner.py <project_dir> --mode auto   # default
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import _path_layout as _pl
import _runner_lock  # ORGANIC #588 — single-driver lock (all 4 runners)
import step_preflight as _spf  # required_inputs PRE-FLIGHT at every dispatch site
# THE L-document write chokepoint — records the producing release on the
# L1 / L4 / L8 documents this runner back-fills from a prompt.
import l_doc_generator_stamp as _stamp
import _entry_attestation

# Phase 1 owns the doc-extraction track. The ~47k-line
# doc-extraction implementation lives in `phase1_doc_one_shot_runner.py`.
# Re-export every public AND
# private (underscore-prefixed) symbol so existing imports of the form
# `from programs.phase1_one_shot_runner import <doc_extraction_helper>`
# keep working without per-test rewrites. Underscore-prefixed symbols
# (which the test harness commonly imports as internal helpers) are
# excluded from `from X import *`, so we use a manual `globals()`
# splice.
import phase1_doc_one_shot_runner as _phase1_doc  # noqa: E402
for _sym in dir(_phase1_doc):
    if not _sym.startswith('__'):
        globals().setdefault(_sym, getattr(_phase1_doc, _sym))
del _sym


PROGRAMS_DIR = Path(__file__).resolve().parent


@dataclass
class StepResult:
    name: str
    status: str
    duration_s: float
    detail: str
    # ADDED for the pre-flight. This runner's row was the only one of the four
    # with no `extras`, so a refusal would have had to throw away everything
    # that makes it actionable — which artefact was absent, which step owed it,
    # where the ledger is. Additive and defaulted, so every existing
    # construction site and every existing `asdict(...)` reader is unchanged.
    extras: Dict[str, Any] = field(default_factory=dict)


def _preflight_refusal(name: str):
    """This runner's refusal row for `step_preflight.gate`.

    `BLOCKED` carries the same meaning it does in the other three runners: the
    step was NOT attempted because an INPUT could not support it, so NOTHING is
    known. It is listed in `_aggregate_verdict._FAIL_STATUSES` — without that it
    would have fallen through that function's catch-all `return "PASS"` and a
    refusal would have produced a GREEN run, which is the defect class this
    whole pre-flight exists to remove. Measured on this ladder specifically:
    Phase 1's verdict was `FAIL if any FAIL else PASS_WITH_WAIVERS if any
    WAIVED/SKIP else PASS`, so a lone BLOCKED row scored PASS — the cleanest
    possible green run over a Phase 1 that was never given a document.
    """
    def _mk(detail: str, extras: Dict[str, Any]) -> StepResult:
        return StepResult(name, _spf.REFUSAL_STATUS, 0.0, detail, extras=extras)
    return _mk


# Statuses that must NOT reach a green verdict. `BLOCKED` is `step_preflight`'s
# refusal status; `FAIL` is this runner's pre-existing one, unchanged.
_FAIL_STATUSES = ("FAIL", _spf.REFUSAL_STATUS)


def _aggregate_verdict(plan: List[StepResult]) -> str:
    """Phase 1's top-level verdict. Extracted from `main()` unchanged except
    for the BLOCKED tier, so a control can assert the non-greenness directly
    rather than re-running the whole dispatcher to observe it."""
    if any(s.status in _FAIL_STATUSES for s in plan):
        return "FAIL"
    if any(s.status in ("WAIVED", "SKIP") for s in plan):
        return "PASS_WITH_WAIVERS"
    return "PASS"


# ── Input-mode detection ────────────────────────────────────────────

def _detect_input_mode(project: Path) -> str:
    """Probe `<project>/` for input artefacts. Returns 'docs',
    'prompt', or 'none'.

    Mode selection:
      - `phase1/input_doc/` populated (Layout P canonical):
            → 'docs' (delegates to phase1_doc_one_shot_runner).
      - `input/docs/` populated OR `input/phase1_*` present
            (legacy phase1_engine inputs):
            → 'prompt' (phase1_engine CLI handles both raw doc
              corpora and structured/free-form prompts).
      - none of the above:
            → 'none' (caller's choice to SKIP or error).
    """
    new_input_doc = _pl.input_doc_dir(project) if hasattr(_pl, "input_doc_dir") else None
    if new_input_doc and new_input_doc.is_dir() and any(new_input_doc.iterdir()):
        return "docs"
    # Raw vendor docs under input/docs/ (PDF/DOCX/MD/TXT/…) must go through
    # the doc-extraction track (phase1_doc_one_shot_runner), NOT the
    # phase1_engine "prompt" path: the engine's run-all reverse-extractor
    # (from_existing_docs) only ingests pre-structured L1..L9 *.json and
    # yields 0 facts on raw prose, producing zero L docs. The doc track is
    # the canonical raw-corpus → L1-L23 ingester. Only treat input/docs/ as
    # a "prompt"-mode engine input when it already holds L*.json layer files.
    legacy_input_docs = project / "input" / "docs"
    if legacy_input_docs.is_dir() and any(legacy_input_docs.iterdir()):
        has_layer_json = any(
            f.is_file() and f.suffix == ".json" and f.name[:1] == "L"
            and f.name[1:2].isdigit()
            for f in legacy_input_docs.iterdir()
        )
        return "prompt" if has_layer_json else "docs"
    # A dialogue convergence fact-graph YAML (phase1_structured.yaml) is the
    # DIALOGUE artefact (User<->IC-Expert convergence). Per the unified-backend
    # directive (2026-06-20) it is rendered into a freestyle document by
    # phase1_dialogue_render and flows through the SAME DOC->JSON doc-extraction
    # track as every other input, so the emitted L1-L24 JSON is HOMOGENEOUS
    # regardless of source. _run_docs_mode performs the render-bridge; the
    # IC-Expert Agent supplies the independent AI track + convergence. (The
    # legacy engine reverse-extractor is still reachable via `--mode prompt`.)
    if (project / "input" / "phase1_structured.yaml").is_file():
        return "docs"
    # A free-text `phase1_prompt.md` is RAW PROSE — a concrete spec DESCRIPTION,
    # exactly like a doc under input/docs/. It must go through the doc-extraction
    # track (the canonical raw-corpus → L1-L24 ingester), NOT the engine reverse-
    # extractor (which "only ingests pre-structured L*.json and yields 0 facts on
    # raw prose"). Routing it to "prompt" was the defect that gave a concrete spec
    # only the deterministic floor instead of the full doc pipeline; the engine
    # "prompt" path is reserved for the DIALOGUE artifact (phase1_structured.yaml)
    # above. The docs dispatch bridges this file into input/docs/ (_run_docs_mode).
    if (project / "input" / "phase1_prompt.md").is_file():
        return "docs"
    return "none"


# ── Prompt mode (IC Expert Agent / dialogue → phase1_engine) ───────

def _find_phase1_engine() -> "Tuple[Optional[Path], List[str]]":
    """Resolve tools/phase1_engine/cli.py via an explicit fallback chain
    (ORGANIC-20260606-plugin-cache-missing-phase1-engine #429):
      1. the engine BUNDLED in the plugin payload (<plugin>/tools/…) — the
         only location that exists in an installed cache;
      2. $CLAUDE_PLUGIN_ROOT/tools/… (plugin-host hint);
      3. repo-checkout walk-up from PROGRAMS_DIR (legacy);
      4. known sibling-checkout guesses (legacy).
    Returns (cli_path_or_None, tried_locations) so the caller can emit a
    HARD, NAMED error listing every location searched — never a silent
    null engine."""
    tried: List[str] = []
    # 1. bundled inside the plugin payload (works from the installed cache)
    cand = PROGRAMS_DIR.parent / "tools" / "phase1_engine" / "cli.py"
    tried.append(str(cand))
    if cand.is_file():
        return cand, tried
    # 2. plugin-host hint
    env_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env_root:
        cand = Path(env_root) / "tools" / "phase1_engine" / "cli.py"
        tried.append(str(cand))
        if cand.is_file():
            return cand, tried
    # 3. repo-checkout walk-up
    here = PROGRAMS_DIR
    for ancestor in (here, *here.parents):
        cand = ancestor / "tools" / "phase1_engine" / "cli.py"
        tried.append(str(cand))
        if cand.is_file():
            return cand, tried
    # 4. opensource_repo / sibling layouts, relative to the walk-up ancestors.
    #    PORTABILITY: an earlier release guessed at absolute paths under a
    #    personal home directory here. Those exist on exactly one machine, so
    #    on every other install they were dead entries that merely padded the
    #    "searched" list. The sibling layout is expressed RELATIVE to the
    #    plugin's own ancestors instead, which works wherever it is installed.
    for ancestor in (here, *here.parents):
        cand = ancestor / "opensource_repo" / "tools" / "phase1_engine" / "cli.py"
        tried.append(str(cand))
        if cand.is_file():
            return cand, tried
    return None, tried


def step_ingest_render(project: Path, ic_name: str) -> StepResult:
    t0 = time.time()
    cli, tried = _find_phase1_engine()
    if cli is None or not cli.is_file():
        # #429 — hard NAMED error: list every location the fallback chain
        # searched so a bare cache install diagnoses itself.
        return StepResult("phase1_ingest_render", "FAIL",
                          time.time() - t0,
                          "phase1_engine cli NOT FOUND. Searched (in "
                          "order): " + "; ".join(tried) + ". The engine "
                          "ships bundled at <plugin>/tools/phase1_engine "
                          "(v0.2.58+); set CLAUDE_PLUGIN_ROOT or run from "
                          "a repo checkout otherwise.")
    structured = project / "input" / "phase1_structured.yaml"
    docs_dir = project / "input" / "docs"
    facts = project / "facts.yaml"
    out_dir = _pl.generated_docs_dir(project)
    out_dir.mkdir(parents=True, exist_ok=True)
    if structured.is_file():
        src = structured
    elif docs_dir.is_dir():
        src = docs_dir
    else:
        # v0.1.32 fix (ORGANIC-20260528-phase1-prompt-md-not-ingested):
        # auto-bridge input/phase1_prompt.md into a synthesized input/docs/
        # so the doc-ingest path can consume it. Previously this path SKIPped
        # silently with PASS_WITH_WAIVERS, leaving phase2 to FAIL at
        # phase1_precheck with 0/13 L docs. The bridge makes the runner
        # turnkey for callers who staged only the prompt.md (the convention
        # the mode detector at line ~110 already recognises).
        prompt_md = project / "input" / "phase1_prompt.md"
        if prompt_md.is_file():
            docs_dir.mkdir(parents=True, exist_ok=True)
            (docs_dir / "design_description.md").write_text(prompt_md.read_text())
            src = docs_dir
        else:
            return StepResult("phase1_ingest_render", "SKIP",
                              time.time() - t0,
                              "neither input/phase1_structured.yaml nor "
                              "input/docs/ nor input/phase1_prompt.md "
                              "present — Phase 1 needs at least one input. "
                              "Caller (IC Expert Agent) must populate "
                              "input/phase1_structured.yaml from dialogue.")
    # cli.py uses package-relative imports (``from .ingest import ...``),
    # so it must be run as a module (``python -m phase1_engine.cli``) with
    # the package parent dir on sys.path — NOT as a standalone script, which
    # fails with "attempted relative import with no known parent package".
    pkg_dir = cli.parent                 # .../tools/phase1_engine
    pkg_parent = pkg_dir.parent          # .../tools
    # NOTE: the engine's ``run-all`` verb does NOT accept ``--facts``; it
    # writes facts.yaml internally (ingest → gaps → render). Passing
    # ``--facts`` triggers an argparse "unrecognized arguments" rc=2.
    cmd = [sys.executable, "-m", f"{pkg_dir.name}.{cli.stem}",
           "run-all", str(src), str(out_dir),
           "--ic-name", ic_name]
    env = dict(os.environ)
    env["PYTHONPATH"] = (str(pkg_parent) + os.pathsep +
                         env.get("PYTHONPATH", "")).rstrip(os.pathsep)
    # gap_detect.DEFAULT_CLASS_KB is a *relative* path
    # ("vibe-ic-marketplace/plugins/.../class_kb"), so the engine must run
    # with cwd = the repo root that contains vibe-ic-marketplace/. Walk up
    # from the package dir to find it; fall back to pkg_parent.
    repo_root = pkg_parent
    for anc in (pkg_dir, *pkg_dir.parents):
        if (anc / "vibe-ic-marketplace").is_dir():
            repo_root = anc
            break
    cp = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                        cwd=str(repo_root), env=env)
    if cp.returncode != 0:
        return StepResult("phase1_ingest_render", "FAIL",
                          time.time() - t0,
                          f"rc={cp.returncode} "
                          f"stderr_tail={cp.stderr[-1200:]}")
    # Deterministic structural-port seed: the LLM-based ingest captures only
    # ~17% of an AI's ports (CVDP audit), missing ports stated in markdown
    # interface tables / inline Verilog. Merge the program-extracted ports /
    # params / reset into L1.pinout + L8R so the structural facts that drive
    # correct RTL are present even on the deterministic path. Best-effort —
    # never fails the render.
    seeded = _seed_structural_ports(project, out_dir)
    note = f"facts={facts.name} out={out_dir.name}"
    if seeded:
        note += f" +{seeded} structural ports seeded (L1.pinout/L8R)"
    return StepResult("phase1_ingest_render", "PASS", time.time() - t0, note)


def _prompt_text_for(project: Path) -> str:
    """Best-effort: the free-text spec the ingest consumed."""
    for p in (project / "input" / "phase1_prompt.md",
              project / "input" / "docs" / "design_description.md"):
        if p.is_file():
            return p.read_text(errors="replace")
    docs = project / "input" / "docs"
    if docs.is_dir():
        return "\n".join(f.read_text(errors="replace")
                         for f in sorted(docs.glob("*")) if f.is_file())
    return ""


def _seed_structural_ports(project: Path, out_dir: Path) -> int:
    """Merge deterministic phase1_port_extract ports/params/reset into the
    generated L1 (pinout) + L8R JSON. Returns the number of ports seeded.
    Never raises — a seeding failure must not break the render."""
    try:
        sys.path.insert(0, str(PROGRAMS_DIR))
        import phase1_port_extract as _ppx
        prompt = _prompt_text_for(project)
        if not prompt.strip():
            return 0
        facts = _ppx.extract(prompt)
        ports = facts.get("ports") or []
        if not ports:
            return 0
        # L1.pinout — only fill if absent/empty (never clobber a richer LLM view)
        l1p = out_dir / "L1_DATASHEET.json"
        if l1p.is_file():
            l1 = json.loads(l1p.read_text())
            if not l1.get("pinout"):
                l1["pinout"] = ports
                _stamp.dump(l1p, l1)
        # L8R — structural RTL constants: ports + parameters + reset
        l8r = out_dir / "L8_RTL_CONSTANTS.json"
        d = json.loads(l8r.read_text()) if l8r.is_file() else {}
        if not d.get("ports"):
            d["ports"] = ports
        if facts.get("parameters") and not d.get("parameters"):
            d["parameters"] = facts["parameters"]
        if facts.get("reset") and not d.get("reset"):
            d["reset"] = facts["reset"]
        if facts.get("enums") and not d.get("enums"):
            d["enums"] = facts["enums"]
        _stamp.dump(l8r, d)
        # L4 — register map (markdown register table with an offset column)
        if facts.get("regmap"):
            l4p = out_dir / "L4_REGMAP.json"
            l4 = json.loads(l4p.read_text()) if l4p.is_file() else {}
            if not l4.get("registers") and not l4.get("regmap"):
                l4["registers"] = facts["regmap"]
                _stamp.dump(l4p, l4)
        return len(ports)
    except Exception:
        return 0


def step_human_docs(project: Path) -> StepResult:
    """The phase1_engine.render emits human MDs alongside the JSON layer
    files when its `--also-human` flag is set. This step verifies those
    landed under <project>/human_docs/."""
    t0 = time.time()
    hd = project / "human_docs"
    if not hd.is_dir() or not list(hd.glob("L*.md")):
        return StepResult("phase1_human_docs", "WAIVED",
                          time.time() - t0,
                          "human_docs/L*.md not produced (engine cli "
                          "may not have --also-human; caller can "
                          "post-process facts.yaml → MD as needed)")
    return StepResult("phase1_human_docs", "PASS",
                      time.time() - t0,
                      f"{len(list(hd.glob('L*.md')))} human MD docs")


# ── Docs mode (vendor docs → phase1_doc_one_shot_runner) ───────────

def _run_docs_mode(project: Path, ic_name: str,
                   forwarded_args: Optional[List[str]] = None) -> int:
    """Dispatch to phase1_doc_one_shot_runner.main() with the project
    dir + forwarded extra args. Returns the runner's exit code.

    phase1_doc_one_shot_runner orchestrates the 17 doc-gen skills (the
    doc-extraction track) and emits its own
    `reports/orchestrator/phase1_doc_one_shot.json` summary. The
    dispatcher then composes that summary into the unified
    `reports/phase1_one_shot.json` so callers see one entry point.
    """
    # Bridge a DIALOGUE / PROMPT front-end into `input/docs/` so the
    # doc-extraction track consumes it as a freestyle document — the unified
    # DOC->JSON backend (owner directive 2026-06-20). Only when `input/docs/`
    # holds no document yet (a real document always wins).
    #   - phase1_structured.yaml (dialogue convergence fact-graph) -> rendered
    #     into a freestyle design-description doc via phase1_dialogue_render.
    #   - phase1_prompt.md (raw prose) -> it IS a document; copied verbatim.
    # A real document wins — but "a real document" means an actual non-empty,
    # ingestible FILE, NOT merely "input/docs/ contains some entry". A bare
    # `.gitkeep` (the standard git empty-dir marker), an empty/hidden file, or an
    # empty subdir must NOT suppress the dialogue/prompt render-bridge — else the
    # staged phase1_structured.yaml dialogue is silently DROPPED and the
    # doc-extraction track ingests an empty dir → empty L-docs with no error
    # (Step-2.7 §4.05). Test for a non-empty real document file.
    docs_dir = project / "input" / "docs"

    def _has_real_doc(d: Path) -> bool:
        if not d.is_dir():
            return False
        for f in d.rglob("*"):
            if (f.is_file() and not f.name.startswith(".")
                    and f.stat().st_size > 0):
                return True
        return False

    if not _has_real_doc(docs_dir):
        structured = project / "input" / "phase1_structured.yaml"
        prompt_md = project / "input" / "phase1_prompt.md"
        rendered: Optional[str] = None
        if structured.is_file():
            try:
                import phase1_dialogue_render as _dlg
                rendered, _kind = _dlg.render_dialogue(structured)
            except Exception:  # noqa: BLE001 — never hard-fail the bridge
                rendered = structured.read_text(errors="replace")
        elif prompt_md.is_file():
            rendered = prompt_md.read_text(errors="replace")
        if rendered is not None:
            docs_dir.mkdir(parents=True, exist_ok=True)
            (docs_dir / "design_description.md").write_text(rendered)
    # Build argv for phase1_doc_one_shot_runner.main(). Its argparse
    # takes the project dir as positional + accepts the standard
    # one-shot flags. Forward any extra runner-specific args.
    orig_argv = sys.argv[:]
    sys.argv = ["phase1_doc_one_shot_runner", str(project)]
    # ORGANIC #583 round-2 — the dispatcher's own argparse CONSUMES
    # --ic-name into args.ic_name (it never lands in `extras`), so the
    # docs runner's #541 authoritative override never fired on the
    # orchestrator-forwarded main path: L1.chip_name stayed None and the
    # L9.top_module fallback picked the project DIRECTORY name. Re-emit
    # it onto the delegated argv whenever the caller stated a real name
    # (the dispatcher default "UNNAMED_CHIP" is not a statement).
    if (ic_name and ic_name.strip()
            and ic_name.strip().upper() != "UNNAMED_CHIP"
            and not any(a == "--ic-name" for a in (forwarded_args or []))):
        sys.argv.extend(["--ic-name", ic_name.strip()])
    if forwarded_args:
        sys.argv.extend(forwarded_args)
    try:
        # Reuse the imported _phase1_doc module's main()
        rc = _phase1_doc.main()  # type: ignore[attr-defined]
    except AttributeError:
        # If phase1_doc_one_shot_runner doesn't expose `main`,
        # fall back to subprocess invocation (same argv shape as above,
        # including the #583 r2 --ic-name re-emit).
        cp = subprocess.run(
            [sys.executable,
             str(PROGRAMS_DIR / "phase1_doc_one_shot_runner.py"),
             *sys.argv[1:]],
            capture_output=False, text=True,
        )
        rc = cp.returncode
    finally:
        sys.argv = orig_argv
    return int(rc) if rc is not None else 0


# ── The second track (both input modes) ────────────────────────────
#
# Wired HERE, not in `phase1_doc_one_shot_runner`, for two reasons:
#
#   * this dispatcher is the one entry point that covers BOTH input modes, and
#     both emit L-docs — a track wired only into the docs backend would never
#     see a design that arrived through the dialogue/prompt path;
#   * `flow_gate_enforcement_audit` (#306) inspects THIS file and not the docs
#     backend. A gate wired where the audit cannot see it reads as AUDIT_ONLY —
#     which is precisely the state that audit measured for 62 of 72 gates, and
#     precisely what this track must not become.

_EXPERT_TRACK = "phase1_expert_parse_track.py"


def _run_expert_track(project: Path) -> int:
    """Run the Phase-1 EXPERT track — the second track of the program-first +
    AI-backup dual-track doctrine (#312).

    Its FINDINGS are advisory: a divergence between the two tracks needs a
    human to converge it, and a design may legitimately not state a fact.

    Its EXECUTION is not. The track must produce a report, and a missing or
    unparseable one FAILs Phase 1. That asymmetry is the whole point: a second
    track that can quietly not run is indistinguishable from no second track,
    which is the defect #312 exists to name.
    """
    prog = PROGRAMS_DIR / _EXPERT_TRACK
    if not prog.is_file():
        print(f"ERROR: {_EXPERT_TRACK} missing — the Phase-1 expert track "
              f"cannot run and its absence must not pass silently",
              file=sys.stderr)
        return 1
    # Resolve the report through the shared path helper rather than naming a
    # directory here: the track writes it via the same helper, and a reader
    # looking in the wrong place sees a track that never ran.
    report = _pl.report_path(project, "phase1/expert_parse_track.json")
    # Remove any prior report FIRST, so "the report exists" can only mean THIS
    # run wrote it. A stale report from an earlier run is exactly how a track
    # that died would still look like a track that ran.
    try:
        report.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        print(f"      ERROR: cannot clear the previous expert-track report "
              f"({exc}) — its freshness could not be established",
              file=sys.stderr)
        return 1
    try:
        cp = subprocess.run(
            [sys.executable, str(prog), str(project)],
            capture_output=True, text=True, timeout=600, check=False)
    except subprocess.TimeoutExpired:
        print("      ERROR: the expert track timed out — a timeout is not a "
              "verdict, and an unevaluated track cannot pass",
              file=sys.stderr)
        return 1
    for line in (cp.stdout or "").strip().splitlines():
        print(f"      {line}")
    # 0 = ran, 2 = ran and nothing applied. Anything else — including a crash
    # that never reached the program's own error path — is a track that did
    # not complete.
    if cp.returncode not in (0, 2):
        print(f"      expert track FAILED to complete (rc={cp.returncode}): "
              f"{(cp.stderr or '').strip().splitlines()[-1:] or ['(no detail)']}",
              file=sys.stderr)
        return 1
    if not report.is_file():
        print("      ERROR: the expert track wrote no report — its verdict is "
              "unknown, which is not the same as clean", file=sys.stderr)
        return 1
    try:
        json.loads(report.read_text(errors="replace"))
    except (OSError, ValueError) as exc:
        print(f"      ERROR: the expert-track report does not parse ({exc}) — "
              f"unreadable evidence is not evidence", file=sys.stderr)
        return 1
    return 0


def run_phase1_second_track(project: Path, rc_in: int) -> int:
    """The second track, run after the L-docs exist. Returns the exit code
    Phase 1 should report: a track that did not run overrides a clean backend
    run, and a backend failure is never masked by the track passing."""
    print("[phase1] expert track (second track) ...")
    rc_track = _run_expert_track(project)
    return max(int(rc_in or 0), rc_track)


# ── Top-level dispatcher ───────────────────────────────────────────

def _finalize_entry_attestation(project: Path, report_path: Path,
                                completion_rc: int) -> int:
    """Record a completed producer; strict score-time verification gates it."""
    docs = project / "phase1" / "generated_docs"
    has_docs = docs.is_dir() and any(docs.glob("L*.json"))
    if not has_docs:
        print("ENTRY_ATTESTATION_NOT_RECORDED: runner produced no L-document "
              "to attest", file=sys.stderr)
        return int(completion_rc)
    test_root = None
    ledger_override = None
    # Pytest subprocesses must not leave temporary-project rows in the real
    # passwd-derived state ledger.  This affects producer WRITE only; the strict
    # guard deliberately ignores every env-selected path.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        test_root = (Path(tempfile.gettempdir()) /
                     f"vibe-ic-entry-attestation-test-{os.getuid()}-{os.getpid()}")
        test_root.mkdir(mode=0o700, exist_ok=True)
        ledger_override = test_root / "entry.jsonl"
    try:
        _entry_attestation.record_completed_run(
            project, runner="phase1_one_shot_runner",
            completion_rc=completion_rc, report=report_path,
            ledger_path_override=ledger_override)
    except _entry_attestation.AttestationError as exc:
        print("ENTRY_ATTESTATION_NOT_RECORDED: " + str(exc), file=sys.stderr)
    finally:
        if test_root is not None:
            try:
                (test_root / "entry.jsonl").unlink(missing_ok=True)
                test_root.rmdir()
            except OSError:
                pass
    return int(completion_rc)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("project", type=Path)
    p.add_argument("--ic-name", default="UNNAMED_CHIP")
    p.add_argument("--mode",
                   choices=["auto", "docs", "prompt"],
                   default="auto",
                   help="input mode: auto-detect (default), force docs, or force prompt")
    args, extras = p.parse_known_args()
    project = args.project.resolve()
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    # ORGANIC #588 — single-driver lock, honored by the standalone phase
    # runner too (not just the orchestrator). Re-enters cleanly when the
    # orchestrator delegated this run (env token); refuses a SECOND
    # standalone phase1 on a project a live runner already drives.
    _lock = _runner_lock.acquire_or_reenter(project, "phase1_one_shot_runner")
    if _lock is None:
        return 3

    # Resolve mode. When auto-detect finds no input, fall through to
    # prompt mode so step_ingest_render emits a SKIP status (verdict
    # PASS_WITH_WAIVERS rc=0). This matches the legacy behaviour where
    # an empty project gracefully reports "nothing to do" rather than
    # exiting non-zero.
    if args.mode == "auto":
        detected = _detect_input_mode(project)
        mode = detected if detected != "none" else "prompt"
    else:
        mode = args.mode

    # Docs mode: delegate to phase1_doc_one_shot_runner
    if mode == "docs":
        t0 = time.time()
        # PRE-FLIGHT (canonical step D1). Its declared input is the STAGED
        # corpus — `input/docs/*`, `input/phase1_prompt.md`,
        # `input/phase1_structured.yaml`, or a directly-staged
        # `phase1/input_{doc,prompt}/`. Without this, a project with nothing
        # staged ran the whole 17-skill doc-extraction track over an empty
        # tree and reported a verdict about the L-docs it "produced".
        _pf = _spf.gate(
            project, "phase1_one_shot_runner", "doc_extract",
            _preflight_refusal("phase1_doc_extract"),
            _run_docs_mode, project, args.ic_name, extras)
        # `_run_docs_mode` returns an int rc; the refusal factory returns a
        # StepResult. The TYPE is the discriminator, and it is exact — there is
        # no rc value that is also a StepResult.
        refused = isinstance(_pf, StepResult)
        rc = 1 if refused else int(_pf)
        if refused:
            # The second track parses the L-docs D1 was supposed to write. D1
            # was never called, so there is nothing for it to examine — running
            # it would manufacture a second, derived failure and bury the real
            # one. RECORDED in the summary below rather than skipped silently.
            second_track = ("not run — D1 was REFUSED, so no L-doc exists for "
                            "the expert track to parse")
        else:
            second_track = "ran"
            rc = run_phase1_second_track(project, rc)
        # The dispatcher always emits reports/phase1_one_shot.json so
        # callers / tests see a unified entry point regardless of mode.
        reports = project / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        verdict = (_aggregate_verdict([_pf]) if refused
                   else ("PASS" if rc == 0 else "FAIL"))
        summary = {
            "phase": 1,
            "mode": "docs",
            "project": str(project),
            "ic_name": args.ic_name,
            "delegated_to": "phase1_doc_one_shot_runner",
            "delegated_rc": rc,
            "duration_s": time.time() - t0,
            "verdict": verdict,
            "second_track": second_track,
        }
        if refused:
            # A refusal must be readable AS a refusal, not as "the delegate
            # returned 1". Same shape as the prompt branch's `steps` list.
            summary["steps"] = [asdict(_pf)]
            summary["preflight_ledger"] = _spf.LEDGER_REL
        # Per-step output view — see the prompt-mode call below. BOTH exits of
        # this main() get it; wiring only one would leave the docs entry (Path
        # A, the vendor-document front door) without a steps tree.
        summary["steps_view"] = _pl.emit_steps_view(
            project, PROGRAMS_DIR, runner="phase1_one_shot_runner")
        report_path = reports / "phase1_one_shot.json"
        report_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
        return _finalize_entry_attestation(project, report_path, rc)

    # Prompt mode: original phase1_engine path
    plan: List[StepResult] = []
    # PRE-FLIGHT (canonical step D1) — the SAME site as the docs branch above:
    # one flow step, two mode branches, one question. Gating only one of them
    # would leave whichever front door a given design used unexamined, which is
    # the shape of the gap this closes.
    plan.append(_spf.gate(
        project, "phase1_one_shot_runner", "doc_extract",
        _preflight_refusal("phase1_ingest_render"),
        step_ingest_render, project, args.ic_name))
    plan.append(step_human_docs(project))

    # The prompt path emits the same L-docs, so it gets the same second track
    # and the same supply gate. Wiring only the docs path would leave every
    # dialogue-entered design unexamined by both.
    #
    # NOT after a refusal, for the reason given in the docs branch: the track
    # parses L-docs that were never written, so it can only report a derived
    # failure on top of the real one.
    _refused = any(s.status == _spf.REFUSAL_STATUS for s in plan)
    rc_second = 0 if _refused else run_phase1_second_track(project, 0)

    reports = project / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    summary = {
        "phase": 1,
        "mode": mode,
        "project": str(project),
        "ic_name": args.ic_name,
        "steps": [asdict(s) for s in plan],
        "verdict": _aggregate_verdict(plan),
        "second_track": "not run — D1 was REFUSED" if _refused else "ran",
    }
    if _refused:
        summary["preflight_ledger"] = _spf.LEDGER_REL
    # Per-step output view — <project>/steps/<phase>/<stage>/<id>_<slug>/.
    # A phase1-only run shows every later step with zero outputs, which is the
    # honest picture: the tree is the flow, and "nothing produced yet" is a
    # statement worth having on disk. Best-effort, non-gating; recorded in
    # reports/audit/steps_view.json either way.
    summary["steps_view"] = _pl.emit_steps_view(
        project, PROGRAMS_DIR, runner="phase1_one_shot_runner")
    report_path = reports / "phase1_one_shot.json"
    report_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(f"\n=== phase1_one_shot_runner DONE (mode={mode}) ===")
    print(f"verdict: {summary['verdict']}")
    for s in plan:
        print(f"  {s.status:6} {s.name:24} {s.detail[:120]}")
    final_rc = max(0 if summary["verdict"] != "FAIL" else 1, rc_second)
    return _finalize_entry_attestation(project, report_path, final_rc)


if __name__ == "__main__":
    sys.exit(main())
