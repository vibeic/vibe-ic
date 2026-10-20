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

    #2158: THE POPULATION IS NOT THE PREFIX LIST. Those four directories
    are one common way to land in this condition, not the condition. A
    third blocking class is derived from the RUN ROOT instead of from a
    list: an absolute path cited in a canonical declaration file that
    resolves OUTSIDE the project and is NOT ON DISK — a location this run
    used and did not preserve — whatever prefix it carries. Measured on
    two lanes at the same plugin tip, the same lost-scratch-path defect
    FAILED under `TMPDIR=/tmp/lane.<lane>` and PASSED under a TMPDIR
    beneath `$HOME`; the verdict turned on the operator's environment.
    Deliberately narrow: an outside path that IS on disk (a toolchain
    root, a PDK, another checkout) is untouched, because it names
    something a reader can still follow. `_PATH_RE` itself is unchanged —
    `collect_external_outputs.py` imports it to decide what to COPY.

Honors waiver ``project_artifacts_external_storage_intentional`` (>=60
chars per offending path).

ENFORCEMENT: **BLOCKING.** A rc-1 from this gate STOPS the run — it does not
merely record and continue. Stated here because `flow-change-acceptance` §5 is
explicit that silence is not neutral: an unstated default of "advisory" is how
62 of 72 gates in this repo ended up unable to stop anything, which is not what
any of their authors intended.

PROVEN BY RUN, not inferred from the wiring (§3; the doctrine's own measured
warning is `cts_quality_check`, which returned FAIL with no waiver on three
consecutive versions while the flow shipped a routed DEF anyway). Scoping
`_STRUCTURAL_RTL_GATES` to this gate alone and varying ONE thing — whether a
blocking external reference is present — moves the umbrella:

    clean tree     -> gate PASS, umbrella passed=True,  status=PASS
    one reference  -> gate FAIL, umbrella passed=False, status=FAIL

The unscoped form of that experiment is VACUOUS and was run first: on a minimal
synthetic tree other gates fail too, so the umbrella reads FAIL on both arms and
the comparison says nothing. The scoped control is the one that measures this
gate.

Usage:
    python3 project_outputs_in_tree_check.py <project_dir>
        [--json REPORT] [--auditor-record REL ...]

    --json REPORT        also write every flagged reference, IN FULL, to REPORT
                         (lane fxlvs, D1). The deciding stdout line is capped at
                         200 characters (#2084) and a long volatile path does not
                         fit it: MEASURED on the spm integration run, the P0 record
                         kept `... exits 1 on: reports/audit/phase23_completion_
                         audit.json:` and the path itself was lost. The P0
                         umbrella passes a scratch REPORT and publishes its
                         `flagged` list in the gate's record.
    --auditor-record REL the run-relative document the INVOKING AUDITOR owns
                         (the completion audit). Not judged here, and disclosed.
                         The flow YAML gives that document to the AUDIT and to no
                         step (P0's own entry: "declaring it here would make P0
                         ... judge a file P0 does not produce"), and every version
                         a P0 can see is superseded by the audit written after P0
                         finishes. MEASURED (D1): a nested scoped pass the auditor
                         runs as a step gate writes the canonical audit with its
                         `command_argv` naming the auditor's private receipt
                         scratch (`/tmp/gate_receipt_*/stageN_compliance.json`),
                         live until the auditor exits; stage-1's P0 read that
                         intermediate and FAILed the run on it, 14 passes in a row,
                         while the final audit carries no volatile path at all.
                         Run WITHOUT the flag (standalone, after the run), the
                         document is judged like any other.

Exit codes:
    0  PASS (>=1 declaration file was READ and none cites external storage,
       OR every citation is waived)
    1  FAIL (a /tmp-class reference in a canonical declaration file — live
       (artifact still on disk, copy it in) or dangling (already swept, the
       evidence is gone), OR (#2158) a reference to any path outside the
       project root that is not on disk. All three block; the split states the remedy, not
       whether there is a finding. The FIRST line of stdout is always the
       `[FAIL]` line naming the blocking population, because
       `flow_compliance_check._p0_first_line` publishes line 0 as the
       failed gate's reason — see the #2084 block in `main()`)
    2  NOT_CHECKED — IO / parse error, OR the scan opened ZERO declaration
       files: nothing was read, so nothing is vouched for (#619; the argument
       is written out at the `scanned == 0` branch of main())
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, List, Optional, Set, Tuple

# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE name.
# Python puts a file's own directory on `sys.path` only when that file is run
# as `__main__`; under `importlib.util.spec_from_file_location` — how the
# gates, the wiring audit and much of the suite load a program — it does not,
# so a bare sibling import raises ModuleNotFoundError. MEASURED: adding
# `_inplace_chain` without this made THIS program the one failure in
# `test_every_shipped_program_loads_by_path` (`unresolved_sibling:
# _inplace_chain`). Idempotent, and the same shape the sibling programs that
# already carry it use.
if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _inplace_chain as _chain                                   # noqa: E402


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

# ── #2158 — THE POPULATION IS "A PATH THAT WILL NOT EXIST AFTER THE RUN" ─────
#
# `_VOLATILE_PREFIXES` / `_PATH_RE` above are a HARD LIST of four directories.
# They are not the definition of the thing this gate is for; they are one
# common way to land in it. The fleet's own standing brief mandates
# `TMPDIR=/tmp/lane.<lane>/`, and lanes that follow it were caught while a lane
# whose TMPDIR sat under `$HOME` was equally dangling and completely invisible.
#
# MEASURED (lanes rbsub5 and rbsub6, 8HD-9, 2026-09-07, same plugin tip): both
# runs recorded a scratch path in `reports/orchestrator/phase2_one_shot.json`
# that no longer existed. rbsub6's began `/tmp/lane.rbsub6/…` and FAILED this
# gate; rbsub5's began `/home/<your-user>/…` and PASSED it. The only variable
# between the two verdicts was where TMPDIR happened to point — a property of
# the operator's environment, not of the run's honesty.
#
# THE DERIVED POPULATION. Rather than lengthening the list of prefixes, which
# can only ever chase the last environment someone used, the gate derives the
# class from the RUN ROOT it was given: an absolute path cited in a canonical
# declaration file, resolving OUTSIDE the project root, that is NOT ON DISK, is
# a dangling reference to something the run cannot produce again — whatever
# directory it lived in. That is the same finding `dangling` already blocks on
# for `/tmp`, stated by its meaning instead of by its spelling.
#
# WHY NON-EXISTENCE IS PART OF THE DEFINITION AND NOT A SOFTENING OF IT. A path
# outside the tree that IS on disk is the enormous, mostly-legitimate class of
# system and toolchain references (`/usr/bin/…`, a PDK root, another checkout);
# blocking on those would make the gate unusable and would say nothing about
# lost evidence. A path outside the tree that is GONE is, by construction,
# either evidence that was swept or a location that never existed — and either
# way a reader following it gets nothing. Only the second class is added here.
#
# `_PATH_RE` IS DELIBERATELY NOT WIDENED. `collect_external_outputs.py` imports
# it (`_gate._PATH_RE`) to decide which LIVE artefacts to copy into the tree;
# widening it there would send that collector after `/usr/bin/...`. The new
# population gets its own expression, and the volatile-prefix behaviour — live
# and dangling alike — is byte-identical to before.
# THE LOOKBEHIND IS WIDER THAN `_PATH_RE`'S, AND THE CENSUS IS WHY. Measured
# over 6847 published run roots on 8HD-8 (2026-09-07, lane cz2158): reusing
# `_PATH_RE`'s `(?<![A-Za-z0-9_/])` admits a `/` preceded by `.`, `~` or `-`,
# so the TAIL of a RELATIVE path reads as an absolute one — `../../edn/README.md`
# came back as `/../edn/README.md`, `~/.claude/plugins/cache` as
# `/.claude/plugins/cache`. Those are the same reference, mis-cut.
_ANY_ABS_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_/.~-])(/[A-Za-z0-9_.-][A-Za-z0-9_./-]*[A-Za-z0-9_-])"
)


# ── #2158 — WHAT "WILL NOT EXIST AFTER THE RUN" IS DERIVED FROM ─────────────
#
# TWO CANDIDATE DERIVATIONS WERE MEASURED, AND THE FIRST ONE FAILED. The
# obvious reading — "outside the project root and not on disk" — was
# implemented and censused over all 6847 published run roots on this host:
#
#     verdict rc 0 -> rc 1 : 2222 roots   (first draft, `_PATH_RE` lookbehind)
#     verdict rc 0 -> rc 1 : 1659 roots   (after the lookbehind fix above)
#
# and the surviving population was almost entirely two classes that are not
# lost evidence at all:
#
#   * SPEC PROSE. `/K/CS/CF/HD/SCR/JESDV/SUBCLASSV`, `/ARP/PMBus`, `/J/K`,
#     `/AIP/CLOSE/BREAK/DONE` — slash-separated field and signal alternatives
#     written by a protocol spec, in 55+ roots each. Nothing distinguishes them
#     from a pathname by shape.
#   * CONTAINER-INTERNAL TOOLCHAIN ROOTS. `/foss/pdks/...`, `/foss/designs/...`
#     — real, correct, still-mounted paths that simply are not on the HOST
#     filesystem the gate runs on. "Not on disk" is a statement about WHERE THE
#     GATE RAN, not about whether the run preserved anything, and using it as
#     the definition would make the gate's verdict depend on whether it was
#     invoked inside or outside the image.
#
# So existence is kept as a NECESSARY condition and is not sufficient. The
# derivation that actually comes from the RUN ROOT is this: the ephemeral
# location a run leaks is a COPY OF THE RUN ROOT ITSELF, somewhere else.
# `step_rtl_gen` stages the project as `<TMPDIR>/vibeic-rtl-step-XXXX/<name>`;
# every staging, snapshot and scratch shape in this flow has the same property,
# because that is what staging IS. A path that carries the run root's own
# directory name as one of its components, resolves OUTSIDE the run root, and
# is not on disk, is a reference to a relocated copy of this very project — and
# a reader following it gets nothing.
#
# `/foss/pdks/...` carries no such component, and neither does `/K/CS/CF/HD`;
# `/tmp/lane.rbsub6/vibeic-rtl-step-6k_pkx29/subservient` and
# `$HOME/_lane_x/stage/subservient/phase2/...` both do. The prefix is never
# consulted, which is the whole point of the issue.
#
# `_PATH_RE` IS DELIBERATELY NOT WIDENED. `collect_external_outputs.py` imports
# it (`_gate._PATH_RE`) to decide which LIVE artefacts to copy into the tree;
# widening it there would send that collector after `/usr/bin/...`. The new
# population gets its own expression, and the volatile-prefix behaviour — live
# and dangling alike — is byte-identical to before.

# A reference has to look like a FILESYSTEM path, not a slash-prefixed prose
# fragment: at least three parts (`/a/b`), and no empty or `..` component — the
# census also surfaced literal text like `/A//F`, which `Path.parts` silently
# normalizes into a plausible-looking three-component path.
_MIN_DERIVED_COMPONENTS = 3


def preserved_in_the_run_root(path_str: str, project: Path) -> Optional[Path]:
    """The run-relative artefact `path_str` names, when it IS in the run root.

    A relocated-copy reference is only lost evidence when the evidence is
    actually gone. The same tree is often named through a SECOND MOUNT -- a run
    bind-mounted into the EDA container is both
    `/home/.../run20/phase3/...` on the host and `/foss/designs/run20/phase3/...`
    inside the image -- and a recorded command line naturally carries the
    container spelling. The artefact it names can be sitting in the run root the
    whole time.

    MEASURED on spm run20, `reports/phase3/die_finishing.json`, whose recorded
    KLayout `argv` carries both of these while the SAME record's `gds_in` gives
    the host spelling of the first:
        /foss/designs/run20/phase3/stage3/pnr/spm.gds         <- IS in the tree
        /foss/designs/run20/phase3/stage3/pnr/spm.sealed.gds  <- is NOT
    Both were reported as "an ephemeral location this run used and did not
    preserve". For the first that is false: the evidence is preserved, at the
    same run-relative path. run18L and run19 recorded the HOST spelling of the
    identical argv, so they were counted as in-tree self-references and this
    never showed -- the reference set changed because a PRODUCER changed, not
    because anything regressed.

    CORRECTED 2026-09-23 (R-0915-162), and the correction is the point of this
    paragraph. This docstring used to end by saying of `spm.sealed.gds` that it
    "keeps its finding, which is the honest answer: that output was never
    written, in any of the three runs". MEASURED on spm run23, that is FALSE:
    the seal ring succeeded (`state: PASS`, `generator_rc: 0`,
    `ring_check.verdict: PASS`) and the staging file was written and then
    PROMOTED onto `spm.gds` by `staged.replace(dest)` -- 102,923,002 bytes
    where the prefinish stream was 73,850,996. The file is absent because it
    was consumed, not because nothing was produced. A reader acting on the old
    sentence would have gone looking for a seal-ring failure that never
    happened. `consumed_into_verified` is how that case is now told apart, and
    it is told apart by the BYTES, not by the producer's word.

    The tail is derived from the run root's own directory NAME, exactly as
    `names_a_relocated_copy` derives condition (2); no prefix list is consulted.
    Returns the run-relative path when it exists in the run root, else None --
    so a staged path whose tail is absent keeps its finding here. Whether that
    is honest depends on WHY it is absent, and this function cannot tell: on
    run23 `spm.sealed.gds` was written and then consumed by a successful
    promotion, and only `consumed_into_verified` -- walking the recorded digest
    chain -- can separate that from an output nothing ever produced.
    """
    parts = Path(path_str).parts
    name = project.name
    if name not in parts:
        return None
    # the LAST occurrence: a copy staged under a directory that repeats the name
    # is still this run, and the tail after the final one is the run-relative path
    index = len(parts) - 1 - parts[::-1].index(name)
    if index + 1 >= len(parts):
        return None
    tail = Path(*parts[index + 1:])
    try:
        return tail if (project / tail).exists() else None
    except OSError:                                        # pragma: no cover
        return None


#: R-0915-166 — only this producer's own document may claim a consumption.
_SEAL_PRODUCER = "die_finishing_gen"


def consumed_into_verified(path_str: str, record: Path,
                           project: Path) -> Optional[str]:
    """The destination `path_str`'s bytes were PROMOTED into, when an unbroken
    CHAIN of recorded rewrites proves the bytes are still there. None otherwise
    -- and None is the default in every doubt.

    R-0915-166 AMENDS R-0915-162, which checked ONE HOP and would have failed
    on every real run. A deliverable is not written once: MEASURED on spm
    run23, `die_density_fill_gen` rewrote the promoted GDS IN PLACE 3 m 24 s
    after the seal ring promoted it (`die_finishing.json` 19:08:28,
    `die_density_fill.json` 19:11:52, `spm.gds` 19:11:52.299), so
    `sha256(destination)` at audit time can never equal the digest taken before
    the rename. The one-hop version appeared to pass only because its
    validating fixture computed the digest FROM the already-filled file, which
    is circular.

    FIVE conditions, all necessary:

      (1) the consumption record is `die_finishing_gen`'s own document. Any
          document could otherwise claim a consumption for a path it never
          wrote;
      (2) the record names THIS staged path. Without it one consumption would
          exempt every missing path in the same document;
      (3) it names where the bytes went;
      (4) that destination EXISTS inside the tree;
      (5) a CONTINUOUS chain `staged_sha256 -> (each in-place writer's
          before -> after) -> sha256(destination now)` is present, with no gap.
          Each link is published by the writer that made it, under
          `_inplace_chain.LINKS_KEY`, and the walk is driven by the DIGESTS
          rather than by the order the links were written -- the only ordering
          a writer cannot arrange to suit itself.

    A GAP IS A FINDING. An unrecorded rewrite and a hand-edited deliverable
    produce exactly the same gap, which is the point: this is not "the producer
    says it is fine", it is "the bytes account for themselves".
    """
    try:
        doc = json.loads(record.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get("producer") != _SEAL_PRODUCER:
        return None                                   # (1)
    tail = _run_relative_tail(path_str, project)
    for rec in _dicts_in(doc):
        staged = rec.get("consumed_staged")
        dest = rec.get("consumed_into")
        want = rec.get("staged_sha256")
        if not isinstance(staged, str) or not isinstance(dest, str):
            continue                                  # (3)
        if not isinstance(want, str) or not want:
            continue                                  # stated, not verifiable
        if not _same_reference(staged, path_str, tail):
            continue                                  # (2)
        dpath = (project / dest) if not os.path.isabs(dest) else Path(dest)
        try:
            if not dpath.is_file():
                return None                           # (4)
            if not _inside_project(str(dpath), project):
                return None
        except OSError:
            return None
        now = _chain.sha256_file(dpath)
        links = _chain.links_for(dest, _reports_documents(project))
        ok, _why = _chain.chain_reaches(want, now or "", links)   # (5)
        if not ok:
            return None
        return dest
    return None


def _reports_documents(project: Path) -> List[Any]:
    """Every readable JSON document under `reports/` — where in-place writers
    publish their links. Read once per call site; the population is the run's
    own reports, never a list of program names."""
    out: List[Any] = []
    root = project / "reports"
    if not root.is_dir():
        return out
    for f in sorted(root.rglob("*.json")):
        try:
            out.append(json.loads(f.read_text()))
        except (OSError, ValueError):
            continue
    return out


def _dicts_in(obj: Any):
    """Every dict inside `obj`, at any depth — the consumption record may sit
    under any key the producer chose."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _dicts_in(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _dicts_in(v)


def _run_relative_tail(path_str: str, project: Path) -> Optional[str]:
    """`path_str` as a run-relative spelling, via the run root's own name.

    The reference may be recorded in the CONTAINER spelling
    (`/foss/designs/<run>/...`) while the producer records the project-relative
    one, so the two are compared on the run-relative tail they share. Reuses
    the derivation `names_a_relocated_copy` already uses — one rule, not a
    second prefix list."""
    parts = Path(path_str).parts
    name = project.name
    if name not in parts:
        return None
    index = len(parts) - 1 - parts[::-1].index(name)
    if index + 1 >= len(parts):
        return None
    return str(Path(*parts[index + 1:]))


def _same_reference(staged: str, path_str: str,
                    tail: Optional[str]) -> bool:
    """Whether the producer's `consumed_staged` names the reference at hand."""
    if staged == path_str:
        return True
    if tail is not None and staged == tail:
        return True
    return False


def _sha256_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _derived_ephemeral(path_str: str, project: Path) -> bool:
    """True when `path_str` names a relocated copy of THIS run root that is gone.

    Three conditions, all necessary:
      (1) it is shaped like a pathname, not like slash-separated prose;
      (2) one of its components is the run root's own directory name — so it is
          this project, staged or copied somewhere else. DERIVED from the run
          root; no prefix list is consulted, so a TMPDIR under `$HOME`, under
          `/scratch`, or anywhere else is caught identically;
      (3) it is not on disk, so there is nothing left for a reader to follow.

    The caller has already established that the path resolves OUTSIDE the run
    root, is not a pinned plugin source, and was not claimed by `_PATH_RE`.
    """
    return (names_a_relocated_copy(path_str, project)
            and not Path(path_str).exists())


def names_a_relocated_copy(path_str: str, project: Path) -> bool:
    """Conditions (1) and (2) above, WITHOUT the existence test.

    Split out so the RECORD WRITER can refuse this shape at the moment it is
    written, which is the only moment at which it is certainly still wrong.
    A writer cannot use `_derived_ephemeral`: at write time the staging copy
    usually still EXISTS -- it is deleted when the transaction closes, minutes
    later -- so condition (3) is False exactly when the refusal would do the
    most good. Existence is the right condition for a gate reading a finished
    run and the wrong one for the writer, and this is the one definition of the
    shape they share (vibe-ic#2158's population, one reader, not two parsers).
    """
    if "//" in path_str:
        return False
    parts = Path(path_str).parts
    if len(parts) < _MIN_DERIVED_COMPONENTS or ".." in parts:
        return False
    name = project.name
    if not name or name not in parts[1:]:
        return False
    try:
        cand, root = Path(path_str).resolve(), project.resolve()
    except OSError:                                     # pragma: no cover
        return True
    # OUTSIDE means neither the root itself nor anything beneath it. The gate's
    # own caller establishes this before reaching `_derived_ephemeral`; a writer
    # calling in directly has to establish it here, and the project's OWN path
    # is the case that makes the difference (it names the project and is not
    # under itself). MEASURED: without this, three landed runner tests lost
    # their report entirely, because `"project": str(project)` in the summary
    # was itself read as a relocated copy.
    return cand != root and root not in cand.parents


# `_docker_watchdog.py` owns this exact private namespace.  The file is a
# process-lifetime coordination marker, deliberately removed when the supervised
# child exits.  Telemetry keeps the marker name so the invocation can be
# diagnosed later; that reference is not a deliverable location.  Keep the
# match exact so an arbitrary /tmp JSON/GDS/netlist remains blocking.
#: `flow_compliance_check._p0_first_line` truncates a gate's deciding line at
#: this many characters (#2084). Named here so the header can be FITTED to it
#: rather than discovered to overflow it by a test.
_P0_LINE_CAP = 200

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


def _parse_argv(argv: List[str]) -> Tuple[Optional[str], Optional[str],
                                           List[str]]:
    """(project, --json REPORT, [--auditor-record REL ...]) from `argv`."""
    project: Optional[str] = None
    report: Optional[str] = None
    auditor: List[str] = []
    it = iter(argv)
    for arg in it:
        if arg == "--json":
            report = next(it, None)
        elif arg == "--auditor-record":
            rel = next(it, None)
            if rel:
                auditor.append(Path(rel).as_posix())
        elif project is None:
            project = arg
    return project, report, auditor


def _write_report(report: Optional[str], verdict: str, rc: int,
                  flagged: List[dict], excluded: List[str], encoding_producer=None) -> None:
    """The findings IN FULL, beside the capped stdout line (see --json)."""
    if not report:
        return
    # Imported HERE, not at module load: `scratch_root_guard` loads this file BY
    # PATH (with only its module-level siblings beside it) to read
    # `_VOLATILE_PREFIXES`, and a report is written only when one was asked for.
    import _atomic_artefact as _aa                                # noqa: E402
    _aa.write_json(Path(report), {
        "gate": "project_outputs_in_tree_check",
        "verdict": verdict,
        "exit_code": rc,
        "reason_class": None,
        "flagged": flagged,
        "auditor_records_not_judged": excluded,
        "encoding_producer": encoding_producer,
    })


def _current_encoding_producer(project: Path):
    """Only actual current source/native evidence admits a new continuation.

    The owning P0 dispatcher supplies the exact receipt/hash after the actual
    producer returns. Historical missing evidence remains missing; this admits
    only a diagnostic role in the presence of independently verified current
    producer evidence. A hand-written history shape alone grants nothing.
    """
    try:
        cap = json.loads(os.environ.get('VIBEIC_P0_ENCODING_PRODUCER', 'null'))
        if not isinstance(cap, dict) or set(cap) != {'path', 'sha256'}:
            return None
        receipt = Path(cap['path'])
        state = project / '.vibeic-state/audit_receipts'
        if (not receipt.is_absolute() or receipt.resolve() != receipt
                or not receipt.is_relative_to(state)
                or receipt.name != 'encoding_audit_report.json'
                or _sha256_file(receipt) != cap['sha256']):
            return None
        payload = json.loads(receipt.read_text())
        cfg = payload.get('configuration') or {}
        summary = payload.get('summary') or {}
        discovery = payload.get('discovery') or {}
        rows = payload.get('interfaces')
        if (payload.get('report_schema') != 'vibeic.interface_encoding_audit.v2'
                or type(payload.get('producer_returncode')) is not int
                or payload['producer_returncode'] != 0
                or not isinstance(cfg.get('native'), dict)
                or discovery.get('complete') is not True or discovery.get('issues') != []
                or not isinstance(rows, list) or not rows
                or not all(isinstance(r, dict) and r.get('status') in
                           ('MATCH', 'MISMATCH', 'UNKNOWN') for r in rows)
                or type(summary.get('total_interfaces')) is not int
                or summary['total_interfaces'] != len(rows)
                or any(type(summary.get(k)) is not int or summary[k] != sum(
                    row['status'] == status for row in rows)
                    for k, status in (('matches','MATCH'),('mismatches','MISMATCH'),('unknowns','UNKNOWN')))):
            return None
        # Select the actual project source, independently of the receipt's
        # self-declared root, using the same existing front-door locations.
        rtl = next((project / rel for rel in ('phase2/stage1/rtl','rtl','src','hdl')
                    if (project / rel).is_dir() and (any((project / rel).glob('*.v'))
                        or any((project / rel).glob('*.sv')))), None)
        if rtl is None and (any(project.glob('*.v')) or any(project.glob('*.sv'))):
            rtl = project
        if rtl is None:
            return None
        shared = Path(__file__).resolve().parent.parent / '_shared'
        if str(shared) not in sys.path:
            sys.path.insert(0,str(shared))
        import skill_compliance_check as checker
        if checker._encoding_native_source_error(payload, receipt):
            return None
        findings = checker._cc_audit_receipt_evidence(
            {'id':'storage_current_encoding','auditor':'interface_encoding_audit'}, '',
            checker.CheckContext(output_path=receipt.parent/'review.md',
                                 evidence_dirs=[receipt.parent], rtl_source_root=rtl))
        if len(findings) != 1:
            return None
        finding = findings[0]
        if (finding.state != 'PASS' and not (
                finding.state == 'NOT_MEASURED' and
                finding.detail.endswith('producer_inconclusive_or_unknown; fresh.'))):
            return None
        return cap
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ImportError):
        return None


def _auditor_diagnostic_text(txt: str, auditor_records: List[str],
                             encoding_producer=None) -> Tuple[str, List[str]]:
    """Project typed auditor diagnostics onto their current declaration role.

    An old gate finding records an earlier measurement, not a fresh output
    declaration. Apply only while the owning auditor invokes this gate; a
    standalone read, malformed record, other fields and declared outputs keep
    the existing scan. Original report bytes are never rewritten.
    """
    if "reports/audit/phase23_completion_audit.json" not in auditor_records:
        return txt, []
    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate diagnostic key")
            value[key] = item
        return value
    try:
        doc = json.loads(txt, object_pairs_hook=unique_object)
    except ValueError:
        return txt, []
    if (not isinstance(doc, dict)
            or not isinstance(doc.get("steps"), list)
            or not isinstance(doc.get("scope"), dict)
            or not isinstance(doc.get("gate_execution_ledger"), list)
            or not isinstance(doc.get("invocation"), str)
            or not doc["invocation"].strip()
            or not (doc.get("program") == "flow_compliance_check"
                    or (doc.get("schema_version") == 2
                        and doc.get("recheck_of") ==
                        "reports/audit/phase23_completion_audit.json"))):
        return txt, []
    projected: List[str] = []
    for si, step in enumerate(doc["steps"]):
        if not isinstance(step, dict):
            continue
        records = step.get("gate_records")
        if not isinstance(records, list):
            continue
        for gi, gate in enumerate(records):
            # A failed measurement explicitly refuses this receipt as proof.
            # Its diagnostic is not a new output declaration on the next audit
            # pass. Keep qualifying/stale/malformed receipts and all other
            # fields visible, and never rewrite the original report bytes.
            evidence = gate.get("evidence") if isinstance(gate, dict) else None
            if (encoding_producer is not None
                    and doc.get("program") == "flow_compliance_check"
                    and doc.get("invoked_as") in ("audit", "producer")
                    and doc.get("overall") in ("FAIL", "NOT_MEASURED")
                    and step.get("id") == "P0"
                    and step.get("status") in ("FAIL", "NOT_MEASURED")
                    and isinstance(gate, dict)
                    and gate.get("name") == "interface_encoding_audit"
                    and gate.get("verdict") == "INCOMPLETE"
                    and gate.get("reason_class") == "EXECUTION_ERROR"
                    and isinstance(evidence, dict)
                    and type(evidence.get("exit_code")) is int
                    and evidence["exit_code"] == 0
                    and evidence.get("receipt_state") == "NOT_MEASURED"
                    and isinstance(evidence.get("receipt_detail"), str)):
                detail = re.fullmatch(
                    r"receipt=(/[^\s]+/encoding_audit_report\.json) "
                    r"sha256=([0-9a-f]{16}) — producer_inconclusive_or_unknown; fresh\.",
                    evidence["receipt_detail"])
                if detail:
                    evidence["receipt_detail"] = (
                        "nonqualifying receipt sha256=" + detail.group(2) +
                        "; producer_inconclusive_or_unknown; original diagnostic retained")
                    projected.append(f"steps/{si}/gate_records/{gi}/evidence/receipt_detail")
            if (not isinstance(gate, dict)
                    or gate.get("name") != "project_outputs_in_tree_check"
                    or not isinstance(gate.get("evidence"), dict)
                    or not isinstance(gate["evidence"].get("flagged"), list)):
                continue
            flags = gate["evidence"]["flagged"]
            # Leave anything that does not have the existing finding shape
            # available to the normal path scanner, including malformed data.
            diagnostic = re.compile(r"^.+ → /.+ \((?:live|dangling|outside-root)\)$")
            retained = [x for x in flags
                        if not isinstance(x, str) or not diagnostic.fullmatch(x)]
            if len(retained) != len(flags):
                gate["evidence"]["flagged"] = retained
                projected.append(f"steps/{si}/gate_records/{gi}/evidence/flagged")
    # Legacy nested audits also recorded their OWN redirected --json argument.
    # Recognize only the stage-compliance receipt matching the typed scope;
    # other argv paths and every declared output remain visible.
    argv = doc.get("command_argv")
    scope = doc["scope"]
    stage = scope.get("stage")
    expected = (f"stage{stage}_compliance.json" if str(stage) in ("1", "2", "3")
                else f"{scope['stage_id']}_compliance.json"
                if isinstance(scope.get("stage_id"), str) else None)
    if isinstance(argv, list) and argv and isinstance(argv[0], str):
        owner = Path(argv[0]).name
        owners = ("flow_compliance_check.py", "stage1_compliance.py",
                  "stage2_compliance.py", "stage3_compliance.py")
        if owner in owners and expected:
            for i, flag in enumerate(argv[:-1]):
                if flag != "--json" or not isinstance(argv[i + 1], str):
                    continue
                target = Path(argv[i + 1])
                if (target.is_absolute() and target.name == expected
                        and target.parent.name.startswith("gate_receipt_")):
                    argv[i + 1] = expected
                    projected.append(f"command_argv/{i + 1} (own stage receipt)")
    return (json.dumps(doc, ensure_ascii=False), projected) if projected else (txt, [])


def main() -> int:
    arg_project, report, auditor_records = _parse_argv(sys.argv[1:])
    if arg_project is None:
        print("usage: project_outputs_in_tree_check <project_dir> "
              "[--json REPORT] [--auditor-record REL ...]", file=sys.stderr)
        return 2
    project = Path(arg_project).resolve()
    if not project.is_dir():
        print(f"ERROR: {project} not a directory", file=sys.stderr)
        return 2
    encoding_producer = _current_encoding_producer(project) if auditor_records else None
    # The invoking auditor's own record(s): not judged here (see --auditor-record).
    auditor_excluded: List[str] = []
    auditor_diagnostics: List[Tuple[str, List[str]]] = []

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
    # (file, path) for an in-tree self-reference whose file is not on disk.
    # Counted and disclosed; never a finding. See the block that fills it.
    in_tree_absent: List[Tuple[str, str]] = []
    # #2158 — the DERIVED ephemeral class: an absolute path outside the
    # project root that is not on disk, whatever prefix it carries.
    # (file, path) — always dangling by construction.
    derived: List[Tuple[str, str]] = []
    #: R-0915-162 — staged paths whose bytes were verified under the final name.
    consumed: List[Tuple[str, str, str]] = []
    # THE SCAN SIZE, kept because the exit code alone cannot carry it
    # (#511/#564). `no /tmp ... paths referenced` is a statement about the
    # FINDING and is exactly as true of a project with nothing in it as of a
    # clean one; over an empty tree this gate answered rc 0 and said nothing
    # about having opened zero files.
    scanned = 0
    seen: Set[str] = set()
    # #2158 — paths the derived pass has already decided about. Kept apart from
    # `seen` so the volatile-prefix pass keeps deciding first and its verdicts
    # are byte-identical to before.
    seen_derived: Set[str] = set()
    ephemeral_derived: List[Tuple[str, str]] = []
    # A relocated-copy reference whose artefact IS in the run root: the same file
    # named through a second mount of this tree. Disclosed, never blocking -- the
    # evidence is not lost, which is the only thing this gate exists to catch.
    # (file, path, run-relative path that exists)
    other_mount: List[Tuple[str, str, str]] = []
    for pat in _SCAN_GLOBS:
        for f in project.glob(pat):
            if not f.is_file():
                continue
            if auditor_records:
                _rel = f.relative_to(project).as_posix()
                if _rel in auditor_records:
                    if _rel not in auditor_excluded:
                        auditor_excluded.append(_rel)
                    continue
            scanned += 1
            try:
                txt = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if f.suffix == ".json":
                txt, fields = _auditor_diagnostic_text(txt, auditor_records, encoding_producer)
                if fields:
                    auditor_diagnostics.append((f.relative_to(project).as_posix(), fields))
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
                    # DISCLOSED, NEVER BLOCKING. An in-tree self-reference whose
                    # file is not on disk is a different question from this
                    # gate's -- "a declared artefact is missing" belongs to the
                    # per-step `required_outputs` resolution, which is what
                    # caught step 23's sta_spef_based.rpt and steps 36/38.
                    #
                    # MEASURED BEFORE DECIDING, over three completed spm runs:
                    #   run18L  200 in-tree self-references, 11 absent
                    #   run19   200                        , 11 absent
                    #   run20   210                        , 10 absent
                    # and all 10 of run20's are classified: FIVE are
                    # directory-shaped DESTINATIONS a record names for a review
                    # that did not run (reports/*/gates/on_pass_review,
                    # reports/crosslayer/baseline_rtl) and FIVE are optional or
                    # prospective artefacts (RESULT.md,
                    # phase1/ai_deep_review_patches.json,
                    # phase2/stage1/lessons{.md,_ack.json},
                    # reports/crosslayer/rewrite_equivalence.json). NOT ONE is a
                    # declared required_output that went missing. Blocking on
                    # them would manufacture ten findings per run and close none.
                    if not Path(p).exists():
                        in_tree_absent.append((str(f.relative_to(project)), p))
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

            # ── #2158 — the SAME question, asked of every prefix ────────────
            # A second pass over the identical text, admitting any absolute
            # path. A path already classified above keeps that classification
            # (`seen`); what is left is the class the hard list could not name:
            # outside the tree, and already gone.
            for m in _ANY_ABS_PATH_RE.finditer(txt):
                p = m.group(1).rstrip(".,;:)")
                if p in seen or p in seen_derived:
                    continue
                if _inside_project(p, project):
                    in_tree_self += 1
                    seen_derived.add(p)
                    # THE SECOND PASS COUNTS TOO. The absent-in-tree disclosure
                    # is filled from BOTH passes: every one of the ten measured on
                    # run20 is found here, by `_ANY_ABS_PATH_RE`, not by the
                    # narrower `_PATH_RE` above -- so filling it in one place only
                    # would have disclosed nothing at all.
                    if not Path(p).exists():
                        in_tree_absent.append((str(f.relative_to(project)), p))
                    continue
                if _pinned_plugin_root(p) is not None:
                    seen_derived.add(p)
                    continue
                if not _derived_ephemeral(p, project):
                    continue
                seen_derived.add(p)
                _kept = preserved_in_the_run_root(p, project)
                if _kept is not None:
                    other_mount.append(
                        (str(f.relative_to(project)), p, str(_kept)))
                    continue
                # R-0915-162 — promoted, not lost. Verified against the bytes,
                # never taken on the producer's word; see
                # `consumed_into_verified`.
                _into = consumed_into_verified(p, f, project)
                if _into is not None:
                    consumed.append((str(f.relative_to(project)), p, _into))
                    continue
                if from_log:
                    # Same rule as #622: a log cites transient tool paths by
                    # nature. Disclosed, non-blocking.
                    ephemeral_derived.append(
                        (str(f.relative_to(project)), p))
                    continue
                derived.append((str(f.relative_to(project)), p))

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
        _write_report(report, "NOT_CHECKED", 2, [], auditor_excluded, encoding_producer)
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

    if in_tree_absent:
        block = [f"[INFO] project_outputs_in_tree_check: "
                 f"{len(in_tree_absent)} in-tree self-reference(s) whose file is "
                 f"not on disk — non-blocking, and NOT this gate's question: a "
                 f"path inside the project that is absent is a missing artefact, "
                 f"which the per-step required_outputs resolution owns. Listed so "
                 f"the fact is visible without manufacturing a finding:"]
        for f_rel, path_s in sorted(in_tree_absent, key=lambda r: r[1]):
            block.append(f"  - {f_rel} → {path_s} (not on disk)")
        print("\n".join(block))

    if other_mount:
        block = [f"[INFO] project_outputs_in_tree_check: "
                 f"{len(other_mount)} reference(s) naming THIS run through "
                 f"another mount of the same tree — non-blocking, because the "
                 f"artefact is present in the run root at the same run-relative "
                 f"path, so no evidence is missing (a run bind-mounted into the "
                 f"EDA container is named both ways, and a recorded command "
                 f"line carries the container spelling):"]
        for f_rel, path_s, kept in other_mount:
            block.append(f"  - {f_rel} → {path_s} (present as {kept})")
        print("\n".join(block))
    if consumed:
        # DISCLOSED, never silent. An exemption a reader cannot see is
        # indistinguishable from a reference the scan missed, and this one is
        # load-bearing enough to say out loud: it is the only class where a
        # path that is NOT on disk stops being a finding.
        block = [f"[INFO] project_outputs_in_tree_check: "
                 f"{len(consumed)} staged path(s) CONSUMED by an in-place "
                 f"promotion — non-blocking, because an UNBROKEN chain of "
                 f"recorded digests runs from the staged bytes, through every "
                 f"in-place rewrite that touched the destination afterwards, "
                 f"to the destination's content now, so the evidence is "
                 f"provably still in the tree under its final name "
                 f"(R-0915-166):"]
        for f_rel, path_s, into in consumed:
            block.append(f"  - {f_rel} → {path_s} (consumed into {into}, "
                         f"sha256 verified)")
        print("\n".join(block))

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

    if ephemeral_derived:
        block = [f"[INFO] project_outputs_in_tree_check: "
                 f"{len(ephemeral_derived)} log-sourced dangling reference(s) "
                 f"outside the project root (#2158 derived class, found in "
                 f"*.log) — non-blocking, same rule as #622: logs cite "
                 f"transient tool paths by nature:"]
        for f, pth in ephemeral_derived[:5]:
            block.append(f"  - {f} → {pth}")
        if len(ephemeral_derived) > 5:
            block.append(f"  ... +{len(ephemeral_derived)-5} more")
        notes.append("\n".join(block))

    if auditor_excluded:
        notes.append(
            f"[INFO] project_outputs_in_tree_check: not judged, "
            f"{len(auditor_excluded)} record(s) the INVOKING AUDITOR owns "
            f"(--auditor-record): {', '.join(auditor_excluded)} — the flow gives "
            f"that document to the audit and to no step, and every version "
            f"visible while the audit runs is superseded by the one it writes "
            f"after this gate; judged like any other file when this gate runs "
            f"standalone")

    if auditor_diagnostics:
        notes.append(
            "[INFO] project_outputs_in_tree_check: historical auditor "
            "diagnostic fields are not current output declarations; original "
            "records retained, other fields judged: " + "; ".join(
                f"{rel}: {', '.join(fields)}" for rel, fields in auditor_diagnostics))

    def _emit_notes() -> None:
        """The non-blocking disclosures, AFTER the verdict line that decides."""
        for note in notes:
            print(note)

    if not nonlog and not derived:
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
              f"tool paths and supervised watchdog pidfiles excluded), and no "
              f"absolute path outside {project} that is already gone "
              f"(#2158: the population is 'a path that will not exist after "
              f"the run', derived from the run root, not a list of four "
              f"directories)")
        _emit_notes()
        _write_report(report, "PASS", 0, [], auditor_excluded, encoding_producer)
        return 0

    # Split: live (file exists at /tmp) vs. dangling (referenced but gone).
    # BOTH block. The split says what the fix is, not whether there is one.
    live = [(f, p) for (f, p, e) in nonlog if e]
    dangling = [(f, p) for (f, p, e) in nonlog if not e]

    waiver_n = _waiver_count(project)
    fail_count = len(live) + len(dangling) + len(derived)
    flagged = ([{"file": f, "path": p, "class": "live"} for f, p in live]
               + [{"file": f, "path": p, "class": "dangling"} for f, p in dangling]
               + [{"file": f, "path": p, "class": "outside-root"}
                  for f, p in derived])

    if waiver_n >= fail_count:
        print(f"[PASS_WITH_WAIVER] "
              f"project_outputs_in_tree_check: "
              f"{fail_count} external-path reference(s) but {waiver_n} "
              f"waiver(s) under '{WAIVER_KEY}'.")
        _emit_notes()
        _write_report(report, "PASS_WITH_WAIVER", 0, flagged, auditor_excluded, encoding_producer)
        return 0

    # THE DECIDING LINE (#2084). First, and tagged with the severity this
    # function is about to exit with. It states the blocking population — the
    # number the exit code is a function of — so a reader that takes only this
    # line still gets the reason and the size of it.
    # THE 200-CHARACTER BUDGET IS PART OF THE CONTRACT (#2084). `_p0_first_line`
    # publishes at most 200 characters of this line, and #2084 pins that the
    # WHOLE deciding sentence survives it — including at four-digit counts. The
    # first draft of the #2158 third term ("N dangling outside the run root")
    # pushed the 1024-reference case to 209 characters and truncated the
    # published reason mid-word; the term is spelled `outside-root` here and
    # written out in full in its own block below. Measured worst case, all three
    # counts four digits: 199 characters.
    # NAME THE FIRST REFERENCE ON THE REFUSAL LINE ITSELF -- WITHIN THE CAP.
    #
    # MEASURED on spm (lane icspm5, 2026-09-23). Step P0 recorded this gate's
    # refusal as the header alone: the path and its citing file are on the
    # lines BELOW, and the umbrella's reader (`flow_compliance_check.
    # _p0_first_line`) keeps exactly one line. The volatile path was swept
    # minutes later, the gate then exited 0, and the occurrence became
    # unattributable.
    #
    # AND THE CAP IS NOT NEGOTIABLE. `_p0_first_line` truncates at 200 chars
    # and #2084 exists because a line cut mid-sentence is how
    # `testbench_exists_check` came to publish `"{"`. My first version simply
    # appended the reference and pushed the line to 267 -- it made the refusal
    # attributable by breaking the rule that makes it publishable at all.
    #
    # So the reference is fitted to what is LEFT, and the sentence still ends
    # in the colon the contract requires. When even an elided reference will
    # not fit -- four-digit counts leave almost nothing -- the header is
    # exactly what it was, and the detail blocks below still carry the path in
    # full. The cap wins; attribution takes the room the cap leaves.
    # "in this project's declaration file(s)" is dropped to make the room.
    # It said nothing the rest of the line and the detail blocks do not: the
    # gate's NAME is in the sentence, the counts follow, and every reference
    # below is printed as "referenced in <file> → <path>". 38 characters of
    # restatement, spent instead on the one thing the record could not carry.
    _stem = (f"[FAIL] project_outputs_in_tree_check: "
             f"{fail_count} blocking external-storage reference(s) "
             f"({len(live)} live, {len(dangling)} dangling, "
             f"{len(derived)} outside-root) — this is what the "
             f"gate exits 1 on:")
    # THE ANCHOR PHRASE STAYS VERBATIM, COLON INCLUDED.
    # `test_r0915_126_an_absent_in_tree_reference_is_disclosed_not_blocked`
    # splits the output on "this is what the gate exits 1 on:" and asserts the
    # absent in-tree reference does not appear in the BLOCKING text after it.
    # My first attempt put the reference BEFORE that colon, which deleted the
    # anchor and raised IndexError -- I moved a phrase another reader parses.
    # `grep` over the plugin finds two readers, both tests; the phrase is now
    # treated as the fixed landmark it evidently is, and the reference goes
    # AFTER it, where that test's claim is measured and still holds.
    _first = (live or dangling or derived or [(None, None)])[0]
    _cited = ""
    if _first[0]:
        _budget = _P0_LINE_CAP - len(_stem) - 1          # 1 for the colon
        # THE CITING FILE FIRST. It is what names the WRITER, which is the
        # question a reader of this line is trying to answer; the path says
        # what was written. Both when they fit, the file alone when they do
        # not, and nothing when even that will not -- the detail blocks below
        # always carry the pair in full.
        _both = f" {_first[0]} → {_first[1]}"
        _file_only = f" {_first[0]}"
        if len(_both) <= _budget:
            _cited = _both
        elif len(_file_only) <= _budget:
            _cited = _file_only
    print(_stem + _cited + ":")

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

    if derived:
        # #2158 — the class the hard prefix list could not name. Blocking for
        # the same reason `dangling` is: the reference points at nothing, so a
        # reader following it learns nothing, and there is no artefact left to
        # copy in. It is separated from `dangling` only to say WHERE the run
        # put it, because that is the part the four-directory list got wrong.
        print(f"[FAIL] project_outputs_in_tree_check: "
              f"{len(derived)} dangling reference(s) to a path outside "
              f"{project} that is NOT on disk — an ephemeral location this "
              f"run used and did not preserve (a TMPDIR under $HOME or "
              f"anywhere else counts; the population is derived from the run "
              f"root, not from a list of volatile prefixes):")
        for f, pth in derived[:8]:
            print(f"  - {f} → {pth} (NOT found on disk)")
        if len(derived) > 8:
            print(f"  ... +{len(derived)-8} more")

    _emit_notes()

    print(f"\nFix: copy live artifacts to canonical project paths and "
          f"update references. Then re-run audit. To accept volatile "
          f"storage (e.g. cache that's intentionally ephemeral), add "
          f"waiver '{WAIVER_KEY}' (one per path, >={WAIVER_MIN} chars).")
    _write_report(report, "FAIL", 1, flagged, auditor_excluded, encoding_producer)
    return 1


if __name__ == "__main__":
    sys.exit(main())
