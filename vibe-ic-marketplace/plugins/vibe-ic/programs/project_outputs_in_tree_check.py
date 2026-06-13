#!/usr/bin/env python3
"""project_outputs_in_tree_check.py

Closes the silent-loss bug where build / EDA tools write outputs to
``/tmp/`` (or other volatile locations outside the project tree) and the
agent forgets to copy them back. The next reboot / tmpfs sweep destroys
the evidence. Worse, gate authors then waiver the missing canonical-path
artifacts thinking they were never produced.

Concrete failure mode (project-agnostic example):
    PnR / GDS tools accept caller-supplied output paths. When agents
    pick a scratch dir under /tmp/, the artifacts are real but live
    on volatile tmpfs. waivers.json + RESULT.md then cite those paths
    and a later audit assumes the artifacts were never produced — so
    spurious waivers get opened for results that DO exist, just outside
    the project tree. A reboot or tmpfs sweep then permanently destroys
    the evidence.

This gate is **chip-AGNOSTIC**:

    Scan the project's waivers.json + RESULT.md + reports/*.json for
    any reference to absolute paths starting with /tmp/, /var/tmp/,
    or any path explicitly outside the project root. FAIL when found
    AND the referenced file actually exists at that path (i.e. the
    artifact got produced but was left outside the project tree).

    The fix is for the agent to copy those artifacts to canonical
    locations under <project>/ before claiming completion.

Honors waiver ``project_artifacts_external_storage_intentional`` (>=60
chars per offending path).

Usage:
    python3 project_outputs_in_tree_check.py <project_dir>

Exit codes:
    0  PASS / SKIP (no /tmp references OR all waived)
    1  FAIL (/tmp references found AND artifacts still on disk)
    2  IO / parse error
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List, Set, Tuple


WAIVER_KEY = "project_artifacts_external_storage_intentional"
WAIVER_MIN = 60


# Volatile / external-storage prefixes. Any absolute path starting with
# one of these is flagged.
_VOLATILE_PREFIXES = (
    "/tmp/",
    "/var/tmp/",
    "/dev/shm/",
    "/run/",
)

# Files to scan for path references.
_SCAN_GLOBS = (
    "RESULT.md",
    "waivers.json",
    "reports/**/*.json",
    "reports/**/*.md",
    "reports/*.log",
    "phase1/generated_docs/*.json",
)


_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_/])(/(?:tmp|var/tmp|dev/shm|run)/[A-Za-z0-9_./-]+)"
)


def _waiver_count(project: Path) -> int:
    p = project / "waivers.json"
    if not p.exists():
        return 0
    try:
        d = json.loads(p.read_text())
    except Exception:
        return 0
    v = d.get(WAIVER_KEY)
    if isinstance(v, str):
        return 1 if len(v.strip()) >= WAIVER_MIN else 0
    if isinstance(v, list):
        return sum(1 for s in v
                   if isinstance(s, str) and len(s.strip()) >= WAIVER_MIN)
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: project_outputs_in_tree_check <project_dir>",
              file=sys.stderr)
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        print(f"ERROR: {project} not a directory", file=sys.stderr)
        return 2

    # (file, path, exists_on_disk, from_log)
    findings: List[Tuple[str, str, bool, bool]] = []
    seen: Set[str] = set()
    for pat in _SCAN_GLOBS:
        for f in project.glob(pat):
            if not f.is_file():
                continue
            try:
                txt = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            from_log = f.name.endswith(".log")
            for m in _PATH_RE.finditer(txt):
                p = m.group(1).rstrip(".,;:)")
                if p in seen:
                    continue
                seen.add(p)
                exists = Path(p).exists()
                findings.append(
                    (str(f.relative_to(project)), p, exists, from_log))

    # ORGANIC #622 — a /tmp reference found INSIDE A LOG FILE (*.log) is a
    # tool-internal ephemeral path (e.g. a yosys/LEC scratch genlib the OS
    # /tmp-sweep removes after the run), NOT a project OUTPUT that must live in
    # the tree. Logs reference ephemeral tool paths by nature, so a log-sourced
    # reference is auto-classified EPHEMERAL — disclosed but NON-BLOCKING, no
    # per-path waiver required. Only references in the canonical artefact files
    # (RESULT.md / waivers.json / reports/**/*.json|md / generated_docs/*.json)
    # — where a real deliverable's location is declared — can FAIL this gate.
    ephemeral = [(f, p, e) for (f, p, e, lg) in findings if lg]
    nonlog = [(f, p, e) for (f, p, e, lg) in findings if not lg]

    if ephemeral:
        print(f"[INFO] project_outputs_in_tree_check: "
              f"{len(ephemeral)} ephemeral tool-path reference(s) inside "
              f"log file(s) — non-blocking (logs cite transient /tmp tool "
              f"paths by nature; not project outputs):")
        for f, p, e in ephemeral[:5]:
            print(f"  - {f} → {p} "
                  f"({'still present' if e else 'swept'})")
        if len(ephemeral) > 5:
            print(f"  ... +{len(ephemeral)-5} more")

    if not nonlog:
        print("[PASS] project_outputs_in_tree_check: "
              "no /tmp / /var/tmp / /dev/shm / /run paths referenced "
              "in RESULT.md / waivers.json / reports/ / generated_docs/ "
              "(log-only ephemeral tool paths excluded — #622)")
        return 0

    # Split: live (file exists at /tmp) vs. dangling (referenced but gone)
    live = [(f, p) for (f, p, e) in nonlog if e]
    dangling = [(f, p) for (f, p, e) in nonlog if not e]

    waiver_n = _waiver_count(project)
    fail_count = len(live) + len(dangling)

    if waiver_n >= fail_count:
        print(f"[PASS_WITH_WAIVER] "
              f"project_outputs_in_tree_check: "
              f"{fail_count} external-path reference(s) but {waiver_n} "
              f"waiver(s) under '{WAIVER_KEY}'.")
        return 0

    if live:
        print(f"[FAIL] project_outputs_in_tree_check: "
              f"{len(live)} live external-storage artifact(s) "
              f"(file exists at volatile path — must copy into project "
              f"tree before claiming completion):")
        for f, p in live[:8]:
            print(f"  - referenced in {f} → {p} (file exists)")
        if len(live) > 8:
            print(f"  ... +{len(live)-8} more")

    if dangling:
        print(f"[WARN] project_outputs_in_tree_check: "
              f"{len(dangling)} dangling external-path reference(s) "
              f"(file no longer exists — likely lost to /tmp sweep):")
        for f, p in dangling[:5]:
            print(f"  - {f} → {p} (NOT found on disk)")
        if len(dangling) > 5:
            print(f"  ... +{len(dangling)-5} more")

    print(f"\nFix: copy live artifacts to canonical project paths and "
          f"update references. Then re-run audit. To accept volatile "
          f"storage (e.g. cache that's intentionally ephemeral), add "
          f"waiver '{WAIVER_KEY}' (one per path, >={WAIVER_MIN} chars).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
