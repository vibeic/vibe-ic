#!/usr/bin/env python3
"""tapeout_readiness_check — the LIVE open-MPW submission gate (closes #1744).

THE DEFECT THIS CLOSES
======================
Every gate vibe-ic has, vibe-ic wrote.  There was exactly ONE interface where an
outside party's refusal was the verdict — the shuttle precheck — and it pointed
at a vendor that shut down in 2025 (`mpw_precheck_driver`,
`mpw_precheck_result_gate`, `caravel_integration_runner.step_c1_run_precheck`).
A dead counterparty cannot refuse, so "are we submittable?" was answered by us
alone, in both halves: the refusal AND the inventory
(`tapeout_checklist_gen`, by its own docstring a DERIVED-VIEW generator).

This program restores the outside refusal.  It RUNS the live shuttle's own
precheck container against the artefact we are about to publish and takes that
container's EXIT CODE as the verdict.

WRAP, NEVER REIMPLEMENT
=======================
The container is the authority.  This module contains NO copy of any of its
rules — not the seal-ring layer number, not the slot dimensions, not the pad
layer, not the ID-cell names.  A reimplementation would be OUR bar again, and
could drift into passing; that drift is the exact problem the gate removes.
Everything below is orchestration, evidence collection and honest accounting.

THE FOUR REFUSALS THIS RESTORES (measured, not asserted)
=======================================================
Run against a GDS this repo has already published, the container refuses at
stage 3 of 16 and stages 4-16 never execute.  Its ladder can refuse for a seal
ring that is absent, a die that is not the slot size, an absent pad layer, and
absent ID cells.  No gate in this tree could raise any of the four before this
one, because no gate of ours examines a submission FRAME at all: the nearest
neighbours screen CELLS for latch-up and parse the WORDS "no seal ring" in a
document.

THE FOUR REQUIREMENTS, AND WHERE EACH LIVES
===========================================
1. DIGEST PIN — `PINNED_IMAGE` is an immutable `@sha256:` reference, and
   `is_digest_pinned` REFUSES any tag reference (`:main`) outright.  A moving
   tag makes a refusal unreproducible, and the first question anyone asks of a
   refusal is whether it would refuse again.  There is deliberately no
   `--allow-unpinned` escape: that would be a way to make the check check less.
2. NO NETWORK — the run is always `--network=none` and always `--pull=never`,
   neither overridable.  A precheck that can reach the network is a precheck
   whose result depends on something outside the artefact.  `--pull` performs an
   explicit pull BEFORE the run and is the module's only network touch; it is
   off by default and never happens inside the graded run.
3. BLOCKED IS ITS OWN STATE — image absent, container failed to start, docker
   missing, timeout, or an exit that produced no evidence all resolve to
   `BLOCKED` with a named reason, and `BLOCKED` FAILS the gate (exit 1).  It can
   never render as "no refusals found"; a check that could not run reporting
   clean is precisely the defect this repo hunts, and self-inflicting it here
   would be worse than not having the gate.
4. HONEST STAGE ACCOUNTING — "3 of 16" with stages 4-16 named as NEVER RAN, not
   "1 failure".  A ladder that stopped at stage 3 has not cleared stages 4-16;
   it has not ATTEMPTED them, and the difference is the whole submission risk.

WHERE EACH NUMBER COMES FROM (and what happens when it cannot be known)
======================================================================
* which stages RAN      — the numbered step directories the run itself wrote.
                          Unambiguous; nothing is inferred.
* the DENOMINATOR       — the container's own flow, enumerated by asking the
                          container (never restated here), CORROBORATED against
                          the `N/M` the run's own progress output printed.
* stages that NEVER RAN — the enumerated names after the stop point, emitted
                          ONLY when the enumeration length agrees with the run's
                          own denominator AND the observed directories match the
                          enumerated prefix.
Any disagreement, or an enumeration that could not be obtained, yields
`NOT_DETERMINED` for the affected field — never a guess, and never a silently
plausible number.  `NOT DETERMINED` beats a guess.

WHY ARGV AND NOT `bash -c`
==========================
Every path reaches docker as its own argv element.  The sibling
`mpw_precheck_driver` embeds paths in a `bash -c` string, and in the plugin's
own EDA container that is not theoretical: `getpass.getuser()` there returns
`'1000\\ndesigner'`, so pytest's `tmp_path` contains a literal NEWLINE and the
composed command splits.  Orchestration must not be able to fail on a filename.

CHIP-AGNOSTIC
=============
No design name, no chip literal, no process/technology literal appears in any
decision rule.  The layout path, top cell, slot, packaging option and die ID are
all parameters; every rule they feed is the container's, not ours.

CLI
    python3 tapeout_readiness_check.py --layout <chip_top.gds> \\
        [--top <cell>] [--slot 1x1] [--cob] [--id <hex>] \\
        [--rundir <dir>] [--timeout 7200] [--pull] [--out-json <path>]

Exit 0 = PASS (the shuttle's precheck ran its ladder and exited 0).
Exit 1 = REFUSED (it ran and refused) or BLOCKED (it could not run).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)


TOOL = "tapeout_readiness_check"

# --------------------------------------------------------------------------- #
# The pin.
#
# An IMMUTABLE digest, not the `:main` tag the shuttle publishes.  Re-pinning is
# a deliberate, reviewable edit: the new digest changes the bytes of this file,
# so a verdict can always be traced to the exact ladder that produced it.
# --------------------------------------------------------------------------- #
PINNED_IMAGE = (
    "ghcr.io/wafer-space/gf180mcu-precheck"
    "@sha256:c6f609d7b3b9c58fcc275db5dbd7f372e79502ce2c18b882b4385b3764d8c876"
)

_DIGEST_RE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")

# Where the container keeps its own tree.  Fixed by the image, not by us.
_CONTAINER_PRECHECK = "/workspace/precheck.py"
_CONTAINER_WORKSPACE = "/workspace"
_CONTAINER_INPUT_DIR = "/ws_input"
_CONTAINER_RUNDIR = "/ws_run"

# The one run tag we ever use, inside a run directory this invocation created.
# Fixing it makes the produced path exactly predictable, so no stale directory
# from an earlier invocation can ever be mistaken for this run's evidence.
RUN_TAG = "precheck"

NOT_DETERMINED = "NOT_DETERMINED"

# Verdicts.
PASS = "PASS"
REFUSED = "REFUSED"
BLOCKED = "BLOCKED"

# BLOCKED reasons — each its own named state, none of which is a pass.
B_IMAGE_NOT_DIGEST_PINNED = "IMAGE_NOT_DIGEST_PINNED"
B_DOCKER_UNAVAILABLE = "DOCKER_UNAVAILABLE"
B_IMAGE_ABSENT = "IMAGE_ABSENT"
B_CONTAINER_FAILED_TO_START = "CONTAINER_FAILED_TO_START"
B_LAYOUT_ABSENT = "LAYOUT_ABSENT"
B_RUNDIR_NOT_FRESH = "RUNDIR_NOT_FRESH"
B_TIMEOUT = "TIMEOUT"
B_NO_EVIDENCE = "NO_EVIDENCE"
B_EVIDENCE_CONTRADICTS_EXIT = "EVIDENCE_CONTRADICTS_EXIT"
B_MALFORMED_REPORT = "MALFORMED_REPORT"

# `docker run` reserves these for "the container never ran your command":
#   125 the docker daemon/CLI itself failed (bad flag, missing image, ...)
#   126 the command was found but could not be invoked
#   127 the command was not found
# They are docker's own vocabulary, not a guess about the precheck's exit codes.
_DOCKER_START_FAILURE_RCS = frozenset({125, 126, 127})

# Conventional "the wall clock ran out" code, matching the sibling driver.
_TIMEOUT_RC = 124

# `01-klayout-checksize` -> (1, "klayout-checksize")
_STEP_DIR_RE = re.compile(r"^(\d+)-(.+)$")

# The run's OWN progress line, e.g. "... Check Slot Size ━━━  2/16 0:00:03".
# Read only as CORROBORATION for the denominator; never as the primary source.
_PROGRESS_RE = re.compile(r"\b(\d+)\s*/\s*(\d+)\s+\d+:\d{2}:\d{2}")

# Marker the enumeration probe prints, so its one line is separable from
# whatever else the container's start-up writes to stdout.
_STAGES_MARKER = "VIBEIC_PRECHECK_STAGES "


# --------------------------------------------------------------------------- #
# Seams — so every state above is reachable in a test with NO live image.
# --------------------------------------------------------------------------- #
# runner(argv, timeout) -> (returncode, stdout, stderr)
Runner = Callable[[List[str], Optional[float]], Tuple[int, str, str]]


def default_runner(cmd: List[str],
                   timeout: Optional[float]) -> Tuple[int, str, str]:
    """Run `cmd` as argv (never through a shell), returning (rc, out, err).

    A timeout surfaces as `_TIMEOUT_RC` with whatever partial output exists; the
    caller then decides BLOCKED on its own terms.  An OSError (docker binary
    vanished mid-flight) surfaces as a start failure rather than an exception,
    because an orchestration crash must still reach a NAMED blocked state.
    """
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired as e:
        out, err = e.stdout or "", e.stderr or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        return _TIMEOUT_RC, out, err + "\n[timeout]"
    except OSError as e:
        return 125, "", f"[docker invocation failed] {e!r}"


def is_digest_pinned(image: str) -> bool:
    """True only for an immutable `repo@sha256:<64 hex>` reference.

    A tag — including the shuttle's own `:main` — is refused.  The point of the
    pin is that a refusal can be reproduced later; a tag that moved makes the
    same command a different check, and there is no way to tell after the fact.
    """
    return bool(_DIGEST_RE.match(image or ""))


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def probe_image(image: str, docker_bin: str = "docker",
                runner: Optional[Runner] = None,
                timeout: Optional[float] = 120.0) -> Optional[str]:
    """The local image ID for `image`, or None when it is not present.

    `docker image inspect` is used rather than `docker images -q` because only
    inspect resolves a `@sha256:` reference; `images -q` filters on tags and
    would report a digest-pinned image as absent even when it is present.
    """
    run = runner or default_runner
    rc, out, _ = run(
        [docker_bin, "image", "inspect", "--format", "{{.Id}}", image], timeout)
    if rc != 0:
        return None
    ident = (out or "").strip().splitlines()
    return ident[0].strip() if ident and ident[0].strip() else None


def pull_image(image: str, docker_bin: str = "docker",
               runner: Optional[Runner] = None,
               timeout: Optional[float] = 1800.0) -> bool:
    """Explicitly fetch `image`.  The ONLY network touch in this module, opt-in
    via `--pull`, and always finished before the graded (`--network=none`) run
    begins — so the run itself never depends on anything outside the artefact."""
    run = runner or default_runner
    rc, _, _ = run([docker_bin, "pull", image], timeout)
    return rc == 0


# --------------------------------------------------------------------------- #
# Asking the container what its own ladder is
# --------------------------------------------------------------------------- #
def build_enumerate_command(image: str, cob: bool,
                            docker_bin: str = "docker") -> List[str]:
    """argv that makes the container print its OWN ordered step list.

    This reads the container's flow object; it does not restate it.  The `--cob`
    substitution is applied through the container's own `Flow.Substitute` API
    with the container's own step class, so the shape of the ladder stays the
    container's answer to the question.
    """
    probe = (
        "import sys, json\n"
        f"sys.path.insert(0, {_CONTAINER_WORKSPACE!r})\n"
        "import precheck\n"
        "flow = precheck.PrecheckFlow\n"
        "if COB:\n"
        "    flow = flow.Substitute("
        "[('+KLayout.CheckSize', precheck.CheckPadMask)])\n"
        "print(MARKER + json.dumps("
        "[{'id': s.id, 'name': s.name} for s in flow.Steps]))\n"
    )
    preamble = f"COB = {bool(cob)!r}\nMARKER = {_STAGES_MARKER!r}\n"
    return [
        docker_bin, "run", "--rm",
        "--network=none", "--pull=never",
        image, "python3", "-c", preamble + probe,
    ]


def parse_enumerated_stages(stdout: str) -> Optional[List[Dict[str, str]]]:
    """The step list out of the probe's stdout, or None if it is not there.

    None means NOT DETERMINED downstream.  It never falls back to a built-in
    list: a hard-coded ladder here would be this module quietly reimplementing
    the very thing it exists to wrap, and it would keep reporting a confident
    denominator after the container's ladder changed underneath it.
    """
    for line in (stdout or "").splitlines():
        idx = line.find(_STAGES_MARKER)
        if idx < 0:
            continue
        try:
            data = json.loads(line[idx + len(_STAGES_MARKER):].strip())
        except json.JSONDecodeError:
            return None
        if not isinstance(data, list) or not data:
            return None
        out: List[Dict[str, str]] = []
        for item in data:
            if not isinstance(item, dict) or "id" not in item:
                return None
            out.append({"id": str(item["id"]),
                        "name": str(item.get("name", item["id"]))})
        return out
    return None


def step_dir_slug(step_id: str) -> str:
    """The directory basename the run writes for a step id.

    `KLayout.ReadLayout` -> `klayout-readlayout`, matching the `01-<slug>`
    directories the run produces.  Used only to CORROBORATE that an enumerated
    ladder describes the run actually observed; when it does not corroborate,
    the never-ran names are withheld rather than guessed.
    """
    return step_id.lower().replace(".", "-")


# --------------------------------------------------------------------------- #
# Reading the run's own evidence
# --------------------------------------------------------------------------- #
def observed_steps(run_root: Path) -> List[Tuple[int, str]]:
    """(index, slug) for every numbered step directory the run wrote, ordered."""
    if not run_root.is_dir():
        return []
    found: List[Tuple[int, str]] = []
    for child in run_root.iterdir():
        if not child.is_dir():
            continue
        m = _STEP_DIR_RE.match(child.name)
        if m:
            found.append((int(m.group(1)), m.group(2)))
    return sorted(found)


def progress_denominator(stdout: str) -> Optional[int]:
    """The `M` of the run's own `N/M` progress output, or None.

    Taken from the LAST match: the flow rewrites the line as it advances, so the
    final one is the state the run ended in.
    """
    hits = _PROGRESS_RE.findall(stdout or "")
    if not hits:
        return None
    try:
        return int(hits[-1][1])
    except (TypeError, ValueError):
        return None


def read_refusal_text(run_root: Path) -> str:
    """The run's own `error.log`, verbatim.

    Verbatim because the whole value of an outside refusal is that it is THEIR
    sentence, in their words; paraphrasing it back into our vocabulary is how a
    wrapped check turns back into our own bar.
    """
    p = run_root / "error.log"
    if not p.is_file():
        return ""
    try:
        return p.read_text(errors="replace").strip()
    except OSError:
        return ""


def read_verdict(path: Path) -> Dict[str, Any]:
    """Read back a verdict JSON this gate wrote.

    Exists for the sign-off ladder, whose own contract is that it CONSUMES
    per-tier artefacts and "does not invoke EDA tools itself".  So the container
    runs once, here, and the ladder reads the result — rather than the ladder
    starting containers during a report roll-up.

    The parsing rule lives with the gate rather than in the consumer so there is
    exactly one place that decides what a verdict file means.  A file that is
    missing, unreadable, not JSON, or carries no recognised verdict resolves to
    BLOCKED/`MALFORMED_REPORT` — never to a pass.  A consumer that cannot tell
    what happened has not been told that nothing was wrong, and that is the
    whole §4.05 point restated at the artefact boundary.
    """
    def _blocked(detail: str) -> Dict[str, Any]:
        return {"verdict": BLOCKED, "blocked_reason": B_MALFORMED_REPORT,
                "blocked_detail": detail, "stage_summary": NOT_DETERMINED}
    try:
        payload = json.loads(Path(path).read_text(errors="replace"))
    except (OSError, json.JSONDecodeError) as e:
        return _blocked(f"verdict file could not be read as JSON: {e!r}")
    if not isinstance(payload, dict):
        return _blocked("verdict file is not a JSON object")
    if payload.get("verdict") not in (PASS, REFUSED, BLOCKED):
        return _blocked(
            f"verdict file carries no recognised verdict "
            f"(found {payload.get('verdict')!r})")
    return payload


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
@dataclass
class ReadinessReport:
    layout: str
    layout_sha256: str
    image: str
    verdict: str                      # PASS / REFUSED / BLOCKED
    blocked_reason: str = ""
    blocked_detail: str = ""
    image_id: Optional[str] = None
    docker_returncode: Optional[int] = None
    network: str = "none"
    slot: str = "1x1"
    cob: bool = False
    top: str = ""
    rundir: Optional[str] = None
    run_root: Optional[str] = None
    # Stage accounting.  Any of these may be NOT_DETERMINED / None, and that is
    # a reported state rather than a defaulted number.
    stages_total: Any = NOT_DETERMINED
    stages_total_source: str = NOT_DETERMINED
    stages_ran: List[str] = field(default_factory=list)
    stopped_at_index: Any = NOT_DETERMINED
    stopped_at_stage: Any = NOT_DETERMINED
    stages_never_ran: Any = NOT_DETERMINED
    stage_summary: str = NOT_DETERMINED
    refusal_text: str = ""
    command: List[str] = field(default_factory=list)
    stdout_tail: str = ""
    stderr_tail: str = ""
    notes: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.verdict == PASS

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["emitted_by"] = _pmd.emitted_by(TOOL)
        return d


def _stage_summary(stopped_at: Any, total: Any) -> str:
    """`"3 of 16"`, degrading to NOT_DETERMINED rather than to a plausible number.

    "1 failure" is not the honest shape: it hides that the ladder never reached
    the remaining stages, which is the part a submitter needs to know.
    """
    if isinstance(stopped_at, int) and isinstance(total, int):
        return f"{stopped_at} of {total}"
    return NOT_DETERMINED


# --------------------------------------------------------------------------- #
# Command construction
# --------------------------------------------------------------------------- #
def build_run_command(image: str, layout: Path, rundir: Path,
                      top: str, die_id: str, slot: str, cob: bool,
                      threads: str = "1", workers: str = "max",
                      docker_bin: str = "docker") -> List[str]:
    """argv for the graded precheck run.

    Every element is its own argv token, so no path can split the command.  The
    layout is bind-mounted as a SINGLE read-only file rather than by its parent
    directory, so nothing beside the artefact under test is even visible to the
    container.

    `--network=none` and `--pull=never` are written here, unconditionally, and
    are not parameters.  Neither is the step selection: the container's own
    `--from` / `--to` / `--skip` are deliberately NOT plumbed through, because
    exposing them would hand a caller a supported way to make the gate pass by
    running fewer of the shuttle's checks.
    """
    layout = layout.resolve()
    rundir = rundir.resolve()
    in_container_layout = f"{_CONTAINER_INPUT_DIR}/{layout.name}"
    cmd = [
        docker_bin, "run", "--rm",
        "--network=none", "--pull=never",
        "-v", f"{layout}:{in_container_layout}:ro",
        "-v", f"{rundir}:{_CONTAINER_RUNDIR}",
        image,
        "python3", _CONTAINER_PRECHECK,
        "--input", in_container_layout,
        "--dir", _CONTAINER_RUNDIR,
        "--run-tag", RUN_TAG,
        "--slot", slot,
        "--id", die_id,
        "--threads", str(threads),
        "--workers", str(workers),
    ]
    if top:
        cmd += ["--top", top]
    if cob:
        cmd += ["--cob"]
    return cmd


def default_rundir(layout: Path) -> Path:
    """A fresh, uniquely named directory beside the artefact under test.

    Unique per invocation because the run's evidence is read back by path: a
    directory shared with an earlier run could hand this one the earlier one's
    step directories, which is a way to read a stale PASS off a run that never
    happened.
    """
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return layout.resolve().parent / "tapeout_readiness_results" / stamp


# --------------------------------------------------------------------------- #
# The gate
# --------------------------------------------------------------------------- #
def evaluate(
    layout: Path,
    top: str = "",
    slot: str = "1x1",
    cob: bool = False,
    die_id: str = "FFFFFFFF",
    image: str = PINNED_IMAGE,
    rundir: Optional[Path] = None,
    timeout: Optional[float] = 7200.0,
    allow_pull: bool = False,
    threads: str = "1",
    workers: str = "max",
    docker_bin: str = "docker",
    runner: Optional[Runner] = None,
    which: Optional[Callable[[str], Optional[str]]] = None,
) -> ReadinessReport:
    """Run the shuttle's precheck on `layout` and return its verdict.

    The container's EXIT CODE is the verdict.  This function never inspects the
    layout, never evaluates a layout rule, and never converts a refusal into
    anything but a refusal.  Its only judgement is the one §4.05 requires: an
    exit that produced no evidence is not a result.
    """
    run = runner or default_runner
    which_fn = which or shutil.which
    layout = Path(layout)
    notes: List[str] = []

    def _blocked(reason: str, detail: str = "",
                 rc: Optional[int] = None,
                 cmd: Optional[List[str]] = None,
                 sha: str = "",
                 image_id: Optional[str] = None,
                 out: str = "", err: str = "",
                 rr: Optional[Path] = None) -> ReadinessReport:
        return ReadinessReport(
            layout=str(layout), layout_sha256=sha, image=image,
            verdict=BLOCKED, blocked_reason=reason, blocked_detail=detail,
            image_id=image_id, docker_returncode=rc,
            slot=slot, cob=cob, top=top,
            rundir=str(rundir) if rundir else None,
            run_root=str(rr) if rr else None,
            command=cmd or [], stdout_tail=out[-8000:], stderr_tail=err[-8000:],
            notes=notes + [
                "BLOCKED is its own state and FAILS the gate: the precheck did "
                "not reach a verdict, which is NOT the same as finding no "
                "refusals, and must never be read as one."],
        )

    # (1) The pin, before anything else.  An unpinned reference is refused here
    #     rather than run, because a run under a moving tag produces a verdict
    #     nobody can reproduce — including a PASS.
    if not is_digest_pinned(image):
        return _blocked(
            B_IMAGE_NOT_DIGEST_PINNED,
            f"image reference {image!r} is not pinned by digest. This gate "
            "requires an immutable 'repo@sha256:<64 hex>' reference so a "
            "refusal can be reproduced; a tag such as ':main' can move under "
            "the same command and is refused.")

    # (2) The artefact under test.
    if not layout.is_file():
        return _blocked(B_LAYOUT_ABSENT, f"layout file does not exist: {layout}")
    sha = sha256_of(layout)

    # (3) Docker itself.
    if not which_fn(docker_bin):
        return _blocked(B_DOCKER_UNAVAILABLE,
                        f"{docker_bin!r} is not on PATH, so the shuttle's "
                        "precheck container cannot be started here.",
                        sha=sha)

    # (4) The pinned image, optionally fetched first.  The fetch is explicit and
    #     finishes before the graded run, which is always --network=none.
    image_id = probe_image(image, docker_bin, run)
    if image_id is None and allow_pull:
        if pull_image(image, docker_bin, run):
            image_id = probe_image(image, docker_bin, run)
    if image_id is None:
        return _blocked(
            B_IMAGE_ABSENT,
            f"the pinned precheck image is not present locally: {image}. "
            f"Fetch it with: {docker_bin} pull {image}",
            sha=sha)

    # (5) A run directory this invocation created, so the evidence read back
    #     cannot be an earlier run's.
    rundir = Path(rundir) if rundir is not None else default_rundir(layout)
    if rundir.exists() and any(rundir.iterdir()):
        return _blocked(B_RUNDIR_NOT_FRESH,
                        f"run directory is not empty: {rundir}. This gate reads "
                        "its verdict back out of the directory the run wrote, "
                        "so it refuses to share one with an earlier run.",
                        sha=sha, image_id=image_id)
    rundir.mkdir(parents=True, exist_ok=True)
    run_root = rundir / "runs" / RUN_TAG

    # (6) Ask the container for its own ladder.  Best effort by construction: a
    #     failure here costs the NAMES of the un-run stages, never the verdict.
    stages = parse_enumerated_stages(
        run(build_enumerate_command(image, cob, docker_bin), 600.0)[1])
    if stages is None:
        notes.append(
            "the container's own step list could not be enumerated, so the "
            "stage denominator and the names of stages that never ran are "
            "NOT DETERMINED (they are not guessed).")

    # (7) The graded run.  Its exit code is the verdict.
    cmd = build_run_command(image, layout, rundir, top, die_id, slot, cob,
                            threads=threads, workers=workers,
                            docker_bin=docker_bin)
    rc, out, err = run(cmd, timeout)

    # (8) What the run itself recorded.
    ran = observed_steps(run_root)
    ran_slugs = [slug for _, slug in ran]
    stopped_idx: Any = ran[-1][0] if ran else NOT_DETERMINED

    total: Any = NOT_DETERMINED
    total_source = NOT_DETERMINED
    enum_total = len(stages) if stages else None
    prog_total = progress_denominator(out)
    if enum_total is not None and prog_total is not None:
        if enum_total == prog_total:
            total, total_source = enum_total, "container-flow+run-progress"
        else:
            notes.append(
                f"the enumerated ladder has {enum_total} steps but the run's "
                f"own progress reported {prog_total}; the two disagree, so the "
                "denominator is NOT DETERMINED rather than one of them chosen.")
    elif enum_total is not None:
        total, total_source = enum_total, "container-flow"
    elif prog_total is not None:
        total, total_source = prog_total, "run-progress"

    # Names of the stages that never ran — emitted only when the enumeration is
    # corroborated as describing THIS run.  An enumeration that does not line up
    # with the directories on disk is describing a different ladder, and naming
    # stages out of it would be inventing the most load-bearing part of the
    # report.
    never_ran: Any = NOT_DETERMINED
    stage_names: List[str] = []
    if stages and isinstance(total, int) and isinstance(stopped_idx, int):
        expected_prefix = [step_dir_slug(s["id"]) for s in stages[:len(ran)]]
        if expected_prefix == ran_slugs and 0 < stopped_idx <= len(stages):
            stage_names = [s["name"] for s in stages]
            never_ran = [s["name"] for s in stages[stopped_idx:]]
        else:
            notes.append(
                "the enumerated ladder does not match the step directories this "
                "run wrote, so the stages that never ran are NOT DETERMINED.")

    ran_names = (stage_names[:len(ran)] if stage_names else ran_slugs)
    summary = _stage_summary(stopped_idx, total)
    refusal = read_refusal_text(run_root)

    def _finish(verdict: str) -> ReadinessReport:
        return ReadinessReport(
            layout=str(layout), layout_sha256=sha, image=image,
            verdict=verdict, image_id=image_id, docker_returncode=rc,
            slot=slot, cob=cob, top=top,
            rundir=str(rundir), run_root=str(run_root),
            stages_total=total, stages_total_source=total_source,
            stages_ran=ran_names,
            stopped_at_index=stopped_idx,
            stopped_at_stage=(stage_names[stopped_idx - 1]
                              if stage_names and isinstance(stopped_idx, int)
                              and 0 < stopped_idx <= len(stage_names)
                              else (ran_slugs[-1] if ran_slugs
                                    else NOT_DETERMINED)),
            stages_never_ran=never_ran, stage_summary=summary,
            refusal_text=refusal, command=cmd,
            stdout_tail=out[-8000:], stderr_tail=err[-8000:], notes=notes)

    # (9) The verdict.
    #
    # A timeout is not a refusal: the ladder did not reach one.  It is BLOCKED
    # even when partial evidence exists, because the honest statement is "we do
    # not know", not "it refused at the stage the clock happened to stop on".
    if rc == _TIMEOUT_RC:
        return _blocked(B_TIMEOUT,
                        f"the precheck did not finish within {timeout}s; it "
                        "reached no verdict, so neither did this gate.",
                        rc=rc, cmd=cmd, sha=sha, image_id=image_id,
                        out=out, err=err, rr=run_root)

    # docker's own "your command never ran" codes.  Distinguished from the
    # precheck's exit codes because a container that failed to START has told us
    # nothing about the artefact.
    if rc in _DOCKER_START_FAILURE_RCS and not ran:
        return _blocked(B_CONTAINER_FAILED_TO_START,
                        f"docker exited {rc} without running the precheck "
                        f"(no step directory was written under {run_root}).",
                        rc=rc, cmd=cmd, sha=sha, image_id=image_id,
                        out=out, err=err, rr=run_root)

    # No evidence at all.  This covers BOTH directions and both are blocked:
    # a non-zero exit that wrote nothing (the container died before the ladder
    # started — the plugin's own EDA image does exactly this when the entrypoint
    # cannot resolve a home directory, and it exits 1, the same code a refusal
    # uses), and a ZERO exit that wrote nothing, which would otherwise be the
    # single most dangerous fabricated pass this gate could emit.
    if not ran:
        return _blocked(B_NO_EVIDENCE,
                        f"the precheck exited {rc} but wrote no step directory "
                        f"under {run_root}; there is no evidence a ladder ran, "
                        "so there is no verdict to report.",
                        rc=rc, cmd=cmd, sha=sha, image_id=image_id,
                        out=out, err=err, rr=run_root)

    if rc != 0:
        return _finish(REFUSED)

    # A clean exit whose own artefacts show the ladder stopping early is a
    # contradiction, and it resolves AWAY from PASS.  This can only ever turn a
    # pass into a non-pass; it can never turn a refusal into a pass.
    if isinstance(total, int) and isinstance(stopped_idx, int) \
            and stopped_idx < total:
        rep = _blocked(
            B_EVIDENCE_CONTRADICTS_EXIT,
            f"the precheck exited 0, but its own run directory records only "
            f"{stopped_idx} of {total} stages. A clean exit over an incomplete "
            "ladder is not evidence of a clean ladder.",
            rc=rc, cmd=cmd, sha=sha, image_id=image_id,
            out=out, err=err, rr=run_root)
        rep.stages_total = total
        rep.stages_total_source = total_source
        rep.stages_ran = ran_names
        rep.stopped_at_index = stopped_idx
        rep.stages_never_ran = never_ran
        rep.stage_summary = summary
        return rep

    return _finish(PASS)


# --------------------------------------------------------------------------- #
# Human-readable rendering
# --------------------------------------------------------------------------- #
def report_to_text(rep: ReadinessReport) -> str:
    """The refusal as a submitter should read it — stage accounting first."""
    out: List[str] = []
    out.append(f"tapeout_readiness_check: {rep.verdict}")
    out.append(f"  layout      : {rep.layout}")
    out.append(f"  layout sha256: {rep.layout_sha256 or NOT_DETERMINED}")
    out.append(f"  image (pinned by digest): {rep.image}")
    out.append(f"  network     : {rep.network}")
    if rep.verdict == BLOCKED:
        out.append(f"  BLOCKED     : {rep.blocked_reason}")
        out.append(f"  detail      : {rep.blocked_detail}")
        out.append("  NOTE        : this is NOT 'no refusals found'. The "
                   "shuttle's precheck did not reach a verdict.")
    out.append(f"  stages      : {rep.stage_summary}")
    if isinstance(rep.stopped_at_stage, str) \
            and rep.stopped_at_stage != NOT_DETERMINED:
        # A ladder that finished did not STOP anywhere. Saying it stopped at its
        # own final stage reads as a halt, and a submitter skimming a wall of
        # reports should not have to check the verdict to tell the two apart.
        label = "last stage  " if rep.verdict == PASS else "stopped at  "
        out.append(f"  {label}: stage {rep.stopped_at_index} "
                   f"— {rep.stopped_at_stage}")
    if isinstance(rep.stages_never_ran, list):
        if rep.stages_never_ran:
            out.append(f"  NEVER RAN   : {len(rep.stages_never_ran)} stage(s) — "
                       + ", ".join(rep.stages_never_ran))
        else:
            out.append("  NEVER RAN   : none — every stage of the ladder ran")
    else:
        out.append(f"  NEVER RAN   : {NOT_DETERMINED}")
    if rep.refusal_text:
        out.append("  refusal (verbatim, from the shuttle's own error.log):")
        for line in rep.refusal_text.splitlines():
            out.append(f"    | {line}")
    for n in rep.notes:
        out.append(f"  note        : {n}")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Run the live open-MPW shuttle's own precheck container against the "
            "artefact we are about to publish and FAIL on its exit code. The "
            "container is the authority; none of its rules are reimplemented "
            "here. Image absent / container failed to start is its own BLOCKED "
            "state and fails the gate — never 'no refusals found'."))
    p.add_argument("--layout", type=Path, required=True,
                   help="The layout to submit (.gds, .gds.gz or .oas).")
    p.add_argument("--top", default="",
                   help="Top-level cell name (default: the layout's basename).")
    p.add_argument("--slot", default="1x1",
                   help="Submission slot size (default 1x1).")
    p.add_argument("--cob", action="store_true",
                   help="Chip-on-Board packaging (adds the pad-mask stage).")
    p.add_argument("--id", dest="die_id", default="FFFFFFFF",
                   help="Die ID to stamp into the ID cells.")
    p.add_argument("--image", default=PINNED_IMAGE,
                   help="Precheck image. MUST be digest-pinned; a tag is "
                        "refused (BLOCKED), because a moving tag makes the "
                        "verdict unreproducible.")
    p.add_argument("--rundir", type=Path, default=None,
                   help="Directory to run in (must be empty/absent). Default: "
                        "<layout dir>/tapeout_readiness_results/<timestamp>.")
    p.add_argument("--timeout", type=float, default=7200.0,
                   help="Wall-clock budget in seconds (default 7200). A "
                        "timeout is BLOCKED, never a refusal and never a pass.")
    p.add_argument("--pull", action="store_true",
                   help="Explicitly fetch the pinned image first. This is the "
                        "only network access; the graded run is --network=none "
                        "either way.")
    p.add_argument("--threads", default="1", help="Precheck DRC threads.")
    p.add_argument("--workers", default="max", help="Precheck DRC workers.")
    p.add_argument("--docker-bin", default="docker", help="Container engine.")
    p.add_argument("--out-json", type=Path,
                   help="Also write the verdict JSON here.")
    p.add_argument("--json", action="store_true",
                   help="Print JSON instead of the human report.")
    args = p.parse_args(argv)

    rep = evaluate(
        layout=args.layout, top=args.top, slot=args.slot, cob=args.cob,
        die_id=args.die_id, image=args.image, rundir=args.rundir,
        timeout=args.timeout, allow_pull=args.pull,
        threads=args.threads, workers=args.workers,
        docker_bin=args.docker_bin)

    payload = rep.as_dict()
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2) if args.json else report_to_text(rep))
    return 0 if rep.passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
