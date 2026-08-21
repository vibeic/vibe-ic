#!/usr/bin/env python3
"""artefact_defect_close_check.py — closing an ARTEFACT-defect issue requires
the ARTEFACT to have changed, not only the checker that detects it.

WHY THIS EXISTS (vibe-ic#381)
-----------------------------
Two issues were closed in two days by changes that added or fixed a CHECKER
while the reported artefact stayed byte-identical, and both defects were
still reproducible on `main` after the close. The issue that recorded it put
the distinction exactly:

    "A checker prevents the NEXT occurrence. It does not correct the one
     that was filed."

`core-agent-loop` step 5a-i already states the rule in prose. Prose depends
on remembering, and the close it was written for is the close it did not
stop. This program is the deterministic half.

THE TRAP THIS EXISTS TO CATCH — A DEBT REGISTER IS NOT A REPAIR
---------------------------------------------------------------
The measured instance's closing commit DID touch a file under the published
data tree: the new gate's own `*_baseline.json` debt register, into which it
recorded the still-defective instance so the gate could report PASS. So a
rule keyed on "did the range touch the data tree at all" reads that close as
clean. The rule must be keyed on **the artefact the issue named**, and a
change confined to code plus a gate's own register must not count as a
repair. That is the state the doctrine calls "reads as done and is not".

WHAT IT DOES
------------
Given an issue and the commit range that closed it:

  1. Parse the issue body for repo-relative paths under the published data
     tree (default `benchmark-data/`) that are TRACKED at the range head —
     an untracked or illustrative path is not a shipped deliverable and is
     not evidence of anything.
  2. Compute the files the range actually changed (net effect, `git diff`).
  3. Decide.

TWO TIERS, AND WHY THEY DIFFER
------------------------------
TIER A — LABELLED (`--label`, default `artefact-defect`). BLOCKING.
    The label is a human assertion that this issue reports a defective
    artefact, so no prose has to be classified and the rule is exact:

      * the range changed >=1 named artefact                     -> PASS
      * else the close carries an explicit unchanged-declaration -> PASS
        (`ARTEFACT-UNCHANGED: <>=30 chars of reason>` in the closing
        comment or in a commit message in the range — the issue's own
        second branch, "an explicit decision to leave the artefact as-is,
        with the reason, so the residue is recorded rather than implied")
      * else                                                     -> FAIL
      * labelled but the body names no tracked artefact path     -> FAIL
        (unverifiable: the label promises an artefact the check cannot
        find. An empty result is not a clean one.)

TIER B — UNLABELLED. ADVISORY (exit 0; `--enforce-advisory` promotes it).
    Nothing marks the issue, so the class has to be inferred, and inferring
    it from prose alone was MEASURED to be unusable: a body citing data-tree
    paths as REPRODUCTION EVIDENCE is indistinguishable in prose from a body
    whose cited path IS the defect. The corpus sweep for #381 put that at
    33 false positives in 35. This tier therefore does not rely on the body
    alone; it additionally requires the CLOSING CHANGE to have the
    checker-only SHAPE:

      * >=1 tracked artefact path cited in the body, AND
      * the range changed NONE of them, AND
      * every file the range changed is plugin program code, its tests, a
        version manifest, or a gate's own `*_baseline.json` register, AND
      * >=1 of those files is a checker (`*_check.py` / `*_audit.py` /
        `*_guard.py` / `*_gate*.py`).

    Anything outside that set — a doc, a skill, a flow definition, an
    unrelated data-tree file — means the change was not "only a checker"
    and no finding is emitted. The tier deliberately UNDER-reaches.

MEASURED FIRING RATE (the corpus sweep #381 demands, run before shipping)
-------------------------------------------------------------------------
Over the 114 closed issues on this repo at the time of writing, attributing
each issue's range to every commit whose message references it:

    cite >=1 TRACKED data-tree artefact              7
    ... of which the range DID change the artefact   5   (correct closes)
    ... of which the range was not code-only         2   (correct closes)
    TIER B findings                                  0

Zero on a corpus where the discriminator still separated 7 candidates into
5 + 2 is a quiet gate, not an inert one. Re-running the sweep against the
measured instance at ITS OWN closing commit — the state #381 was filed about
— produces the finding. Tier B is nonetheless left ADVISORY: 7 candidates is
too thin a corpus to justify blocking a close on an inference, and a wrong
FAIL here costs a maintainer an argument they cannot win with data.

OPERATIONAL NOTE — HOW A TIER-A FAIL IS CLEARED
------------------------------------------------
In sweep mode a tier-A FAIL is repo-wide red, which is heavy, so the way out
must not itself require a push: the `ARTEFACT-UNCHANGED:` declaration is read
from the issue's COMMENTS, so posting it on the tracker clears the gate on
the next run. Repairing the artefact clears it too. Removing the label also
clears it, and that is visible in the issue's own timeline — a silent bypass
would defeat the point, an auditable one does not.

WHY THE COMMIT RANGE AND NOT THE CLOSING COMMENT
------------------------------------------------
The first attempt at this rule looked for a commit NAMED in the closing
comment and found one in 0 of 35 candidates — the comment describes the fix,
it does not cite SHAs. The range is the durable, checkable object, and every
finding prints it.

chip-AGNOSTIC: operates on issue text, git metadata and repo-relative paths.
No design is opened, no vendor / PDK / SKU literal appears in the logic.
Reads no design artefact at all, so §4.05 is vacuous here.

USAGE
-----
    # one issue, explicit range (the pre-close gate)
    artefact_defect_close_check.py --issue-number N --range BASE..HEAD
        [--issue-file BODY.json] [--close-comment-file COMMENT.md]

    # repo sweep: the K most recently closed issues, each range derived
    # from the commits whose message references it (the CI wiring)
    artefact_defect_close_check.py --recent K

EXIT CODES
----------
    0 = PASS, ADVISORY-only, or SKIPPED (no issue API reachable)
    1 = FAIL (a labelled artefact-defect close with an untouched artefact,
        or any finding when --enforce-advisory is given)
    2 = cannot run (range or repository unusable)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

DEFAULT_LABEL = "artefact-defect"
DEFAULT_DATA_ROOT = "benchmark-data"
# The vacuous outcome, named so a reader can never mistake it for a verdict.
NO_CITATION = "NOT_APPLICABLE_NO_CITATION"


UNCHANGED_MARKER = "ARTEFACT-UNCHANGED:"
UNCHANGED_MIN_REASON = 30

# A path token in issue prose. Anchored on a known top-level directory so a
# bare word with a slash in it (a URL fragment, a module path) is not read as
# a repo path. The trailing class excludes `.` so a sentence-final period is
# not eaten into the filename.
_PATH_RE = re.compile(
    r"(?<![\w/.-])"
    r"((?:benchmark-data|benchmark_external|vibe-ic-marketplace|plugins|programs"
    r"|tools|docs|IP)/[\w./@+-]*[\w/@+-])"
)

_CHECKER_RE = re.compile(r"(_check|_audit|_guard)\.py$|(^|/)[\w.]*_gate[\w.]*\.py$")
# A gate's own debt register. Recording the still-defective instance here is
# what let the measured close read as green; it is explicitly NOT a repair.
_REGISTER_RE = re.compile(r"(_baseline|_register|_debt)\.json$")
_MANIFEST_NAMES = ("plugin.json", "marketplace.json")


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------
def _git(root: Path, *args: str, timeout: int = 120) -> Tuple[int, str]:
    try:
        r = subprocess.run(["git", "-C", str(root), *args],
                           capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return r.returncode, r.stdout


def repo_root(start: Path) -> Optional[Path]:
    rc, out = _git(start, "rev-parse", "--show-toplevel")
    return Path(out.strip()) if rc == 0 and out.strip() else None


def range_commits(root: Path, rng: str) -> List[str]:
    """The commits a range denotes. A bare rev means that ONE commit."""
    if ".." in rng:
        rc, out = _git(root, "log", "--format=%H", rng)
    else:
        rc, out = _git(root, "log", "--format=%H", "-1", rng)
    if rc != 0:
        return []
    return [c for c in out.splitlines() if c.strip()]


def _files_of_commit(root: Path, sha: str) -> Set[str]:
    """Net effect of ONE commit. Falls back to `show` for a root commit."""
    rc, out = _git(root, "diff", "--name-only", f"{sha}^", sha)
    if rc != 0:
        rc, out = _git(root, "show", "--pretty=format:", "--name-only", sha)
        if rc != 0:
            return set()
    return {l.strip() for l in out.splitlines() if l.strip()}


def changed_files(root: Path, rng: str) -> Set[str]:
    """Files a range changed, by NET effect.

    For `A..B` that is `git diff A B`: an artefact touched and reverted did
    not change, and "the artefact must have CHANGED" is the rule. For a set
    of non-contiguous commits (sweep mode) it is the union of each commit's
    own net effect, which is the closest honest equivalent.
    """
    if ".." in rng:
        base, _, head = rng.partition("..")
        head = head.lstrip(".") or "HEAD"
        rc, out = _git(root, "diff", "--name-only", base, head)
        if rc == 0:
            return {l.strip() for l in out.splitlines() if l.strip()}
        return set()
    return _files_of_commit(root, rng)


def changed_files_multi(root: Path, shas: Sequence[str]) -> Set[str]:
    changed: Set[str] = set()
    for s in shas:
        changed |= _files_of_commit(root, s)
    return changed


def tracked_at(root: Path, rev: str) -> Set[str]:
    rc, out = _git(root, "ls-tree", "-r", "--name-only", rev)
    if rc != 0:
        rc, out = _git(root, "ls-files")
        if rc != 0:
            return set()
    return {l.strip() for l in out.splitlines() if l.strip()}


def commit_messages(root: Path, shas: Sequence[str]) -> str:
    if not shas:
        return ""
    parts = []
    for s in shas:
        rc, out = _git(root, "log", "-1", "--format=%B", s)
        if rc == 0:
            parts.append(out)
    return "\n".join(parts)


# --------------------------------------------------------------------------
# classification
# --------------------------------------------------------------------------
def cited_artefacts(body: str, tracked: Set[str], data_root: str) -> List[str]:
    """Tracked paths under the published data tree that the body names.

    Untracked is excluded on purpose: a path that ships nowhere is not a
    deliverable, so a close that leaves it alone left no reader wrong.
    """
    prefix = data_root.rstrip("/") + "/"
    found = {p for p in _PATH_RE.findall(body or "") if p.startswith(prefix)}
    return sorted(p for p in found if p in tracked)


def is_code_only(paths: Set[str], data_root: str) -> Tuple[bool, List[str]]:
    """True when every changed file is plugin code, a test, a version
    manifest, or a gate's own debt register. Returns the offenders too."""
    outside: List[str] = []
    for p in sorted(paths):
        if p.endswith(_MANIFEST_NAMES):
            continue
        if "/plugins/vibe-ic/programs/" in p or p.startswith("programs/"):
            continue
        if _REGISTER_RE.search(p):
            continue
        outside.append(p)
    return (not outside), outside


def touched_checkers(paths: Set[str]) -> List[str]:
    return sorted(p for p in paths if _CHECKER_RE.search(p))


def touched_registers(paths: Set[str]) -> List[str]:
    return sorted(p for p in paths if _REGISTER_RE.search(p))


def has_unchanged_declaration(text: str) -> bool:
    """`ARTEFACT-UNCHANGED:` plus a real reason.

    The >=30-character floor is the repo's existing dialect for a written
    justification (`--scope-expanded`), reused rather than reinvented so a
    second convention does not have to be remembered.
    """
    if not text:
        return False
    for m in re.finditer(re.escape(UNCHANGED_MARKER), text):
        tail = text[m.end():]
        stop = tail.find("\n\n")
        reason = (tail[:stop] if stop != -1 else tail).strip()
        if len(reason) >= UNCHANGED_MIN_REASON:
            return True
    return False


def _titled_checker(issue: Dict) -> Optional[str]:
    """The program name an issue's TITLE names, or None.

    Word-bounded against the actual `programs/*.py` stems, so it recognises
    only programs this tree really ships. Private helpers (`_`-prefixed) are
    excluded — they are not the subject of an issue.
    """
    title = str(issue.get("title") or "")
    if not title:
        return None
    try:
        stems = sorted(
            p.stem for p in (Path(__file__).resolve().parent).glob("*.py")
            if not p.name.startswith("_"))
    except OSError:
        return None
    for stem in stems:
        if len(stem) < 8:
            continue          # too short to be an unambiguous subject
        if re.search(r"\b" + re.escape(stem) + r"\b", title):
            return stem
    return None


def classify(issue: Dict, changed: Set[str], tracked: Set[str],
             close_text: str, label: str, data_root: str) -> Dict:
    """The whole rule. Pure: no git, no network — so a test can drive it."""
    number = issue.get("number")
    labels = {str(l).lower() for l in issue.get("labels", [])}
    cited = cited_artefacts(issue.get("body") or "", tracked, data_root)
    hit = sorted(p for p in cited if p in changed)
    labelled = label.lower() in labels

    out: Dict = {
        "issue": number,
        "labelled": labelled,
        "cited_artefacts": cited,
        "artefacts_changed": hit,
        "checkers_changed": touched_checkers(changed),
        "registers_changed": touched_registers(changed),
        "verdict": "PASS",
        "tier": "A" if labelled else "B",
        "reason": "",
    }

    if labelled:
        if not cited:
            out["verdict"] = "FAIL"
            out["reason"] = (
                "labelled '%s' but the body names no TRACKED path under %s/ — "
                "the label asserts a defective artefact the check cannot "
                "locate, and an unverifiable claim is not a clean one"
                % (label, data_root.rstrip("/")))
            return out
        if hit:
            out["reason"] = "the named artefact changed in the range"
            return out
        if has_unchanged_declaration(close_text):
            out["verdict"] = "PASS"
            out["reason"] = ("artefact deliberately unchanged, declared with %s "
                             "and a recorded reason" % UNCHANGED_MARKER)
            return out
        out["verdict"] = "FAIL"
        out["reason"] = (
            "the range changed none of the named artefacts and the close "
            "carries no '%s <reason>' declaration" % UNCHANGED_MARKER)
        return out

    # Tier B — advisory inference.
    #
    # An issue whose TITLE names a checker is an issue about the CHECKER, and
    # for those "the range changed only checker code" is the CORRECT shape of
    # a fix, not a symptom. Inferring on them inverts the gate's meaning.
    #
    # MEASURED before adding this: over the 40 most recently closed issues, 6
    # carry a program name in the title and all 6 are genuinely checker
    # defects (#441 VACUOUS, #418/#417/#412 formal_proof_evidence_check,
    # #416 nda_tracked_tree_scan, #399 final_report_generate). The gate was
    # emitting ADVISORY on #441 because that issue QUOTES an artefact path
    # while explaining that a DIFFERENT issue cites it — a citation of a
    # citation, which no path regex can tell from a defect report.
    #
    # NEGATIVE CONTROL, which is what makes this narrow rather than a
    # loophole: #366 — the artefact-defect close this whole gate exists
    # because of — is titled "formal_evidence.json PASS in ... references a
    # .sby that does not exist". That names an ARTEFACT, not a program, so it
    # stays in scope and still fires. Tier A is untouched: an explicitly
    # LABELLED artefact-defect issue is never inferred away by a title.
    subject = _titled_checker(issue)
    if subject is not None:
        out["reason"] = ("the title names the checker %r, so this is a defect "
                         "IN a checker — a checker-only change is the correct "
                         "fix, not a symptom" % subject)
        return out
    if not cited:
        # NOT a PASS. "I found nothing to check" and "I checked and it is
        # clean" are different statements, and this gate spent its first
        # landing reporting them with the same word — including on vibe-ic#365,
        # one of the two issues it exists because of, whose body names its
        # subject in prose and carries no repo-relative path at all. So the
        # gate covered 1 of its 2 motivating instances while reading as if it
        # covered both. Widening the path regex to parse prose is refused
        # separately: measured 33 of 35 false positives on the corpus.
        # Non-fatal, exactly as before — only the WORD changes, because the
        # word was the false part.
        out["verdict"] = NO_CITATION
        out["reason"] = ("no tracked artefact cited — this issue's body names "
                         "no repo-relative path under %s/, so there is nothing "
                         "to compare; this is NOT a verified clean close"
                         % data_root.rstrip("/"))
        return out
    if hit:
        out["reason"] = "the cited artefact changed in the range"
        return out
    code_only, outside = is_code_only(changed, data_root)
    if not code_only:
        out["reason"] = ("the range is not a checker-only change (e.g. %s)"
                         % outside[0])
        return out
    if not out["checkers_changed"]:
        out["reason"] = "the range changed no checker"
        return out
    out["verdict"] = "ADVISORY"
    out["reason"] = (
        "the body names a shipped artefact the range never changed, and the "
        "range changed only checker code")
    return out


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------
def render(res: Dict, rng: str, repo_slug: str) -> str:
    tag = res["verdict"]
    lines = [
        "[%s] issue #%s%s" % (tag, res["issue"],
                              "  (labelled, BLOCKING)" if res["labelled"] else ""),
        "        range   : %s" % rng,
    ]
    if repo_slug:
        lines.append("        issue   : https://github.com/%s/issues/%s"
                     % (repo_slug, res["issue"]))
    lines.append("        reason  : %s" % res["reason"])
    for p in res["cited_artefacts"]:
        mark = "CHANGED " if p in res["artefacts_changed"] else "UNCHANGED"
        lines.append("        artefact: %s  %s" % (mark, p))
    for p in res["checkers_changed"]:
        lines.append("        checker : %s" % p)
    for p in res["registers_changed"]:
        lines.append("        register: %s   <- a debt-register entry is not a repair"
                     % p)
    return "\n".join(lines)


# --------------------------------------------------------------------------
# issue source
# --------------------------------------------------------------------------
def _normalise(raw: Dict) -> Dict:
    labels = raw.get("labels") or []
    names = [l.get("name", "") if isinstance(l, dict) else str(l) for l in labels]
    return {"number": raw.get("number"), "title": raw.get("title", ""),
            "body": raw.get("body") or "", "labels": names,
            "closedAt": raw.get("closedAt", "")}


def load_issue_file(path: Path, number: Optional[int]) -> Optional[Dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, list):
        for row in data:
            if number is None or row.get("number") == number:
                return _normalise(row)
        return None
    return _normalise(data)


def gh_available() -> bool:
    return shutil.which("gh") is not None


def gh_json(args: Sequence[str], timeout: int = 60):
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True,
                           timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def fetch_issue(number: int, repo: str) -> Optional[Dict]:
    data = gh_json(["issue", "view", str(number), "--repo", repo, "--json",
                    "number,title,body,labels,closedAt"])
    return _normalise(data) if isinstance(data, dict) else None


def fetch_recent_closed(k: int, repo: str) -> Optional[List[Dict]]:
    data = gh_json(["issue", "list", "--repo", repo, "--state", "closed",
                    "--limit", str(k), "--json",
                    "number,title,body,labels,closedAt"], timeout=120)
    if not isinstance(data, list):
        return None
    return [_normalise(r) for r in data]


def fetch_close_comments(number: int, repo: str) -> str:
    data = gh_json(["issue", "view", str(number), "--repo", repo, "--json",
                    "comments"])
    if not isinstance(data, dict):
        return ""
    return "\n\n".join(c.get("body") or "" for c in data.get("comments") or [])


def repo_slug(root: Path) -> str:
    env = os.environ.get("GH_REPO")
    if env:
        return env
    rc, out = _git(root, "remote", "get-url", "origin")
    if rc != 0:
        return ""
    url = out.strip()
    m = re.search(r"[:/]([\w.-]+/[\w.-]+?)(?:\.git)?$", url)
    return m.group(1) if m else ""


# --------------------------------------------------------------------------
# modes
# --------------------------------------------------------------------------
def run_single(args, root: Path) -> Tuple[int, List[Dict], List[str]]:
    shas = range_commits(root, args.range)
    if not shas:
        print("[SKIP] range '%s' resolves to no commit in %s" % (args.range, root))
        return 2, [], []
    head = args.range.split("..")[-1].lstrip(".") or shas[0]
    tracked = tracked_at(root, head)
    changed = changed_files(root, args.range)

    issue = None
    if args.issue_file:
        issue = load_issue_file(Path(args.issue_file), args.issue_number)
    slug = args.repo or repo_slug(root)
    if issue is None and not args.offline and gh_available() and slug:
        issue = fetch_issue(args.issue_number, slug)
    if issue is None:
        print("[SKIP] issue #%s unavailable (no --issue-file and no issue API)"
              % args.issue_number)
        return 2, [], []

    close_text = commit_messages(root, shas)
    if args.close_comment_file:
        try:
            close_text += "\n\n" + Path(args.close_comment_file).read_text(
                encoding="utf-8")
        except OSError:
            pass
    elif not args.offline and gh_available() and slug:
        close_text += "\n\n" + fetch_close_comments(args.issue_number, slug)

    res = classify(issue, changed, tracked, close_text, args.label,
                   args.data_root)
    res["range"] = args.range
    lines = [render(res, args.range, slug)]
    return 0, [res], lines


def run_sweep(args, root: Path) -> Tuple[int, List[Dict], List[str]]:
    slug = args.repo or repo_slug(root)
    issues: Optional[List[Dict]] = None
    if args.issues_json:
        try:
            issues = [_normalise(r) for r in
                      json.loads(Path(args.issues_json).read_text(encoding="utf-8"))]
        except (OSError, ValueError):
            issues = None
    elif not args.offline and gh_available() and slug:
        issues = fetch_recent_closed(args.recent, slug)
    if issues is None:
        # An unreachable issue API is NOT a clean sweep. Say SKIPPED and mean
        # it; the caller must not read this line as a PASS.
        print("[SKIPPED] artefact-defect close discipline: no issue corpus "
              "(no --issues-json, and the issue API is unavailable or "
              "unauthenticated). This is NOT a PASS.")
        return 0, [], []

    tracked = tracked_at(root, "HEAD")
    results: List[Dict] = []
    lines: List[str] = []
    for issue in issues[: args.recent]:
        num = issue.get("number")
        if num is None:
            continue
        rc, out = _git(root, "log", "--format=%H", "--grep", r"#%d\b" % num,
                       "-E", "HEAD")
        shas = [c for c in out.splitlines() if c.strip()] if rc == 0 else []
        if not shas:
            continue
        changed = changed_files_multi(root, shas)
        close_text = commit_messages(root, shas)
        res = classify(issue, changed, tracked, close_text, args.label,
                       args.data_root)
        rng = ",".join(s[:9] for s in shas)
        res["range"] = rng
        if res["verdict"] in ("FAIL", "ADVISORY"):
            # A labelled FAIL needs the closing comment before it is asserted:
            # the declaration branch lives there, and refusing to look would
            # manufacture the finding.
            if (res["verdict"] == "FAIL" and res["labelled"] and res["cited_artefacts"]
                    and not args.offline and gh_available() and slug):
                extra = fetch_close_comments(num, slug)
                if extra:
                    res = classify(issue, changed, tracked,
                                   close_text + "\n\n" + extra, args.label,
                                   args.data_root)
                    res["range"] = rng
            if res["verdict"] in ("FAIL", "ADVISORY"):
                lines.append(render(res, rng, slug))
        results.append(res)
    n_vac = sum(1 for r in results if r["verdict"] == NO_CITATION)
    print("swept %d closed issue(s) with an attributable range; %d cited a "
          "tracked artefact; %d cited NONE and were not checkable (%s)"
          % (len(results), sum(1 for r in results if r["cited_artefacts"]),
             n_vac, NO_CITATION))
    return 0, results, lines


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="closing an artefact-defect issue requires the ARTEFACT "
                    "to have changed, not only a checker (vibe-ic#381)")
    ap.add_argument("--issue-number", type=int,
                    help="the issue being closed (single-issue mode)")
    ap.add_argument("--range", metavar="BASE..HEAD",
                    help="the commit range that closes it; a bare rev means "
                         "that one commit")
    ap.add_argument("--recent", type=int, metavar="K",
                    help="sweep mode: the K most recently closed issues")
    ap.add_argument("--issue-file", metavar="JSON",
                    help="issue JSON (single object or list) instead of the API")
    ap.add_argument("--issues-json", metavar="JSON",
                    help="sweep corpus as JSON instead of the API")
    ap.add_argument("--close-comment-file", metavar="MD",
                    help="the closing comment text, for the unchanged-declaration")
    ap.add_argument("--repo", metavar="OWNER/NAME", default="",
                    help="repository slug (default: the origin remote)")
    ap.add_argument("--repo-root", metavar="DIR", default=".",
                    help="repository to read (default: %(default)s)")
    ap.add_argument("--label", default=DEFAULT_LABEL,
                    help="the artefact-defect label (default: %(default)s)")
    ap.add_argument("--data-root", default=DEFAULT_DATA_ROOT,
                    help="published-deliverable tree (default: %(default)s)")
    ap.add_argument("--offline", action="store_true",
                    help="never call the issue API")
    ap.add_argument("--enforce-advisory", action="store_true",
                    help="make a tier-B advisory finding exit 1")
    ap.add_argument("--json", metavar="OUT", help="write the findings as JSON")
    args = ap.parse_args(argv)

    root = repo_root(Path(args.repo_root).resolve())
    if root is None:
        print("[SKIP] %s is not inside a git repository" % args.repo_root)
        return 2

    if args.recent is not None:
        rc, results, lines = run_sweep(args, root)
    elif args.issue_number is not None and args.range:
        rc, results, lines = run_single(args, root)
    else:
        ap.error("give either --recent K, or both --issue-number N and --range")
        return 2  # pragma: no cover - argparse exits

    if rc == 2:
        if args.json:
            Path(args.json).write_text(json.dumps(
                {"verdict": "SKIP", "findings": []}, indent=1), encoding="utf-8")
        return 2

    fails = [r for r in results if r["verdict"] == "FAIL"]
    advis = [r for r in results if r["verdict"] == "ADVISORY"]
    for line in lines:
        print(line)

    if args.json:
        Path(args.json).write_text(json.dumps(
            {"verdict": "FAIL" if fails else ("ADVISORY" if advis else "PASS"),
             "findings": results}, indent=1, ensure_ascii=False), encoding="utf-8")

    if fails:
        print("[FAIL] %d labelled artefact-defect close(s) left the artefact "
              "unchanged with no recorded reason" % len(fails))
        return 1
    if advis:
        print("[ADVISORY] %d close(s) look like a checker-only fix to a "
              "reported artefact defect — read the finding, then either "
              "repair the artefact or record why it stays" % len(advis))
        return 1 if args.enforce_advisory else 0
    if results:
        print("[PASS] no artefact-defect close left its artefact unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
