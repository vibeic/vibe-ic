#!/usr/bin/env python3
"""handoff_bundle_check.py — the COMPLETENESS-CONTRACT gate (Q3).

The unit of contribution for a Field deep-resolution handoff is the WHOLE
verified solution — not a surface symptom that Core then round-trips r2..r6
as deeper layers keep surfacing. Today Field hands over the top symptom and
Core re-discovers every layer underneath it; this gate makes the bundle
ADMIT only when ALL of the following hold, else INCOMPLETE naming the gap:

  (1) ROOT-CAUSE per LAYER. A root-cause statement for EVERY layer peeled
      (>= 1 layer), each naming the station/program that produced or
      surfaced the defect. A handoff that pins only the surface symptom and
      leaves the deeper layers un-stated is INCOMPLETE.

  (2) CANDIDATE PATCH. `candidate.patch` exists, is non-empty, and applies
      clean (`git apply --check`). A patch that no longer applies, or is
      empty, is INCOMPLETE — the receiver cannot land it.

  (3) TWO-DEPTH REGRESSION. A SURFACE regression test (fails before / passes
      after) AND a DEEPER-LAYER regression test pinning the NEXT layer down,
      so a future SHALLOW fix can't silently reopen the issue. Satisfied by
      >= 2 DISTINCT test files OR >= 2 test functions tied to DISTINCT layers.
      A single-layer test set is INCOMPLETE — it is exactly the round-trip
      this gate exists to stop.

  (4) CLEAN-ROOM PROOF. A transcript showing the benchmark re-ran with 0
      residual across 2 INDEPENDENT clean-room rounds. One round can hide an
      order-dependence; the clean-room-binding-directive floor is TWO. A
      single round, or any round still showing residual, is INCOMPLETE.

  (5) ROOT-CAUSE (not surface) verdict. `fix_surface_classify.py` (COMPOSED,
      not re-implemented) must classify the candidate patch as a PRODUCER
      change — i.e. it alters the real artifact surface (route / floorplan /
      streamout / geometry / RTL / netlist) where the defect actually lives
      — NOT a CONSUMER_ONLY change (a checker / classifier / verdict-message
      edit that only re-interprets the symptom). A CONSUMER_ONLY candidate is
      a surface fix; a MIXED candidate could not be proven a root-cause fix.
      Both are INCOMPLETE (fail-closed). The PRODUCER verdict is what makes
      the contribution a DEEP resolution rather than a re-label of the
      symptom.

  (6) chip-AGNOSTIC candidate. `source_chip_agnostic_check.scan` (COMPOSED)
      must come back clean on the files the candidate patches — a deep fix
      must not smuggle a chip / vendor / SKU literal into plugin source.

  (7) VERSION-LESS candidate. The candidate.patch must NOT bump a version
      file (`.claude-plugin/{plugin,marketplace}.json`). Owner directive
      2026-06-17: "field dont need to have version to issue pr. all versions
      are given by gatekeeper" — two in-flight bundles that each self-bumped
      would COLLIDE; only the serialized gatekeeper assigns the next
      strictly-monotonic version at merge (gatekeeper_assign_version.py). A
      bundle whose patch touches a version file is INCOMPLETE.

§4.05 (no-leak): this gate is FAIL-CLOSED. An INCOMPLETE bundle must NEVER
ADMIT. A missing clean-room round, a single-layer test, a non-applying
patch, a CONSUMER_ONLY/MIXED surface-classify verdict, a chip-specific
literal, or a version-file bump each independently BLOCK. ADMIT requires ALL
SEVEN green. Nothing is waived; "missing item" never degrades to a warning.

chip-AGNOSTIC: this program hardcodes no chip / vendor / benchmark name; it
operates purely on the bundle's structural contract.

──────────────────────────────────────────────────────────────────────────
BUNDLE SCHEMA  (a directory, OR a manifest pointed at by --manifest)
──────────────────────────────────────────────────────────────────────────
A handoff bundle is a directory:

    <bundle>/
      manifest.json              # the contract (schema below)
      candidate.patch            # the fix, a unified diff (default name)
      tests/                     # regression tests (>=2 files OR >=2 fns)
      clean_room/
        round1.log               # clean-room round 1 transcript
        round2.log               # clean-room round 2 transcript

manifest.json (all paths are bundle-relative; every key but `bundle_version`
is REQUIRED for ADMIT):

    {
      "bundle_version": 1,

      // (1) one entry PER peeled layer; >= 1 required; each names the
      //     station/program that produced or surfaced that layer.
      "root_causes": [
        {"layer": "surface",
         "statement": "<root-cause prose>",
         "station": "phase3.step_route",          // pipeline station
         "program": "detailed_route"},            // emitter/checker program
        {"layer": "deeper-1",
         "statement": "...",
         "station": "phase3.streamout",
         "program": "_gds_grid_snap"}
      ],

      // (2) candidate patch (default "candidate.patch" if omitted)
      "candidate": "candidate.patch",

      // (3) two-depth regression: surface + next-layer pin. EITHER give an
      //     explicit surface_test + deeper_layer_test pair, OR drop >= 2
      //     test files / >= 2 test functions tagged with distinct layers
      //     under tests/ and let the gate discover them.
      "surface_test":      {"file": "tests/test_surface.py",
                            "function": "test_symptom_before_after",
                            "layer": "surface"},
      "deeper_layer_test": {"file": "tests/test_deeper.py",
                            "function": "test_next_layer_pinned",
                            "layer": "deeper-1"},

      // (4) clean-room: two INDEPENDENT rounds, each 0 residual
      "clean_room": {"round1": "clean_room/round1.log",
                     "round2": "clean_room/round2.log"},

      // (6) repo the candidate's patched files live in, for the
      //     chip-AGNOSTIC scan + `git apply --check`. Defaults to the
      //     plugin root resolved from this program's location.
      "repo_root": "/abs/path/to/checkout"        // optional
    }

A clean-room round log ADMITs for check (4) when it shows BOTH an explicit
"clean-room" / independent-round marker AND a 0-residual PASS signal (e.g.
"0 residual", "residual: 0", "PASS"), and shows NO non-zero residual line.

CLI:
    handoff_bundle_check.py <bundle_dir> [--json OUT]
    handoff_bundle_check.py --manifest manifest.json [--json OUT]
    handoff_bundle_check.py <bundle_dir> --repo-root /path/to/checkout

There is NO `--bundle` flag. The bundle directory is the POSITIONAL argument.
`skills/field-agent-loop/SKILL.md` shipped `--bundle <bundle_dir>` at two call
sites; measured, argparse answered `unrecognized arguments: --bundle` with
rc=2, and the skill's own comment reads `exit !0 -> NOT admissible`, so a field
agent following the shipped instruction got a permanent false REFUSAL and never
a verdict. Both call sites are corrected; this paragraph exists so the next
edit does not re-introduce the flag from memory.

Exit codes:
    0  ADMIT       — all SEVEN contract items green
    1  INCOMPLETE  — at least one item missing (fail-closed; never ADMIT)
    2  usage / I/O error (bundle or manifest not found / unreadable)

──────────────────────────────────────────────────────────────────────────
WHAT THIS GATE IS NOT WIRED TO, AND THE MEASUREMENT THAT SAYS WHY
──────────────────────────────────────────────────────────────────────────
This gate is run by an AGENT following `skills/field-agent-loop/SKILL.md`
(and `docs/GATEKEEPER_CUTOVER_RUNBOOK.md` §6). It is deliberately NOT wired
into `flow/phase1_phase2_phase3.yaml`, `tools/ci/repo_hygiene_gates.sh`,
`tools/git-hooks/pre-push` or `tools/gatekeeper-land.sh`, and the reason is a
measurement rather than a preference:

  * ITS ARTEFACT CLASS DOES NOT EXIST IN-REPO. `origin/main` contains 0
    `candidate.patch` files and 0 `clean_room/` directories; no bundle path
    convention is declared anywhere. A `--changed-since`-scoped call on a
    push rail would therefore scan a path class nothing produces.
  * ITEM (5) REFUSES EVERY REAL CHANGE BODY MEASURED. Feeding the 200 most
    recent `origin/main` commits to `fix_surface_classify.classify_diff` as
    candidate bodies yields PRODUCER 0 · CONSUMER_ONLY 85 · MIXED 115. Since
    item (5) admits ONLY `PRODUCER`, 200 of 200 measured change bodies would
    be refused ADMIT. Item (5) is not wrong — it is stricter than the
    PRODUCER registry can currently recognise, and `fix_surface_classify`'s
    own docstring calls MIXED "the genuine judgment residual a human/agent
    must read", i.e. advisory, which this gate promotes to a refusal.

What would make an automated rail meaningful: a declared bundle path
convention AND a non-zero measured PRODUCER rate over real change bodies.
Until both exist, an automated wiring would either fire on nothing or refuse
everything, and both are worse than the agent-driven invocation it has.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
import _watchdog as _wd            # noqa: E402  progress supervision
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# COMPOSE the two existing programs (do NOT re-implement their logic). Both
# live alongside this file in programs/; the test conftest puts that dir on
# sys.path, and direct CLI use runs from programs/ too.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import fix_surface_classify as _fsc                 # noqa: E402
import source_chip_agnostic_check as _agnostic      # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402

# Bundle conventions (defaults; manifest may override the candidate name and
# clean-room log paths).
DEFAULT_CANDIDATE = "candidate.patch"
DEFAULT_CLEAN_ROOM = {"round1": "clean_room/round1.log",
                      "round2": "clean_room/round2.log"}

# A clean-room round must show an INDEPENDENT-round/clean-room marker ...
_CLEAN_ROOM_MARKER_RE = re.compile(
    r"clean[\s_-]?room|independent\s+round|round\s*[12]\b", re.IGNORECASE)
# ... AND a 0-residual PASS signal ...
_ZERO_RESIDUAL_RE = re.compile(
    r"\b0\s+residual\b|residual\s*[:=]\s*0\b|zero\s+residual\b", re.IGNORECASE)
_PASS_RE = re.compile(r"\bPASS\b|\bADMIT\b|all\s+pass", re.IGNORECASE)
# ... and must NOT show a NON-zero residual line (that would mean the round
# did not actually reach 0 — fail-closed).
_NONZERO_RESIDUAL_RE = re.compile(
    r"residual\s*[:=]\s*(?!0\b)([1-9]\d*)\b|\b([1-9]\d*)\s+residual\b",
    re.IGNORECASE)

# Map the COMPOSED fix_surface_classify verdict onto the root-cause contract:
#   PRODUCER      → the patch alters the real artifact surface where the
#                   defect lives → ROOT-CAUSE (deep) → check (5) passes.
#   CONSUMER_ONLY → checker / classifier / verdict-message only → SURFACE
#                   (re-label of the symptom) → BLOCK.
#   MIXED         → could not be PROVEN a root-cause fix → BLOCK (fail-closed;
#                   ambiguity never ADMITs).
_ROOT_CAUSE_VERDICT = "PRODUCER"

#: THE contract, in the order `evaluate()` checks it. Single source of truth:
#: the JSON report's `contract` field is rendered from this tuple and
#: `evaluate()` is asserted against it by `test_handoff_bundle_check`. The
#: report used to carry a hand-written list of SIX keys while `items` carried
#: seven — `version_less_candidate`, the owner directive that a field bundle
#: must not self-assign a version, was the one missing — so a consumer reading
#: `contract` to learn what the gate enforces was told one rule too few.
CONTRACT_ITEMS: Tuple[str, ...] = (
    "root_cause_per_layer",
    "candidate_applies_clean",
    "two_depth_regression",
    "clean_room_two_rounds",
    "root_cause_not_surface",
    "chip_agnostic_candidate",
    "version_less_candidate",
)


@dataclass
class Item:
    """One contract item's verdict."""
    key: str
    ok: bool
    detail: str


@dataclass
class Report:
    verdict: str = "INCOMPLETE"
    bundle: str = ""
    items: List[Item] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)

    def add(self, key: str, ok: bool, detail: str) -> None:
        self.items.append(Item(key=key, ok=ok, detail=detail))
        if not ok:
            self.missing.append(f"{key}: {detail}")


# ── manifest / bundle loading ───────────────────────────────────────────────

def _load_manifest(bundle_dir: Optional[Path],
                   manifest_path: Optional[Path]
                   ) -> Tuple[Optional[dict], Optional[Path], str]:
    """Return (manifest_dict, bundle_root, error). bundle_root is the dir all
    bundle-relative paths resolve against."""
    if manifest_path is not None:
        if not manifest_path.is_file():
            return None, None, f"manifest not found: {manifest_path}"
        try:
            man = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            return None, None, f"manifest unreadable/invalid JSON: {e}"
        # bundle root = the manifest's own directory
        return man, manifest_path.resolve().parent, ""
    assert bundle_dir is not None
    if not bundle_dir.is_dir():
        return None, None, f"bundle dir not found: {bundle_dir}"
    mpath = bundle_dir / "manifest.json"
    if not mpath.is_file():
        return None, None, f"manifest.json missing in bundle: {bundle_dir}"
    try:
        man = json.loads(mpath.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, None, f"manifest.json unreadable/invalid JSON: {e}"
    return man, bundle_dir.resolve(), ""


def _bp(bundle_root: Path, rel: Optional[str]) -> Optional[Path]:
    """Resolve a bundle-relative path; None stays None."""
    if not rel:
        return None
    p = Path(rel)
    return p if p.is_absolute() else (bundle_root / p)


# ── (1) root-cause per layer ────────────────────────────────────────────────

def check_root_causes(man: dict) -> Tuple[bool, str, List[str]]:
    rcs = man.get("root_causes")
    if not isinstance(rcs, list) or len(rcs) < 1:
        return (False,
                "no root_causes[] — need a root-cause statement for EVERY "
                "layer peeled (>= 1), each naming the station/program", [])
    layers: List[str] = []
    bad: List[str] = []
    for i, rc in enumerate(rcs):
        if not isinstance(rc, dict):
            bad.append(f"#{i} is not an object")
            continue
        layer = str(rc.get("layer", "")).strip()
        stmt = str(rc.get("statement", "")).strip()
        station = str(rc.get("station", "")).strip()
        program = str(rc.get("program", "")).strip()
        missing_fields = [k for k, v in
                          (("layer", layer), ("statement", stmt),
                           ("station", station), ("program", program))
                          if not v]
        if missing_fields:
            bad.append(f"layer '{layer or i}' missing "
                       f"{'/'.join(missing_fields)}")
            continue
        layers.append(layer)
    if bad:
        return (False,
                "incomplete root-cause entr(ies): " + "; ".join(bad),
                layers)
    return (True,
            f"{len(rcs)} layer(s) each with root-cause + station + program: "
            f"{', '.join(layers)}", layers)


# ── (2) candidate patch applies clean ───────────────────────────────────────

#: How long `git apply --check` may be COMPLETELY IDLE before it is called
#: wedged. Not a runtime bound: a check that is reading objects is working, and
#: on a large repository or a loaded host it may legitimately take longer than
#: any constant somebody picks.
_APPLY_STALL_GRACE_S = 60


def _git_apply_check(repo_root: Path, patch: Path) -> Tuple[bool, str]:
    argv = ["git", "-C", str(repo_root), "apply", "--check", str(patch)]
    try:
        # PROGRESS, NOT RUNTIME. The first attempt at this fix relabelled the
        # 60 s kill INCONCLUSIVE, which is the last-resort shape used as a first
        # resort: the check was still killed while it was working, and the field
        # agent whose bundle it rejected still lost the answer. The kill is the
        # defect. `run_host_supervised` reads CPU and I/O from /proc, so a check
        # that is doing anything runs to completion.
        res = _wd.run_host_supervised(argv, stall_grace_s=_APPLY_STALL_GRACE_S)
    except FileNotFoundError:
        return False, "git not available to run `git apply --check`"
    if res.outcome in ("stalled", "ceiling"):
        # A MEASURED finding, and about GIT rather than about the patch:
        # fail-closed (the bundle is not admitted) with the reason named.
        return False, (f"INCONCLUSIVE — `git apply --check` made no forward "
                       f"progress (no CPU, no I/O) for "
                       f"{_APPLY_STALL_GRACE_S}s and was stopped. git was "
                       f"wedged; that is not a finding that the patch "
                       f"conflicts. The bundle is NOT admitted, but this item "
                       f"was never judged. Re-run it.")
    out = _wd.completed_process(argv, res)
    if out.returncode == 0:
        return True, "applies clean"
    err = (out.stderr or out.stdout or "").strip().splitlines()
    return False, ("does not apply: " + (err[0] if err else "unknown error"))


def check_candidate(man: dict, bundle_root: Path, repo_root: Path
                    ) -> Tuple[bool, str, Optional[Path]]:
    rel = man.get("candidate", DEFAULT_CANDIDATE)
    patch = _bp(bundle_root, rel)
    if patch is None or not patch.is_file():
        return False, f"candidate patch missing: {rel}", None
    try:
        body = patch.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return False, f"candidate patch unreadable: {e}", patch
    if not body.strip():
        return False, "candidate patch is empty", patch
    if not re.search(r"^(?:diff --git |--- |\+\+\+ |@@ )", body, re.MULTILINE):
        return False, "candidate patch is not a unified diff", patch
    ok, detail = _git_apply_check(repo_root, patch)
    return ok, f"candidate.patch: {detail}", patch


# ── (7) version-less candidate (gatekeeper assigns ALL versions) ─────────────
# Owner directive 2026-06-17: "field dont need to have version to issue pr. all
# versions are given by gatekeeper". A field bundle's candidate.patch must NOT
# bump the version — two in-flight bundles that each self-bumped would COLLIDE;
# only the serialized gatekeeper, landing one at a time onto an advancing main,
# can assign a strictly-monotonic version (gatekeeper_assign_version.py). Detect
# any hunk touching a version file (the .claude-plugin/{plugin,marketplace}.json
# that the version gates read) and INCOMPLETE the bundle if found.
_VERSION_FILE_RE = re.compile(
    r"\.claude-plugin/(?:plugin|marketplace)\.json\s*$")


def _patched_paths(body: str) -> List[str]:
    """The file paths a unified diff touches, from its `+++ b/<path>` headers
    (strip the `b/` prefix; ignore /dev/null deletions' destination)."""
    paths: List[str] = []
    for ln in body.splitlines():
        if ln.startswith("+++ "):
            p = ln[4:].strip()
            if p in ("/dev/null",):
                continue
            if p.startswith("b/"):
                p = p[2:]
            # strip a trailing tab-timestamp some diff tools append
            p = p.split("\t", 1)[0].strip()
            paths.append(p)
    return paths


def check_version_less(patch: Optional[Path]) -> Tuple[bool, str]:
    if patch is None or not patch.is_file():
        return False, "no candidate.patch to scan for a version bump"
    try:
        body = patch.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return False, f"candidate patch unreadable: {e}"
    hits = [p for p in _patched_paths(body) if _VERSION_FILE_RE.search(p)]
    if hits:
        return False, ("candidate.patch bumps a version file (gatekeeper "
                       f"assigns ALL versions): {sorted(set(hits))}")
    return True, "version-less — gatekeeper assigns the version at merge"


# ── (3) two-depth (surface + deeper-layer) regression ───────────────────────

def _tests_under(bundle_root: Path) -> List[Path]:
    tdir = bundle_root / "tests"
    if not tdir.is_dir():
        return []
    return sorted(tdir.rglob("test_*.py"))


_LAYER_TAG_RE = re.compile(r"#\s*layer\s*[:=]\s*([A-Za-z0-9_\-]+)",
                           re.IGNORECASE)
_DEF_RE = re.compile(r"^\s*def\s+(test_\w+)\s*\(", re.MULTILINE)


def _functions_with_layers(path: Path) -> List[Tuple[str, Optional[str]]]:
    """Return [(test_function_name, layer_tag_or_None)] for a test file.
    A `# layer: <name>` comment on the def line (or the line above) tags
    a function with the design layer it pins."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    out: List[Tuple[str, Optional[str]]] = []
    for idx, ln in enumerate(lines):
        m = re.match(r"\s*def\s+(test_\w+)\s*\(", ln)
        if not m:
            continue
        # look on the def line and the line above for a layer tag
        tag = None
        for probe in (ln, lines[idx - 1] if idx > 0 else ""):
            tm = _LAYER_TAG_RE.search(probe)
            if tm:
                tag = tm.group(1)
                break
        out.append((m.group(1), tag))
    return out


def check_two_depth_regression(man: dict, bundle_root: Path
                               ) -> Tuple[bool, str]:
    # Path A: explicit surface_test + deeper_layer_test pair in the manifest.
    st = man.get("surface_test")
    dt = man.get("deeper_layer_test")
    if isinstance(st, dict) and isinstance(dt, dict):
        sf = _bp(bundle_root, st.get("file"))
        df = _bp(bundle_root, dt.get("file"))
        s_fn = str(st.get("function", "")).strip()
        d_fn = str(dt.get("function", "")).strip()
        s_layer = str(st.get("layer", "surface")).strip()
        d_layer = str(dt.get("layer", "deeper")).strip()
        problems: List[str] = []
        if sf is None or not sf.is_file():
            problems.append(f"surface_test file missing: {st.get('file')}")
        if df is None or not df.is_file():
            problems.append(f"deeper_layer_test file missing: {dt.get('file')}")
        if not s_fn:
            problems.append("surface_test.function not named")
        if not d_fn:
            problems.append("deeper_layer_test.function not named")
        # the two tests must pin DISTINCT layers (distinct file OR distinct fn)
        same_file = (sf is not None and df is not None and sf == df)
        if same_file and s_fn and d_fn and s_fn == d_fn:
            problems.append("surface and deeper tests are the SAME test "
                            "function — a single-layer test cannot pin the "
                            "next layer down")
        if s_layer and d_layer and s_layer == d_layer:
            problems.append(f"surface and deeper tests both tagged layer "
                            f"'{s_layer}' — they must pin DISTINCT layers")
        # verify the named functions actually exist in their files
        if sf is not None and sf.is_file() and s_fn:
            names = {n for n, _ in _functions_with_layers(sf)}
            if s_fn not in names:
                problems.append(f"surface_test.function '{s_fn}' not found in "
                                f"{st.get('file')}")
        if df is not None and df.is_file() and d_fn:
            names = {n for n, _ in _functions_with_layers(df)}
            if d_fn not in names:
                problems.append(f"deeper_layer_test.function '{d_fn}' not "
                                f"found in {dt.get('file')}")
        if problems:
            return False, "; ".join(problems)
        return (True,
                f"surface test '{s_fn}' (layer {s_layer}) + deeper-layer test "
                f"'{d_fn}' (layer {d_layer}) pin two distinct layers")

    # Path B: discover >= 2 test files OR >= 2 layer-tagged functions under
    # tests/, tied to DISTINCT layers.
    files = _tests_under(bundle_root)
    if not files:
        return (False,
                "no tests/ dir or no test_*.py, and no explicit "
                "surface_test/deeper_layer_test pair in the manifest")
    fn_layers: List[Tuple[Path, str, Optional[str]]] = []
    for f in files:
        for name, tag in _functions_with_layers(f):
            fn_layers.append((f, name, tag))
    if not fn_layers:
        return False, "tests/ has no test_* functions"
    distinct_layers = {tag for _, _, tag in fn_layers if tag}
    # >= 2 functions tagged with DISTINCT layers is the strongest signal ...
    if len(distinct_layers) >= 2:
        return (True,
                f"{len(fn_layers)} test fn(s) across {len(files)} file(s) "
                f"pin {len(distinct_layers)} distinct layers: "
                f"{', '.join(sorted(distinct_layers))}")
    # ... else >= 2 DISTINCT test FILES (each a separately-named depth) ...
    if len(files) >= 2:
        return (True,
                f"{len(files)} distinct test files (surface + deeper-layer "
                f"regression): {', '.join(f.name for f in files)}")
    # ... else >= 2 distinct functions in the one file count only if they are
    # layer-tagged with distinct layers (already handled above); a single
    # untagged file with multiple fns is NOT a two-DEPTH proof.
    return (False,
            "single test file with no distinct layer tags — need >= 2 test "
            "files OR >= 2 test functions tied to DISTINCT layers (a surface "
            "test AND a deeper-layer test). A single-layer test set lets a "
            "future shallow fix reopen the issue.")


# ── (4) clean-room: two independent 0-residual rounds ───────────────────────

def _round_ok(log: Optional[Path]) -> Tuple[bool, str]:
    if log is None or not log.is_file():
        return False, "log missing"
    try:
        txt = log.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return False, f"log unreadable: {e}"
    if _NONZERO_RESIDUAL_RE.search(txt):
        m = _NONZERO_RESIDUAL_RE.search(txt)
        n = m.group(1) or m.group(2)
        return False, f"shows NON-zero residual ({n}) — not a clean round"
    if not _CLEAN_ROOM_MARKER_RE.search(txt):
        return False, "no clean-room / independent-round marker in transcript"
    if not (_ZERO_RESIDUAL_RE.search(txt) and _PASS_RE.search(txt)):
        return False, "no '0 residual' + PASS signal"
    return True, "clean-room round, 0 residual, PASS"


def check_clean_room(man: dict, bundle_root: Path) -> Tuple[bool, str]:
    cr = man.get("clean_room") or {}
    r1 = _bp(bundle_root, cr.get("round1", DEFAULT_CLEAN_ROOM["round1"]))
    r2 = _bp(bundle_root, cr.get("round2", DEFAULT_CLEAN_ROOM["round2"]))
    ok1, d1 = _round_ok(r1)
    ok2, d2 = _round_ok(r2)
    if not ok1 and not ok2:
        return False, f"BOTH clean-room rounds bad — round1: {d1}; round2: {d2}"
    if not ok1:
        return False, (f"round1 bad ({d1}); one round can hide order-"
                       "dependence — TWO independent 0-residual rounds required")
    if not ok2:
        return False, (f"round2 bad ({d2}); one round can hide order-"
                       "dependence — TWO independent 0-residual rounds required")
    # the two rounds must be DISTINCT files (independent), not one log twice
    if r1 is not None and r2 is not None and r1.resolve() == r2.resolve():
        return False, ("round1 and round2 point at the SAME log — two "
                       "INDEPENDENT rounds required (one round can hide "
                       "order-dependence)")
    return True, "two independent clean-room rounds, each 0 residual + PASS"


# ── (5) ROOT-CAUSE (not surface) — COMPOSE fix_surface_classify ─────────────

def check_root_cause_verdict(patch: Optional[Path]) -> Tuple[bool, str]:
    if patch is None or not patch.is_file():
        return False, "no candidate patch to classify"
    try:
        diff_text = patch.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return False, f"patch unreadable: {e}"
    try:
        rep = _fsc.classify_diff(diff_text)
    except Exception as exc:      # defence-in-depth, see below
        # A COMPOSED program that dies is NOT a verdict about the bundle.
        # Before this guard the exception propagated out of `evaluate()`, out
        # of `main()`, and the interpreter exited 1 — the SAME rc as a
        # legitimate INCOMPLETE — with no `--json` report written at all, so a
        # caller branching on rc could not tell a crash from a judgment.
        # (Measured: a candidate patch that deletes one file and edits another
        # crashed `fix_surface_classify.classify_diff`; that specific defect is
        # fixed at its source, this guard is for the next one.) Fail-closed is
        # preserved — the item is NOT green — but the detail says INCONCLUSIVE
        # so nobody reads a crash as "the patch is a surface fix".
        return False, (f"INCONCLUSIVE — composed fix_surface_classify CRASHED "
                       f"({type(exc).__name__}: {exc}). A crash is not a "
                       f"verdict; the bundle is NOT admitted, but this item "
                       f"was never judged.")
    verdict = rep.get("verdict")
    if verdict == _ROOT_CAUSE_VERDICT:
        prods = rep.get("producers") or []
        return True, (f"fix_surface_classify = PRODUCER (root-cause) — alters "
                      f"artifact surface: {', '.join(prods) or 'producer hunk'}")
    if verdict == "CONSUMER_ONLY":
        return False, ("fix_surface_classify = CONSUMER_ONLY — the candidate "
                       "only re-interprets the symptom (checker / classifier / "
                       "verdict-message). That is a SURFACE fix, not a deep "
                       "root-cause resolution.")
    # MIXED (or any non-PRODUCER) → could not be PROVEN a root-cause fix.
    return False, (f"fix_surface_classify = {verdict} — could not be proven a "
                   "root-cause (PRODUCER) fix; fail-closed.")


# ── (6) chip-AGNOSTIC candidate — COMPOSE source_chip_agnostic_check ────────

def _patched_files(diff_text: str) -> List[str]:
    """Bundle-target file paths the patch writes (the `+++ b/...` side)."""
    out: List[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            p = line[4:].strip().split("\t", 1)[0]
            if p.startswith("b/"):
                p = p[2:]
            if p != "/dev/null":
                out.append(p)
    return out


def check_chip_agnostic(patch: Optional[Path], repo_root: Path
                        ) -> Tuple[bool, str]:
    if patch is None or not patch.is_file():
        return False, "no candidate patch to scan"
    try:
        diff_text = patch.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return False, f"patch unreadable: {e}"
    targets = _patched_files(diff_text)
    if not targets:
        return False, "patch touches no files (cannot scan)"
    # Scan the WHOLE plugin source tree with source_chip_agnostic_check, then
    # restrict findings to the files THIS candidate patches (we judge the
    # candidate, not pre-existing tree state).
    findings = _agnostic.scan(repo_root)  # [(rel_path, line, token), ...]
    target_set = {t.replace("\\", "/") for t in targets}

    def _hits(rel: str) -> bool:
        rel = rel.replace("\\", "/")
        # a finding rel-path is relative to plugin_root; match if it ends with
        # (or equals) any patched target path tail.
        for t in target_set:
            if rel == t or rel.endswith("/" + t) or t.endswith("/" + rel) \
                    or rel.endswith(t):
                return True
        return False

    bad = [(rel, ln, tok) for (rel, ln, tok) in findings if _hits(rel)]
    if bad:
        sample = "; ".join(f"{r}:{l} '{t}'" for r, l, t in bad[:5])
        return False, (f"candidate introduces chip/vendor/SKU token(s) in "
                       f"patched file(s): {sample}")
    return True, (f"chip-AGNOSTIC clean on {len(target_set)} patched file(s)")


# ── driver ──────────────────────────────────────────────────────────────────

def _resolve_repo_root(man: dict, bundle_root: Path) -> Path:
    """The checkout the candidate's patched files + chip-agnostic scan run
    against. Manifest `repo_root` wins; else the plugin root resolved from
    this program's location (…/programs/handoff_bundle_check.py → plugin
    root is two parents up)."""
    rr = man.get("repo_root")
    if rr:
        p = Path(rr)
        return p if p.is_absolute() else (bundle_root / p)
    # programs/ -> plugin root
    return _HERE.parent


def evaluate(bundle_dir: Optional[Path], manifest_path: Optional[Path],
             repo_root_override: Optional[Path] = None) -> Report:
    rep = Report()
    man, bundle_root, err = _load_manifest(bundle_dir, manifest_path)
    if man is None:
        rep.verdict = "ERROR"
        rep.bundle = str(bundle_dir or manifest_path or "")
        rep.add("manifest", False, err)
        return rep
    assert bundle_root is not None
    rep.bundle = str(bundle_root)
    repo_root = repo_root_override or _resolve_repo_root(man, bundle_root)

    # (1) root-cause per layer
    ok1, d1, _layers = check_root_causes(man)
    rep.add("root_cause_per_layer", ok1, d1)

    # (2) candidate patch applies clean
    ok2, d2, patch = check_candidate(man, bundle_root, repo_root)
    rep.add("candidate_applies_clean", ok2, d2)

    # (3) two-depth regression
    ok3, d3 = check_two_depth_regression(man, bundle_root)
    rep.add("two_depth_regression", ok3, d3)

    # (4) clean-room: two independent 0-residual rounds
    ok4, d4 = check_clean_room(man, bundle_root)
    rep.add("clean_room_two_rounds", ok4, d4)

    # (5) ROOT-CAUSE (not surface) verdict — composed
    ok5, d5 = check_root_cause_verdict(patch)
    rep.add("root_cause_not_surface", ok5, d5)

    # (6) chip-AGNOSTIC candidate — composed
    ok6, d6 = check_chip_agnostic(patch, repo_root)
    rep.add("chip_agnostic_candidate", ok6, d6)

    # (7) version-less candidate — the gatekeeper assigns ALL versions
    ok7, d7 = check_version_less(patch)
    rep.add("version_less_candidate", ok7, d7)

    # §4.05 fail-closed: ADMIT iff ALL items green; else INCOMPLETE.
    rep.verdict = "ADMIT" if all(it.ok for it in rep.items) else "INCOMPLETE"
    return rep


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Completeness-contract gate for a Field deep-resolution "
                    "handoff bundle (Q3). ADMIT iff all SEVEN items green; "
                    "else INCOMPLETE naming the gap (fail-closed).",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bundle_dir", nargs="?",
                    help="handoff bundle directory (contains manifest.json)")
    ap.add_argument("--manifest", help="path to a manifest.json directly "
                    "(its directory is the bundle root)")
    ap.add_argument("--repo-root", help="checkout the candidate's patched "
                    "files apply against / are scanned in (overrides the "
                    "manifest's repo_root)")
    ap.add_argument("--json", help="write the JSON report to this path")
    args = ap.parse_args(argv)

    if not args.bundle_dir and not args.manifest:
        ap.error("need a <bundle_dir> or --manifest")
        return 2

    bundle_dir = Path(args.bundle_dir) if args.bundle_dir else None
    manifest_path = Path(args.manifest) if args.manifest else None
    repo_override = Path(args.repo_root) if args.repo_root else None

    rep = evaluate(bundle_dir, manifest_path, repo_override)

    report = {
        "gate": "handoff_bundle_check",
        "verdict": rep.verdict,
        "bundle": rep.bundle,
        "items": [asdict(it) for it in rep.items],
        "missing": rep.missing,
        "contract": list(CONTRACT_ITEMS),
    }
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")

    if rep.verdict == "ERROR":
        print(f"ERROR: {rep.missing[0] if rep.missing else 'bundle error'}",
              file=sys.stderr)
        return 2
    if rep.verdict == "ADMIT":
        print(f"ADMIT: handoff bundle is the WHOLE verified solution — all "
              f"{len(CONTRACT_ITEMS)} contract items green ({rep.bundle})")
        for it in rep.items:
            print(f"  [ok] {it.key}: {it.detail}")
        return 0
    print(f"INCOMPLETE: handoff bundle does NOT ADMIT (fail-closed) — "
          f"{len(rep.missing)} gap(s):", file=sys.stderr)
    for it in rep.items:
        mark = "ok" if it.ok else "MISSING"
        stream = sys.stdout if it.ok else sys.stderr
        print(f"  [{mark}] {it.key}: {it.detail}", file=stream)
    return 1


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(main))
