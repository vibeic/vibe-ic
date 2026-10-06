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

ONE FRONT DOOR (#2052): `--mode prompt` is a request, not an override. When the
detector says the staged input belongs to the doc-extraction track, the request
is resolved to `docs` and announced — the `phase1_engine` reverse-extractor is
not a second entry for raw design input. See `_resolve_mode`.

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

# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Measured
# on the base tree: 454 of the 1385 top-level programs died that way. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------


import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import _path_layout as _pl
import verdict as _V  # R-0915-85: the five step verdicts + the one cascade rule
import _runner_summary as _rsum  # noqa: E402  vibe-ic#2081
import _runner_lock  # ORGANIC #588 — single-driver lock (all 4 runners)
import _delivery_route
import _watchdog as _wd  # progress supervision — never a runtime bound
import step_preflight as _spf  # required_inputs PRE-FLIGHT at every dispatch site
# THE L-document write chokepoint — records the producing release on the
# L1 / L4 / L8 documents this runner back-fills from a prompt.
import l_doc_generator_stamp as _stamp
# Step 0.5ic's shared path vocabulary — the SAME module its two producers
# and its two judges read, so a runner cannot dispatch against a path the
# producer does not write to.
import _submission_template as _ST
import _tapeout_declaration as _TD

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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402
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
    # ── the structured fields R-0915-85 put beside the verdict ──────────
    # `status` above is now one of the FIVE words in `programs/verdict.py`, and
    # every distinction the deleted vocabulary carried lives here. The module's
    # DESIGN section says why; `_V.StepVerdict` is where the same rules are
    # enforced for readers. Validated in `__post_init__` below, so a site that
    # says NOT_MEASURED without a reason — or NOT_APPLICABLE without naming the
    # input line that declares it — is a loud error where it is written, not a
    # quiet hole in a published report.
    reason_class: str = ""
    declared_by: str = ""
    waiver_rows: List[Dict[str, str]] = field(default_factory=list)
    attribution: str = ""
    disclosures: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        _V.validate_step_row(self)


def _preflight_refusal(name: str):
    """This runner's refusal row for `step_preflight.gate`.

    `BLOCKED` carries the same meaning it does in the other three runners: the
    step was NOT attempted because an INPUT could not support it, so NOTHING is
    known. It is `NOT_MEASURED(input_absent)` in the one vocabulary — which is
    would have fallen through that function's catch-all `return "PASS"` and a
    refusal would have produced a GREEN run, which is the defect class this
    whole pre-flight exists to remove. Measured on this ladder specifically:
    Phase 1's verdict was `FAIL if any FAIL else PASS_WITH_WAIVERS if any
    WAIVED/SKIP else PASS`, so a lone BLOCKED row scored PASS — the cleanest
    possible green run over a Phase 1 that was never given a document.
    """
    def _mk(detail: str, extras: Dict[str, Any]) -> StepResult:
        return StepResult(name, _spf.REFUSAL_STATUS, 0.0, detail, extras=extras, reason_class=_spf.REFUSAL_REASON_CLASS)
    return _mk


# Statuses that must NOT reach a green verdict. `BLOCKED` is `step_preflight`'s
# refusal status; `FAIL` is this runner's pre-existing one, unchanged.
#: RETIRED by R-0915-85. Two runners kept their own "these words are failures"
#: tuple beside `_aggregate_verdict`, and the pre-flight refusal had to be
#: remembered into each of them (it was not, once, and a refusal produced a
#: GREEN run — #544). There is one roll-up now, `verdict.run_verdict`, and a
#: refusal is `NOT_MEASURED(input_absent)`: not green, and — per the one
#: cascade rule — voiding nothing downstream.

#: How long a dispatched Phase-1 producer may be COMPLETELY IDLE — no CPU, no
#: I/O, no output anywhere in its process tree — before it is called wedged.
#: This is NOT a runtime bound. The number is the one the old
#: `subprocess.run(timeout=600)` used, reinterpreted: every job that bound let
#: through, this lets through, and it additionally lets through every job that
#: was still working at 600s. It can only ever kill LESS.
_TRACK_STALL_GRACE_S = 600



def _aggregate_verdict(plan: List[StepResult]) -> str:
    """The run's verdict, from `verdict.run_verdict`. ONE rule for the flow.

    WHAT THIS REPLACES, and why the replacement is a deletion rather than a
    migration. Every one-shot runner carried its own hand-maintained lists of
    which words meant what, and the lists disagreed: phase 2 read `SKIP` as
    clean while phase 3 read the identical word as a waiver, over the same
    forty-four steps. This function's own predecessor said so in its comments
    and declined to fix it because fixing it "would restate every published
    phase-2 result". R-0915-85 is the decision to restate them: there is one
    vocabulary, five words, and one roll-up — `verdict.run_verdict` — whose
    precedence is FAIL > NOT_MEASURED > PASS_WITH_WAIVERS > PASS.

    The catch-all is gone by construction, not by enumeration: `verdict.parse`
    refuses a word outside the five at the row that carries it.
    """
    # R-0915-85 — THE SKIP DISCLOSURE SURVIVES THE COLLAPSE. The predecessor
    # printed every step it had excused to stderr, by name, so a green run said
    # out loud which of its steps produced no verdict about the design. Five
    # words say less per row than eighteen did, so each row is named here with
    # the word AND the reason or declaration beside it. A run whose skips go
    # silent is the run16 shape.
    _rows = list(_step_verdicts(plan))
    _skipped = [r for r in _rows
                if r.verdict in (_V.Verdict.NOT_MEASURED,
                                 _V.Verdict.NOT_APPLICABLE)]
    if _skipped:
        print(f"[verdict] {len(_skipped)} SKIPPED step(s) — produced no "
              f"verdict about the design: " + ", ".join(
                  f"{r.name}={r.verdict.value}"
                  f"({(r.reason_class.value if r.reason_class else '')}"
                  f"{r.declared_by and ' ' + r.declared_by})"
                  for r in _skipped), file=sys.stderr)
    return _V.run_verdict(_rows).value


def _step_verdicts(plan):
    """This runner's own rows, as `verdict.StepVerdict` records.

    One conversion, here, so no consumer re-derives the structured fields from
    a `StepResult` and no two of them do it differently.
    """
    for s in plan:
        yield _V.StepVerdict(
            verdict=_V.parse(s.status),
            step_id=getattr(s, "name", ""), name=getattr(s, "name", ""),
            reason_class=(_V.ReasonClass(s.reason_class)
                          if getattr(s, "reason_class", "") else None),
            reason=getattr(s, "detail", "") or "",
            declared_by=getattr(s, "declared_by", "") or "",
            waiver_rows=[_V.WaiverRow(**w)
                         for w in (getattr(s, "waiver_rows", None) or [])],
            attribution=getattr(s, "attribution", "") or "",
            disclosures=list(getattr(s, "disclosures", None) or ()),
        )



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


# ── ONE front door (#2052) ──────────────────────────────────

#: The mode a caller may ask for on the command line.
REQUESTABLE_MODES = ("auto", "docs", "prompt")

#: The name BOTH branches report for canonical flow step D1 — read the design
#: input and render the L documents. It was two names for one step (#2052).
D1_STEP_NAME = "phase1_ingest_render"


def _resolve_mode(requested: str, detected: str) -> "Tuple[str, Optional[str]]":
    """Which backend actually runs, and — when that is not what the caller
    typed — why.

    Returns ``(mode, redirect_note_or_None)``.

    WHAT THIS CHANGES, AND WHAT IT DELIBERATELY DOES NOT
    ---------------------------------------------------
    ``--mode prompt`` used to be an ENTRY into ``phase1_engine``'s
    ``_stub_l_docs_from_prose`` for ANY staged input, including raw design
    prose that ``_detect_input_mode`` had already ruled belongs to the
    doc-extraction track. Measured on one 409-byte ``input/phase1_prompt.md``
    (8HD-6, v1.17.80): the AUTO/docs door published 28 L documents, 4 ports
    and a sufficient verdict at rc 0, while ``--mode prompt`` over the SAME
    bytes published 13 L documents, 0 ports, an EXTRACTION GAP and rc 1. One
    input, two doors, two different designs — and the flow says there is one
    canonical front door.

    So a REQUEST for the prompt backend no longer overrides the detector when
    the detector says the input belongs to the docs track: the prompt is staged
    exactly as AUTO stages it and goes through the docs door, so every layer has
    ONE derivation. ``phase1_engine`` remains reachable, and remains a LIBRARY
    the docs door itself calls (v1.17.74's shared port extractor, v1.17.80's
    shared top-module derivation) — what it stops being is a second front door
    for raw design input.

    AUTO IS UNCHANGED BY CONSTRUCTION: the ``auto`` branch below is the
    pre-existing expression, untouched. The engine still runs exactly where the
    DETECTOR itself answers "prompt" (an ``input/docs/`` that already holds
    pre-structured ``L*.json`` — the reverse-extractor's actual job) and where
    nothing is staged at all (the SKIP that reports "nothing to do").

    Pure: takes two strings, reads no filesystem, returns two. chip-AGNOSTIC.
    """
    if requested == "auto":
        # UNCHANGED — the pre-#2052 expression, verbatim.
        return (detected if detected != "none" else "prompt"), None
    if requested == "prompt" and detected == "docs":
        return "docs", (
            "requested --mode prompt; the staged input is a doc-extraction "
            "input (_detect_input_mode='docs'), so it was routed through the "
            "canonical docs front door. The phase1_engine reverse-extractor "
            "is not a second entry for raw design input (#2052); it stays "
            "reachable for a pre-structured L*.json corpus, and its "
            "extractors remain a library the docs door calls.")
    return requested, None


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
            return StepResult("phase1_ingest_render", "NOT_MEASURED",
                              time.time() - t0,
                              "neither input/phase1_structured.yaml nor "
                              "input/docs/ nor input/phase1_prompt.md "
                              "present — Phase 1 needs at least one input. "
                              "Caller (IC Expert Agent) must populate "
                              "input/phase1_structured.yaml from dialogue.", reason_class=_V.ReasonClass.INPUT_ABSENT)
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
    # THE SAME REPLACEMENT as the two dispatch sites below, and this one was not
    # even handled: `subprocess.run(timeout=600)` RAISES, so the bound firing on
    # the doc-extraction engine escaped this function as a `TimeoutExpired`
    # traceback and reached the caller as a crash — a Phase-1 failure attributed
    # to the design, on a host that was merely busy. Doc extraction over a large
    # vendor corpus is exactly the honest long work a runtime bound murders.
    res = _wd.run_host_supervised(cmd, stall_grace_s=_TRACK_STALL_GRACE_S,
                                  cwd=str(repo_root), env=env)
    if res.outcome in ("stalled", "ceiling"):
        return StepResult("phase1_ingest_render", "FAIL",
                          time.time() - t0,
                          f"the ingest engine STALLED — no CPU, no I/O and no "
                          f"output from its process tree for the "
                          f"{_TRACK_STALL_GRACE_S}s grace, after "
                          f"{res.elapsed_s:.0f}s. It was not slow; it was doing "
                          f"nothing.")
    cp = _wd.completed_process(cmd, res)
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


def _prompt_sources_for(project: Path) -> "Dict[str, str]":
    """The free-text spec the ingest consumed, keyed by its own file NAME.

    #czl9prompt — the text alone was enough to extract ports, but not to record
    WHERE they came from, and L9's prose channel names its documents. Returning
    the mapping keeps provenance available to every caller; `_prompt_text_for`
    is now a view over it, so there is still ONE place that decides what the
    input IS."""
    for p in (project / "input" / "phase1_prompt.md",
              project / "input" / "docs" / "design_description.md"):
        if p.is_file():
            return {p.name: p.read_text(errors="replace")}
    docs = project / "input" / "docs"
    if docs.is_dir():
        return {f.name: f.read_text(errors="replace")
                for f in sorted(docs.glob("*")) if f.is_file()}
    return {}


def _prompt_text_for(project: Path) -> str:
    """Best-effort: the free-text spec the ingest consumed."""
    srcs = _prompt_sources_for(project)
    return "\n".join(srcs[k] for k in sorted(srcs))


def _seed_structural_ports(project: Path, out_dir: Path) -> int:
    """Merge deterministic phase1_port_extract ports/params/reset into the
    generated L1 (pinout) + L8R JSON. Returns the number of ports seeded.
    Never raises — a seeding failure must not break the render."""
    try:
        sys.path.insert(0, str(PROGRAMS_DIR))
        import phase1_port_extract as _ppx
        srcs = _prompt_sources_for(project)
        prompt = "\n".join(srcs[k] for k in sorted(srcs))
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
        # L9 — the INTEGRATION SPEC, and the reason this lane exists.
        #
        # Before #czl9prompt this function stopped at L1/L8R. L9 is the document
        # the interface-reading gates downstream actually walk, and the prompt
        # engine's own L9 is a STUB: `top_ports` is a list of bare NAME STRINGS
        # with no direction, so a consumer asking "which of these is an output"
        # got nothing. Measured on this base, the two front doors emitted L9s
        # from ONE byte-identical input that agreed on nothing: docs mode five
        # ports carrying their direction plus 554 characters of the input's own
        # prose; prompt mode five strings, no direction, no prose.
        #
        # Only fills an L9 that carries NO structured port: a richer L9 (dict
        # entries) is never clobbered, and a bare-string `top_ports` is not
        # "structured" — it is the stub this repairs.
        l9p = out_dir / "L9_INTEGRATION_SPEC.json"
        if l9p.is_file():
            l9 = json.loads(l9p.read_text())
            structured = [e for k in ("ports", "top_ports", "top_module_pins")
                          for e in (l9.get(k) or []) if isinstance(e, dict)]
            if not structured:
                evidence = sorted(srcs)[0] if srcs else None
                entries = [{"name": pt["name"],
                            "mode": pt["dir"],
                            "direction": pt["dir"],
                            "io": None,
                            "evidence": evidence,
                            # names the PROGRAM that read it, not a grammar it
                            # did not use. The two doors agree on the ports and
                            # their directions and say honestly that different
                            # readers produced them.
                            "extraction_strategy": "phase1_port_extract"}
                           for pt in ports]
                l9["ports"] = entries
                l9["top_ports"] = entries
                l9["top_module_pins"] = entries
                # The SAME prose emitter the docs door runs, on the same input.
                # Without it L9's prose channel stays empty and every prose rule
                # downstream is dormant — a verdict over zero characters.
                _ppx.emit_interface_prose(l9, srcs)
                _stamp.dump(l9p, l9)
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
        return StepResult("phase1_human_docs", "PASS_WITH_WAIVERS",
                          time.time() - t0,
                          "human_docs/L*.md not produced (engine cli "
                          "may not have --also-human; caller can "
                          "post-process facts.yaml → MD as needed)")
    return StepResult("phase1_human_docs", "PASS",
                      time.time() - t0,
                      f"{len(list(hd.glob('L*.md')))} human MD docs")


# ── Docs mode (vendor docs → phase1_doc_one_shot_runner) ───────────

def _docs_hold_identical_bytes(docs_dir: Path, candidate: Path) -> bool:
    """True when a non-hidden regular file under `docs_dir` is byte-identical to
    `candidate`.

    The v1.14.50 prompt-JOINS-the-docs bridge below guards only against its OWN
    target name (`docs_dir / prompt.name`) already existing. An operator (or an
    upstream stager) that has ALREADY written the same prompt content into
    `input/docs/` under any other name defeats that guard, so the same bytes land
    in `phase1/input_doc/` TWICE — and a doc that restates a whole interface
    doubles every parsed port list downstream. Content identity (sha256 of raw
    bytes) is the only guard that survives a rename.
    """
    if not docs_dir.is_dir() or not candidate.is_file():
        return False
    # An unreadable file cannot be proven identical, so it never suppresses the
    # bridge: the doc pipeline tolerates unreadable docs (issue #3/#26), and a
    # duplicate bridged anyway is absorbed by the parser-level port dedup.
    try:
        want = hashlib.sha256(candidate.read_bytes()).hexdigest()
    except OSError:
        return False
    for f in docs_dir.rglob("*"):
        if not f.is_file() or f.name.startswith("."):
            continue
        try:
            if hashlib.sha256(f.read_bytes()).hexdigest() == want:
                return True
        except OSError:
            continue
    return False


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

    had_real_doc = _has_real_doc(docs_dir)

    if not had_real_doc:
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

    # v1.14.50 — the prompt is an ADDITIONAL document, not a COMPETING one.
    # The bridge above deliberately yields to "a real document" in input/docs/.
    # That is right for the DIALOGUE artefact (it restates the same design) and
    # WRONG for `input/phase1_prompt.md`, which is the only carrier of directives
    # the vendor docs cannot contain: parameter overrides, PDK target, tie-off
    # decisions, the intended implementation path, the verification oracle.
    # Measured (opentitan_aes, 2026-08-31, v1.14.49): with input/docs/ populated the
    # prompt was read by NOTHING — 0 of 28 emitted L docs cited it — so its stated
    # "SecMasking disabled" never reached Phase 2, the glue built the masked S-box,
    # and yosys failed on a module the corpus deliberately excludes. The coverage
    # gate still said "0 UNREAD / 100.0%" because the denominator is the VISITED
    # set: a file that is never opened cannot be counted unread.
    # So: when input/docs/ already holds real documents, the prompt JOINS them
    # under its own basename (provenance survives into L-doc source_documents) and
    # never overwrites an existing entry. `had_real_doc` is sampled BEFORE the
    # bridge above so a prompt already rendered to design_description.md is not
    # ingested twice.
    # ... and never bridges bytes `input/docs/` ALREADY holds under any name —
    # a byte-identical copy staged there by the operator would otherwise land
    # the same content twice in phase1/input_doc/ (doubling every restated
    # interface downstream). See `_docs_hold_identical_bytes`.
    _prompt_md = project / "input" / "phase1_prompt.md"
    if _prompt_md.is_file() and had_real_doc:
        _bridged = docs_dir / _prompt_md.name
        if (not _bridged.exists()
                and not _docs_hold_identical_bytes(docs_dir, _prompt_md)):
            # An unreadable prompt cannot be bridged; the doc pipeline's
            # tolerance contract (issues #3/#26) says that is a skip, never a
            # front-door crash.
            try:
                _bridged.write_text(_prompt_md.read_text(errors="replace"))
            except OSError:
                pass
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


def _delegated_rc_verdict(rc: int) -> str:
    """Map a delegated Phase-1 result without laundering rc=2."""
    if rc == 0:
        return _V.Verdict.PASS.value
    if rc == 2:
        return _V.Verdict.NOT_MEASURED.value
    return _V.Verdict.FAIL.value


def _delegated_step_result(name: str, rc: int, duration_s: float,
                           detail: str, *, upstream: bool = False) -> StepResult:
    """Build a truthful row for the docs delegate and its dependent track."""
    status = _delegated_rc_verdict(rc)
    reason = "upstream_refused" if upstream and rc == 2 else (
        "no_population" if rc == 2 else "")
    return StepResult(name, status, duration_s, detail,
                      reason_class=reason)


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
    # NOT `subprocess.run(..., timeout=600)`. Ending the track because a clock
    # expired does not make sense at any label: the run may have been one second
    # from finishing, and the same design gets a different answer on a fast host
    # than on a loaded one. Relabelling that kill NOT_MEASURED would have made
    # the report honest and left the behaviour just as broken — the kill IS the
    # defect.
    #
    # `run_host_supervised` bounds NO PROGRESS, never runtime. Progress is read
    # out of /proc over the whole process tree — CPU (utime+stime), I/O
    # (read_bytes+write_bytes) — plus the captured output growing. Any signal
    # moving resets the grace, so a track that is working runs to completion
    # however long that legitimately takes. Nothing moving at all across the
    # grace is a MEASURED finding: the track is wedged, and that is a real
    # verdict about the track rather than a shrug about the clock.
    argv = [sys.executable, str(prog), str(project),
            "--invoked-by", "phase1_one_shot_runner"]
    res = _wd.run_host_supervised(argv, stall_grace_s=_TRACK_STALL_GRACE_S)
    if res.outcome in ("stalled", "ceiling"):
        print(f"      ERROR: the expert track STALLED — its whole process tree "
              f"made no forward progress (no CPU, no I/O, no output) for the "
              f"{_TRACK_STALL_GRACE_S}s grace, after {res.elapsed_s:.0f}s, and "
              f"was stopped. It was not slow; it was doing nothing. An "
              f"unevaluated track cannot pass.", file=sys.stderr)
        return 1
    cp = _wd.completed_process(argv, res)
    for line in (cp.stdout or "").strip().splitlines():
        print(f"      {line}")
    # 0 = completed review. 1 can be either an honestly INCOMPLETE review or a
    # crash, so the report below decides which. rc 2 is retained only as a
    # defensive read of an older track binary; it cannot earn execution credit.
    # rc 4 is the track's AWAITING code (#2014 D1): the hand-off is written and
    # the subagent has not answered. Accepted HERE only as "the track ran to a
    # state it defines"; whether it is credited is still decided below, from
    # the report, by `_expert_track_disposition` — the rc never grants credit.
    if cp.returncode not in (0, 1, 2, _EXPERT_TRACK_AWAITING_RC):
        print(f"      expert track FAILED to complete (rc={cp.returncode}): "
              f"{(cp.stderr or '').strip().splitlines()[-1:] or ['(no detail)']}",
              file=sys.stderr)
        return 1
    if not report.is_file():
        print("      ERROR: the expert track wrote no report — its verdict is "
              "unknown, which is not the same as clean", file=sys.stderr)
        return 1
    try:
        evidence = json.loads(report.read_text(errors="replace"))
    except (OSError, ValueError) as exc:
        print(f"      ERROR: the expert-track report does not parse ({exc}) — "
              f"unreadable evidence is not evidence", file=sys.stderr)
        return 1
    disposition, detail = _expert_track_disposition(evidence)
    if disposition == _EXPERT_DEFECT:
        print(f"      ERROR: the expert track did not produce a usable reading "
              f"({detail}); a refused, erroring or self-contradictory record "
              f"is not a second track", file=sys.stderr)
        return 1
    if disposition == _EXPERT_PENDING:
        # NOT a failure, and NOT credit. `ai_subtrack` documents
        # HANDOFF_EMITTED as the designed FIRST pass — "invoke subagent … and
        # re-run to consume its answer" — and CONSUMED_EMPTY as a real reading
        # of zero. A program cannot spawn the subagent, so every single-pass
        # non-agent invocation lands here: making it exit 1 turned a
        # two-pass protocol into a gate no legitimate input can pass, and it
        # took the Shape-C benchmark hard gate `phase1_run_all` with it
        # (MEASURED: 14 emit-blocking cases across 7 test files went red at
        # 7d1da41d7 and are green at its parent 55bb6967b, same tree
        # otherwise). What #1973 actually measured was a REPORTING lie — the
        # summary said the second track "ran". That lie is fixed where it
        # lives, in `_expert_track_summary`, which publishes
        # "INCOMPLETE — <detail>" here and never "ran"; credit is still
        # withheld. Reporting honesty and run failure are different things.
        print(f"      PENDING: the Phase-1 expert answer is not yet consumed "
              f"({detail}); recorded uncredited — re-run after the subagent "
              f"answers to convert it into execution", file=sys.stderr)
        return 0
    if cp.returncode != 0:
        print(f"      ERROR: the expert report says complete but the program "
              f"exited {cp.returncode}; contradictory execution evidence "
              f"cannot be credited", file=sys.stderr)
        return 1
    return 0


#: The three dispositions a track record can carry. CREDITED is execution;
#: PENDING is a stated, uncredited waiting state the protocol defines; DEFECT
#: is a record that cannot be read as either.
_EXPERT_CREDITED = "CREDITED"
_EXPERT_PENDING = "PENDING"
_EXPERT_DEFECT = "DEFECT"

#: Statuses `phase1_expert_parse_track.ai_subtrack` defines as a state of the
#: hand-off protocol rather than a fault. HANDOFF_EMITTED = pack written, the
#: agent has not answered yet; CONSUMED_EMPTY = the agent answered and its
#: `expectations` list was empty, "a real reading of zero". Neither earns
#: credit; neither is a failed run. Any OTHER non-CONSUMED status — ERROR,
#: ANSWER_SCHEMA_MISMATCH, or one this reader does not know — is a defect.
_EXPERT_PENDING_STATUSES = frozenset({"HANDOFF_EMITTED", "CONSUMED_EMPTY"})

#: The track's own AWAITING exit code (`phase1_expert_parse_track
#: .AWAITING_EXIT_CODE`). Named here rather than imported so this dispatcher
#: keeps working against an older track binary that does not define it; the
#: number is pinned by `test_issue2014_d1_expert_handoff_is_a_wait_not_a_fail`
#: against the track's constant, so the two cannot drift unnoticed.
_EXPERT_TRACK_AWAITING_RC = 4


def _expert_track_disposition(report: Any) -> Tuple[str, str]:
    """Classify a track record as execution, a stated wait, or a defect."""
    complete, detail = _expert_track_completion(report)
    if complete:
        return _EXPERT_CREDITED, detail
    if isinstance(report, dict):
        ai = report.get("ai_subtrack")
        if isinstance(ai, dict) and ai.get("status") in _EXPERT_PENDING_STATUSES:
            return _EXPERT_PENDING, detail
    return _EXPERT_DEFECT, detail


def _expert_track_completion(report: Any) -> Tuple[bool, str]:
    """Whether a report proves a non-empty IC Expert answer was consumed.

    Report existence is deliberately insufficient. Issue #1973 measured a
    `HANDOFF_EMITTED` report with deterministic=0, AI=0 and consumed=0 that the
    runner nevertheless called executed. Keep every required denominator here,
    at the credit boundary, so a producer regression cannot recreate that pass.
    """
    if not isinstance(report, dict):
        return False, "report top level is not an object"
    ai = report.get("ai_subtrack")
    convergence = report.get("ai_convergence")
    denominator = report.get("denominator")
    if not isinstance(ai, dict):
        return False, "ai_subtrack evidence is absent"
    status = ai.get("status", "UNKNOWN")
    if status != "CONSUMED":
        return False, f"ai_subtrack.status={status}"
    if not isinstance(convergence, dict):
        return False, "ai_convergence evidence is absent"
    consumed = convergence.get("consumed")
    if not isinstance(consumed, int) or isinstance(consumed, bool) or consumed < 1:
        return False, f"ai_convergence.consumed={consumed!r}"
    if not isinstance(denominator, dict):
        return False, "denominator evidence is absent"
    ai_den = denominator.get("ai")
    total = denominator.get("total")
    if ai_den != consumed or not isinstance(total, int) or total < consumed:
        return False, (f"denominator.ai={ai_den!r}, total={total!r}, "
                       f"consumed={consumed}")
    return True, f"CONSUMED {consumed} expectation(s)"


def _expert_track_summary(project: Path) -> str:
    """Human-readable execution state for the runner's own summary JSON."""
    report = _pl.report_path(project, "phase1/expert_parse_track.json")
    try:
        blob = json.loads(report.read_text(errors="replace"))
    except (OSError, ValueError) as exc:
        return f"INCOMPLETE — expert-track report unreadable ({exc})"
    complete, detail = _expert_track_completion(blob)
    return (f"consumed — {detail}" if complete else
            f"INCOMPLETE — {detail}")


# ── Step 0.5ic — the route declaration (both input modes) ──────────
#
# WHY THIS IS WIRED, AND WHAT WIRING IT DOES NOT BUY.
#
# Step 0.5ic declares two programs and, until this branch, NOTHING in the
# shipped tree could execute either of them. Measured, not argued:
# `test_matrix_d1_wiring.ORPHAN_DECLARED_PROGRAMS` pinned both as reachable
# through none of the three channels, and
# `test_path_step_matrix_ic_and_ip` carried a strict xfail saying a step whose
# producer nothing dispatches "reports MISSING for every design forever, and
# every reader charges that to the design". That is exactly what happened: a
# real run reported 0.5ic MISSING / declared-artefact-absent, and 36 further
# steps inherited it as `derived-from-upstream`. One step nobody could run
# voided a whole flow.
#
# WIRED HERE rather than in `phase1_doc_one_shot_runner` for the reason the
# expert track above gives: this dispatcher is the one entry point that covers
# BOTH input modes, and `flow_gate_enforcement_audit` inspects THIS file.
#
# RUN BEFORE THE MODE BRANCH, and unconditionally. Step 0.5ic's `blocks_on` is
# empty and it takes no input from D1 — which delivery route a design is on is
# a property of the DESIGN, not of its documents — so gating it behind a D1
# that refused would leave the route unstated for exactly the runs that most
# need to say so.
#
# NOTHING IS INFERRED, AND THAT IS THE POINT. The two producers are handed the
# design's own staged answers and nothing else. A design that staged none gets
# a template searched-for-and-absent with NO reason stated and an entirely
# NOT_DETERMINED declaration; step 0.5ic's own gate then FAILS it with
# NO_TEMPLATE_WITHOUT_REASON, naming what the design did not say. Wiring the
# producers makes the step RUN. It cannot make it PASS, and it must not: a
# route this runner picked on a design's behalf would be a default wearing a
# declaration's clothes.

def _import_answers_rel() -> str:
    """The answers path, read from the program that writes it."""
    try:
        import submission_template_answers as _sta
        return _sta.ANSWERS_REL
    except Exception:                                       # noqa: BLE001
        # A deployment missing the program is a defect the loop below reports
        # by name; this only has to not crash before it gets there.
        return "input/submission_template/operator_answers.json"


_STEP_0_5IC_FETCH = "submission_template_fetch.py"
_STEP_0_5IC_INGEST = "submission_template_ingest.py"
_STEP_0_5IC_ANSWERS = "submission_template_answers.py"
#: Where `submission_template_answers` writes the ONE answers file
#: `tapeout_declaration_gen` reads. Imported from that module rather than
#: spelled again here: a path written in two places is two places to forget.
_MERGED_ANSWERS_REL = _import_answers_rel()
_STEP_0_5IC_DECLARE = "tapeout_declaration_gen.py"


def _import_fetch_report_rel() -> str:
    """The fetch's report path, read from the program that writes it."""
    try:
        import submission_template_fetch as _stf
        return _stf.REPORT_REL
    except Exception:                                       # noqa: BLE001
        return "reports/phase1/submission_template_fetch.json"


#: Where `submission_template_fetch` writes the record `submission_template_
#: answers --technology-json` reads. Imported, not spelled twice.
_ST_FETCH_REPORT_REL = _import_fetch_report_rel()


def _step_0_5ic_answers(project: Path
                        ) -> "Tuple[Optional[Path], Optional[Dict[str, Any]], Optional[str]]":
    """(path, document, why-not) for the design's own step-0.5ic answers.

    An ABSENT file is not an error — it is a design that has not answered, and
    the producers record that faithfully. An UNREADABLE one IS an error: a
    design that tried to answer and could not be read must never be reported as
    a design that said nothing.
    """
    path = project / _ST.DESIGN_ANSWERS_REL
    if not path.is_file():
        return None, None, None
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError) as exc:
        return path, None, f"{path} could not be read as JSON: {exc}"
    if not isinstance(doc, dict):
        return path, None, (f"{path}'s top level is {type(doc).__name__}, "
                            f"not a mapping")
    return path, doc, None


def _pdk_of_this_run(extras: "Optional[List[str]]") -> str:
    """The PDK this run targets, read out of `--pdk` WITHOUT consuming it.

    `--pdk` is forwarded to this runner through `parse_known_args` extras (the
    orchestrator adds it so a PDK-keyed spec table can be resolved), and those
    same extras are handed on to the docs-mode delegate. Declaring an argparse
    option for it here would take it out of `extras` and silently stop that
    forwarding, so this reads it and leaves it in place.

    `auto` is not a PDK. It is the orchestrator's word for "resolve one later",
    and treating it as a process name would have step 0.5ic transcribe the
    technology facts of a PDK called `auto`.
    """
    items = list(extras or [])
    for i, tok in enumerate(items):
        if tok == "--pdk" and i + 1 < len(items):
            val = str(items[i + 1]).strip()
            break
        if tok.startswith("--pdk="):
            val = tok.split("=", 1)[1].strip()
            break
    else:
        return ""
    return "" if val.lower() in ("", "auto") else val


def _run_step_0_5ic(project: Path, pdk: str = "") -> int:
    """Run step 0.5ic's two producers, in the order the flow declares them.

    `submission_template_ingest` records what the OPERATOR published;
    `tapeout_declaration_gen` records what the DESIGN declares about itself and
    retires the marker the first one wrote when the design is a die doing its
    own tape-out. The order is load-bearing and is the flow's own.

    EXECUTION is not advisory: a producer that could not run, or that wrote no
    report, FAILs Phase 1 — a step whose record is missing is indistinguishable
    from a step that never ran, which is the whole defect this step exists to
    refuse. The VERDICT on those records is not taken here; it belongs to the
    step's own two gate clauses, which `flow_compliance_check` evaluates.
    """
    import execution_policy
    if execution_policy._ordinary_runtime is not None:
        _, bound_answers, error = _step_0_5ic_answers(project)
        if error:
            return 1
        operator = (bound_answers or {}).get('operator_template') or {}
        # Use the same actual search location as the canonical producer below.
        # This names a lookup; it neither creates a template nor buys absence.
        template = operator.get('path')
        if template is None:
            template = _ST.STAGED_TEMPLATE_REL
        parameters = {'template': template, 'slot': operator.get('slot')}
        # The real producer omits an absent reason from its issued arguments.
        # Preserve every provided owner value, including invalid empty values.
        if operator.get('absent_reason') is not None:
            parameters['no_template_reason'] = operator['absent_reason']
        result = execution_policy.dispatch_fixed_step(project, '0.5ic', parameters=parameters)
        return 0 if result['status'] == 'ADOPTED' else 1
    answers_path, answers, err = _step_0_5ic_answers(project)
    if err is not None:
        print(f"      ERROR: the design's step-0.5ic answers could not be "
              f"read ({err}) — an unreadable answer is not the same fact as "
              f"no answer, and must not be recorded as one", file=sys.stderr)
        return 1

    # BLOCKING route admission, before fetch, ingest, declaration or Phase-1
    # extraction. The owner declared HARDMACRO and a shuttle purchase to be
    # mutually exclusive; neither downstream consumer may choose a side.
    if _TD.bought_slot_hardmacro(project):
        print(f"      REFUSED: {_TD.BOUGHT_SLOT_HARDMACRO_MESSAGE}",
              file=sys.stderr)
        return 1

    template, slot, reason = None, None, None
    if answers:
        operator = answers.get("operator_template")
        if isinstance(operator, dict):
            template = operator.get("path")
            slot = operator.get("slot")
            reason = operator.get("absent_reason")

    # THE ONE INPUT THAT DECIDES WHETHER THIS STEP CAN PASS, DISCLOSED WHEN IT
    # IS NOT THERE. Nothing here is inferred and nothing is defaulted -- that
    # stays exactly as it was -- but a run that proceeds in silence tells the
    # reader nothing about WHY the step is about to refuse. Measured: a reader
    # holding a FAILing 0.5ic beside a generated `SELF_TAPEOUT.txt` concluded
    # the gate had ignored the declaration, and the run had never named the
    # file the design was supposed to write. A decline that discloses nothing
    # reads downstream as "nothing needed doing".
    if not isinstance(reason, str) or not reason.strip():
        _where = ("the design staged NO step-0.5ic answers"
                  if answers_path is None else
                  f"the design's answers at {_ST.DESIGN_ANSWERS_REL} answer no "
                  f"`operator_template.absent_reason`")
        print(f"      NOTE: {_where}. If no operator template is found at the "
              f"path searched below, step 0.5ic will REFUSE with "
              f"NO_TEMPLATE_WITHOUT_REASON: an absent template has to be "
              f"BOUGHT with the design's own words. Supply them at "
              f"{_ST.DESIGN_ANSWERS_REL}, key "
              f"`operator_template.absent_reason`. Declaring "
              f"`deliverable` alone does not buy it -- the route is derived "
              f"FROM the absence, so it cannot pay for it.")
    # THE SEARCH ALWAYS HAPPENS. A driven run looks in the place a design
    # stages an operator template even when nothing is there, so the record
    # names a path that was searched instead of recording that nobody looked.
    root = Path(template) if template else Path(_ST.STAGED_TEMPLATE_REL)
    if not root.is_absolute():
        root = project / root

    # Clear both records FIRST, so "the record exists" can only mean THIS run
    # wrote it. A stale record from an earlier run is exactly how a producer
    # that died would still look like one that ran.
    records = [project / _ST.REPORT_REL, project / _TD.REPORT_REL]
    for record in records:
        try:
            record.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            print(f"      ERROR: cannot clear the previous step-0.5ic record "
                  f"at {record} ({exc}) — its freshness could not be "
                  f"established", file=sys.stderr)
            return 1

    ingest = [sys.executable, str(PROGRAMS_DIR / _STEP_0_5IC_INGEST),
              str(project), "--template", str(root)]
    if isinstance(slot, str) and slot.strip():
        ingest += ["--slot", slot.strip()]
    if isinstance(reason, str) and reason.strip():
        ingest += ["--no-template-reason", reason.strip()]
    declare = [sys.executable, str(PROGRAMS_DIR / _STEP_0_5IC_DECLARE),
               str(project)]
    # Filled in after `answers` runs: it is the MERGED file when one was
    # written, and the design's own only when no operator stated anything.
    # Resolved late on purpose — deciding it here would freeze the precedence
    # before the operator has spoken.

    # THE OPERATOR'S TEMPLATE, FETCHED. Before this, `root` was searched and
    # found absent for every design in the corpus, because the step declared its
    # template `from: external` and nothing external ever went and got it. The
    # fetch is NOT_APPLICABLE for a PDK with no live shuttle and refuses only
    # when there IS an operator whose terms it could not obtain.
    #
    # `--pdk` REACHES THE FETCH (#2070). Two things in this step are facts of
    # the PROCESS THIS RUN BUILDS rather than of the design: which families the
    # design named (checked against the run's target, refused when the run is
    # on one the design never named) and the database unit the technology
    # declares. Neither can be answered without knowing which PDK this is, and
    # until now step 0.5ic was never told — so the fetch fell back to a
    # declared target that phase 1 has not written yet at this point in the
    # dispatch order, and reported "the design declares no PDK" for designs
    # whose L1 names two.
    fetch = [sys.executable, str(PROGRAMS_DIR / _STEP_0_5IC_FETCH),
             str(project)]
    if isinstance(pdk, str) and pdk.strip():
        fetch += ["--pdk", pdk.strip()]

    # THE OPERATOR'S TERMS, TRANSCRIBED. `tapeout_declaration_gen` refuses to
    # infer — rightly — so without this nothing could ever answer a field, and
    # all 18 stayed NOT_DETERMINED. It merges the design's own answers
    # UNDERNEATH the operator's and emits ONE file, because the generator takes
    # one: leaving the precedence to whichever file was passed is how a design's
    # self-declared die size would silently outrank the slot it was sold.
    answers = [sys.executable, str(PROGRAMS_DIR / _STEP_0_5IC_ANSWERS),
               str(project)]
    if isinstance(slot, str) and slot.strip():
        answers += ["--slot", slot.strip()]
    if answers_path is not None:
        answers += ["--design-answers", str(answers_path)]
    # THE TRANSCRIPTION THE FETCH JUST WROTE. Passed as the fetch's own report
    # rather than re-measured here: the number in the declaration has to be the
    # number a named program read out of a named file at a named line, and a
    # second reader of the same tech LEF is a second answer waiting to differ.
    answers += ["--technology-json", str(project / _ST_FETCH_REPORT_REL)]
    merged_answers = project / _MERGED_ANSWERS_REL
    try:
        merged_answers.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass

    for argv in (fetch, ingest, answers, declare):
        if argv is declare:
            src = (merged_answers if merged_answers.is_file()
                   else answers_path)
            if src is not None:
                argv = argv + ["--answers", str(src)]
        name = Path(argv[1]).name
        # Same replacement as `_run_expert_track`, same reason. See there.
        res = _wd.run_host_supervised(argv, stall_grace_s=_TRACK_STALL_GRACE_S)
        if res.outcome in ("stalled", "ceiling"):
            print(f"      ERROR: {name} STALLED — no CPU, no I/O and no output "
                  f"from its process tree for the {_TRACK_STALL_GRACE_S}s "
                  f"grace, after {res.elapsed_s:.0f}s. It was not slow; it was "
                  f"doing nothing. An undispatched producer cannot pass.",
                  file=sys.stderr)
            return 1
        cp = _wd.completed_process(argv, res)
        for line in (cp.stdout or "").strip().splitlines():
            print(f"      {line}")
        if cp.returncode != 0:
            print(f"      {name} FAILED to complete (rc={cp.returncode}): "
                  f"{(cp.stderr or '').strip().splitlines()[-1:] or ['(no detail)']}",
                  file=sys.stderr)
            return 1

    for record in records:
        if not record.is_file():
            print(f"      ERROR: step 0.5ic wrote no record at {record} — a "
                  f"step that produced nothing is indistinguishable from one "
                  f"that never ran", file=sys.stderr)
            return 1
        try:
            json.loads(record.read_text(errors="replace"))
        except (OSError, ValueError) as exc:
            print(f"      ERROR: the step-0.5ic record at {record} does not "
                  f"parse ({exc}) — unreadable evidence is not evidence",
                  file=sys.stderr)
            return 1
    return 0


def run_phase1_second_track(project: Path, rc_in: int) -> int:
    """The second track, run after the L-docs exist. Returns the exit code
    Phase 1 should report: a track that did not run overrides a clean backend
    run, and a backend failure is never masked by the track passing.

    THE ORDER IS LOAD-BEARING, AND IT IS THE WHOLE OF #2144. This call must
    stay BELOW the doc-extraction call in `main`. The track selects its expert
    pack CLASS-FIRST (#2094), and it learns the class from
    `ic_class_profile.detect_ic_class`, which classifies from the L documents
    step D1 emits — they are D1's own `required_outputs` and this track is D1's
    own gate clause, which is where `flow/phase1_phase2_phase3.yaml` states the
    obligation. Hoisted above them the classifier answers `unknown`, a PROFILED
    class's pack falls back to the unconfined phrase-selected one with a null
    target module and a null contract, and the run still exits 0 — measured.
    `test_issue2144_expert_track_runs_after_the_l_docs` is the pin; before it,
    that reorder moved no test in the impacted selection.
    """
    print("[phase1] expert track (second track) ...")
    rc_track = _run_expert_track(project)
    return max(int(rc_in or 0), rc_track)


#: #505's COVERAGE-ONLY SIDECAR, AND WHO IS ENTITLED TO NAME IT. R-0915-160, third cut.
#:
#: The sidecar says a phase-1 failure was PURELY doc-coverage, which is what lets the front door
#: demote instead of halting. It is therefore an EXEMPTION, and an exemption must belong to the
#: pass that earned it.
#:
#: MY SECOND CUT ORDERED THE SIDECAR AGAINST THE RECORD, AND THAT ORDER IS ALWAYS WRONG.
#: `run_second_pass_only` named the sidecar only when `sidecar.mtime >= record.mtime`, reasoning
#: that a sidecar older than its own pass-1 record describes a still earlier run. But pass 1 writes
#: the sidecar FIRST -- `phase1_doc_one_shot_runner` emits it in-process, from inside D1 -- and its
#: record LAST, after the expert track and the steps view. So on every real re-invocation the
#: sidecar IS older than the record, the name was never carried, and the front door read "NOT
#: demoting": a `--skip-phase3` coverage-only project that was PASS_WITH_WAIVERS flipped to FAIL
#: and halted at phase 1. The tests did not catch it because the fixture back-dated the sidecar to
#: `record + 10s`, the reverse of the real order, and the front-door arm only grepped source text.
#:
#: SO NOTHING IS ORDERED BY MTIME HERE ANY MORE. PASS ONE NAMES ITS OWN SIDECAR, and the
#: entitlement is structural instead of temporal:
#:
#:   * pass 1 FORGETS any earlier sidecar before it starts, so a file present when it writes its
#:     record is one D1 wrote in THIS pass -- whatever the clock says, and whichever mode ran;
#:   * pass 1 stamps that file's sha256 into the record it publishes;
#:   * the second pass CARRIES the name forward with the record and computes nothing;
#:   * the front door demotes only when the carried name matches the bytes on disk.
#:
#: A sidecar the carried record does not name stays refused, which is the half that keeps this from
#: laundering a stale file -- the same guarantee the mtime rule was reaching for, from the one
#: direction that is not guaranteed backwards.
#: THE PATH ITSELF LIVES IN `_path_layout` NOW (next/icslot-sidecarpath). This module used to
#: spell it, and `vibe_ic_one_shot_runner` spelled it twice more, and the producer twice more
#: again -- five copies of one exemption's location. Retired rather than re-exported: an alias
#: here would be a second NAME for one path, which is the defect being closed.


def _forget_any_earlier_coverage_sidecar(project: Path) -> None:
    """Drop a coverage-only sidecar left by an EARLIER run, before this pass begins.

    This is what makes the naming below structural. Without it, a pass whose D1 never reached its
    own classifier -- a refusal, or an early return inside the doc runner -- would find a previous
    run's sidecar on disk and name it, and the name is an exemption. Absence is the honest state:
    the front door treats "no sidecar" as "do not demote".

    Never raises: this is housekeeping, and a run must not die because a stale advisory file could
    not be removed. If it survives, the naming below is the only thing that could misread it, and a
    reviewer reading this comment knows where to look.
    """
    try:
        _pl.coverage_only_sidecar_path(project).unlink()
    except OSError:
        pass


def _name_the_sidecar_this_pass_wrote(project: Path, summary: Dict[str, Any],
                                      *, d1_ran: bool) -> None:
    """Stamp `pass1_coverage_sidecar` into THIS pass's record, or say why not.

    `d1_ran` is the structural entitlement: D1 is the only thing that writes the sidecar, so a pass
    in which D1 was REFUSED wrote none and must name none, even if a file is somehow there.
    """
    side = _pl.coverage_only_sidecar_path(project)
    if not d1_ran:
        if side.is_file():
            summary["pass1_coverage_sidecar_refused"] = (
                f"D1 was REFUSED in this pass, so it wrote no {_pl.COVERAGE_ONLY_SIDECAR_REL}; "
                f"the file present belongs to an earlier run and is not named")
        return
    if not side.is_file():
        return                                              # nothing written, nothing to name
    try:
        import hashlib as _hashlib                          # noqa: PLC0415
        summary["pass1_coverage_sidecar"] = {
            "rel": _pl.COVERAGE_ONLY_SIDECAR_REL,
            "sha256": _hashlib.sha256(side.read_bytes()).hexdigest(),
            "named_by": "pass 1, which wrote it",
        }
    except OSError:                                         # pragma: no cover
        summary["pass1_coverage_sidecar_refused"] = (
            f"{_pl.COVERAGE_ONLY_SIDECAR_REL} could not be read to name it")


def run_second_pass_only(project: Path, ic_name: str,
                         route: Optional[str]) -> int:
    """PASS 2 of the Phase-1 expert hand-off, and NOTHING else (#2204).

    `phase1_expert_parse_track` ends its first pass by telling the operator to
    invoke the `vibe-ic:ic-expert-agent` subagent and "re-run to consume its
    answer". This is the entry that performs that re-run, and it is what
    `vibe_ic_one_shot_runner._phase1_decision` dispatches when it finds an
    answer on disk that the track's own record says nobody has read.

    THE DOC-EXTRACTION TRACK IS NOT RE-RUN, and that is deliberate twice over:
    it already ran, and its L documents are the very thing the delivered answer
    was authored against — re-deriving them under the answer would move the
    ground the second track is about to compare against.

    IT DOES NOT ERASE WHAT PASS 1 RECORDED. `reports/phase1_one_shot.json` is
    the file every caller reads for Phase 1's verdict; replacing a full D1
    record with a one-row second-pass record would throw away the extraction's
    own report in order to close a hand-off. The prior summary is carried
    forward and only the fields THIS pass re-measured are rewritten.
    """
    route_refusal = _delivery_route.admit(project, route)
    if route_refusal:
        print(_delivery_route.refusal_message(route_refusal), file=sys.stderr)
        return 2
    print("[phase1] EXPERT SECOND PASS — consuming the delivered IC-Expert "
          "answer; the doc-extraction track is NOT re-run")
    reports = project / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    # ONE DEFINITION OF WHERE THIS REPORT LIVES, and it is the router's. R-0915-151.
    #
    # This runner used to write `reports/phase1_one_shot.json` while `_path_layout`
    # categorises the file as `orchestrator`, like phase2's and phase3's. The tree then
    # carried FOUR answers: the router's, this producer's, `vibe_ic_entry_guard`'s (which
    # accepts both and calls the flat one "legacy"), and the front door's, which read the
    # routed path and so read a path nothing wrote -- every phase1-inclusive run came out
    # NOT_MEASURED at exit 1, and a real phase1 FAIL became NOT_MEASURED, so the halt never
    # fired and phase2/3 ran on bad L documents.
    #
    # The ROUTER is the sanctioned answer, and the repo says so twice without being asked:
    # `reports_subfolder_taxonomy_check` FAILS on the flat location -- measured, it reports
    # `1 stray file(s): phase1_one_shot.json` -- and `vibe_ic_entry_guard` already documents
    # `reports/orchestrator/phase1_one_shot.json` as the standalone runner's location and the
    # flat one as legacy. So the producer moves INTO its own repo's taxonomy rather than the
    # reader learning a second place to look.
    out = _pl.report_path(project, "phase1_one_shot.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    # THE WRITE IS THE ROUTER'S (above). THE READ MUST ALSO SEE AN OLDER PROJECT.
    # R-0915-160. Pass 1 of a project produced before R-0915-151 is at the flat path, and
    # reading only the routed one reported that pass as MISSING: `carried=False`, a second
    # pass publishing "UNREADABLE -- the pass-1 record could not be carried forward", and the
    # front door halting at phase 1 on a project that had in fact run. One shared read-side
    # resolver, and the legacy hit is DISCLOSED in the summary rather than accepted quietly.
    _read_from, _read_legacy = _pl.report_path_for_reading(
        project, "phase1_one_shot.json")
    try:
        summary = json.loads(_read_from.read_text(errors="replace"))
        if not isinstance(summary, dict):
            raise ValueError("phase1_one_shot.json top level is not an object")
        carried = True
        # R-0915-160 — THE COVERAGE-ONLY SIDECAR'S NAME IS CARRIED, NOT RE-DERIVED.
        #
        # `summary` above IS pass 1's record, so a `pass1_coverage_sidecar` pass 1 stamped is
        # already in it and this pass has nothing to compute: it carries the name forward, exactly
        # as it carries the rest of the record. See `_name_the_sidecar_this_pass_wrote` for who is
        # entitled to mint that name and why it is no longer an mtime question.
        #
        # THIS BLOCK USED TO RE-DERIVE IT HERE, ordering the sidecar against the record, and that
        # order is ALWAYS wrong: pass 1 writes the sidecar first (in-process, from inside D1) and
        # its record last, so `sidecar.mtime >= record.mtime` was false on every real
        # re-invocation, no name was ever carried, and the front door refused the demotion the
        # re-invocation existed to act on.
        #
        # A record that names nothing is DISCLOSED rather than quietly accepted: the front door
        # will refuse the demotion, and a reader deserves to know it was the carried record that
        # was silent, not the sidecar that was missing.
        if not isinstance(summary.get("pass1_coverage_sidecar"), dict):
            if _pl.coverage_only_sidecar_path(project).is_file():
                summary["pass1_coverage_sidecar_refused"] = (
                    f"{_pl.COVERAGE_ONLY_SIDECAR_REL} is on disk but the pass-1 record carried "
                    f"here does not name it, so nothing says which pass wrote it: not carried")
        if _read_legacy:
            summary["pass1_record_read_from"] = str(
                _read_from.relative_to(project))
            summary["pass1_record_layout"] = (
                "LEGACY -- pass 1 was written at the pre-R-0915-151 flat path "
                f"{_read_from.relative_to(project)}; it was carried forward, and this "
                f"pass publishes at the routed path {out.relative_to(project)}")
    except (OSError, ValueError) as exc:
        # DEGRADE LOUDLY. A second pass over a project whose pass-1 summary is
        # gone or unreadable still reports, and it says so rather than
        # publishing a fresh-looking record that implies pass 1 was fine.
        summary = {"phase": 1, "project": str(project), "ic_name": ic_name}
        summary["pass1_summary"] = (
            f"UNREADABLE — the pass-1 record could not be carried forward "
            f"({exc}); this file now describes the second pass ONLY")
        carried = False
    summary.update(_delivery_route.report_label(project))
    # Freeze the extraction/route outcome independently of replaceable expert
    # retries. Old second-pass FAIL summaries cannot tell which pass failed;
    # retain that uncertainty instead of manufacturing a successful extraction.
    pass1 = summary.get("pass1")
    if not isinstance(pass1, dict):
        prior_verdict = summary.get("verdict")
        known = (carried and summary.get("mode") != "expert_second_pass"
                 and prior_verdict in ("PASS", "PASS_WITH_WAIVERS", "FAIL"))
        pass1 = {
            "verdict": prior_verdict if known else "NOT_MEASURED",
            "rc": 0 if known and prior_verdict != "FAIL" else 1,
            "source": ("carried first-pass summary" if known else
                       "first-pass outcome unavailable; extraction not rerun"),
        }
    pass1_rc = pass1.get("rc")
    if (type(pass1_rc) is not int or pass1_rc < 0
            or pass1.get("verdict") not in ("PASS", "PASS_WITH_WAIVERS", "FAIL")):
        pass1_rc = 1
    if pass1.get("verdict") == "FAIL":
        pass1_rc = max(pass1_rc, 1)
    summary["pass1"] = pass1
    rc = run_phase1_second_track(project, 0)
    summary["mode"] = "expert_second_pass"
    summary["second_track"] = _expert_track_summary(project)
    summary["second_pass"] = {
        "ran": True,
        "rc": rc,
        "consumes": str(_pl.report_path(
            project, "phase1/expert_parse_track.json").parent
            / "expert_parse_track_pack" / "l_doc_expectations.json"),
        "doc_extraction_rerun": False,
        "pass1_summary_carried_forward": carried,
    }
    # Only this retry's failure can clear. The CLI and consumer-visible verdict
    # both include the independently retained first-pass failure.
    rc_out = max(pass1_rc, rc)
    summary["verdict"] = "FAIL" if rc_out else pass1["verdict"]
    import ai_signed_judgement as _ai_judgement
    summary["ai_judgements"] = _ai_judgement.pending(project, ("D1",))
    if not summary["ai_judgements"] and rc == 0:
        _ai_judgement.restore_runner_rows(summary.get("steps", []))
        # The carried row's program_detail describes pass 1, when the expert
        # pack was still awaiting an answer. Its status may now be restored to
        # PASS, but that old prose must not claim HANDOFF_EMITTED after this
        # pass consumed the signed answer.
        for row in summary.get("steps", []):
            if (row.get("name") == "phase1_expert_parse_track"
                    and row.get("status") in ("PASS", "PASS_WITH_WAIVERS")):
                row["detail"] = summary["second_track"]
    _ai_judgement.demote_runner_rows(summary.get("steps", []), summary["ai_judgements"])
    if summary["ai_judgements"] and summary["verdict"] in ("PASS", "PASS_WITH_WAIVERS"):
        summary["verdict"] = "NOT_MEASURED"
        summary["reason_class"] = "awaiting_signed_judgement"
        rc_out = max(rc_out, 1)
    from benchmark_dispatch import _bind_runner_report
    summary = _bind_runner_report(summary, project, __file__, out.name)
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print("\n=== phase1_one_shot_runner DONE (mode=expert_second_pass) ===")
    print(f"verdict: {summary['verdict']}")
    print(f"second track: {summary['second_track']}")
    return rc_out


def _czl9_sufficiency_gate(project: Path) -> Tuple[bool, str]:
    """#czl9docs — run the sufficiency gate on the PROMPT branch too.

    The docs branch reaches this gate inside its delegate's advisory table, and
    the extraction-gap clause blocks there. The prompt branch reached NEITHER:
    measured on this base, a prompt-mode run over an input declaring five ports
    emitted an L9 with 0 ports and 0 characters of prose, printed no sufficiency
    line at all, and exited 0. So the front door a design happened to come
    through decided whether anyone looked — which is the exact shape this
    function's own neighbours already call out:

        "one flow step, two mode branches, one question. Gating only one of
         them would leave whichever front door a given design used unexamined"

    Returns ``(extraction_gap, first_output_line)``. ADVISORY like the docs
    branch, with the SAME single exception: the extraction gap (the input
    declares ports and the L documents carry none), which blocks. rc 1 here can
    only come from ``--strict-extraction-gap``, which is the only strict flag
    passed."""
    chk = PROGRAMS_DIR / "phase1_sufficiency_check.py"
    if not chk.is_file():
        # DEGRADE LOUDLY: an absent check is stated, never assumed clean.
        print("      phase1_sufficiency_check: SKIPPED (program not present) "
              "[ADVISORY]")
        return False, "SKIPPED (program not present)"
    rp = _pl.report_path(project, "phase1/phase1_sufficiency.json")
    rp.parent.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, str(chk), str(_pl.generated_docs_dir(project)),
            "--project", str(project), "--strict-extraction-gap",
            "--json", str(rp)]
    # NO `timeout=`. `run_host_supervised` bounds NO PROGRESS, never runtime —
    # a slow-but-working check on a loaded host runs to completion however long
    # that legitimately takes, and only a tree that is idle across the grace is
    # killed. I wrote `subprocess.run(..., timeout=300)` here first, copying the
    # docs branch, and `test_no_runtime_bound_remains_at_either_dispatch_site`
    # caught it by AST: a clock-based kill is the defect, and a bigger constant
    # is the same defect restated.
    res = _wd.run_host_supervised(argv, stall_grace_s=_TRACK_STALL_GRACE_S)
    if res.outcome in ("stalled", "ceiling"):
        # A STALL IS NOT A VERDICT about the design. Report it as a stall and
        # do not let it become an extraction-gap FAIL.
        print(f"      phase1_sufficiency_check: STALLED — no CPU, no I/O and "
              f"no output from its process tree for the "
              f"{_TRACK_STALL_GRACE_S}s grace, after {res.elapsed_s:.0f}s "
              f"[ADVISORY, NOT_MEASURED]")
        return False, "STALLED (NOT_MEASURED)"
    try:
        cp = _wd.completed_process(argv, res)
    except Exception as exc:            # never let an advisory crash the run
        print(f"      phase1_sufficiency_check: SKIPPED ({exc}) [ADVISORY]")
        return False, f"SKIPPED ({exc})"
    out = (cp.stdout or cp.stderr or "").strip().splitlines()
    gap = cp.returncode == 1
    head = out[0] if out else "(no output)"
    print(f"      phase1_sufficiency_check: {head}"
          f"{' [BLOCKING: extraction gap]' if gap else ' [ADVISORY]'}")
    for line in out[1:6]:
        print(f"        {line}")
    return gap, head



# ── Top-level dispatcher ───────────────────────────────────────────

#: The project THIS invocation of `main` resolved (None until it has one).
#: Read only by `main_recorded`, right after `main` returns, to stamp it.
_RUN = {"project": None, "second_track_only": False, "extracting": False,
        "knobs": None}


def main_recorded() -> int:
    """Phase 1, RECORDED, then stamped with its producer identity.

    The script entry point (`__main__` below), so every run the front door
    launches is recorded. `main` stays the phase itself: several landed gates
    read `main`'s own body for the calls it must make, and it must keep them.

    FX_STALE_LDOCS. The front door reuses generated L docs only when they are
    what the CURRENT producer would write (`_phase1_producer_identity.assess`),
    so phase 1 has to say who wrote them: it runs inside
    `_phase1_producer_identity.ProducerRecorder` -- the plugin modules it
    loaded and the plugin scripts it launched, in the step recorder's record
    format, with no profiler -- and, as its last act, stamps
    `phase1/step_identity.json` (kind `phase1`).

    Stamped only when THIS run dispatched D1 (`_as_the_producer`); a refused
    or locked-out run did not, and must not claim the docs on disk. The stamp
    covers only the docs this run WROTE. A `--second-track-only` pass is not
    the doc producer: the docs it rewrote are recorded as derivations, and the
    producer's recording, inputs and every other doc are left alone."""
    import _phase1_producer_identity as _pid
    _RUN.update(project=None, second_track_only=False, extracting=False,
                knobs=None)
    # The design-input tree BEFORE phase 1: whatever it creates or rewrites
    # there -- in this process or a launched one (step 0.5ic's declaration) --
    # is the flow's own output, not design input (review wave8 BLOCKER 1).
    _proj0 = _project_arg()
    input_before = (_pid.input_tree_snapshot(_proj0)
                    if _proj0 is not None and _proj0.is_dir() else None)
    recorder = _pid.ProducerRecorder()
    with recorder:
        rc = globals()["main"]()
    project = _RUN["project"]
    try:
        if project is not None and _pid.docs_snapshot(project):
            if _RUN["extracting"]:
                _pid.stamp(project, recorder, input_before=input_before,
                           knobs=_RUN.get("knobs"))
            elif _RUN["second_track_only"]:
                _pid.restamp_outputs(project, recorder.written_docs(project))
    except Exception as exc:                               # noqa: BLE001
        print(f"[phase1] producer identity NOT stamped ({exc}); the next run "
              f"will regenerate these docs rather than trust them",
              file=sys.stderr)
    return rc


def _as_the_producer(fn):
    """`fn` is the D1 extraction: when the preflight lets it RUN, this run is
    the doc producer of record.

    FX_STALE_LDOCS (review wave8). Set only here, where D1 is actually
    dispatched -- a D1-REFUSED run wrote nothing and must not stamp -- and the
    previous stamp is voided at this same point, so a run that dies half way
    through regenerating leaves NO_PRODUCER_IDENTITY (which regenerates),
    never an old stamp vouching for half-new docs (which would refuse)."""
    def _run(project, *a, **k):
        import _phase1_producer_identity as _pid
        _RUN["extracting"] = True
        _pid.void(project)
        return fn(project, *a, **k)
    return _run


def _project_arg() -> Optional[Path]:
    """The project positional, read the way `main`'s parser will read it."""
    for tok in sys.argv[1:]:
        if not tok.startswith("-"):
            try:
                return Path(tok).resolve()
            except OSError:
                return None
        break
    return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("project", type=Path)
    p.add_argument("--ic-name", default="UNNAMED_CHIP")
    p.add_argument("--route", choices=("ic", "ip"),
                   help="Owner-stated delivery route: ic=DIE, ip=HARDMACRO. "
                        "Required unless already owner-declared in this project.")
    p.add_argument("--mode",
                   choices=REQUESTABLE_MODES,
                   default="auto",
                   help="input mode: auto-detect (default), force docs, or "
                        "request prompt. #2052: a `prompt` REQUEST over an "
                        "input the detector routes to the doc-extraction "
                        "track is resolved to `docs` and announced — the "
                        "engine reverse-extractor is not a second front door "
                        "for raw design input.")
    p.add_argument("--second-track-only", action="store_true",
                   help="#2204: run ONLY the Phase-1 expert second track — "
                        "the second pass of the hand-off that "
                        "`phase1_expert_parse_track` asks for when it writes "
                        "a pack and a subagent answers it. The "
                        "doc-extraction track is NOT re-run: it already ran, "
                        "and its L documents are what the delivered answer "
                        "was authored against. Dispatched automatically by "
                        "`vibe_ic_one_shot_runner` when a delivered answer is "
                        "on disk and the track's own record says nobody has "
                        "read it.")
    p.add_argument("--skip-analog", action="store_true",
                   help="Preserve the parent invocation's explicit analog routing choice.")
    import execution_policy as _execution
    _execution.add_arguments(p)
    args, extras = p.parse_known_args()
    _execution.configure(args)
    project = args.project.resolve()
    _execution.bootstrap(project, parameters={"ic_name": args.ic_name,
        "skip_analog": bool(args.skip_analog)}, phase1_only=True)
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2
    _RUN.update(project=project, second_track_only=bool(args.second_track_only),
                knobs={"ic_name": args.ic_name, "pdk": _pdk_of_this_run(extras),
                       "mode": "docs" if args.mode in ("auto", "docs")
                       else args.mode})

    # ORGANIC #588 — single-driver lock, honored by the standalone phase
    # runner too (not just the orchestrator). Re-enters cleanly when the
    # orchestrator delegated this run (env token); refuses a SECOND
    # standalone phase1 on a project a live runner already drives.
    _lock = _runner_lock.acquire_or_reenter(project, "phase1_one_shot_runner")
    if _lock is None:
        return 3
    route_refusal = _delivery_route.admit(project, args.route)
    if route_refusal:
        print(_delivery_route.refusal_message(route_refusal), file=sys.stderr)
        _lock.release()
        return 2

    # #2204 — the expert second pass short-circuits EVERYTHING below. Step
    # 0.5ic and D1 both already ran in the pass that emitted the hand-off;
    # this entry exists to read one delivered answer and record what it made
    # of it, so it runs the second track alone and re-runs nothing.
    if args.second_track_only:
        return run_second_pass_only(project, args.ic_name, args.route)
    # PASS 1 BEGINS HERE, so this is where an EARLIER pass's coverage-only sidecar stops being
    # this project's answer. R-0915-160. Below the second-pass short-circuit on purpose: the
    # second pass carries pass 1's sidecar and must not erase it. See
    # `_name_the_sidecar_this_pass_wrote` for why the entitlement is structural and not a clock.
    _forget_any_earlier_coverage_sidecar(project)

    # STEP 0.5ic — the route declaration. Dispatched before the mode branch
    # and on every path, because 0.5ic `blocks_on: []` and takes no input from
    # D1: which delivery route a design is on is a property of the DESIGN, not
    # of its documents.
    print("[phase1] step 0.5ic — submission template + tape-out declaration ...")
    rc_route = _run_step_0_5ic(project, pdk=_pdk_of_this_run(extras))

    # Resolve mode. When auto-detect finds no input, fall through to
    # prompt mode so step_ingest_render emits a SKIP status (verdict
    # PASS_WITH_WAIVERS rc=0). This matches the legacy behaviour where
    # an empty project gracefully reports "nothing to do" rather than
    # exiting non-zero.
    detected = _detect_input_mode(project)
    mode, mode_redirect = _resolve_mode(args.mode, detected)
    if mode_redirect:
        # A route the caller did not type is announced, never silent.
        print(f"[phase1] mode: {mode_redirect}")

    # Docs mode: delegate to phase1_doc_one_shot_runner
    if mode == "docs":
        t0 = time.time()
        # PRE-FLIGHT (canonical step D1). Its declared input is the STAGED
        # corpus — `input/docs/*`, `input/phase1_prompt.md`,
        # `input/phase1_structured.yaml`, or a directly-staged
        # `phase1/input_{doc,prompt}/`. Without this, a project with nothing
        # staged ran the whole 17-skill doc-extraction track over an empty
        # tree and reported a verdict about the L-docs it "produced".
        # ONE NAME FOR ONE FLOW STEP (#2052). D1 was `phase1_doc_extract` here
        # and `phase1_ingest_render` on the prompt branch — one step, two names,
        # so a reader comparing two runs of the same design could not join them.
        # Now that `--mode prompt` resolves to this door, the name a run reports
        # for D1 must not depend on which door it came through either.
        _pf = _spf.gate(
            project, "phase1_one_shot_runner", "doc_extract",
            _preflight_refusal(D1_STEP_NAME),
            _as_the_producer(_run_docs_mode), project, args.ic_name, extras)
        # `_run_docs_mode` returns an int rc; the refusal factory returns a
        # StepResult. The TYPE is the discriminator, and it is exact — there is
        # no rc value that is also a StepResult.
        refused = isinstance(_pf, StepResult)
        rc = 1 if refused else int(_pf)
        rc_extract = rc
        pass1_rc = max(rc_extract, rc_route)
        pass1_verdict = ("FAIL" if rc_route or rc_extract == 1 else
                         ("NOT_MEASURED" if rc_extract == 2 else "PASS"))
        rc_track = 0
        if refused:
            # The second track parses the L-docs D1 was supposed to write. D1
            # was never called, so there is nothing for it to examine — running
            # it would manufacture a second, derived failure and bury the real
            # one. RECORDED in the summary below rather than skipped silently.
            second_track = ("not run — D1 was REFUSED, so no L-doc exists for "
                            "the expert track to parse")
        elif rc_extract == 2:
            # A VACUOUS generator-stamp handoff is an undetermined D1 result;
            # parsing the absent population would manufacture a second error.
            rc_track = 2
            second_track = ("not run — D1 was UNDETERMINED, so no L-doc "
                            "population exists for the expert track")
        else:
            rc_track = run_phase1_second_track(project, 0)
            rc = max(rc_extract, rc_track, rc_route)
            second_track = _expert_track_summary(project)
        # The dispatcher always emits reports/phase1_one_shot.json so
        # callers / tests see a unified entry point regardless of mode.
        reports = project / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        verdict = (_aggregate_verdict([_pf]) if refused
                   else ("FAIL" if rc_route else _delegated_rc_verdict(rc)))
        summary = {
            "phase": 1,
            "mode": "docs",
            "project": str(project),
            **_delivery_route.report_label(project),
            "ic_name": args.ic_name,
            "delegated_to": "phase1_doc_one_shot_runner",
            "delegated_rc": rc_extract,
            "mode_requested": args.mode,
            "mode_detected": detected,
            "mode_redirect": mode_redirect,
            "duration_s": time.time() - t0,
            "verdict": verdict,
            "pass1": {"verdict": pass1_verdict, "rc": pass1_rc,
                      "source": "extraction and route before expert track"},
            "second_track": second_track,
        }
        producer = _execution.phase1_producer_disclosure(project)
        if producer is not None:
            summary['canonical_producer'] = producer
        import ai_signed_judgement as _ai_judgement
        summary["ai_judgements"] = _ai_judgement.pending(project, ("D1",))
        if summary["ai_judgements"] and summary["verdict"] in ("PASS", "PASS_WITH_WAIVERS"):
            summary["verdict"] = "NOT_MEASURED"
            summary["reason_class"] = "awaiting_signed_judgement"
            rc = max(rc, 1)
        # THE REPORT SHAPE IS THE SAME ON BOTH DOORS (#2052). A refusal was
        # already reported here as a `steps` list; a COMPLETED run was not, so
        # `reports/phase1_one_shot.json` carried a `steps` key on one door and
        # not on the other for the same design — a divergence about the doors,
        # not about the design, in the file every caller reads. Both branches
        # now report the same two rows: D1, and the independent expert track.
        _t_docs = time.time() - t0
        if refused:
            # A refusal must be readable AS a refusal, not as "the delegate
            # returned 1". Same shape as the prompt branch's `steps` list.
            summary["steps"] = [asdict(_pf)]
            summary["preflight_ledger"] = _spf.LEDGER_REL
        else:
            summary["steps"] = [
                asdict(_delegated_step_result(
                    D1_STEP_NAME, rc_extract, _t_docs,
                    f"delegated to phase1_doc_one_shot_runner (rc={rc_extract}); "
                    f"L documents under "
                    f"{_pl.generated_docs_dir(project).name}/")),
                asdict(_delegated_step_result(
                    "phase1_expert_parse_track", rc_track, 0.0,
                    str(second_track)[:400], upstream=rc_extract == 2)),
            ]
        _ai_judgement.demote_runner_rows(summary["steps"], summary["ai_judgements"])
        # Per-step output view — see the prompt-mode call below. BOTH exits of
        # this main() get it; wiring only one would leave the docs entry (Path
        # A, the vendor-document front door) without a steps tree.
        summary["steps_view"] = _pl.emit_steps_view(
            project, PROGRAMS_DIR, runner="phase1_one_shot_runner")
        summary["step_0_5ic"] = "ran" if rc_route == 0 else "FAILED to run"
        # R-0915-160 — PASS 1 NAMES THE SIDECAR IT WROTE, so the second pass can carry the name
        # instead of re-deriving it from an ordering that is guaranteed backwards.
        _name_the_sidecar_this_pass_wrote(project, summary, d1_ran=not refused)
        _p1 = _pl.report_path(project, "phase1_one_shot.json")   # the router, always
        _p1.parent.mkdir(parents=True, exist_ok=True)
        # Dispatched producers must state their generation themselves — the
        # docs-mode main branch is a first-class report writer, so its write
        # passes through the same producer binding the second-pass tail uses.
        # Standalone runs (no VIBEIC_RUNNER_INVOCATION_CONTEXT) are unchanged.
        from benchmark_dispatch import _bind_runner_report
        summary = _bind_runner_report(summary, project, __file__, _p1.name)
        _p1.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
        return max(rc, rc_route)

    # Prompt mode: original phase1_engine path
    plan: List[StepResult] = []
    # PRE-FLIGHT (canonical step D1) — the SAME site as the docs branch above:
    # one flow step, two mode branches, one question. Gating only one of them
    # would leave whichever front door a given design used unexamined, which is
    # the shape of the gap this closes.
    plan.append(_spf.gate(
        project, "phase1_one_shot_runner", "doc_extract",
        _preflight_refusal(D1_STEP_NAME),
        _as_the_producer(step_ingest_render), project, args.ic_name))
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

    # #czl9docs — the sufficiency gate, on THIS branch too. NOT after a
    # refusal, for the same reason the second track is not: it would parse
    # L-docs that were never written and report a derived failure on top of the
    # real one.
    _gap, _suff = (False, "not run — D1 was REFUSED") if _refused else \
        _czl9_sufficiency_gate(project)

    reports = project / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    pass1_verdict = _aggregate_verdict(plan)
    # R-0915-85 — THE EXIT CODE IS THE RUN WORD, and NOT_MEASURED is not green.
    # This ladder read only `== "FAIL"`, so an empty project — D1 refused for
    # want of any input at all — aggregated to NOT_MEASURED and EXITED 0. That
    # is the run16 shape exactly: nothing was measured and the shell was told
    # the phase had passed.
    #
    # And the word is NOT overwritten into FAIL when the rc is 1. A run that
    # measured nothing did not fail; `run_verdict` already put it off PASS, and
    # rewriting it here would make the artefact claim a finding the run never
    # made. Only a route failure — which IS a failure — sets FAIL.
    _not_green = pass1_verdict in (_V.Verdict.FAIL.value,
                                   _V.Verdict.NOT_MEASURED.value)
    pass1_rc = max(1 if _not_green or _gap else 0, rc_route)
    if rc_route or _gap:
        pass1_verdict = _V.Verdict.FAIL.value
    summary = {
        "phase": 1,
        "mode": mode,
        **_delivery_route.report_label(project),
        "mode_requested": args.mode,
        "mode_detected": detected,
        "mode_redirect": mode_redirect,
        "project": str(project),
        "ic_name": args.ic_name,
        "steps": [asdict(s) for s in plan],
        # R-0915-85 — the published word is the RUN's word, not the exit code
        # spelled as a word. A non-zero rc means "not green", and NOT_MEASURED
        # is not green; overwriting it with FAIL made the artefact claim a
        # finding about a design nothing had looked at, which is the one thing
        # this ruling exists to stop.
        "verdict": (_V.Verdict.FAIL.value
                    if (rc_second or pass1_verdict == _V.Verdict.FAIL.value)
                    else pass1_verdict),
        "pass1": {"verdict": pass1_verdict, "rc": pass1_rc,
                  "source": "extraction, sufficiency and route without expert track"},
        "second_track": ("not run — D1 was REFUSED" if _refused else
                         _expert_track_summary(project)),
        "step_0_5ic": "ran" if rc_route == 0 else "FAILED to run",
        "sufficiency": _suff,
        "extraction_gap": _gap,
    }
    producer = _execution.phase1_producer_disclosure(project)
    if producer is not None:
        summary['canonical_producer'] = producer
    import ai_signed_judgement as _ai_judgement
    summary["ai_judgements"] = _ai_judgement.pending(project, ("D1",))
    _ai_judgement.demote_runner_rows(summary["steps"], summary["ai_judgements"])
    if summary["ai_judgements"] and summary["verdict"] in ("PASS", "PASS_WITH_WAIVERS"):
        summary["verdict"] = "NOT_MEASURED"
        summary["reason_class"] = "awaiting_signed_judgement"
    if _refused:
        summary["preflight_ledger"] = _spf.LEDGER_REL
    # Per-step output view — <project>/steps/<phase>/<stage>/<id>_<slug>/.
    # A phase1-only run shows every later step with zero outputs, which is the
    # honest picture: the tree is the flow, and "nothing produced yet" is a
    # statement worth having on disk. Best-effort, non-gating; recorded in
    # reports/audit/steps_view.json either way.
    summary["steps_view"] = _pl.emit_steps_view(
        project, PROGRAMS_DIR, runner="phase1_one_shot_runner")
    # R-0915-160 — the SAME call as the docs branch. Wiring only one door would mean a design's
    # demotion depended on which front door it came through, which is the shape #2052 exists to
    # refuse. `--mode prompt` resolves to the docs door for D1, so this branch's D1 refusal is
    # `_refused` under its own spelling.
    _name_the_sidecar_this_pass_wrote(project, summary, d1_ran=not _refused)
    _p1 = _pl.report_path(project, "phase1_one_shot.json")       # the router, always
    _p1.parent.mkdir(parents=True, exist_ok=True)
    # Same producer binding as the docs branch and the second-pass tail: a
    # dispatched run's fresh phase1 report must carry its generation, and a
    # standalone run (no invocation context) is byte-identical to before.
    from benchmark_dispatch import _bind_runner_report
    summary = _bind_runner_report(summary, project, __file__, _p1.name)
    _p1.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(f"\n=== phase1_one_shot_runner DONE (mode={mode}) ===")
    print(f"verdict: {summary['verdict']}")
    for s in plan:
        print(f"  {s.status:6} {s.name:24} "
              f"{_rsum.summary_detail(s.detail, s.status)}")
    if _gap:
        # Same clause, same wording and same rc as the docs branch. A design
        # must not get a different answer because of which front door it came
        # through.
        print("FAIL: EXTRACTION GAP — the design input declares ports and the "
              "generated L documents carry none; every downstream gate that "
              "reads a port list would report a verdict over ZERO ports. See "
              "reports/phase1/phase1_sufficiency.json (ports_reason="
              "extraction_gap)")
    # R-0915-85 — THE EXIT CODE IS THE RUN WORD. This read `!= "FAIL"`, so
    # every word that is not FAIL exited 0, and after the line above stopped
    # overwriting NOT_MEASURED into FAIL that included "nothing was measured".
    # `verdict.GREEN` is the two words a run may exit 0 on; everything else is
    # rc 1, whether it failed or was never looked at.
    return max(0 if summary["verdict"] in (_V.Verdict.PASS.value,
                                           _V.Verdict.PASS_WITH_WAIVERS.value)
               else 1,
               rc_second, rc_route, 1 if _gap else 0)


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(main_recorded))
