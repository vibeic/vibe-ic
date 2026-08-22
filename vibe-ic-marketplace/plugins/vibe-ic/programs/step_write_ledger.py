#!/usr/bin/env python3
"""step_write_ledger.py — record what a run ACTUALLY WROTE, then residual it
against what the flow DECLARED.

WHY THIS EXISTS
---------------
`step_output_collector.materialize()` builds `<project>/steps/` entirely from
each step's `required_outputs` (via flow_dashboard_data._resolve_spec). Every
entry in that tree is therefore a RESTATEMENT of the declaration: it cannot
witness anything the declaration does not already claim, and anything that
reads it to CHECK required_outputs is reading a cache of its own answer.

    grep -ciE 'created|mtime|provenance|written_by' step_output_collector.py  ->  0

This module records the other half — the FILES THIS RUN ACTUALLY PRODUCED,
observed from the filesystem, and the tool invocations that were witnessed
producing them — and then emits the RESIDUAL between observation and
declaration:

    actually written, never declared  ->  D7 candidate (required_outputs incomplete)
    declared, never written           ->  D3 finding, ATTRIBUTED TO THE STEP
    written with no witnessed tool    ->  D5 candidate (unexpected producer)

CAPTURE DESIGN, AND WHY
-----------------------
1. ONE post-hoc `os.walk` + `lstat` over the project tree. Not a per-step
   before/after snapshot pair.

   * It SURVIVES A CONTAINER MOUNT. A step that shells into docker writes
     through a bind mount; the bind mount shares the host inode, so size and
     mtime land on the host filesystem and a host-side lstat sees them. A
     capture that hooked the writing PROCESS would see nothing for those
     steps — the process is in another namespace.
   * It is CHEAP and bounded: one walk for the whole run, not 2N walks.
     MEASURED (see the module docstring's COST section below).
   * It cannot be defeated by a step that writes a file the declaration never
     mentions, which is the entire D7 direction.

2. `lstat`, NEVER `stat`. A dangling symlink must be *seen*, not followed into
   nonexistence and dropped. `Path.glob` yields dangling symlinks and
   `Path.exists()` then silently rejects them; classifying with lstat is what
   lets this module say "dangling_symlink" instead of either "missing" or,
   worse, "produced".

3. NOTHING here is `produced=True` unless it is a regular file with size > 0.
   A 0-byte file is `kind="empty_file", produced=False, reason="zero_byte"`.
   A broken link is `kind="dangling_symlink", produced=False`. A resolvable
   symlink is `kind="symlink", produced=False, reason="symlink_alias"` — an
   alias is not a write of content. All three are RECORDED (they are evidence
   about the run) and none of them counts as an artefact.

4. Producer attribution comes from the run's OWN `provenance.jsonl` invocation
   windows [timestamp, timestamp+duration], matched against each file's mtime.
   See the ATTRIBUTION HONESTY section — this is inference, not process truth,
   and the module says so in every record it emits.

WHAT THE RUN WINDOW IS, AND WHEN IT IS UNKNOWN
----------------------------------------------
"This run wrote it" needs a t0. Resolved in this order:
  1. `steps/.write_ledger_t0.json` — an explicit marker (one tiny write at run
     start). Most precise; requires the runner to drop it.
  2. DERIVED: for each orchestrator summary present
     (`reports/orchestrator/*_one_shot.json`, `reports/phase1_one_shot.json`),
     `t0 = mtime(summary) - duration_s`. The earliest such value wins. This
     needs NO instrumentation and works on run directories that already exist,
     including published ones.
  3. None available -> `t0_source="none"`, every `in_run_window` is null, and
     the D7 direction is reported as UNDETERMINED rather than guessed. A run
     whose age cannot be established does not get a fabricated answer.

ATTRIBUTION HONESTY — WHAT CAN AND CANNOT BE ATTRIBUTED
-------------------------------------------------------
CAN:
  * that a write happened, its size, its mtime, and its kind — for every step,
    including container steps (bind mounts share inodes).
  * WHICH LOGGED TOOL INVOCATION was running when the write landed, when
    `provenance.jsonl` has a record whose [start, end] window contains the
    file's mtime and no other record's window does.
  * that a write landed inside NO logged invocation window at all — the
    "unwitnessed write" signal, which is the original failure class the
    provenance logger was built for ("agent writes file, gate passes").

CANNOT:
  * the writing PROCESS. Nothing here reads /proc, ptrace, fanotify or a
    container's PID namespace. A step that shells out to a container tool is
    attributable only by TIME WINDOW; the identity of the binary inside the
    container is taken from the provenance record's own `tool` field, which
    is the wrapper's claim, not an observation of the container.
  * a unique producer when invocation windows OVERLAP. Provenance timestamps
    are second-granularity ISO strings; concurrent or back-to-back tools
    produce ambiguous windows. Those records get
    `producer_confidence="ambiguous"` and a candidate list, never a single
    name.
  * ANYTHING time-derived, on a tree whose mtimes have been flattened by a
    copy or a git checkout. `mtime_fidelity()` detects that and WITHHOLDS the
    run window, the D7 residual and all window attribution — see its docstring
    for the measured separation between live runs and copies. The published
    benchmark cells are git working trees and fall on the withheld side.
  * whether an observed tool is the tool the step was SUPPOSED to use. The
    flow YAML declares `programs:` (plugin python module names) and
    `mcp_tools:` (MCP tool names); provenance records EDA BINARIES
    (yosys/openroad/klayout/magic/netgen/sta). These are two different
    vocabularies and this repo contains no mapping between them. Inventing
    one to manufacture a D5 verdict would be the exact defect this repo keeps
    finding, so it is NOT done: `observed_producers` is reported per step as
    raw material, and the only D5 CANDIDATE emitted is the one that needs no
    mapping — a declared output written with no witnessed tool at all.

COST — MEASURED, not estimated
------------------------------
`build()` end-to-end (walk + glob resolution + residual), best of 3, on real
run directories:

Run directories are named the way the measurer's shell would write them —
home-relative — because they are local scratch runs on the machine the numbers
were taken on, not paths this plugin ships, resolves or expects to exist.

    directory                          files    build()   of which walk
    $HOME/_sky130A_r3_run                455     211 ms         ~45 ms
    $HOME/_r6_sky130A/run                482     306 ms         ~50 ms
    published spm v1.5.66_gf180mcuD      216     179 ms         ~15 ms
    $HOME/_nXX_internal/runXX          12007     434 ms        ~250 ms

`emit()` (build + JSON write + per-step slices) on the 470 MB / 12k-file
that run: 492-508 ms across three runs. That run's own
`reports/orchestrator/vibe_ic_one_shot.json` records duration_s = 344.1, and a
full backend run is measured in hours — so the ledger costs well under 0.2% of
the smallest run it was measured against, once, at the end.

No file CONTENT is read: no hashing, no open(). Deliberate — hashing 470 MB
would cost seconds and buy nothing this module claims. The one place a hash
WOULD matter (does the file still match what provenance recorded?) is answered
for free in the cases that matter, via _EMPTY_SHA: a 0-byte or dangling path
cannot match a real recorded digest, and that is decidable from lstat.

NEVER FAILS A RUN
-----------------
`emit()` catches everything and returns a result dict with `ok=False` plus the
reason. `materialize()`'s caller is already best-effort; this adds no new way
for bookkeeping to kill a run. A ledger that cannot be written is reported as
absent, never raised.

chip-AGNOSTIC: derives step identity from the flow YAML and everything else
from the project's own filesystem and its own provenance log.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import json
import os
import re
import stat as _stat
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

SCHEMA = "vibe-ic/write-ledger/1"

# Directories never walked. `steps/` is the collector's own VIEW (symlinks to
# declared outputs) — walking it would let the declaration re-enter the
# observation and re-create the circularity this module exists to break.
_SKIP_DIRS = {"steps", ".git", "__pycache__", ".pytest_cache", "node_modules",
              ".mypy_cache", ".ruff_cache"}

# Ledger artefacts are excluded from the D7 residual: a ledger reporting
# itself as an undeclared write is noise.
_SELF_PATHS = {"reports/write_ledger.json", "reports/write_ledger.md"}

# D7 asks "written but never DECLARED AS AN OUTPUT". The flow's own path
# convention puts a run's INPUTS under these prefixes; they are materialised
# (copied in) during the run window, so without this they would be reported as
# undeclared outputs — a false D7. This is a narrow, path-convention-based
# exclusion from a REPORT, not a relaxation of any gate, and it is echoed into
# the emitted ledger under capture.d7_input_prefixes so a reader sees it.
_D7_INPUT_PREFIXES = ("input/", "input_doc/", "input_prompt/",
                      "phase1/input_doc/", "phase1/input_prompt/")

_OR_RE = re.compile(r"\s+OR\s+")

# How much slack to add to each side of a provenance invocation window.
# Provenance timestamps are formatted "%Y-%m-%dT%H:%M:%SZ" — truncated to the
# second — so a write at t+0.4 s can carry an mtime that reads as BEFORE a
# start stamp that truncated down. 2 s covers truncation on both ends without
# swallowing an adjacent invocation whole.
_WINDOW_SLACK_S = 2.0

_MAX_LISTED = 4000            # cap on any one emitted list; counts stay exact

# sha256 of zero bytes. Lets the ledger catch "provenance recorded a real
# digest for this path, but the path is now empty / dangling" WITHOUT reading
# any file content — the contradiction is decidable from lstat alone.
_EMPTY_SHA = ("sha256:e3b0c44298fc1c149afbf4c8996fb924"
              "27ae41e4649b934ca495991b7852b855")


# --------------------------------------------------------------------------- #
# Observation: the tree walk
# --------------------------------------------------------------------------- #
def _classify(path: str, st: os.stat_result) -> Tuple[str, bool, str, Optional[str]]:
    """(kind, produced, reason, link_target) from an LSTAT result.

    `produced` is True for exactly one shape: a regular file with size > 0.
    Everything else is recorded faithfully and counted as NOT an artefact —
    that distinction is the whole point of this module.
    """
    mode = st.st_mode
    if _stat.S_ISLNK(mode):
        try:
            target = os.readlink(path)
        except OSError:
            target = None
        # os.path.exists() FOLLOWS the link: False here means the link dangles.
        if os.path.exists(path):
            return "symlink", False, "symlink_alias", target
        return "dangling_symlink", False, "dangling_symlink", target
    if _stat.S_ISREG(mode):
        if st.st_size == 0:
            return "empty_file", False, "zero_byte", None
        return "file", True, "", None
    if _stat.S_ISDIR(mode):
        return "dir", False, "directory", None
    return "other", False, "not_a_regular_file", None


def snapshot(project: Path, skip_dirs: Iterable[str] = ()) -> Dict[str, Any]:
    """One lstat walk of the project tree. Never raises: an unreadable subtree
    is skipped and counted, not propagated."""
    project = Path(project)
    skip = set(_SKIP_DIRS) | set(skip_dirs)
    entries: Dict[str, Dict[str, Any]] = {}
    walked = 0
    errors = 0
    t0 = time.perf_counter()
    for root, dirs, files in os.walk(str(project), topdown=True, onerror=lambda e: None):
        dirs[:] = [d for d in dirs if d not in skip]
        for name in files + dirs:
            full = os.path.join(root, name)
            walked += 1
            try:
                st = os.lstat(full)
            except OSError:
                errors += 1
                continue
            kind, produced, reason, target = _classify(full, st)
            if kind == "dir":
                continue
            rel = os.path.relpath(full, str(project))
            entries[rel] = {
                "rel": rel,
                "kind": kind,
                "produced": produced,
                "size": int(st.st_size),
                "mtime": round(st.st_mtime, 6),
                "mtime_ns": int(st.st_mtime_ns),
                "ino": int(st.st_ino),
                "nlink": int(st.st_nlink),
            }
            if reason:
                entries[rel]["not_produced_reason"] = reason
            if target is not None:
                entries[rel]["link_target"] = target
    return {
        "entries": entries,
        "walk_ms": round((time.perf_counter() - t0) * 1000.0, 1),
        "entries_walked": walked,
        "lstat_errors": errors,
        "skipped_dirs": sorted(skip),
    }


# --------------------------------------------------------------------------- #
# The run window (t0)
# --------------------------------------------------------------------------- #
_SUMMARIES = (
    "reports/orchestrator/vibe_ic_one_shot.json",
    "reports/orchestrator/phase3_one_shot.json",
    "reports/orchestrator/phase2_one_shot.json",
    "reports/phase1_one_shot.json",
    "reports/phase2_one_shot.json",
    "reports/phase3_one_shot.json",
)


def mtime_fidelity(entries: Dict[str, Dict[str, Any]],
                   project: Path) -> Dict[str, Any]:
    """Decide whether the mtimes in this tree carry WRITE-TIME information at
    all — before any conclusion is drawn from them.

    MEASURED, and this is why the check exists: the published cell
    benchmark-data/ic/spm/v1.5.66_gf180mcuD has 216 files and exactly THREE
    distinct mtimes (98.1% share one), because 213 of its files are git-tracked
    and GIT DOES NOT STORE MTIMES — a checkout stamps every file with the
    checkout time.

    The DISCRIMINATOR is the share of files sitting on the single most common
    mtime second, NOT a distinct/total ratio — a ratio false-positives on any
    large run, where thousands of files are legitimately written inside a few
    dozen seconds. Measured on real directories (originals, not copies):

        share on top mtime   distinct   n       directory
        0.981                3          216     published spm v1.5.66_gf180mcuD
        0.964                78       12006     $HOME/_nXX_internal/runXX
        0.884                85        4316     $HOME/_car15_evidence
        0.165               44          455     $HOME/_sky130A_r3_run
        0.122               54          482     $HOME/_r6_sky130A/run

    The gap between 0.165 and 0.884 is the whole population; 0.5 sits in the
    middle of it. Note that run29 and _car15_evidence are NOT live runs — they
    are bulk copies, and this check correctly says so.

    Without this, the ledger would report "216 produced in run window" and 135
    D7 candidates off timestamps that record a `git checkout`. That is exactly
    the self-issued clean bill this repo keeps finding, so the time-dependent
    conclusions are WITHHELD instead.
    """
    import collections
    counts = collections.Counter(int(e["mtime"]) for e in entries.values())
    n = len(entries)
    distinct = len(counts)
    top_share = (counts.most_common(1)[0][1] / n) if n else 0.0
    flattened = (n >= 20 and (distinct <= 4 or top_share >= 0.5))
    vcs = None
    try:
        p = Path(project).resolve()
        for cand in [p, *p.parents]:
            if (cand / ".git").exists():
                vcs = str(cand)
                break
    except OSError:
        pass
    return {
        "n_files": n,
        "distinct_mtimes": distinct,
        "top_mtime_share": round(top_share, 4),
        "flattened": flattened,
        "under_vcs": vcs,
        "rule": "flattened if n>=20 and (distinct<=4 or top_mtime_share>=0.5)",
        "note": (
            "mtimes are FLATTENED — they record a copy/checkout, not the run's "
            "writes; every time-derived conclusion is withheld"
            if flattened else
            "mtimes vary across the tree and are usable as write times"),
    }


def resolve_run_window(project: Path) -> Dict[str, Any]:
    """Establish t0 — when THIS run started — without instrumenting anything.

    Marker first (exact), then derived from an orchestrator summary's own
    mtime minus its recorded duration. If neither exists the window is
    UNKNOWN and the caller must not pretend otherwise.
    """
    project = Path(project)
    marker = project / "steps" / ".write_ledger_t0.json"
    if marker.is_file():
        try:
            m = json.loads(marker.read_text())
            t0 = float(m.get("t0_epoch"))
            return {"t0_epoch": t0, "t0_source": "marker",
                    "t0_detail": str(marker.relative_to(project)),
                    "known": True}
        except Exception:
            pass

    best: Optional[float] = None
    detail = ""
    for rel in _SUMMARIES:
        p = project / rel
        if not p.is_file():
            continue
        try:
            dur = float(json.loads(p.read_text()).get("duration_s") or 0.0)
            start = p.stat().st_mtime - dur
        except Exception:
            continue
        if dur <= 0:
            continue
        if best is None or start < best:
            best, detail = start, f"{rel} mtime - duration_s({dur:.1f})"
    if best is not None:
        return {"t0_epoch": best, "t0_source": "orchestrator_summary",
                "t0_detail": detail, "known": True}
    return {"t0_epoch": None, "t0_source": "none",
            "t0_detail": "no marker and no orchestrator summary with duration_s",
            "known": False}


# --------------------------------------------------------------------------- #
# Producer attribution from the run's own provenance log
# --------------------------------------------------------------------------- #
def _parse_ts(value: Any) -> Optional[float]:
    if not isinstance(value, str) or not value:
        return None
    txt = value.strip().replace("Z", "+00:00")
    try:
        dt = _dt.datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.timestamp()


def load_provenance(project: Path) -> Dict[str, Any]:
    """Read provenance.jsonl into time windows. Tolerates BOTH record shapes
    seen in real runs (the provenance_logger wrapper record, and the
    `record:"invocation"` shape emitted in-runner) and skips malformed lines
    rather than failing."""
    path = Path(project) / "provenance.jsonl"
    windows: List[Dict[str, Any]] = []
    declared: Dict[str, List[Dict[str, Any]]] = {}
    n_lines = n_bad = 0
    if not path.is_file():
        return {"present": False, "path": "provenance.jsonl", "records": 0,
                "windows": [], "declared_outputs": {}, "bad_lines": 0}
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return {"present": False, "path": "provenance.jsonl", "records": 0,
                "windows": [], "declared_outputs": {}, "bad_lines": 0}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        n_lines += 1
        try:
            rec = json.loads(line)
        except Exception:
            n_bad += 1
            continue
        if not isinstance(rec, dict):
            n_bad += 1
            continue
        start = _parse_ts(rec.get("timestamp"))
        dur = rec.get("duration_s")
        if dur is None and rec.get("duration_ms") is not None:
            try:
                dur = float(rec["duration_ms"]) / 1000.0
            except (TypeError, ValueError):
                dur = None
        try:
            dur = float(dur) if dur is not None else 0.0
        except (TypeError, ValueError):
            dur = 0.0
        tool = str(rec.get("tool") or "") or "unknown"
        cmd = rec.get("argv") or rec.get("command") or ""
        if isinstance(cmd, list):
            cmd = " ".join(str(c) for c in cmd)
        idx = len(windows)
        if start is not None:
            windows.append({
                "i": idx,
                "tool": tool,
                # The wrapper's own post-run timestamp; a container tool's
                # END is what is stamped, so the window is [end-dur, end+slack]
                # only when the record is the logger shape. Both shapes stamp
                # at COMPLETION in practice, so widen to cover the run.
                "start": start - dur - _WINDOW_SLACK_S,
                "end": start + _WINDOW_SLACK_S,
                "duration_s": dur,
                "step": str(rec.get("step") or ""),
                "cmd": cmd[:400],
                "exit_code": rec.get("exit_code"),
            })
        outs = rec.get("outputs")
        if isinstance(outs, dict):
            for rel, digest in outs.items():
                declared.setdefault(str(rel).lstrip("./"), []).append({
                    "tool": tool, "digest": str(digest),
                    "window": idx if start is not None else None,
                })
    return {"present": True, "path": "provenance.jsonl", "records": n_lines,
            "windows": windows, "declared_outputs": declared,
            "bad_lines": n_bad}


def attribute(entry: Dict[str, Any], prov: Dict[str, Any]) -> None:
    """Attach producer attribution to one ledger entry, IN PLACE.

    Confidence ladder, strongest first:
      provenance_output   the invocation's own post-run record names this exact
                          path as one of its outputs (the wrapper hashed it).
                          This is the wrapper's CLAIM about its own write — the
                          strongest available, still not process-level truth.
      window              the file's mtime falls inside exactly one logged
                          invocation window.
      ambiguous           inside 2+ windows; candidates listed, no single name.
      unwitnessed         inside NO window, though provenance has coverage.
      unattributable      provenance.jsonl absent or empty — nothing to match
                          against; NOT the same as "unwitnessed".
    """
    rel = entry["rel"]
    if not prov.get("present"):
        entry["producer"] = None
        entry["producer_confidence"] = "unattributable"
        entry["producer_evidence"] = "no provenance.jsonl in this run"
        return

    # Path-named claims are checked BEFORE time windows: they do not depend on
    # mtime at all, so they survive a tree whose mtimes have been flattened by
    # a copy or a git checkout.
    claims = prov.get("declared_outputs", {}).get(rel) or []
    real = [c for c in claims if not str(c.get("digest", "")).startswith(("missing", "error"))]
    if real:
        entry["producer"] = real[0]["tool"]
        entry["producer_confidence"] = "provenance_output"
        entry["producer_evidence"] = (
            f"provenance record declares this path as its output "
            f"({real[0]['digest'][:23]}...)")
        # A provenance record that names a real digest for a path which is now
        # ZERO BYTES or DANGLING is self-contradictory, and it is decidable
        # from lstat alone — no hashing. This is the shape where the ledger
        # and the log disagree, and the log is the one making a claim.
        if entry["kind"] == "empty_file" and real[0]["digest"] != _EMPTY_SHA:
            entry["provenance_contradiction"] = (
                f"provenance claims {real[0]['digest'][:23]}... for a file that "
                f"is now 0 bytes")
        elif entry["kind"] in ("dangling_symlink",):
            entry["provenance_contradiction"] = (
                f"provenance claims {real[0]['digest'][:23]}... for a path that "
                f"is now a broken symlink -> {entry.get('link_target')}")
        return

    if not prov.get("windows"):
        entry["producer"] = None
        entry["producer_confidence"] = "unattributable"
        entry["producer_evidence"] = "no usable tool-invocation windows"
        return

    mt = entry["mtime"]
    hits = [w for w in prov["windows"] if w["start"] <= mt <= w["end"]]
    if len(hits) == 1:
        w = hits[0]
        entry["producer"] = w["tool"]
        entry["producer_confidence"] = "window"
        entry["producer_evidence"] = (
            f"mtime inside invocation #{w['i']} ({w['tool']}, {w['duration_s']:.1f}s)")
        return
    if len(hits) > 1:
        entry["producer"] = None
        entry["producer_candidates"] = sorted({w["tool"] for w in hits})
        entry["producer_confidence"] = "ambiguous"
        entry["producer_evidence"] = (
            f"mtime inside {len(hits)} overlapping invocation windows; "
            f"provenance timestamps are second-granularity")
        return
    entry["producer"] = None
    entry["producer_confidence"] = "unwitnessed"
    entry["producer_evidence"] = (
        "mtime falls inside no logged tool invocation window")


# --------------------------------------------------------------------------- #
# The declaration side (parsed HERE, not taken from flow_dashboard_data)
# --------------------------------------------------------------------------- #
def _flow_yaml_path() -> Path:
    return (Path(__file__).resolve().parent.parent
            / "flow" / "phase1_phase2_phase3.yaml")


def _iter_flow_steps(doc: Any) -> List[dict]:
    out: List[dict] = []

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            if "id" in o and ("name" in o or "required_outputs" in o):
                out.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(doc)
    return out


_STAGE_PHASE = {
    "stage_phase1": "phase1", "stage1": "phase2", "stage2": "phase2",
    "stage3": "phase3", "stage4": "phase3", "stage_analog": "analog",
    "stage_mixed_signal": "mixed", "stage5_manufacturing": "manufacturing",
}


def load_declaration() -> Dict[str, Any]:
    """Steps + their required_outputs + their DECLARED tool surface, straight
    from the flow YAML. Deliberately does NOT call flow_dashboard_data: that
    module is the thing whose answer we are auditing, and reusing its resolver
    would rebuild the circularity."""
    try:
        import yaml  # type: ignore
        doc = yaml.safe_load(_flow_yaml_path().read_text())
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "steps": []}
    steps: List[Dict[str, Any]] = []
    for s in _iter_flow_steps(doc):
        ro = s.get("required_outputs") or []
        if not ro:
            continue                      # containers / umbrella nodes
        stage = str(s.get("stage") or "")
        steps.append({
            "id": str(s.get("id", "")),
            "name": str(s.get("name", "")),
            "stage": stage or "stage",
            "phase": _STAGE_PHASE.get(stage, ""),
            "required_outputs": [str(x) for x in ro],
            # Recorded so a reader can TRIAGE a D3 without this module
            # deciding for them. A step carrying a `condition:` may legally
            # not have run at all; that is not the same defect as a step that
            # ran and produced nothing, and the ledger must not conflate them
            # — nor may it silently drop the finding, which would be exactly
            # the kind of self-issued clean bill this repo keeps finding.
            "conditional": bool(s.get("condition")),
            "declared_tools": sorted(
                {str(x) for x in (s.get("programs") or [])}
                | {str(x) for x in (s.get("mcp_tools") or [])}),
        })
    return {"ok": True, "steps": steps, "source": str(_flow_yaml_path())}


def load_waivers(project: Path) -> Dict[str, Dict[str, Any]]:
    """step id -> waiver record from <project>/waivers.json, for ANNOTATION
    ONLY. A waived step's missing output is still reported as D3; the waiver
    is attached so a reader can triage it. Suppressing it here would be
    widening a waiver into a silence."""
    out: Dict[str, Dict[str, Any]] = {}
    p = Path(project) / "waivers.json"
    if not p.is_file():
        return out
    try:
        doc = json.loads(p.read_text())
    except Exception:
        return out
    for w in (doc.get("waived_steps") or []):
        if isinstance(w, dict) and w.get("id") is not None:
            out[str(w["id"])] = {
                "reason": str(w.get("reason", ""))[:300],
                "review_required": w.get("review_required"),
                "approver": w.get("approver") or w.get("approved_by"),
            }
    return out


def _spec_candidates(project: Path, spec: str) -> List[str]:
    """Relative paths a `required_outputs` spec POINTS AT, whether or not they
    are usable. Uses Path.glob (which yields dangling symlinks) and does NOT
    filter on exists() — filtering here is what erases the very evidence this
    module is for. Classification is the ledger's job, not the glob's."""
    rels: List[str] = []
    for alt in [a.strip() for a in _OR_RE.split(str(spec).strip()) if a.strip()]:
        pat = alt.lstrip("/")
        if not pat:
            continue
        try:
            if any(c in pat for c in "*?["):
                for p in sorted(project.glob(pat)):
                    rels.append(os.path.relpath(str(p), str(project)))
            else:
                rels.append(pat)
        except (OSError, ValueError):
            continue
    return rels


def _spec_claimed_patterns(spec: str) -> List[str]:
    return [a.strip().lstrip("/")
            for a in _OR_RE.split(str(spec).strip()) if a.strip()]


# --------------------------------------------------------------------------- #
# The residual
# --------------------------------------------------------------------------- #
def build(project: Path) -> Dict[str, Any]:
    """Observe, attribute, and residual against the declaration."""
    project = Path(project).expanduser().resolve()
    snap = snapshot(project)
    entries = snap["entries"]
    window = resolve_run_window(project)
    prov = load_provenance(project)

    fidelity = mtime_fidelity(entries, project)
    if fidelity["flattened"]:
        # Every time-derived conclusion is now unsupported. Say so once, here,
        # rather than emitting numbers computed from a checkout timestamp.
        window = dict(window, known=False, t0_source="withheld_flattened_mtimes",
                      t0_epoch=None, t0_detail=fidelity["note"])
        prov = dict(prov, windows=[])       # window matching is meaningless

    t0 = window.get("t0_epoch")
    for e in entries.values():
        e["in_run_window"] = (None if t0 is None else bool(e["mtime"] >= t0))
        attribute(e, prov)
        if fidelity["flattened"] and e.get("producer_confidence") == "unattributable":
            e["producer_evidence"] = (
                "mtimes in this tree are flattened (copy/checkout), so window "
                "attribution is withheld; only a provenance record naming this "
                "exact path can attribute it")

    decl = load_declaration()
    waivers = load_waivers(project)
    undetermined: List[str] = []
    if fidelity["flattened"]:
        undetermined.append(
            f"mtimes are FLATTENED ({fidelity['top_mtime_share']:.1%} of "
            f"{fidelity['n_files']} files share one mtime second; "
            f"{fidelity['distinct_mtimes']} distinct"
            + (f"; tree is under VCS at {fidelity['under_vcs']}"
               if fidelity["under_vcs"] else "")
            + ") -> they record a copy or a git checkout, NOT this run's "
              "writes. The run window, the D7 residual, and all time-window "
              "producer attribution are WITHHELD. What survives: existence, "
              "size, kind (zero-byte / dangling / alias), the D3 residual, and "
              "any provenance record that names a path directly.")
    elif not window.get("known"):
        undetermined.append(
            "run window unknown (no t0 marker, no orchestrator summary with "
            "duration_s) -> 'written, never declared' (D7) is NOT reported; "
            "pre-existing files cannot be told from this run's writes")
    if not prov.get("present"):
        undetermined.append(
            "provenance.jsonl absent -> producer attribution and the D5 "
            "'unwitnessed write' candidate are NOT reported")
    if not decl.get("ok"):
        undetermined.append(
            f"flow YAML unreadable ({decl.get('error')}) -> no residual against "
            f"required_outputs; the observation half is still recorded")

    step_rows: List[Dict[str, Any]] = []
    claimed_rels: set = set()
    claimed_patterns: List[str] = []

    for s in decl.get("steps", []):
        produced: List[Dict[str, Any]] = []
        d3: List[Dict[str, Any]] = []
        d5: List[Dict[str, Any]] = []
        observed_producers: set = set()

        for spec in s["required_outputs"]:
            claimed_patterns.extend(_spec_claimed_patterns(spec))
            cands = _spec_candidates(project, spec)
            claimed_rels.update(cands)
            usable: List[Dict[str, Any]] = []
            rejected: List[Dict[str, Any]] = []
            for rel in cands:
                e = entries.get(rel)
                if e is None:
                    continue                    # nothing at that path at all
                if e["produced"]:
                    usable.append(e)
                else:
                    rejected.append(e)
            if usable:
                for e in usable:
                    produced.append({
                        "rel": e["rel"], "size": e["size"], "mtime": e["mtime"],
                        "kind": e["kind"], "spec": spec,
                        "producer": e.get("producer"),
                        "producer_confidence": e.get("producer_confidence"),
                        "producer_evidence": e.get("producer_evidence"),
                    })
                    if e.get("producer"):
                        observed_producers.add(e["producer"])
                    # D5 CANDIDATE — the only one this module can defend
                    # without inventing a program-name -> binary-name mapping:
                    # a DECLARED output that landed inside no witnessed tool
                    # invocation. That is the "agent wrote the file by hand and
                    # the gate passed" shape the provenance logger exists for.
                    if (prov.get("present") and prov.get("windows")
                            and e.get("producer_confidence") == "unwitnessed"):
                        d5.append({
                            "dimension": "D5", "kind": "candidate",
                            "rule": "unwitnessed_write",
                            "step": s["id"], "rel": e["rel"],
                            "detail": ("declared output exists but its mtime "
                                       "falls inside no logged tool invocation "
                                       "window"),
                            "caveat": ("provenance coverage in this run is "
                                       f"{len(prov['windows'])} invocation(s); "
                                       "a real tool run that was never wrapped "
                                       "produces this signal too"),
                        })
            else:
                # DECLARED, NEVER WRITTEN — attributed to THIS STEP.
                if rejected:
                    worst = rejected[0]
                    reason = worst.get("not_produced_reason", worst["kind"])
                    detail = (f"path exists but is not a produced artefact: "
                              f"{worst['rel']} ({worst['kind']}"
                              + (f" -> {worst['link_target']}"
                                 if worst.get("link_target") else "")
                              + f", size={worst['size']})")
                else:
                    reason = "absent"
                    detail = "no path on disk matches this spec"
                rec = {
                    "dimension": "D3", "kind": "finding",
                    "rule": "declared_output_not_produced",
                    "step": s["id"], "step_name": s["name"],
                    "phase": s["phase"], "stage": s["stage"],
                    "spec": spec, "reason": reason, "detail": detail,
                    "step_conditional": s["conditional"],
                }
                if rejected and rejected[0].get("provenance_contradiction"):
                    rec["provenance_contradiction"] = \
                        rejected[0]["provenance_contradiction"]
                    rec["claimed_producer"] = rejected[0].get("producer")
                if s["id"] in waivers:
                    # ANNOTATION, not suppression — the finding still counts.
                    rec["waiver"] = waivers[s["id"]]
                d3.append(rec)

        step_rows.append({
            "id": s["id"], "name": s["name"], "phase": s["phase"],
            "stage": s["stage"],
            "conditional": s["conditional"],
            "waiver": waivers.get(s["id"]),
            "declared_tools": s["declared_tools"],
            "n_required_outputs": len(s["required_outputs"]),
            "n_produced": len(produced),
            "produced": produced[:_MAX_LISTED],
            "observed_producers": sorted(observed_producers),
            "producer_vocabulary_note": (
                "declared_tools are plugin program / MCP tool names; "
                "observed_producers are EDA binary names from provenance.jsonl. "
                "No mapping between the two exists in this repo, so they are "
                "NOT compared — see ATTRIBUTION HONESTY in the module doc."),
            "findings": d3 + d5,
        })

    # ---- written, never declared (D7 candidates) ----
    d7: List[Dict[str, Any]] = []
    d7_by_dir: Dict[str, int] = {}
    if window.get("known") and decl.get("ok"):
        for rel, e in sorted(entries.items()):
            if not e["produced"] or not e.get("in_run_window"):
                continue
            if rel in claimed_rels or rel in _SELF_PATHS:
                continue
            if rel.startswith(_D7_INPUT_PREFIXES):
                continue
            if any(fnmatch.fnmatch(rel, pat) for pat in claimed_patterns):
                continue
            d7.append({
                "dimension": "D7", "kind": "candidate",
                "rule": "written_never_declared",
                "rel": rel, "size": e["size"], "mtime": e["mtime"],
                "producer": e.get("producer"),
                "producer_confidence": e.get("producer_confidence"),
            })
            d = os.path.dirname(rel) or "."
            d7_by_dir[d] = d7_by_dir.get(d, 0) + 1

    kinds: Dict[str, int] = {}
    for e in entries.values():
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    in_win = sum(1 for e in entries.values() if e.get("in_run_window"))
    produced_in_win = sum(1 for e in entries.values()
                          if e["produced"] and e.get("in_run_window"))

    all_d3 = [f for r in step_rows for f in r["findings"] if f["dimension"] == "D3"]
    all_d5 = [f for r in step_rows for f in r["findings"] if f["dimension"] == "D5"]

    return {
        "schema": SCHEMA,
        "project": str(project),
        "captured_at": _dt.datetime.now(_dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "capture": {
            "method": "post-hoc os.walk + lstat (no content read, no hashing)",
            "walk_ms": snap["walk_ms"],
            "entries_walked": snap["entries_walked"],
            "entries_recorded": len(entries),
            "lstat_errors": snap["lstat_errors"],
            "skipped_dirs": snap["skipped_dirs"],
            "container_note": (
                "container steps write through a bind mount, which shares the "
                "host inode, so size/mtime ARE observed here; the writing "
                "PROCESS is in another namespace and is NOT observed"),
            "d7_input_prefixes": list(_D7_INPUT_PREFIXES),
        },
        "mtime_fidelity": fidelity,
        "run_window": window,
        "provenance": {
            "present": prov["present"], "records": prov["records"],
            "windows": len(prov.get("windows") or []),
            "bad_lines": prov.get("bad_lines", 0),
            "declared_output_paths": len(prov.get("declared_outputs") or {}),
            "attributed_writes": sum(
                1 for e in entries.values()
                if e.get("producer_confidence") in ("provenance_output", "window")),
            "coverage_note": (
                "provenance.jsonl logs WRAPPED TOOL INVOCATIONS only. Steps "
                "whose work is done by a plugin program or by the agent — "
                "Phase 1 doc generation is the largest — write nothing through "
                "the wrapper and therefore land as 'unwitnessed'. That is a "
                "true statement about this run's provenance COVERAGE, not "
                "proof of a hand-written artefact; triage accordingly."),
        },
        "counts": {
            "recorded": len(entries),
            "by_kind": kinds,
            "in_run_window": in_win,
            "produced_in_run_window": produced_in_win,
            "zero_byte": kinds.get("empty_file", 0),
            "dangling_symlink": kinds.get("dangling_symlink", 0),
            "symlink_alias": kinds.get("symlink", 0),
        },
        "declaration": {"ok": decl.get("ok"), "source": decl.get("source"),
                        "steps_with_required_outputs": len(decl.get("steps", []))},
        "steps": step_rows,
        "residual": {
            "declared_never_written": all_d3,
            "unwitnessed_writes": all_d5,
            "written_never_declared": d7[:_MAX_LISTED],
            "written_never_declared_total": len(d7),
            "written_never_declared_by_dir": dict(
                sorted(d7_by_dir.items(), key=lambda kv: -kv[1])[:40]),
        },
        "totals": {
            "D3": len(all_d3), "D5": len(all_d5), "D7": len(d7),
            "provenance_contradictions": sum(
                1 for e in entries.values() if e.get("provenance_contradiction")),
        },
        "undetermined": undetermined,
        "written": sorted(
            (e for e in entries.values() if e.get("in_run_window") is not False),
            key=lambda e: e["rel"])[:_MAX_LISTED],
    }


# --------------------------------------------------------------------------- #
# Emission — best-effort, never raises
# --------------------------------------------------------------------------- #
def mark_run_start(project: Path) -> bool:
    """Drop the t0 marker. One tiny write; call at run start if you want an
    EXACT run window instead of the derived one. Never raises."""
    try:
        d = Path(project) / "steps"
        d.mkdir(parents=True, exist_ok=True)
        (d / ".write_ledger_t0.json").write_text(json.dumps({
            "t0_epoch": time.time(),
            "t0_iso": _dt.datetime.now(_dt.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"),
            "pid": os.getpid(),
        }) + "\n")
        return True
    except Exception:
        return False


def _step_folders(project: Path) -> Dict[str, str]:
    """step id -> folder, read from the collector's steps/index.json when it
    exists. Used ONLY to decide where to drop a per-step slice; no evidence is
    taken from it."""
    try:
        idx = json.loads((Path(project) / "steps" / "index.json").read_text())
        return {str(s.get("id")): str(s.get("folder"))
                for s in idx.get("steps", []) if s.get("folder")}
    except Exception:
        return {}


def emit(project: Path) -> Dict[str, Any]:
    """Build the ledger and write it. NEVER raises — a run must not die because
    its bookkeeping failed."""
    try:
        project = Path(project).expanduser().resolve()
        led = build(project)

        # Primary artefact lives under reports/ — benchmark_evidence_publish
        # excludes steps/ by name ("per-step scratch"), so a ledger written
        # only into steps/ would never reach a published cell.
        out = project / "reports" / "write_ledger.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(led, indent=2, ensure_ascii=False) + "\n")

        # Per-step slice next to the collector's outputs.json, when that tree
        # exists. Additive: the collector's own files are not touched.
        folders = _step_folders(project)
        n_slices = 0
        for row in led["steps"]:
            folder = folders.get(row["id"])
            if not folder:
                continue
            sdir = project / "steps" / folder
            if not sdir.is_dir():
                continue
            try:
                (sdir / "written.json").write_text(
                    json.dumps(row, indent=2, ensure_ascii=False) + "\n")
                n_slices += 1
            except OSError:
                continue
        return {"ok": True, "path": str(out), "slices": n_slices,
                "walk_ms": led["capture"]["walk_ms"],
                "totals": led["totals"],
                "undetermined": led["undetermined"]}
    except Exception as exc:      # noqa: BLE001 — bookkeeping never fails a run
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Record what a run ACTUALLY WROTE; residual vs required_outputs.")
    ap.add_argument("project", type=Path)
    ap.add_argument("--json", type=Path, default=None,
                    help="also write the full ledger here")
    ap.add_argument("--mark-start", action="store_true",
                    help="write the t0 marker and exit (call at run start)")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    if a.mark_start:
        ok = mark_run_start(a.project)
        print(json.dumps({"marked": ok}))
        return 0

    res = emit(a.project)
    if a.json and res.get("ok"):
        try:
            a.json.parent.mkdir(parents=True, exist_ok=True)
            a.json.write_text(
                (Path(res["path"]).read_text()))
        except OSError:
            pass
    if not a.quiet:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0            # never non-zero: this is bookkeeping, not a gate


if __name__ == "__main__":
    raise SystemExit(main())
