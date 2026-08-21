#!/usr/bin/env python3
"""Every tracked .json / .yaml parses — read from the INDEX, never from disk.

WHY THIS EXISTS
===============
The retired `ci.yml` and `gatekeeper-ci.yml` both ran a step called
"Validate all JSON + YAML". When GitHub Actions was disabled and
`tools/gatekeeper-land.sh` took over, that step was not carried across. Nobody
noticed, because the tree happened to be clean and a check that does not exist
looks exactly like a check that passes.

Measured on 2026-07-30 by corrupting `benchmark/CAPTURE_ROUTING.json` — truncated
mid-string, unparseable — and running the landing gates: all eight cheap-tier
gates PASSED and `plugin_full_audit` exited 0. A structurally broken config file
could be landed on main with nothing objecting. That file is read by the flow
dispatcher; a parse error there is every step that consults the routing table
failing at once, at the point of use, on somebody else's machine.

WHY IT READS BLOBS AND NOT FILES
================================
The first version walked the disk with `Path.read_text()`, and
`gate_host_independence_check` caught it immediately — which is the whole reason
that gate exists (vibe-ic#447).

This repository tracks 160 symlinks, 114 of them pointing at `.json`/`.yaml`.
Their targets are benchmark artefacts. In a working checkout many of those
targets are present, so the symlink resolves and the file parses; in a fresh
`git worktree` — tracked content only — they are absent and the same path is
unreadable. Same commit, different verdict line, decided by run leftovers that
are not in the commit at all.

So the question is asked of the INDEX. `git ls-files -s` gives the mode and the
blob sha, `git cat-file --batch` gives the content, and neither depends on what
is lying around this machine. Symlinks (mode 120000) are skipped by mode rather
than by guessing from the name: a symlink's blob is its target PATH, so parsing
it as JSON would fail for a file that is not a JSON file at all.

WHAT IT REFUSES TO DO
=====================
* Report success having checked NOTHING. `git ls-files` returning no candidates
  means the scan is broken or this is not the repository — never that the repo
  has no config. rc 2, because a scan of zero files trivially finds zero errors,
  and that is the shape this gate exists to reject.
* Skip YAML in silence when PyYAML is missing. Tracked YAML going unparsed is a
  fact about the RUN — rc 2 and say so, rather than pass on the JSON half.
* Report a blob it could not read as a parse failure. `git cat-file` failing is
  "I could not ask", and it is counted and named separately.

Exit: 0 everything parsed, 1 something did not, 2 could not check.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

RC_OK, RC_UNPARSEABLE, RC_CANNOT_CHECK = 0, 1, 2

_JSON_SUFFIXES = (".json",)
_YAML_SUFFIXES = (".yaml", ".yml")
#: git's mode for a symlink. Its blob holds the TARGET PATH, not the target's
#: content, so it is not a config file and must not be parsed as one.
_SYMLINK_MODE = "120000"


def _index_entries(root: Path) -> Tuple[List[Tuple[str, str]], str]:
    """[(blob_sha, path)] for tracked, non-symlink config files — or ([], reason).

    Read from the index rather than the worktree: the verdict must depend on the
    commit and nothing else.
    """
    try:
        r = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "-z"],
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return [], f"{type(exc).__name__}: {exc}"
    if r.returncode != 0:
        return [], f"git ls-files exited {r.returncode}: {r.stderr.strip()[:160]}"

    out: List[Tuple[str, str]] = []
    for rec in r.stdout.split("\0"):
        if not rec:
            continue
        # "<mode> <sha> <stage>\t<path>"
        meta, _, path = rec.partition("\t")
        bits = meta.split()
        if len(bits) < 2 or not path:
            continue
        mode, sha = bits[0], bits[1]
        if mode == _SYMLINK_MODE:
            continue
        if path.endswith(_JSON_SUFFIXES) or path.endswith(_YAML_SUFFIXES):
            out.append((sha, path))
    return out, ""


def _read_blobs(root: Path, entries: List[Tuple[str, str]]) -> Tuple[Dict[str, bytes], List[str]]:
    """sha → content via one `git cat-file --batch`, plus the shas it could not give."""
    if not entries:
        return {}, []
    shas = sorted({sha for sha, _ in entries})
    try:
        # Bytes in AND bytes out: blob content is not necessarily UTF-8, and a
        # decode failure is a finding this gate must report rather than die on.
        r = subprocess.run(["git", "-C", str(root), "cat-file", "--batch"],
                           input=("\n".join(shas) + "\n").encode("ascii"),
                           capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        return {}, [f"<batch failed: {type(exc).__name__}: {exc}>"]

    blobs: Dict[str, bytes] = {}
    missing: List[str] = []
    buf, pos = r.stdout, 0
    while pos < len(buf):
        nl = buf.find(b"\n", pos)
        if nl < 0:
            break
        header = buf[pos:nl].decode("utf-8", "replace").split()
        pos = nl + 1
        if len(header) < 3:                       # "<sha> missing"
            if header:
                missing.append(header[0])
            continue
        sha, size = header[0], int(header[2])
        blobs[sha] = buf[pos:pos + size]
        pos += size + 1                           # trailing newline
    return blobs, missing


def check(root: Path) -> dict:
    entries, err = _index_entries(root)
    if err:
        return {"error": err}
    if not entries:
        return {"error": "no tracked .json or .yaml blob was found; a scan that "
                         "examined nothing cannot report a clean tree"}

    js = [(s, p) for s, p in entries if p.endswith(_JSON_SUFFIXES)]
    ys = [(s, p) for s, p in entries if p.endswith(_YAML_SUFFIXES)]

    yaml_mod = None
    if ys:
        try:
            import yaml as yaml_mod  # noqa: F401
        except ImportError:
            yaml_mod = None

    blobs, missing = _read_blobs(root, entries)
    unparseable: List[Tuple[str, str]] = []
    unreadable: List[str] = [p for s, p in entries if s in missing]

    def _decode(sha: str, path: str):
        raw = blobs.get(sha)
        if raw is None:
            unreadable.append(path)
            return None
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            unparseable.append((path, f"UnicodeDecodeError: {exc}"))
            return None

    for sha, path in js:
        text = _decode(sha, path)
        if text is None:
            continue
        try:
            json.loads(text)
        except ValueError as exc:
            unparseable.append((path, str(exc)[:110]))

    if yaml_mod is not None:
        for sha, path in ys:
            text = _decode(sha, path)
            if text is None:
                continue
            try:
                list(yaml_mod.safe_load_all(text))
            except Exception as exc:              # yaml.YAMLError et al
                unparseable.append((path, str(exc).replace("\n", " ")[:110]))

    return {"json_total": len(js), "yaml_total": len(ys),
            "yaml_checked": bool(yaml_mod) or not ys,
            "unparseable": sorted(unparseable),
            "unreadable": sorted(set(unreadable))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)

    root = Path(a.root).resolve()
    try:
        res = check(root)
    except Exception as exc:                      # noqa: BLE001 — see below
        # An uncaught exception exits 1, and rc 1 here MEANS "a tracked file does
        # not parse". A crash would therefore be read as a finding about the
        # tree. It happened once already, in the first version of this file: a
        # str/bytes mix-up in the `git cat-file` call produced a TypeError and
        # the gate reported the landing as having unparseable config.
        # "I could not run" is rc 2, and the docstring's promise that check()
        # never raises is enforced HERE rather than assumed.
        print(f"[NOT CHECKED] {type(exc).__name__}: {exc}", file=sys.stderr)
        return RC_CANNOT_CHECK
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(
            {"program": "tracked_json_yaml_parses_check", **res}, indent=2) + "\n",
            encoding="utf-8")

    if "error" in res:
        print(f"[NOT CHECKED] {res['error']}", file=sys.stderr)
        return RC_CANNOT_CHECK

    if not res["yaml_checked"]:
        print(f"[NOT CHECKED] PyYAML is not importable, so {res['yaml_total']} "
              f"tracked YAML blob(s) were not parsed. The JSON half passing is "
              f"not the check this gate claims to be.", file=sys.stderr)
        return RC_CANNOT_CHECK

    if res["unreadable"]:
        print(f"[NOT CHECKED] {len(res['unreadable'])} blob(s) named in the index "
              f"could not be read back: {', '.join(res['unreadable'][:4])}",
              file=sys.stderr)
        return RC_CANNOT_CHECK

    if res["unparseable"]:
        print(f"[FAIL] {len(res['unparseable'])} tracked file(s) do not parse:",
              file=sys.stderr)
        for rel, why in res["unparseable"][:20]:
            print(f"    {rel}\n        {why}", file=sys.stderr)
        return RC_UNPARSEABLE

    n = res["json_total"] + res["yaml_total"]
    print(f"[PASS] {n} tracked config blob(s) parse "
          f"({res['json_total']} JSON, {res['yaml_total']} YAML; symlinks are "
          f"skipped by mode, not by name).", file=sys.stderr)
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
