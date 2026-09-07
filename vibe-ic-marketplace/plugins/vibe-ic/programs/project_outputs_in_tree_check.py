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
    or any path explicitly outside the project root. FAIL when one is
    found in a canonical declaration file, whether or not the file is
    still on disk:

      * still on disk  — the artifact got produced but was left outside
        the project tree. Recoverable: copy it in.
      * already gone   — the reference is dangling, so the artifact was
        produced and then swept. Worse, and NOT recoverable.

    #2084: this paragraph used to read "FAIL when found AND the
    referenced file actually exists", which described only the first of
    the two while `main()` has always exited 1 on both (`fail_count =
    len(live) + len(dangling)`). The prose was the narrower of two
    classifications the file carried at once; the code's is the one that
    decides, so the prose is corrected to it rather than the reverse —
    a dangling reference names evidence that is already lost, which is
    not the half of this finding to stop blocking on.

    The fix is for the agent to copy live artifacts to canonical
    locations under <project>/ before claiming completion.

Honors waiver ``project_artifacts_external_storage_intentional`` (>=60
chars per offending path).

Usage:
    python3 project_outputs_in_tree_check.py <project_dir>

Exit codes:
    0  PASS (>=1 declaration file was READ and none cites external storage,
       OR every citation is waived)
    1  FAIL (a /tmp-class reference in a canonical declaration file — live
       (artifact still on disk, copy it in) or dangling (already swept, the
       evidence is gone). Both block; the split states the remedy, not
       whether there is a finding. The FIRST line of stdout is always the
       `[FAIL]` line naming the blocking population, because
       `flow_compliance_check._p0_first_line` publishes line 0 as the
       failed gate's reason — see the #2084 block in `main()`)
    2  NOT_CHECKED — IO / parse error, OR the scan opened ZERO declaration
       files: nothing was read, so nothing is vouched for (#619; the argument
       is written out at the `scanned == 0` branch of main())
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import List, Optional, Set, Tuple


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

# `_docker_watchdog.py` owns this exact private namespace.  The file is a
# process-lifetime coordination marker, deliberately removed when the supervised
# child exits.  Telemetry keeps the marker name so the invocation can be
# diagnosed later; that reference is not a deliverable location.  Keep the
# match exact so an arbitrary /tmp JSON/GDS/netlist remains blocking.
_WATCHDOG_PIDFILE_RE = re.compile(
    r"^/tmp/\.vibeic-job-[A-Za-z0-9_-]+\.pid$"
)


# ── R7 (v1.3.50 fork-adapt) — a PINNED plugin worktree is a legit plugin source ──
# When the whole flow runs with the vibe-ic plugin PINNED under a scratch/worktree
# location (e.g. `/tmp/.../.claude/worktrees/<wt>/vibe-ic-marketplace/plugins/
# vibe-ic/...` or `/tmp/.../wt-<ver>-*/vibe-ic-marketplace/plugins/vibe-ic/...`),
# RESULT.md / reports/ legitimately cite the plugin's OWN program/config files by
# their pinned absolute path. Because that path begins with a volatile prefix
# (/tmp, /run, …), the raw scanner used to flag the plugin's own source as a
# "live external-storage artifact" and HALT the flow — a FALSE POSITIVE that is
# purely an artifact of WHERE the plugin was pinned, not a lost project OUTPUT.
#
# A path is a pinned-plugin SOURCE (not a volatile project output) iff ALL hold:
#   (1) it contains the plugin-root anchor  .../vibe-ic-marketplace/plugins/vibe-ic/…
#   (2) an ancestor above that anchor is a worktree/scratch dir — either the
#       consecutive `.claude/worktrees` pair OR a `wt-*` dir (the pinning markers)
#   (3) the resolved plugin root actually carries `.claude-plugin/plugin.json`
#       (i.e. it REALLY is a plugin checkout, not just a coincidental substring).
# All three together make it impossible for a genuine volatile project artifact
# (a stray /tmp/<run>/design.gds) to be mis-exempted: (3) is the hard gate — no
# plugin.json → not a plugin root → still FLAGGED. chip-AGNOSTIC (pure path/marker).
_PLUGIN_ANCHOR = ("vibe-ic-marketplace", "plugins", "vibe-ic")


def _pinned_plugin_root(path_str: str) -> Optional[Path]:
    """If `path_str` resolves INTO a pinned plugin worktree, return the plugin
    root Path (…/vibe-ic-marketplace/plugins/vibe-ic); else None.

    Deterministic path-pattern + plugin-root marker check (R7). Returns None
    unless the path both matches the pinned-worktree layout AND the resolved
    plugin root carries `.claude-plugin/plugin.json` on disk.

    §4.05 false-negative guard: the path is LEXICALLY normalized first
    (os.path.normpath), so a `..`-escape such as
    `.../vibe-ic/../../../out.gds` collapses to `/…/out.gds` — the plugin anchor
    is destroyed and the genuine escaped output is (correctly) NOT exempted. An
    in-tree `..` (`.../vibe-ic/programs/../x.py`) stays under the plugin root and
    is still recognised. A belt-and-suspenders containment check re-confirms the
    file lives under the resolved plugin root."""
    parts = Path(os.path.normpath(path_str)).parts
    # (1) locate the plugin-root anchor within the path.
    anchor_idx = None
    for i in range(len(parts) - 2):
        if (parts[i], parts[i + 1], parts[i + 2]) == _PLUGIN_ANCHOR:
            anchor_idx = i
            break
    if anchor_idx is None:
        return None
    ancestors = parts[:anchor_idx]
    # (2) a worktree/scratch pinning marker must sit above the anchor.
    pinned = any(a.startswith("wt-") for a in ancestors)
    if not pinned:
        for j, a in enumerate(ancestors):
            if a == "worktrees" and j > 0 and ancestors[j - 1] == ".claude":
                pinned = True
                break
    if not pinned:
        return None
    # (3) hard gate — the resolved root must be a REAL plugin checkout AND the
    # normalized file must live UNDER it (containment; blocks any `..` escape).
    root = Path(*parts[: anchor_idx + 3])
    norm = Path(os.path.normpath(path_str))
    try:
        norm.relative_to(root)
    except ValueError:
        return None
    if (root / ".claude-plugin" / "plugin.json").is_file():
        return root
    return None


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


def _inside_project(path_str: str, project: Path) -> bool:
    """True when `path_str` resolves to the project root or anything under it.

    A volatile-looking absolute path is only an EXTERNAL-STORAGE finding when
    it points OUTSIDE the project being audited.  When the project root itself
    sits under a volatile prefix (`/tmp/...`, `/var/tmp/...`, `/dev/shm/...`,
    `/run/...`) every absolute self-reference the flow writes into its own
    `reports/**/*.json` matches `_PATH_RE` — so the gate reported the project's
    OWN in-tree files as artifacts that must be "copied into the project tree".

    That is self-inflating, because `flow_compliance_check` REGENERATES those
    gate JSONs (stamping the absolute project path into them) every time it
    runs: auditing a project from a scratch copy — the standard way to audit
    without mutating the original — manufactures the very violation being
    audited for, and the count grows with each audit run.

    Measured on a real run dir (spm x ihp-sg13g2), copied to /tmp and audited:
        before any audit run : 1 live external-storage artifact
        after ONE audit run  : 21 live, 13 gate JSONs now carrying the copy's
                               own absolute path
    The only variable between the two readings is that the audit ran.

    Sibling precedent: this file already carves out two non-violating classes
    the same way — R7 pinned plugin worktrees (`_pinned_plugin_root`) and #622
    log-sourced ephemeral tool paths. The project's own tree is the third, and
    the most basic: `project` is already resolved at the top of `main()`.
    """
    try:
        p = Path(path_str).resolve()
    except (OSError, ValueError):
        return False
    return p == project or project in p.parents


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
    # R7 — pinned plugin-source references (disclosed, non-blocking).
    plugin_src: List[Tuple[str, str]] = []
    # Supervision metadata references a process marker that is expected to be
    # absent after normal cleanup; it is never a project output.
    process_markers: List[Tuple[str, str]] = []
    # In-tree self-references: absolute paths that resolve INSIDE the project
    # being audited (counted only, never a finding — see _inside_project).
    in_tree_self = 0
    # THE SCAN SIZE, kept because the exit code alone cannot carry it
    # (#511/#564). `no /tmp ... paths referenced` is a statement about the
    # FINDING and is exactly as true of a project with nothing in it as of a
    # clean one; over an empty tree this gate answered rc 0 and said nothing
    # about having opened zero files.
    scanned = 0
    seen: Set[str] = set()
    for pat in _SCAN_GLOBS:
        for f in project.glob(pat):
            if not f.is_file():
                continue
            scanned += 1
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
                # A path that resolves INSIDE the project being audited is
                # in-tree BY DEFINITION, whatever the project root happens to
                # be. Must precede the exists() classification: otherwise
                # auditing a project that itself lives under /tmp reports the
                # project's OWN files as external storage.
                if _inside_project(p, project):
                    in_tree_self += 1
                    continue
                # R7 — a pinned plugin worktree path is a legitimate plugin
                # SOURCE, not a volatile project output. Disclose, never FAIL.
                if _pinned_plugin_root(p) is not None:
                    plugin_src.append((str(f.relative_to(project)), p))
                    continue
                if _WATCHDOG_PIDFILE_RE.fullmatch(p):
                    process_markers.append((str(f.relative_to(project)), p))
                    continue
                exists = Path(p).exists()
                findings.append(
                    (str(f.relative_to(project)), p, exists, from_log))

    # ── #619 / #564 — A SCAN THAT OPENED NOTHING IS NOT A CLEAN SCAN ────────
    #
    # Over a project where none of
    # `_SCAN_GLOBS` matched, every list above is empty for the same reason a
    # genuinely clean project's lists are empty, and the two were collapsed
    # into one rc 0. `gate_zero_denominator_refuses_check` reported exactly
    # that (`ZERO_DENOMINATOR_EXITS_ZERO`), and its argument is the P0
    # umbrella's: the umbrella reads EXIT CODES, so the honesty already in the
    # prose ("0 file(s) scanned") never reached the verdict.
    #
    # WHY THIS GATE CANNOT TAKE THE `_ZERO_IS_A_PASS` ROUTE, which is the other
    # half of the finding and the half that must be argued rather than assumed.
    # For `professional_tb_check` the zero is a correct pass because the missing
    # input belongs to an OPTIONAL step: absence is a legitimate, expected state
    # the gate is not owed. Here it is the opposite. This gate's entire subject
    # is "the flow wrote its outputs somewhere other than the project tree", and
    # a project whose RESULT.md / waivers.json / reports/ / generated_docs are
    # ALL absent is the strongest possible symptom of that condition: if the
    # declaration files themselves were written to a scratch dir — the same
    # mistake this gate exists to catch, one level up — the canonical tree is
    # empty and the old rc 0 answered "no outputs outside the tree" for a
    # project whose every output is outside the tree. The gate cannot tell that
    # apart from "nothing has been produced yet", so it must not vouch for
    # either.
    #
    # IT IS A REFUSAL, NOT A FAILURE. rc 2 is the disclosed-skip convention;
    # `flow_compliance_check` classifies this message ZERO_DENOMINATOR, which is
    # NOT skip-eligible, so the P0 tier reads INCOMPLETE instead of PASS — the
    # gate stops contributing a green it never earned, and stops contributing a
    # red it cannot justify either.
    #
    # THE DETECTION SIDE IS UNTOUCHED: the refusal is keyed on `scanned == 0`
    # alone, so any project carrying even one declaration file still runs the
    # full scan and a live external artefact is still rc 1.
    #
    # MEASURED 2026-09-03 over 196 real run trees on this host (every directory
    # under ~/vibeic-designs, ~/_hyg_bd_tip, ~/_matrix_benchmark_data and
    # ~/_kicspm_accept2 carrying `phase1/generated_docs/`): 0 of 196 scanned
    # zero files, so no real run's verdict moves.
    if scanned == 0:
        print(f"[SKIP] project_outputs_in_tree_check: read 0 file(s) — none "
              f"of RESULT.md / waivers.json / reports/**/*.json|md / "
              f"reports/*.log / phase1/generated_docs/*.json exists under "
              f"{project}, so there is no artefact declaration to read and "
              f"NOT_CHECKED is the only answer this gate can give. A project "
              f"that declares nothing is indistinguishable here from a project "
              f"whose declarations were themselves written outside the tree — "
              f"which is the very condition this gate exists to detect — so a "
              f"zero denominator may not be reported as a clean scan.")
        return 2

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

    # ── #2084 — ONE CLASSIFICATION, AND THE LINE THAT CARRIES IT COMES FIRST ─
    #
    # MEASURED (lane rbsha2, 2026-09-07, plugin v1.17.62): the completion audit
    # read 246 invoked / 182 passed / 1 failed, and the message it published for
    # the ONE failed gate was this gate's
    #
    #     "[INFO] … 2 ephemeral process-marker reference(s) — non-blocking (the
    #      supervised watchdog removes these pidfiles after child exit; they are
    #      runtime metadata, not project outputs)"
    #
    # — a sentence that declares, in the same breath, that the finding does not
    # matter and that the run failed on it.
    #
    # THE CLASSIFICATION WAS NEVER DOUBLE. Reproduced on this tip (8HD-4, lane
    # cz2084, pinned image): the four non-blocking classes above — in-tree self
    # references, R7 pinned plugin sources, watchdog process markers, log-sourced
    # ephemeral tool paths — are each `continue`d before the finding is recorded,
    # so a marker CANNOT reach `nonlog` and CANNOT contribute to the exit code. A
    # project whose ONLY volatile references are two watchdog pidfiles exits 0.
    # What failed the run was a separate, genuinely blocking reference in the same
    # tree; the audit simply never said so.
    #
    # TWO REPORTING DEFECTS PRODUCED THAT, AND BOTH ARE FIXED HERE.
    #
    #   (1) THE DECIDING LINE WAS NOT FIRST. `flow_compliance_check._p0_first_line`
    #       records a failed gate's FIRST output line as its message, and the four
    #       non-blocking [INFO] disclosures were printed BEFORE the verdict line.
    #       Line 0 of a FAIL was therefore whichever disclosure happened to sort
    #       first — a note whose own text says "non-blocking". The gate is the half
    #       that must fix this: a reader taking the first line is taking the line a
    #       program is entitled to treat as the reason, so the reason has to BE
    #       first. Disclosures follow the verdict now, unchanged in wording.
    #
    #   (2) A DANGLING-ONLY FAILURE PRINTED NO FAILING LINE AT ALL. `live` empty +
    #       `dangling` non-empty exits 1 (it always has: `fail_count = len(live) +
    #       len(dangling)`), yet the only line the gate emitted for it was tagged
    #       `[WARN]`. So even a reader holding the FULL stdout was told the highest
    #       severity present was a warning, and handed a blocking exit code. The
    #       severity a gate prints must be the severity it exits with; a dangling
    #       reference is now stated as what it is — blocking, and worse than a live
    #       one, because the artefact is already gone and cannot be copied back.
    #
    # NEITHER HALF MOVES A VERDICT. Every exit code this function can return is
    # byte-identical to before; what changed is which sentence a reader — human or
    # `_p0_first_line` — gets when it asks WHY. chip-AGNOSTIC: pure classification
    # and output ordering, no design, PDK or vendor literal anywhere in it.
    #
    # The non-blocking disclosures are BUILT here and PRINTED after the verdict.
    notes: List[str] = []

    # R7 — a pinned plugin worktree path (…/vibe-ic-marketplace/plugins/vibe-ic/
    # … under a `.claude/worktrees` or `wt-*` dir, with a real plugin.json) is a
    # legitimate plugin SOURCE, not a volatile project OUTPUT. Disclosed, never
    # FAILs — it is only cited because the plugin itself was pinned there.
    if plugin_src:
        block = [f"[INFO] project_outputs_in_tree_check: "
                 f"{len(plugin_src)} pinned plugin-source reference(s) "
                 f"(vibe-ic plugin pinned under a worktree/scratch dir; a "
                 f"legitimate plugin source, NOT a volatile project output — "
                 f"non-blocking):"]
        for f, p in plugin_src[:5]:
            block.append(f"  - {f} → {p}")
        if len(plugin_src) > 5:
            block.append(f"  ... +{len(plugin_src)-5} more")
        notes.append("\n".join(block))

    if in_tree_self:
        notes.append(f"[INFO] project_outputs_in_tree_check: "
                     f"{in_tree_self} in-tree self-reference(s) under the "
                     f"project root {project} — in-tree by definition, "
                     f"non-blocking (the project itself lives at a volatile "
                     f"path; these are its OWN files, not external storage)")

    if process_markers:
        block = [f"[INFO] project_outputs_in_tree_check: "
                 f"{len(process_markers)} ephemeral process-marker "
                 f"reference(s) — non-blocking (the supervised watchdog "
                 f"removes these pidfiles after child exit; they are runtime "
                 f"metadata, not project outputs):"]
        for f, p in process_markers[:5]:
            block.append(f"  - {f} → {p}")
        if len(process_markers) > 5:
            block.append(f"  ... +{len(process_markers)-5} more")
        notes.append("\n".join(block))

    if ephemeral:
        block = [f"[INFO] project_outputs_in_tree_check: "
                 f"{len(ephemeral)} ephemeral tool-path reference(s) inside "
                 f"log file(s) — non-blocking (logs cite transient /tmp tool "
                 f"paths by nature; not project outputs):"]
        for f, p, e in ephemeral[:5]:
            block.append(f"  - {f} → {p} "
                         f"({'still present' if e else 'swept'})")
        if len(ephemeral) > 5:
            block.append(f"  ... +{len(ephemeral)-5} more")
        notes.append("\n".join(block))

    def _emit_notes() -> None:
        """The non-blocking disclosures, AFTER the verdict line that decides."""
        for note in notes:
            print(note)

    if not nonlog:
        # The scan size leads, and the sentence that follows is phrased so it
        # reads as a statement about the POPULATION rather than about the
        # finding: `no such reference found` is false of a scan that read a
        # thousand files and hit one, and empty of meaning over a scan that
        # read none — which is why the count precedes it.
        print(f"[PASS] project_outputs_in_tree_check: "
              f"{scanned} file(s) scanned, {len(seen)} distinct absolute path "
              f"reference(s) examined — no such reference found: no /tmp / "
              f"/var/tmp / /dev/shm / /run paths referenced in RESULT.md / "
              f"waivers.json / reports/ / generated_docs/ (log-only ephemeral "
              f"tool paths and supervised watchdog pidfiles excluded)")
        _emit_notes()
        return 0

    # Split: live (file exists at /tmp) vs. dangling (referenced but gone).
    # BOTH block. The split says what the fix is, not whether there is one.
    live = [(f, p) for (f, p, e) in nonlog if e]
    dangling = [(f, p) for (f, p, e) in nonlog if not e]

    waiver_n = _waiver_count(project)
    fail_count = len(live) + len(dangling)

    if waiver_n >= fail_count:
        print(f"[PASS_WITH_WAIVER] "
              f"project_outputs_in_tree_check: "
              f"{fail_count} external-path reference(s) but {waiver_n} "
              f"waiver(s) under '{WAIVER_KEY}'.")
        _emit_notes()
        return 0

    # THE DECIDING LINE (#2084). First, and tagged with the severity this
    # function is about to exit with. It states the blocking population — the
    # number the exit code is a function of — so a reader that takes only this
    # line still gets the reason and the size of it.
    print(f"[FAIL] project_outputs_in_tree_check: "
          f"{fail_count} blocking external-storage reference(s) in this "
          f"project's own declaration file(s) "
          f"({len(live)} live, {len(dangling)} dangling) — this is what the "
          f"gate exits 1 on:")

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
        # Tagged [FAIL], not [WARN] (#2084 defect 2). It exits 1 either way; a
        # dangling reference is the WORSE of the two — the artefact is already
        # gone, so there is nothing left to copy — and printing the milder word
        # for the worse finding is precisely the disagreement this issue names.
        print(f"[FAIL] project_outputs_in_tree_check: "
              f"{len(dangling)} dangling external-path reference(s) "
              f"(file no longer exists — likely lost to /tmp sweep; "
              f"unrecoverable, so copying it in is no longer an option):")
        for f, p in dangling[:5]:
            print(f"  - {f} → {p} (NOT found on disk)")
        if len(dangling) > 5:
            print(f"  ... +{len(dangling)-5} more")

    _emit_notes()

    print(f"\nFix: copy live artifacts to canonical project paths and "
          f"update references. Then re-run audit. To accept volatile "
          f"storage (e.g. cache that's intentionally ephemeral), add "
          f"waiver '{WAIVER_KEY}' (one per path, >={WAIVER_MIN} chars).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
