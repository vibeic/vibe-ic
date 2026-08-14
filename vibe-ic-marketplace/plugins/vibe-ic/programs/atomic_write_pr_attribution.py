#!/usr/bin/env python3
"""Which OPEN PR owns each non-atomic declared-report write (vibe-ic#1468).

WHY THIS EXISTS
===============
`atomic_artifact_write_check` (vibe-ic#1082) answers "does THIS TREE contain a
new offender". It cannot answer "WHOSE PR put it there", and group (d) of the
BATCH IDX round needs the second question: seventeen sites that each have to be
converted on the branch that carries them, because none of them is on main yet.

The map in vibe-ic#1468 answered it by hand, and the method under-reported. It
built ONE tree, dropping each PR's new `programs/*.py` into a copy of #1110, and
then ran the gate once. Four filenames are added by more than one open PR, so
one version overwrote the other and only the survivor was ever scanned. The
issue named that limitation itself -- "It does NOT prove the earlier PR is
clean" -- and re-measuring per (file, PR) shows it fired in every one of the
four cases: #1145, #1122, #1257 and #1253 each carry a site of their own that
the single-tree run could not see.

    artefact_digest_ledger.py            #1165:299   AND  #1145:229
    step_metrics.py                      #1205:214   AND  #1122:279, :316
    bundled_attribution_notice_check.py  #1328:263   AND  #1257:287
    vendored_attribution_retained_check  #1309:398   AND  #1253:183

Five PRs were told by that map that they had nothing to fix. A map that misses
an offender is worse than no map, because the round is worked FROM it and
whoever lands last inherits the red.

WHAT IT MEASURES
================
For every PR in scope, for every top-level `programs/*.py` the PR adds or
modifies, the PR's OWN head version of that file is scanned with the gate's own
`scan_program`. No staging, no shared tree, so two PRs carrying the same
filename are two measurements and neither can hide the other.

A site is ATTRIBUTED to a PR when all three hold:

  * the gate's `scan_program` finds a non-atomic write to a declared report
    destination in that PR's version of the file, and
  * the filename is not named in the residual baseline -- a name already in the
    residual is the tree's debt, not this PR's, and the gate treats it that way,
    and
  * the PR INTRODUCED it: the file is absent from main, or main's version of it
    is clean.

That third clause is the one the hand method had no way to apply, and dropping
it costs precision rather than recall. On the 2026-08-14 population it is the
difference between attributing `perc_signoff_check.py` to #1187 and noticing
that main already writes that file non-atomically at a different line -- #1187
merely edited a file that was already an offender, and telling its author to
convert it would hand them someone else's debt. Both such files are converted by
#1110 already.

WHAT IT REFUSES TO DO
=====================
* Report a zero it did not measure. A PR whose file list or whose head blob
  could not be read is not a PR with no offenders. Any such failure makes the
  whole run rc 2, and the sites that WERE found are printed as a FLOOR, labelled
  as one. This is the `org_open_work_poll` rule (vibe-ic#554) applied to a
  second population: "I asked and got nothing" and "I could not ask" may never
  encode the same way.
* Run at all without the gate. `atomic_artifact_write_check.py` and its residual
  arrive in #1110 and are not on main; with either missing this is rc 2 and says
  which path was missing, rather than scanning with a rule of its own. A second
  copy of the rule is how the two `branch_is_ours` copies in vibeic-eda#29 came
  to disagree, and the answer here has to be the gate's answer or it is worth
  nothing.

exit 0 = no attributable site in scope
exit 1 = at least one site attributed to a PR
exit 2 = NOT CHECKED -- the gate is absent, or some PR could not be read
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

RC_CLEAN, RC_ATTRIBUTED, RC_NOT_CHECKED = 0, 1, 2

DEFAULT_OWNER_REPO = "vibeic/vibe-ic"
#: Relative to the git top level. The gate globs this directory, so "a program"
#: means a top-level `*.py` here and nothing deeper.
DEFAULT_PROGRAMS_REL = "vibe-ic-marketplace/plugins/vibe-ic/programs"

#: Every subprocess bound in this file is under a minute, deliberately. The
#: landing harness runs at --timeout=180 --timeout-method=thread, so an inner
#: bound above that kills the SESSION instead of this one test and every other
#: result in the run is lost unnamed. `_gh_cli.gh` defaults to 120s; it is
#: always called with an explicit bound here for that reason.
SUBPROCESS_TIMEOUT = 45
#: Refs are fetched in batches so one `git fetch` stays inside the bound above.
FETCH_BATCH = 20


# --------------------------------------------------------------------------
# process helpers
# --------------------------------------------------------------------------
def _run(args: Sequence[str], cwd: Optional[Path] = None,
         timeout: int = SUBPROCESS_TIMEOUT) -> Tuple[int, bytes, bytes]:
    """Run a command; return (rc, stdout, stderr). Never raises.

    A timeout is rc 124, not an empty result, for the same reason `_gh_cli`
    separates 126/127 from gh's own codes: the caller has to be able to tell a
    clean answer from no answer.
    """
    try:
        r = subprocess.run(list(args), cwd=str(cwd) if cwd else None,
                           capture_output=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, b"", f"timeout after {timeout}s: {' '.join(args)}".encode()
    except (OSError, subprocess.SubprocessError) as exc:
        return 126, b"", f"{type(exc).__name__}: {exc}".encode()


# --------------------------------------------------------------------------
# the gate, loaded rather than reimplemented
# --------------------------------------------------------------------------
def load_gate(programs_dir: Path, baseline: Optional[Path]) -> Tuple[Any, Set[str], str]:
    """Import the gate's `scan_program` and read its residual baseline.

    Returns (scan_program, baseline_names, "") or (None, set(), reason).
    """
    checker = programs_dir / "atomic_artifact_write_check.py"
    if not checker.is_file():
        return None, set(), f"{checker} is absent (it arrives in vibe-ic#1110)"
    bl = baseline or (programs_dir / "_atomic_artefact_residual.json")
    if not bl.is_file():
        return None, set(), f"{bl} is absent (it arrives in vibe-ic#1110)"
    try:
        names = set(json.loads(bl.read_text()).get("offenders", []))
    except (OSError, ValueError) as exc:
        return None, set(), f"{bl} is unreadable: {exc}"

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_atomic_gate_for_attribution", checker)
    if spec is None or spec.loader is None:            # pragma: no cover
        return None, set(), f"{checker} could not be loaded as a module"
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:                           # pragma: no cover
        return None, set(), f"{checker} failed to import: {exc}"
    fn = getattr(mod, "scan_program", None)
    if fn is None:
        return None, set(), f"{checker} has no scan_program()"
    return fn, names, ""


# --------------------------------------------------------------------------
# PR enumeration
# --------------------------------------------------------------------------
def open_pr_numbers(owner_repo: str) -> Tuple[Optional[List[int]], str]:
    """Every open PR number, or (None, reason). `--paginate` so there is no cap.

    A capped listing and a complete one are byte-identical (vibe-ic#554), so the
    cap is refused rather than raised. `--jq` over `--paginate` emits
    newline-delimited scalars, not one JSON document; they are parsed as such.
    """
    rc, out, err = _run(["gh", "api", "--paginate",
                         f"repos/{owner_repo}/pulls?state=open&per_page=100",
                         "--jq", ".[].number"])
    if rc == 127:
        return None, "gh is not on PATH, so the open-PR list could not be read"
    if rc != 0:
        return None, (f"could not list open PRs (rc={rc}): "
                      f"{err.decode('utf-8', 'replace').strip()[:200]}")
    try:
        return sorted({int(x) for x in out.split()}), ""
    except ValueError as exc:
        return None, f"could not parse the open PR numbers gh returned: {exc}"


def pr_program_files(owner_repo: str, pr: int, programs_rel: str,
                     cache_dir: Optional[Path], offline: bool
                     ) -> Tuple[Optional[List[Tuple[str, str]]], str]:
    """[(status, filename)] for the PR's top-level programs/*.py changes."""
    cache = (cache_dir / f"{pr}.tsv") if cache_dir else None
    raw: Optional[str] = None
    if cache is not None and cache.is_file():
        try:
            raw = cache.read_text()
        except OSError as exc:
            return None, f"#{pr}: cache {cache} unreadable: {exc}"
    if raw is None:
        if offline:
            return None, f"#{pr}: --offline and no cached file list at {cache}"
        rc, out, err = _run(["gh", "api", "--paginate",
                             f"repos/{owner_repo}/pulls/{pr}/files?per_page=100",
                             "--jq", r".[] | [.status, .filename] | @tsv"])
        if rc != 0:
            return None, (f"#{pr}: could not list changed files "
                          f"(rc={rc}) {err.decode('utf-8', 'replace').strip()[:200]}")
        raw = out.decode("utf-8", "replace")
        if cache is not None:
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                _atomic_write_text(cache, raw)
            except OSError:                            # pragma: no cover
                pass                                   # a cache miss is not a failure

    prefix = programs_rel.rstrip("/") + "/"
    out_rows: List[Tuple[str, str]] = []
    for line in raw.splitlines():
        status, _, name = line.partition("\t")
        if status not in ("added", "modified") or not name.startswith(prefix):
            continue
        rest = name[len(prefix):]
        if "/" in rest or not rest.endswith(".py"):
            continue                                   # the gate globs one level
        out_rows.append((status, name))
    return out_rows, ""


# --------------------------------------------------------------------------
# blob access
# --------------------------------------------------------------------------
def fetch_pr_heads(repo: Path, owner_repo: str, prs: Sequence[int],
                   ref_template: str, remote: str) -> List[str]:
    """Fetch every PR head into a local ref. Returns the failures, by name."""
    problems: List[str] = []
    prs = list(prs)
    for i in range(0, len(prs), FETCH_BATCH):
        batch = prs[i:i + FETCH_BATCH]
        refspecs = [f"+refs/pull/{n}/head:refs/heads/{ref_template.format(pr=n)}"
                    for n in batch]
        rc, _, err = _run(["git", "fetch", "--quiet", remote, *refspecs], cwd=repo)
        if rc != 0:
            problems.append(f"git fetch of PRs {batch[0]}..{batch[-1]} failed "
                            f"(rc={rc}): {err.decode('utf-8', 'replace').strip()[:200]}")
    return problems


def show_blob(repo: Path, ref: str, path: str) -> Tuple[Optional[bytes], str]:
    rc, out, err = _run(["git", "show", f"{ref}:{path}"], cwd=repo)
    if rc != 0:
        return None, f"git show {ref}:{path} rc={rc} {err.decode('utf-8', 'replace').strip()[:160]}"
    return out, ""


# --------------------------------------------------------------------------
# attribution
# --------------------------------------------------------------------------
def _scan_bytes(scan_program, blob: bytes, scratch: Path) -> List[Dict[str, Any]]:
    """Run the gate's per-file rule over bytes, via a temp file it can read."""
    scratch.write_bytes(blob)
    return list(scan_program(scratch))


def attribute(repo: Path, owner_repo: str, prs: Sequence[int], programs_rel: str,
              scan_program, baseline: Set[str], main_ref: str,
              ref_template: str, cache_dir: Optional[Path], offline: bool,
              remote: str) -> Dict[str, Any]:
    problems: List[str] = []
    if not offline:
        problems.extend(fetch_pr_heads(repo, owner_repo, prs, ref_template, remote))

    #: main's own verdict per filename, so a file that ALREADY offends on main
    #: is never billed to the PR that merely edited it. Cached: many PRs touch
    #: the same file and `git show` is the expensive part.
    main_verdict: Dict[str, Optional[bool]] = {}
    sites: List[Dict[str, Any]] = []
    scanned = 0

    with tempfile.TemporaryDirectory() as td:
        scratch = Path(td) / "candidate.py"
        for pr in prs:
            rows, why = pr_program_files(owner_repo, pr, programs_rel,
                                         cache_dir, offline)
            if rows is None:
                problems.append(why)
                continue
            for status, path in rows:
                name = path.rsplit("/", 1)[1]
                ref = ref_template.format(pr=pr)
                blob, why = show_blob(repo, ref, path)
                if blob is None:
                    problems.append(f"#{pr}: {why}")
                    continue
                scanned += 1
                hits = _scan_bytes(scan_program, blob, scratch)
                if not hits or name in baseline:
                    continue

                if name not in main_verdict:
                    mblob, _ = show_blob(repo, main_ref, path)
                    if mblob is None:
                        main_verdict[name] = None      # absent from main
                    else:
                        main_verdict[name] = bool(
                            _scan_bytes(scan_program, mblob, scratch))
                on_main = main_verdict[name]
                for h in hits:
                    sites.append({
                        "pr": pr, "file": name, "path": path, "status": status,
                        "line": h["line"], "form": h["form"],
                        # None = absent from main; False = main is clean, the PR
                        # introduced it; True = main already offends, so this is
                        # the tree's debt and not this PR's to pay.
                        "already_offends_on_main": on_main,
                        "introduced_by_pr": on_main is not True,
                    })

    sites.sort(key=lambda s: (s["file"], s["pr"], s["line"]))
    attributed = [s for s in sites if s["introduced_by_pr"]]
    return {
        "prs_in_scope": len(prs),
        "file_versions_scanned": scanned,
        "attributed_sites": attributed,
        "pre_existing_sites": [s for s in sites if not s["introduced_by_pr"]],
        "attributed_site_count": len(attributed),
        "attributed_file_count": len({s["file"] for s in attributed}),
        "attributed_pr_count": len({s["pr"] for s in attributed}),
        "baseline_size": len(baseline),
        "problems": problems,
        "complete": not problems,
    }


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------
def _atomic_write_text(dest: Path, text: str) -> None:
    """Write whole or not at all -- this program's own report included.

    Uses `_atomic_artefact.write_json` when the tree has it; the fallback is the
    same tmp+`os.replace` shape rather than a `write_text`, because a report
    that names non-atomic writers must not be one (vibe-ic#1082).
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(dest.parent), prefix=f".{dest.name}.")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:                                # pragma: no cover
            pass
        raise


def write_report(dest: Path, programs_dir: Path, report: Dict[str, Any]) -> None:
    sys.path.insert(0, str(programs_dir))
    try:
        from _atomic_artefact import write_json       # type: ignore
        write_json(str(dest), report)
        return
    except Exception:                                  # noqa: BLE001
        pass
    finally:
        if sys.path and sys.path[0] == str(programs_dir):
            sys.path.pop(0)
    _atomic_write_text(dest, json.dumps(report, indent=2) + "\n")


def render(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    floor = "" if report["complete"] else " (a FLOOR -- see NOT CHECKED below)"
    lines.append(
        f"atomic_write_pr_attribution: {report['prs_in_scope']} PR(s) in scope; "
        f"{report['file_versions_scanned']} file version(s) scanned; "
        f"{report['attributed_site_count']} site(s) across "
        f"{report['attributed_file_count']} program(s) and "
        f"{report['attributed_pr_count']} PR(s){floor}")
    for s in report["attributed_sites"]:
        where = "new program" if s["already_offends_on_main"] is None \
            else "main is clean"
        lines.append(f"   {s['file']}:{s['line']:<5} {s['form']:<16} "
                     f"#{s['pr']:<5} [{s['status']}, {where}]")
    pre = report["pre_existing_sites"]
    if pre:
        lines.append(f"  not attributed -- already non-atomic on main, so the "
                     f"tree's debt and not the PR's ({len(pre)}):")
        for s in pre:
            lines.append(f"   {s['file']}:{s['line']}  #{s['pr']}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".", help="git checkout to read blobs from")
    ap.add_argument("--owner-repo", default=DEFAULT_OWNER_REPO)
    ap.add_argument("--pr", type=int, action="append", dest="prs",
                    help="PR number; repeatable. Default: every open PR.")
    ap.add_argument("--programs-dir", default=None,
                    help="where the gate and its residual live; "
                         "default: this program's own directory")
    ap.add_argument("--programs-rel", default=DEFAULT_PROGRAMS_REL,
                    help="path of the programs dir INSIDE the PR trees")
    ap.add_argument("--baseline", default=None,
                    help="default <programs-dir>/_atomic_artefact_residual.json")
    ap.add_argument("--main-ref", default="origin/main",
                    help="ref standing for 'already the tree's debt'")
    ap.add_argument("--ref-template", default="pr{pr}",
                    help="local ref a PR head is fetched into")
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--cache-dir", default=None,
                    help="reuse/record per-PR changed-file lists here")
    ap.add_argument("--offline", action="store_true",
                    help="never call gh or git fetch; require --cache-dir and "
                         "refs already present")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve()
    # Default to this file's OWN directory, the way the gate does: the
    # instrument is whatever ships next to it, not whatever the cwd happens to
    # contain. `--programs-dir` still points it at another checkout -- which is
    # how it runs today, since the gate is not on main yet.
    programs_dir = Path(args.programs_dir).resolve() if args.programs_dir \
        else Path(__file__).resolve().parent
    baseline_path = Path(args.baseline).resolve() if args.baseline else None

    scan_program, baseline, why = load_gate(programs_dir, baseline_path)
    if scan_program is None:
        print(f"NOT CHECKED: {why}", file=sys.stderr)
        return RC_NOT_CHECKED

    prs = sorted(set(args.prs)) if args.prs else None
    if prs is None:
        if args.offline:
            print("NOT CHECKED: --offline needs an explicit --pr; the open-PR "
                  "list can only come from gh", file=sys.stderr)
            return RC_NOT_CHECKED
        prs, why = open_pr_numbers(args.owner_repo)
        if prs is None:
            print(f"NOT CHECKED: {why}", file=sys.stderr)
            return RC_NOT_CHECKED

    report = attribute(repo, args.owner_repo, prs, args.programs_rel,
                       scan_program, baseline, args.main_ref,
                       args.ref_template,
                       Path(args.cache_dir) if args.cache_dir else None,
                       args.offline, args.remote)
    print(render(report))
    if args.json_out:
        write_report(Path(args.json_out), programs_dir, report)

    if not report["complete"]:
        # A run that could not read every PR has not established that the PRs it
        # could not read are clean. The sites above stand; the COUNT does not.
        print(f"[NOT CHECKED] {len(report['problems'])} PR(s) could not be "
              f"read, so the count above is a floor:", file=sys.stderr)
        for p in report["problems"]:
            print(f"   {p}", file=sys.stderr)
        return RC_NOT_CHECKED
    if report["attributed_site_count"]:
        print(f"[FAIL] {report['attributed_site_count']} non-atomic declared-"
              f"report write(s) belong to an open PR. Each is converted on its "
              f"own branch:\n  from _atomic_artefact import write_json   "
              f"# vibe-ic#1082", file=sys.stderr)
        return RC_ATTRIBUTED
    print("[PASS] no open PR carries a new non-atomic declared-report write.")
    return RC_CLEAN


if __name__ == "__main__":
    sys.exit(main())
