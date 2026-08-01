#!/usr/bin/env python3
"""A `docker exec` whose deadline bounds the CLIENT and not the tool.

WHAT THIS AUDITS
================
    subprocess.run(["docker", "exec", <c>, "bash", "-lc", cmd], timeout=N)

The ``timeout=N`` bounds the local docker CLIENT. On expiry Python kills the
client and raises; the tool inside the container is never signalled, keeps its
cores, and never finishes writing its output. See ``_container_exec`` for the
measurement (survivors = 2 before, 0 after) and the fix.

The failure is invisible in the worst way: ``ps`` shows the orphan busy, so a
host that is burning CPU-hours on an abandoned simulation looks like a host
doing work. Every such site is one place the flow can hang without saying so.

THE PREDICATE, and why it is this one
=====================================
FLAG a call that is BOTH

  (a) a ``docker exec`` invocation built as a subprocess argv list, AND
  (b) carrying a ``timeout=`` keyword

but which does NOT route through ``_container_exec`` and does NOT place a
container-side ``timeout`` in the argv itself.

Condition (b) is load-bearing and deliberately narrow. A ``docker exec``
WITHOUT a timeout is not this defect — it is an unbounded call, honestly
unbounded, and whatever policy governs it is a separate question this gate does
not answer. What this gate catches is the call that LOOKS bounded and is not:
the deadline that exists in the caller's belief and nowhere else. Widening to
all ``docker exec`` calls would bury that population in a much larger one and
make the finding unactionable, which is how a gate stops being read.

``docker ps`` / ``docker image inspect`` and other non-``exec`` subcommands are
out of scope by construction: they do not start a process inside a container,
so there is nothing to orphan.

VERDICT CLASS: **ADVISORY** (exit 0 with findings) unless ``--strict``, which
makes it BLOCKING (exit 1). It ships advisory because the un-converted call
sites are pre-existing and a gate that turns every landing red gets deleted
rather than fixed; ``--strict`` is what the conversion is driven to zero under,
after which it becomes the default. Stated here rather than intended, so the
promotion is observable.

Exit: 0 clean (or advisory findings), 1 findings under --strict, 2 could not
measure.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

PASS, FAIL, UNMEASURABLE = 0, 1, 2

#: The helper that enforces the deadline container-side. A call routed through
#: it is compliant by construction.
_SANCTIONED_MODULE = "_container_exec"

#: Placed in the argv itself, coreutils `timeout` runs as the tool's parent
#: inside the container and can signal it. An argv carrying it is compliant.
_CONTAINER_SIDE_DEADLINE = "timeout"


def _argv_string_elements(node: ast.AST) -> List[str]:
    """Every string constant in a list/tuple literal argument, else []."""
    if not isinstance(node, (ast.List, ast.Tuple)):
        return []
    return [e.value for e in node.elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)]


def _is_docker_exec_argv(elements: List[str]) -> bool:
    """True when the argv literal starts a `docker exec`."""
    return (len(elements) >= 2
            and elements[0] == "docker"
            and elements[1] == "exec")


def scan_source(src: str, path: str) -> List[Dict[str, Any]]:
    """Findings for one source file. Pure — no filesystem, no subprocess."""
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return [{"file": path, "line": getattr(exc, "lineno", 0) or 0,
                 "code": "UNPARSEABLE", "detail": str(exc)}]

    routed_through_helper = _SANCTIONED_MODULE in src
    findings: List[Dict[str, Any]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        elements = _argv_string_elements(node.args[0])
        if not _is_docker_exec_argv(elements):
            continue
        # (b) does it CLAIM a deadline?
        has_client_timeout = any(kw.arg == "timeout" for kw in node.keywords)
        if not has_client_timeout:
            continue          # honestly unbounded — a different question
        # compliant if the deadline is in the argv itself...
        if _CONTAINER_SIDE_DEADLINE in elements:
            continue
        # ...or if this module routes through the sanctioned helper.
        if routed_through_helper:
            continue
        findings.append({
            "file": path,
            "line": node.lineno,
            "code": "CLIENT_SIDE_DEADLINE_ONLY",
            "detail": ("`docker exec` carries timeout= but the deadline bounds "
                       "the local docker client, not the containerised tool; "
                       "on expiry the tool is orphaned and keeps running. "
                       f"Route through `{_SANCTIONED_MODULE}.run_in_container` "
                       "or put coreutils `timeout` in the argv."),
        })
    return findings


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Find `docker exec` calls whose deadline bounds the "
                    "client instead of the containerised tool.")
    ap.add_argument("root", nargs="?", default=".",
                    help="directory to scan for *.py (default: cwd)")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="write the structured report here")
    ap.add_argument("--strict", action="store_true",
                    help="make findings BLOCKING (exit 1) instead of advisory")
    args = ap.parse_args(argv)

    root = Path(args.root)
    if not root.exists():
        print(f"UNMEASURABLE: {root} does not exist", file=sys.stderr)
        return UNMEASURABLE

    sources = sorted(root.rglob("*.py")) if root.is_dir() else [root]
    findings: List[Dict[str, Any]] = []
    for src_path in sources:
        try:
            text = src_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        findings += scan_source(text, str(src_path))

    scanned = len(sources)
    report = {
        "gate": "container_exec_deadline_check",
        "files_scanned": scanned,
        "findings": findings,
        "blocking": bool(args.strict),
        "verdict": ("FAIL" if (findings and args.strict)
                    else ("ADVISORY" if findings else "PASS")),
    }
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2))

    # The denominator is printed ALWAYS: a clean result over zero files is not
    # a clean result, and a reader must be able to tell those apart.
    for f in findings:
        print(f"  {f['file']}:{f['line']}: {f['code']}: {f['detail']}")
    print(f"{report['verdict']}: container_exec_deadline_check — "
          f"{len(findings)} finding(s) over {scanned} file(s) scanned")

    if findings and args.strict:
        return FAIL
    # vibe-ic#564 — THE COMMENT ABOVE ALREADY SAYS THIS: "a clean result over
    # zero files is not a clean result". It printed the zero and returned PASS
    # anyway, so the P0 umbrella — which reads exit codes, not prose — recorded
    # a silent pass. rc 2 is this repo's disclosed-skip convention and promotes
    # the step to VACUOUS-PASS instead.
    if scanned == 0:
        print("VACUOUS_PASS: container_exec_deadline_check scanned 0 file(s) — "
              "nothing was examined, which is not a clean result",
              file=sys.stderr)
        return 2
    return PASS


if __name__ == "__main__":
    sys.exit(main())
