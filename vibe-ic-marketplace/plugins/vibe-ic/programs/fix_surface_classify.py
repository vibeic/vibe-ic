#!/usr/bin/env python3
"""ORGANIC #602 — fix_surface_classify: deterministic consumer-vs-producer
classification of a closed fix's diff, so the field agent KNOWS whether an
artifact-first verify (seconds) suffices or a full re-run (~40 min) is
justified — without having to REMEMBER a prose rule.

Background (#598): the field-agent artifact-first discipline says "before
re-running a closed fix, classify its diff — CONSUMER-only (a checker /
classifier / verdict-message change → re-verify against the persisted
artifacts in seconds) vs PRODUCER (route / floorplan / streamout / geometry
emitter → a full re-run is justified)." #599 already programmed the run
STATE half (run_status.py). This programs the CLASSIFY half — the
load-bearing decision that #598 left as SKILL.md prose. A rule parked in
prose is one a fresh field-agent must remember to apply; as a program it
auto-fires.

The decision is deterministic: map a fix commit's diff hunks to their
enclosing functions / files and classify each against a maintained
PRODUCER symbol set (route/floorplan/streamout/geometry emitters) vs a
CONSUMER set (checkers, classifiers, verdict-message strings):

  CONSUMER_ONLY  every touched surface is a consumer → artifact-first
                 verify (drive the new checker/classifier against the
                 persisted reports/RTL/GDS; no producer re-run needed)
  PRODUCER       every touched surface is a producer → a full re-run is
                 justified (launch async + run_status watchdog)
  MIXED          touches both sets, OR an unknown/ambiguous surface that
                 cannot be proven consumer-only → conservatively re-run;
                 the genuine judgment residual a human/agent must read
                 (this is the only thing that stays in SKILL.md prose).

Conservative by construction: anything not PROVABLY consumer-only falls to
MIXED/PRODUCER (re-run). A needless re-run wastes time; it never ships an
unverified producer fix as artifact-first.

Usage
-----
  fix_surface_classify.py <issue-number | commit-sha>   # resolve via git
  fix_surface_classify.py --diff-file <unified.diff>    # offline / test
  fix_surface_classify.py 600 --json
  fix_surface_classify.py --repo-root /path/to/repo 601

Exit codes (so a driver can branch): 0 CONSUMER_ONLY · 10 PRODUCER ·
11 MIXED · 2 usage/resolve error.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── maintained surface registries ───────────────────────────────────────────
# PRODUCER: route / floorplan / streamout / geometry emitters. A change here
# alters the ARTIFACTS (DEF/GDS/SPEF/…), so the persisted artifacts are stale
# → a re-run is justified. Matched (case-insensitively) against the hunk's
# enclosing symbol + its changed-line text.
PRODUCER_PATTERNS = [
    r"\bstep_pnr\b", r"\bstep_gds\b", r"\bstep_floorplan\b", r"\bstep_cts\b",
    r"\bstep_route\b", r"\bstep_place\b", r"\bstep_synth\b",
    r"make_tracks", r"_build_pnr_tcl", r"_post_route_spef",
    r"_post_buffered_repair", r"_gds_grid_snap", r"_magic_def_to_gds",
    r"_klayout_merge_layers", r"_gds_streamout", r"\bstream_out\b",
    r"_gds_\w+_py", r"_pnr_\w*tcl", r"global_route", r"detailed_route",
    r"\bpdn\b", r"tapcell", r"floorplan", r"placement",
    r"reg\.merge", r"reg\.snap", r"\.flatten\(",
    # ORGANIC #603 — PRODUCER-ACTION tokens that ONLY appear in real
    # artifact-writing code (not log filenames / comments): a function with
    # no producer symbol name that nonetheless writes a DEF/GDS/SPEF is a
    # producer. Kept deliberately NARROW (the `write_*` verb form) so a mere
    # mention of a tool name in a log path or comment does not false-fire.
    r"\bwrite_def\b", r"\bwrite_gds\b", r"\bwrite_spef\b",
]
# CONSUMER: checkers / classifiers / verdict-message strings. A change here
# only re-INTERPRETS existing artifacts, so it verifies against the persisted
# reports in seconds.
#
# ORGANIC #603 — broadened to the full CONSUMER-OUTPUT family so a consumer
# FUNCTION living INSIDE a runner/producer file (e.g. a verdict-message edit
# to `_emit_lvs_verdict` in phase3_one_shot_runner.py) is recognised by what
# the hunk DOES, not just by the file path. Two prior misses fixed: the
# `\bverdict\b` word-boundary did not match `verdict` inside
# `_emit_lvs_verdict` (underscore is a word char), and message-variable
# edits (`note = "…"`) carried no consumer token. These are emitter /
# verdict / message / note / report / finding / disclosure patterns — a
# general output-string vocabulary, NOT chip/issue-specific literals.
# NOTE on precision: tokens that are also ordinary English words (note,
# finding, report) are matched ONLY in their CODE forms (a `note = …`
# assignment, an `_emit_*` identifier) — never as a bare word — so the same
# word inside a producer function's docstring/comment cannot false-fire it
# into a consumer (the #602-round-1 "prose word" failure mode). Tokens that
# read as code identifiers (verdict / classify / emit / msg / triage) keep
# their substring form.
CONSUMER_PATTERNS = [
    r"classif\w*", r"_count_\w+", r"_parse\w*", r"verdict",
    r"_scan\b", r"_audit\b", r"\bcheck\b", r"\bmsg\b", r"\bmessage\b",
    r"_violations?\b", r"_triage\b", r"_report\b", r"_message\b",
    r"_emit\w*", r"\bnote\s*=", r"\bfinding\s*=", r"disclos\w*",
    r"\bcross.?ref", r"_mismatch\b", r"\bmismatch\s*=",
]
# CONSUMER by FILE: standalone gate/checker/classifier modules. Used as a
# fallback consumer signal (e.g. a verdict-message-only edit in a checker).
CONSUMER_FILE_PATTERNS = [
    r"_check\.py$", r"_classif\w*\.py$", r"_audit\w*\.py$", r"_scan\w*\.py$",
    r"_gate\w*\.py$", r"(^|/)acceptance_", r"_acceptance", r"(^|/)defect_",
    r"run_status\.py$", r"field_agent_\w+\.py$", r"_version_\w*\.py$",
    r"version_\w+_check\.py$", r"marketplace_\w+_check\.py$",
]
# ORGANIC #602 round 2 — classify-NEUTRAL files. EVERY core-agent fix commit
# bumps marketplace.json + plugin.json (a mandatory push step), regenerates
# INDEX.md, and ships test files (the author's EVIDENCE, not a runtime
# surface) + prose .md (docs / skills). If any of these counted as a
# surface, a single bumped version line would drop every real commit into
# "ambiguous" → MIXED → a needless 40-min re-run on EVERY fix — defeating
# the whole point of the classifier (the field agent measured exactly this:
# #599/#600/#597 all wrongly returned MIXED). So these files are EXCLUDED
# from producer/consumer/ambiguous bucketing entirely; the verdict is
# decided only by the genuine runtime surfaces a commit touches.
NEUTRAL_FILE_PATTERNS = [
    r"(^|/)marketplace\.json$",          # version bump (mandatory)
    r"(^|/)plugin\.json$",               # version bump (mandatory)
    r"(^|/)INDEX\.md$",                  # auto-regenerated catalog
    r"(^|/)tests?/",                     # any tests directory (evidence)
    r"(^|/)test_[^/]*\.py$",             # test modules (evidence)
    r"\.md$",                            # docs / skills / prose
]

_VERDICTS = {
    "CONSUMER_ONLY": 0,
    "PRODUCER": 10,
    "MIXED": 11,
}


def _any(patterns: List[str], text: str) -> Optional[str]:
    for p in patterns:
        if re.search(p, text, re.IGNORECASE):
            return p
    return None


def _consumer_file(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    base = path.rsplit("/", 1)[-1]
    for p in CONSUMER_FILE_PATTERNS:
        if re.search(p, path, re.IGNORECASE) or re.search(p, base, re.IGNORECASE):
            return p
    return None


def _neutral_file(path: Optional[str]) -> Optional[str]:
    """ORGANIC #602 r2 — is this a classify-neutral file (version bump /
    generated index / test evidence / prose)? Such hunks are dropped before
    bucketing so a mandatory version-bump line can't force MIXED."""
    if not path:
        return None
    for p in NEUTRAL_FILE_PATTERNS:
        if re.search(p, path, re.IGNORECASE):
            return p
    return None


def classify_hunk(path: Optional[str], symbol: Optional[str],
                  changed_text: str = "") -> Dict:
    """Classify ONE hunk as producer / consumer / mixed / unknown, with the
    matched evidence. symbol = enclosing function (from the hunk header);
    changed_text = the +/- line bodies."""
    blob = " ".join([symbol or "", changed_text])
    prod = _any(PRODUCER_PATTERNS, blob)
    cons = _any(CONSUMER_PATTERNS, blob) or _consumer_file(path)
    if prod and not cons:
        cls = "producer"
    elif cons and not prod:
        cls = "consumer"
    elif prod and cons:
        cls = "mixed"
    else:
        cls = "unknown"
    return {"path": path, "symbol": symbol, "class": cls,
            "producer_evidence": prod, "consumer_evidence": cons}


def _symbol_from_context(ctx: str) -> Optional[str]:
    """Pull the enclosing symbol from a git hunk-header context, e.g.
    `def step_pnr(project):` → step_pnr, `class Foo:` → Foo,
    `_GDS_GRID_SNAP_PY = r'''` → _GDS_GRID_SNAP_PY.

    ORGANIC #602 r2 — ONLY a real Python `def`/`class`/module-assignment is
    a symbol. The earlier generic first-word fallback scraped words out of
    JSON/markdown/prose hunk contexts (`Auto`, `the`, `artifact`, `_`) and
    fed them in as bogus 'function names'; return None instead so such a
    hunk is decided by its file/changed-line signals (and neutral files are
    excluded upstream anyway)."""
    ctx = ctx.strip()
    if not ctx:
        return None
    m = re.search(r"\b(?:def|class)\s+(\w+)", ctx)
    if m:
        return m.group(1)
    # module-level assignment of an UPPER/underscore constant (e.g. an
    # embedded TCL/py emitter blob) — a real code symbol, not prose.
    m = re.match(r"([A-Za-z_]\w*)\s*=", ctx)
    if m and ("_" in m.group(1) or m.group(1).isupper()):
        return m.group(1)
    return None


def parse_unified_diff(diff_text: str) -> List[Dict]:
    """Parse a unified diff into per-hunk {path, symbol, changed} records."""
    hunks: List[Dict] = []
    cur_file: Optional[str] = None
    cur: Optional[Dict] = None
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            p = line[4:].strip().split("\t", 1)[0]
            if p.startswith("b/"):
                p = p[2:]
            cur_file = None if p == "/dev/null" else p
        elif line.startswith("@@"):
            m = re.match(r"@@ .* @@ ?(.*)", line)
            ctx = m.group(1) if m else ""
            cur = {"path": cur_file, "symbol": _symbol_from_context(ctx),
                   "changed": []}
            hunks.append(cur)
        elif cur is not None and line[:1] in ("+", "-") \
                and not line.startswith(("+++", "---")):
            cur["changed"].append(line[1:])
    return hunks


def classify_diff(diff_text: str) -> Dict:
    """Classify a whole unified diff → CONSUMER_ONLY / PRODUCER / MIXED.

    ORGANIC #602 r2 — classify-neutral files (version bumps, INDEX.md,
    tests, prose .md) are dropped BEFORE bucketing so a mandatory
    version-bump line cannot force every real commit to MIXED."""
    records = []
    neutral = []
    for h in parse_unified_diff(diff_text):
        nf = _neutral_file(h["path"])
        if nf:
            neutral.append(h["path"])
            continue
        records.append(
            classify_hunk(h["path"], h["symbol"], "\n".join(h["changed"])))
    classes = {r["class"] for r in records}
    has_p = "producer" in classes
    has_c = "consumer" in classes
    has_x = "mixed" in classes or "unknown" in classes
    if records and has_c and not has_p and not has_x:
        verdict = "CONSUMER_ONLY"
    elif records and has_p and not has_c and not has_x:
        verdict = "PRODUCER"
    else:
        verdict = "MIXED" if records else "CONSUMER_ONLY"
    return {
        "verdict": verdict,
        "action": ("artifact-first verify"
                   if verdict == "CONSUMER_ONLY"
                   else "justified re-run (launch async + run_status)"),
        "hunks": records,
        "producers": sorted({r["symbol"] or r["path"]
                             for r in records if r["class"] == "producer"}),
        "consumers": sorted({r["symbol"] or r["path"]
                             for r in records if r["class"] == "consumer"}),
        "ambiguous": sorted({r["symbol"] or r["path"]
                             for r in records
                             if r["class"] in ("mixed", "unknown")}),
        "neutral": sorted(set(filter(None, neutral))),
    }


# ── git resolution (CLI; offline tests use --diff-file) ─────────────────────

def _git(repo_root: Path, *args: str) -> Optional[str]:
    try:
        out = subprocess.run(["git", "-C", str(repo_root), *args],
                             capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            return None
        return out.stdout
    except Exception:
        return None


def resolve_commit(arg: str, repo_root: Path) -> Optional[str]:
    """An all-digit arg is an issue number → newest commit whose message
    references it; a hex arg is a commit sha."""
    if re.fullmatch(r"\d+", arg):
        log = _git(repo_root, "log", "--format=%H %s", "-n", "400")
        if not log:
            return None
        pat = re.compile(rf"#\s*{re.escape(arg)}\b")
        for line in log.splitlines():
            sha, _, subj = line.partition(" ")
            if pat.search(subj):
                return sha
        return None
    if re.fullmatch(r"[0-9a-fA-F]{7,40}", arg):
        return arg
    return None


def diff_for(arg: str, repo_root: Path) -> Tuple[Optional[str], str]:
    sha = resolve_commit(arg, repo_root)
    if not sha:
        return None, f"could not resolve '{arg}' to a commit in {repo_root}"
    d = _git(repo_root, "show", sha, "--format=", "--unified=3")
    if d is None:
        return None, f"git show {sha} failed"
    return d, sha


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?",
                    help="issue number or commit sha")
    ap.add_argument("--diff-file", help="classify a unified diff from a file "
                    "(offline; skips git resolution)")
    ap.add_argument("--repo-root", default=".", help="git repo root")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.diff_file:
        diff_text = Path(args.diff_file).read_text(errors="replace")
        sha = None
    elif args.target:
        diff_text, sha = diff_for(args.target, Path(args.repo_root))
        if diff_text is None:
            print(f"[ERROR] {sha}", file=sys.stderr)
            return 2
    else:
        ap.error("need a <issue-number | commit-sha> or --diff-file")
        return 2

    rep = classify_diff(diff_text)
    rep["commit"] = sha
    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        print(f"verdict: {rep['verdict']}  →  {rep['action']}")
        if rep["producers"]:
            print(f"  producers: {', '.join(rep['producers'])}")
        if rep["consumers"]:
            print(f"  consumers: {', '.join(rep['consumers'])}")
        if rep["ambiguous"]:
            print(f"  ambiguous (needs read): {', '.join(rep['ambiguous'])}")
    return _VERDICTS.get(rep["verdict"], 11)


if __name__ == "__main__":
    sys.exit(main())
