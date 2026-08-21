#!/usr/bin/env python3
"""benchmark_run_manifest.py — a scored benchmark run must leave behind the
NAME SET, not only the count. vibe-ic#635.

THE DEFECT. A `cvdp-open` regression sweep set out to diff its per-problem
results against the recorded baseline (202/302, v1.4.14) and could not: that run
persisted `reports/gate_full302.json` (the GATE verdict — 302 admitted) and
`responses/responses.jsonl`, and nothing that said which problems passed. So the
sweep could report that the score moved and never which problems moved.

"Compare failure NAME SETS, not counts" is a rule this repo already relies on at
the test-suite level, for a measured reason: two suites at "93 failed vs 77
failed" once nearly became "my change fixed 16 tests" when the runs had different
scopes. A count that moves says something changed; only a name set says WHAT, and
only that is actionable. The same rule applies to what we PERSIST.

MEASURED ACROSS THE PUBLISHED CORPUS, by CONTENT rather than by filename — the
first pass of this survey looked for `report.json` / `raw_result.json` and found
nothing anywhere, which was the probe failing, not the corpus:

    runs carrying a per-problem structure    5 of 25
      rtllm/run_v1.3.26          pass_at_1.json      results[50]
      rtllm/run_v127             pass_at_1.json      results[50]
      rtllm/run_blind_v0126      pass_at_1.json      results[50]
      rtllm/run_cleanroom_v1388  pass_at_1.json      results[50]
      cvdp/run_v1239_converge    score_final/passrate.json  detail[302]
    runs carrying only a count               20 of 25

So this is NOT a format that needs inventing. Every RTLLM run already does the
right thing and one CVDP run does; the practice exists and is unenforced. This
program normalises the shapes that already occur and makes the presence of one
CHECKABLE, so a run that keeps only its aggregate fails before it is published.

THE TWO SHAPES THAT OCCUR, and why extraction is structural rather than keyed to
either benchmark's vocabulary (a `rtllm_`/`cvdp_`-named extractor would be the
overfit this repo forbids):

    list-of-records   {"results": [{"design": "…/accu", "verdict": "PASS"}, …]}
    id-keyed-mapping  {"detail": {"cvdp_copilot_…_0001": {"pass": true, …}, …}}

Both are "a collection of per-problem entries, each carrying an identity and a
verdict". `extract_verdicts` reads that shape wherever it sits, and REFUSES on
anything it cannot read rather than returning an empty set — an empty name set
compares equal to another empty one, which would make two unrelated runs look
identical.

WHAT A MANIFEST RECORDS, from the issue's own list:

    verdicts        id -> pass | fail | error, the scorer's own output
    dataset         path + sha256, so a changed DENOMINATOR is visible rather
                    than inferred: a differently-filtered run producing a
                    different total is otherwise indistinguishable from a drop
    plugin_version  what was measured
    image           the image reference actually measured, not the one intended
    scorer_argv     verbatim, so the invocation can be repeated

Exit codes: 0 PASS, 1 the run is missing what a later comparison needs, 2 the
question could not be put (unreadable path, no scorer output supplied).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MANIFEST_NAME = "RUN_MANIFEST.json"

#: Verdict spellings that occur in the corpus, normalised to three outcomes. A
#: word outside these is kept as-is and counted as neither pass nor fail, so an
#: unrecognised verdict cannot silently become a pass.
_PASS_WORDS = {"PASS", "PASSED", "TRUE", "OK"}
_FAIL_WORDS = {"FAIL", "FAILED", "FALSE", "NO"}
_ERROR_WORDS = {"ERROR", "ERR", "CRASH", "TIMEOUT"}


def normalize_verdict(raw: Any) -> str:
    """`pass` / `fail` / `error` / the original token, lowercased.

    A bare bool is the `{"pass": true}` shape; a string is the
    `{"verdict": "PASS"}` shape. Anything else is returned as text and lands in
    none of the three buckets — an unreadable verdict must not become a pass.
    """
    if isinstance(raw, bool):
        return "pass" if raw else "fail"
    s = str(raw or "").strip().upper()
    if s in _PASS_WORDS:
        return "pass"
    if s in _FAIL_WORDS:
        return "fail"
    if s in _ERROR_WORDS:
        return "error"
    return s.lower()


def _entry_verdict(entry: Any) -> Optional[str]:
    """The verdict inside one per-problem record, or None when it has none."""
    if isinstance(entry, bool):
        return normalize_verdict(entry)
    if not isinstance(entry, dict):
        return None
    for key in ("verdict", "pass", "passed", "result", "status", "outcome"):
        if key in entry:
            return normalize_verdict(entry[key])
    return None


def _entry_id(entry: Any, fallback: Optional[str]) -> Optional[str]:
    if fallback is not None:
        return str(fallback)
    if not isinstance(entry, dict):
        return None
    for key in ("id", "design", "problem", "name", "task", "problem_id"):
        if entry.get(key):
            return str(entry[key])
    return None


def extract_verdicts(obj: Any) -> Optional[Dict[str, str]]:
    """`{problem id: verdict}` from a scorer's own output, or None.

    STRUCTURAL, not keyed to a benchmark's vocabulary: it looks for a collection
    of per-problem entries each carrying an identity and a verdict, wherever in
    the document that collection sits. Both shapes in the corpus are that shape.

    None — never `{}` — when nothing readable is found. An empty name set
    compares equal to another empty one, so returning it would make two
    unrelated runs look identical, which is the failure this program exists to
    prevent.
    """
    best: Optional[Dict[str, str]] = None

    def consider(cand: Dict[str, str]) -> None:
        nonlocal best
        if cand and (best is None or len(cand) > len(best)):
            best = cand

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 6:
            return
        if isinstance(node, list):
            out: Dict[str, str] = {}
            for item in node:
                v = _entry_verdict(item)
                i = _entry_id(item, None)
                if v is not None and i is not None:
                    out[i] = v
            consider(out)
            for item in node[:200]:
                walk(item, depth + 1)
            return
        if isinstance(node, dict):
            out = {}
            for key, val in node.items():
                v = _entry_verdict(val)
                if v is not None:
                    out[str(key)] = v
            consider(out)
            for val in node.values():
                walk(val, depth + 1)

    walk(obj)
    return best


def file_sha256(path: Path) -> Optional[str]:
    """The digest, or None for a file that is not there — never the digest of
    nothing. `sha256("")` is a real, quotable hash, and publishing it for an
    absent dataset would state an identity for content that does not exist."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def build_manifest(verdicts: Dict[str, str],
                   dataset: Optional[Path] = None,
                   plugin_version: str = "",
                   image: str = "",
                   scorer_argv: Optional[List[str]] = None,
                   scorer_output: Optional[Path] = None) -> Dict[str, Any]:
    counts: Dict[str, int] = {}
    for v in verdicts.values():
        counts[v] = counts.get(v, 0) + 1
    return {
        "_comment": ("What a later run needs to diff against this one. The "
                     "aggregate alone cannot localise a regression, cannot "
                     "distinguish one from a scope change, and cannot attribute "
                     "an improvement — see vibe-ic#635."),
        "schema": 1,
        "total": len(verdicts),
        "counts": counts,
        "verdicts": dict(sorted(verdicts.items())),
        "dataset": {
            "path": str(dataset) if dataset else None,
            "sha256": file_sha256(dataset) if dataset else None,
        },
        "plugin_version": plugin_version,
        "image": image,
        "scorer_argv": list(scorer_argv or []),
        "scorer_output": str(scorer_output) if scorer_output else None,
    }


#: Every field a later comparison needs. Named here so the checker and the
#: emitter cannot drift into different notions of "complete".
REQUIRED_FIELDS = ("verdicts", "dataset", "plugin_version", "image",
                   "scorer_argv")


def manifest_gaps(man: Any) -> List[str]:
    """What this manifest is missing, as named gaps. Empty means complete."""
    gaps: List[str] = []
    if not isinstance(man, dict):
        return ["the manifest is not an object"]
    v = man.get("verdicts")
    if not isinstance(v, dict) or not v:
        gaps.append("verdicts: no per-problem name set — the run records a "
                    "count whose composition is gone")
    ds = man.get("dataset")
    if not isinstance(ds, dict) or not ds.get("sha256"):
        gaps.append("dataset.sha256: a changed denominator would be "
                    "indistinguishable from a regression")
    if not man.get("plugin_version"):
        gaps.append("plugin_version: the measurement names no subject")
    if not man.get("image"):
        gaps.append("image: the toolchain actually measured is unrecorded")
    if not man.get("scorer_argv"):
        gaps.append("scorer_argv: the invocation cannot be repeated")
    if isinstance(v, dict) and v:
        total = man.get("total")
        if isinstance(total, int) and total != len(v):
            gaps.append(f"total {total} disagrees with {len(v)} verdict(s) — "
                        "the aggregate and its composition describe different "
                        "runs")
    return gaps


def check_run(run_dir: Path) -> Tuple[int, str]:
    man_path = run_dir / MANIFEST_NAME
    if not man_path.is_file():
        return 1, (f"{run_dir}: no {MANIFEST_NAME}. A scored run must leave the "
                   f"per-problem name set behind, or the next sweep can only "
                   f"report that the point estimate moved (vibe-ic#635).")
    try:
        man = json.loads(man_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return 2, f"{man_path}: unreadable ({exc})"
    gaps = manifest_gaps(man)
    if gaps:
        return 1, f"{man_path}: incomplete\n  - " + "\n  - ".join(gaps)
    n = len(man["verdicts"])
    return 0, (f"{man_path}: PASS — {n} per-problem verdict(s), dataset "
               f"sha256:{man['dataset']['sha256'][:12]}, "
               f"plugin {man['plugin_version']}")


#: A run directory PUBLISHES A NUMBER when it carries an aggregate someone can
#: quote. That, not the directory's name, is what obliges it to carry the
#: composition too — a partial or probe run that scored nothing is not asked for
#: a name set it never had.
def publishes_an_aggregate(run_dir: Path) -> Optional[str]:
    """The file stating this run's score, or None when it states none."""
    if (run_dir / "RESULT.md").is_file():
        return str(run_dir / "RESULT.md")
    for f in sorted(run_dir.rglob("*.json"))[:400]:
        if f.name == MANIFEST_NAME:
            continue
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(doc, dict) and isinstance(doc.get("total"), int) and (
                "passed" in doc or "pass_at_1_pct" in doc):
            return str(f)
    return None


def changed_run_dirs(tree: Path, base: str) -> Optional[List[Path]]:
    """Scored-run directories touched since `base`, or None if that could not
    be determined.

    Scoped like `benchmark_evidence_structure_check --changed-since`, and for
    the same reason: 20 of the 25 runs already published carry no name set, and
    a gate applied retroactively would fail every landing over work nobody is
    doing today. What must not happen again is a NEW number arriving without
    its composition.

    RETURNS None RATHER THAN [] WHEN GIT FAILS (vibe-ic#1254). `[]` and "git
    could not answer" were the same value, and the caller renders `[]` as
    `PASS - 0 run director(y/ies) touched`. So a gate that could not look
    reported that it had looked and found nothing wrong -- in the pre-push
    hook, the one enforced gate on what reaches the remote. The two states are
    now distinct at the only place that can tell them apart; deciding what a
    non-answer is worth belongs to the caller.
    """
    import subprocess
    # 30 s, measured at 0.00 s over the real `benchmark-data` tree. Kept under
    # the 60 s inner ceiling for the same reason as the test above.
    r = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD", "--",
                        str(tree)], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return None
    seen: Dict[str, Path] = {}
    for line in r.stdout.splitlines():
        parts = Path(line).parts
        for i, seg in enumerate(parts):
            if seg.startswith("run_"):
                d = Path(*parts[: i + 1])
                seen[str(d)] = d
                break
    return [d for d in sorted(seen.values()) if d.is_dir()]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("emit", help="write RUN_MANIFEST.json for a scored run")
    e.add_argument("run_dir")
    e.add_argument("--scorer-output", required=True,
                   help="the SCORER's own output file. Required, and not "
                        "re-derived from the run tree: a re-derivation is a "
                        "second implementation of the scorer that can disagree "
                        "with it silently.")
    e.add_argument("--dataset")
    e.add_argument("--plugin-version", default="")
    e.add_argument("--image", default="")
    e.add_argument("--scorer-argv", default="",
                   help="the invocation, verbatim")

    c = sub.add_parser("check", help="does this run leave a name set behind?")
    c.add_argument("run_dir", nargs="?")
    c.add_argument("--tree", help="scan a tree instead of one directory")
    c.add_argument("--changed-since", help="only runs touched since this rev")

    a = ap.parse_args(argv)

    if a.cmd == "check":
        if a.tree and a.changed_since:
            dirs = changed_run_dirs(Path(a.tree), a.changed_since)
            # A CHECK THAT COULD NOT LOOK HAS NOT PASSED (vibe-ic#1254). rc 2 is
            # this repo's "the question could not be put", and the pre-push hook
            # already renders it as `NOT CHECKED` rather than as a finding -- the
            # distinction the hook's own comment insists on. Before this, the
            # undeterminable case fell through to the `not scored` branch below
            # and printed PASS.
            if dirs is None:
                print(f"UNDETERMINED: benchmark_run_manifest could not determine what "
                      f"changed since {a.changed_since} (git diff failed), so it "
                      f"scanned NOTHING. This is not a pass.", file=sys.stderr)
                return 2
            scored = [(d, publishes_an_aggregate(d)) for d in dirs]
            scored = [(d, s) for d, s in scored if s]
            if not scored:
                print(f"benchmark_run_manifest: PASS — {len(dirs)} run "
                      f"director(y/ies) touched, none publishes an aggregate")
                return 0
            worst, lines = 0, []
            for d, src in scored:
                rc, msg = check_run(d)
                worst = max(worst, rc)
                lines.append(f"  [{'PASS' if rc == 0 else 'FAIL'}] {msg}"
                             f"\n        aggregate published in {src}")
            print(f"benchmark_run_manifest: {len(scored)} scored run(s) touched")
            print("\n".join(lines))
            return worst
        if not a.run_dir:
            print("check needs a run_dir, or --tree with --changed-since",
                  file=sys.stderr)
            return 2
        rc, msg = check_run(Path(a.run_dir))
        print(msg)
        return rc

    run_dir = Path(a.run_dir)

    so = Path(a.scorer_output)
    if not so.is_file():
        print(f"scorer output not found: {so}", file=sys.stderr)
        return 2
    try:
        verdicts = extract_verdicts(_load_json(so))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"{so}: unreadable ({exc})", file=sys.stderr)
        return 2
    if not verdicts:
        print(f"{so}: no per-problem verdicts found. Refusing to write a "
              f"manifest with an empty name set — an empty set compares equal "
              f"to another empty one, so two unrelated runs would look "
              f"identical.", file=sys.stderr)
        return 2
    man = build_manifest(
        verdicts,
        dataset=Path(a.dataset) if a.dataset else None,
        plugin_version=a.plugin_version,
        image=a.image,
        scorer_argv=a.scorer_argv.split() if a.scorer_argv else [],
        scorer_output=so,
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / MANIFEST_NAME
    out.write_text(json.dumps(man, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    counts = ", ".join(f"{k}={v}" for k, v in sorted(man["counts"].items()))
    print(f"wrote {out} — {man['total']} problem(s) ({counts})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
