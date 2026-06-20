#!/usr/bin/env python3
"""phase1_one_shot_runner.py — Phase 1 unified dispatcher.

Phase 1 produces structured L1-L23 JSON from one of two input modes:

  - input_doc : vendor docs under `input/docs/` or `phase1/input_doc/`,
                processed by the 17-skill doc-extraction track that
                lives in `phase1_doc_one_shot_runner.py`.
  - input_prompt : free-text prompt under `input/phase1_prompt.md` or
                structured YAML under `input/phase1_structured.yaml`,
                processed by `tools/phase1_engine/cli.py run-all`
                (PM Agent dialogue path).

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
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Tuple
import _path_layout as _pl
import _runner_lock  # ORGANIC #588 — single-driver lock (all 4 runners)

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
    if (project / "input" / "phase1_structured.yaml").is_file():
        return "prompt"
    if (project / "input" / "phase1_prompt.md").is_file():
        return "prompt"
    return "none"


# ── Prompt mode (PM Agent / dialogue → phase1_engine) ──────────────

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
    # 4. opensource_repo / sibling layouts
    for guess in ("/home/user/AI_IC_design/tools/phase1_engine/cli.py",
                  "/home/user/AI_IC_design/opensource_repo/tools/"
                  "phase1_engine/cli.py"):
        p = Path(guess)
        tried.append(str(p))
        if p.is_file():
            return p, tried
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
                              "Caller (PM agent) must populate "
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
                l1p.write_text(json.dumps(l1, indent=2))
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
        l8r.write_text(json.dumps(d, indent=2))
        # L4 — register map (markdown register table with an offset column)
        if facts.get("regmap"):
            l4p = out_dir / "L4_REGMAP.json"
            l4 = json.loads(l4p.read_text()) if l4p.is_file() else {}
            if not l4.get("registers") and not l4.get("regmap"):
                l4["registers"] = facts["regmap"]
                l4p.write_text(json.dumps(l4, indent=2))
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


# ── Top-level dispatcher ───────────────────────────────────────────

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
        rc = _run_docs_mode(project, args.ic_name, extras)
        # The dispatcher always emits reports/phase1_one_shot.json so
        # callers / tests see a unified entry point regardless of mode.
        reports = project / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        verdict = "PASS" if rc == 0 else "FAIL"
        summary = {
            "phase": 1,
            "mode": "docs",
            "project": str(project),
            "ic_name": args.ic_name,
            "delegated_to": "phase1_doc_one_shot_runner",
            "delegated_rc": rc,
            "duration_s": time.time() - t0,
            "verdict": verdict,
        }
        (reports / "phase1_one_shot.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
        return rc

    # Prompt mode: original phase1_engine path
    plan: List[StepResult] = []
    plan.append(step_ingest_render(project, args.ic_name))
    plan.append(step_human_docs(project))

    reports = project / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    summary = {
        "phase": 1,
        "mode": mode,
        "project": str(project),
        "ic_name": args.ic_name,
        "steps": [asdict(s) for s in plan],
        "verdict": ("FAIL" if any(s.status == "FAIL" for s in plan)
                    else "PASS_WITH_WAIVERS"
                    if any(s.status in ("WAIVED", "SKIP") for s in plan)
                    else "PASS"),
    }
    (reports / "phase1_one_shot.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(f"\n=== phase1_one_shot_runner DONE (mode={mode}) ===")
    print(f"verdict: {summary['verdict']}")
    for s in plan:
        print(f"  {s.status:6} {s.name:24} {s.detail[:120]}")
    return 0 if summary["verdict"] != "FAIL" else 1


if __name__ == "__main__":
    sys.exit(main())
