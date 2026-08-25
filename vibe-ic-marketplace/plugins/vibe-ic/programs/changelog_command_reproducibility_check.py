#!/usr/bin/env python3
"""
changelog_command_reproducibility_check.py — anti-fabrication gate
(v1.6.43).

Doctrine: any shell command quoted in CHANGELOG.md / plugin.json /
marketplace.json (e.g. `$ bash tools/ci/run_plugin_self_audit.sh`,
`$ python3 programs/foo.py <project>`) must reference a target that
actually exists in the plugin tree. CHANGELOG examples are de-facto
documentation; if the command can't run because the target script is
missing, the example is fabricated.

Real-world inspiration (v1.6.42 escape):
  CHANGELOG.md:13 and CHANGELOG.md:162 quoted
      $ bash tools/ci/run_plugin_self_audit.sh
  but the script did not exist at that path. The 4 self-audit gates were
  individually invocable but the batch-runner shown to users was a
  phantom. `changelog_metric_reproducibility_check` couldn't catch it
  because it only watches numerics.

Patterns scanned:
  * Lines starting with `$ ` inside fenced code blocks
  * `bash <relative-path>`              → file must exist
  * `python3 <relative-path>.py …`      → file must exist
  * `pytest …`                          → pytest must be importable
  * `make <target>`                     → Makefile must exist with target
  * Bare-word commands not in this set are SKIPPED (not flagged) —
    we only audit invocations that reference a path inside the plugin.

Acceptable forms:
    $ bash tools/ci/run_plugin_self_audit.sh
    $ python3 programs/literal_verdict_keyword_check.py .
    $ python3 -m pytest tests/

Usage:
    python3 changelog_command_reproducibility_check.py <plugin_root>
                                                       [--json <out>]

Exit codes:
    0  PASS / VACUOUS_PASS
    1  FAIL — at least one quoted command's target is missing
    2  argument or I/O error

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Tuple


# Match a leading-`$ ` shell prompt anywhere on the line (allow indentation
# inside fenced blocks). Captures the rest of the line.
_PROMPT_RE = re.compile(r"^\s*\$\s+(?P<cmd>.+?)\s*$")

# Audit only the first token + path-like argument of these well-known
# command verbs. Anything else is silently skipped.
_AUDITED_VERBS: Tuple[str, ...] = ("bash", "sh", "python3", "python",
                                   "pytest", "make")


#: THE DENOMINATOR THIS GATE'S PASS STANDS ON.
#: `gate_discloses_denominator_check` measured this program answering PASS
#: over an EMPTY tree while saying only "PASS: every ... is reproducible" —
#: an output indistinguishable from a real clean run. A pass that does not
#: say what it looked at is the same shape as a scan that looked at nothing.
#: Recorded by `audit()` and printed by `main()`; nothing else reads it, and
#: no signature changed, so every existing caller and test is untouched.
_SCANNED = {"files": 0, "items": 0}


@dataclass
class CommandFinding:
    file: str
    line: int
    command: str
    rule: str
    detail: str = ""


def _audit_files(plugin_root: Path) -> List[Path]:
    """Scan plugin CHANGELOG, plugin.json, marketplace.json **plus**
    repo-root README and every `.md` under `docs/` (v1.6.48). Quoted
    `$ <cmd>` examples in user-facing docs must reference real
    targets, not phantom scripts."""
    out: List[Path] = []
    for cand in (
        plugin_root / "CHANGELOG.md",
        plugin_root / ".claude-plugin" / "plugin.json",
        plugin_root.parent / ".claude-plugin" / "marketplace.json",
        plugin_root.parent / "CHANGELOG.md",
    ):
        if cand.is_file():
            out.append(cand)
    repo_root = plugin_root.parent.parent.parent
    readme = repo_root / "README.md"
    if readme.is_file():
        out.append(readme)
    docs_dir = repo_root / "docs"
    if docs_dir.is_dir():
        out.extend(sorted(docs_dir.rglob("*.md")))
    return out


def _check_command(cmd: str, plugin_root: Path
                   ) -> Optional[Tuple[str, str]]:
    """Return (rule, detail) if `cmd` is broken, else None.

    Conservative: any verb not in `_AUDITED_VERBS` is treated as
    out-of-scope (e.g. `git status`, `docker ps`). This keeps the gate
    focused on plugin-internal references."""
    toks = cmd.split()
    if not toks:
        return None
    verb = toks[0]
    if verb not in _AUDITED_VERBS:
        return None

    # Plugin documents several CWDs in practice: examples invoked from
    # the plugin tree (relative to plugin_root), from the marketplace repo
    # root (`marketplace/plugins/<plugin>` -> repo root; the canonical batch
    # runner lives at repo-root `tools/ci/`), and — the commonest of all —
    # from INSIDE a tool directory, because that is where a person stands
    # when running one tool after another:
    #
    #     $ python3 ppa_head_to_head_check.py REC.json
    #     $ python3 _ppa/backends/openroad.py --log … --json …
    #
    # Both of those are honest transcripts of a command that ran; resolving
    # them only against the two roots reported them MISSING_SCRIPT and asked
    # an author to rewrite a line to something they did not type. A capture
    # document quoting what it actually ran is the behaviour this gate exists
    # to encourage, so the resolver — not the document — is what was wrong.
    repo_root = plugin_root.parent.parent.parent

    #: Directories a documented command is plausibly run FROM. Order is
    #: irrelevant: this is existence, not precedence.
    _CWDS = (plugin_root, repo_root,
             plugin_root / "programs", plugin_root / "benchmark",
             repo_root / "tools", repo_root / "tools" / "ci")

    def _exists_at_either(target: str) -> bool:
        if target.startswith("./"):
            target = target[2:]
        return any((base / target).is_file() for base in _CWDS)

    if verb in ("bash", "sh"):
        if len(toks) < 2:
            return None
        target = toks[1]
        if not _exists_at_either(target):
            return ("MISSING_SCRIPT",
                    f"`{verb} {target}` references a file that does "
                    "not exist relative to either plugin root or "
                    "repo root.")
        return None

    if verb in ("python3", "python"):
        # Skip module invocations: `python3 -m pytest`
        if len(toks) >= 3 and toks[1] == "-m":
            return None
        if len(toks) < 2:
            return None
        target = toks[1]
        # Bail if the second token isn't a path-shaped argument
        if not (target.endswith(".py") or "/" in target):
            return None
        if not _exists_at_either(target):
            return ("MISSING_SCRIPT",
                    f"`{verb} {target}` references a python file that "
                    "does not exist relative to either plugin root or "
                    "repo root.")
        return None

    if verb == "pytest":
        if shutil.which("pytest") is None:
            return ("PYTEST_NOT_FOUND",
                    "command quotes `pytest` but pytest is not on "
                    "PATH at audit time. Install pytest or rewrite "
                    "the example as `python3 -m pytest`.")
        return None

    if verb == "make":
        if not (plugin_root / "Makefile").is_file() and \
                not (plugin_root / "makefile").is_file():
            return ("MISSING_MAKEFILE",
                    "command quotes `make` but no Makefile exists in "
                    "the plugin root.")
        return None
    return None


def audit(plugin_root: Path) -> Tuple[str, List[CommandFinding]]:
    findings: List[CommandFinding] = []
    if not plugin_root.is_dir():
        return "VACUOUS_PASS", []
    files = _audit_files(plugin_root)
    _SCANNED["files"] = len(files)
    _SCANNED["items"] = 0
    if not files:
        return "VACUOUS_PASS", []

    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        for ln_no, line in enumerate(text.splitlines(), start=1):
            m = _PROMPT_RE.match(line)
            if m:
                _SCANNED["items"] += 1
            if not m:
                continue
            cmd = m.group("cmd")
            check = _check_command(cmd, plugin_root)
            if check is None:
                continue
            rule, detail = check
            try:
                rel = str(f.relative_to(plugin_root.parent))
            except ValueError:
                rel = str(f)
            findings.append(CommandFinding(
                file=rel, line=ln_no, command=cmd,
                rule=rule, detail=detail,
            ))

    return ("FAIL" if findings else "PASS"), findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Anti-fabrication: every quoted shell command in "
                    "CHANGELOG / plugin.json / marketplace.json must "
                    "reference a real target inside the plugin tree.")
    ap.add_argument("plugin_root")
    ap.add_argument("--json", help="write JSON report to this path")
    args = ap.parse_args(argv)

    root = Path(args.plugin_root).resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2

    verdict, findings = audit(root)
    report = {
        "gate": "changelog_command_reproducibility_check",
        "verdict": verdict,
        "plugin_root": str(root),
        "findings_count": len(findings),
        "findings": [asdict(f) for f in findings[:200]],
    }
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")

    if verdict == "VACUOUS_PASS":
        print("VACUOUS_PASS: no CHANGELOG.md / plugin.json / "
              "marketplace.json found")
        return 0
    if verdict == "PASS":
        print(f"PASS: {_SCANNED['items']} quoted command(s) across "
              f"{_SCANNED['files']} audited file(s) — every one "
              f"references a real target")
        return 0
    print(f"FAIL: {len(findings)} unreproducible quoted command(s):",
          file=sys.stderr)
    for f in findings[:10]:
        print(f"  {f.file}:{f.line}  [{f.rule}] {f.command!r}",
              file=sys.stderr)
    if len(findings) > 10:
        print(f"  … and {len(findings) - 10} more", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
