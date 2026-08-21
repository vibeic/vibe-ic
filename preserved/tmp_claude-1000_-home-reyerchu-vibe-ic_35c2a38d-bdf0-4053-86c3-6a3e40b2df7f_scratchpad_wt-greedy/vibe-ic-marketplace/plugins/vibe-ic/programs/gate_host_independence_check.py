#!/usr/bin/env python3
"""gate_host_independence_check.py — the same commit must give the same verdict.

THE CLASS (vibe-ic#447), and why a SECOND probe was needed
===========================================================
`gate_discloses_denominator_check` catches a gate that PASSes over an empty
tree without saying so. It does NOT catch the other half of the same class: a
gate that examines the WRONG POPULATION and reports confidently about it.

    provenance_output_hash_completeness_check  PASS in a worktree, FAIL in a
                                               working checkout (v1.6.88)
    cross_layer_reference_check                46 cells vs 23, making a
                                               COUNT baseline host-dependent
    l4_systemrdl_export                        299 documents on disk vs 201
                                               tracked (v1.6.91)
    benchmark_evidence_publish                 reproduced by the author IN the
                                               fix for #448, one day after
                                               landing the shared helper that
                                               exists to prevent it (v1.7.13)

Every one walked THIS MACHINE'S DISK where the question was what the PUBLISHED
tree carries. A working checkout keeps untracked run leftovers; a fresh clone
and a `git worktree` do not. So the verdict depended on who ran it — and always
in the same direction: whoever exercises the tool most gets the most false
alarms.

THE PROBE
=========
Run each corpus-scanning gate TWICE at the same commit — once in the working
checkout, once in a throwaway `git worktree` (tracked files only) — and require
the verdict line to be IDENTICAL. A difference is proof the gate is reading
something that is not in the commit.

Proven BOTH ways before landing, which is what separates this from a guess:

  negative control  the two gates fixed at v1.6.90/91 agree exactly
  positive control  restoring `cross_layer_reference_check`'s pre-fix
                    disk-walking `corpus_cells` makes the checkout report an
                    extra finding while the worktree says PASS — caught

WHY NOT A STATIC CHECK
======================
"Programs that rglob a project directory without using `_published_tree`" is 37
of them, and nearly all are RIGHT: a gate reading a RUN directory should read
the disk, because nothing is published yet. There is no static discriminator
for "this walk targets a published tree", so a static rule would fire on
legitimate code — the failure mode that got the orphan-capability detector
(#439) deleted rather than landed. Running it is the discriminator.

THE REFUSAL WAS KEYED ON THE WRONG SIGNAL (vibe-ic#539)
=======================================================
The probe detects a gate reading LOCAL state by giving ONE side that state and
the other side none of it. The working checkout's untracked and ignored
leftovers ARE the stimulus; the fresh worktree is the control. Take the
leftovers away from both sides and the two trees are byte-identical, every gate
agrees by construction, and the PASS measured nothing.

Until #539 this program refused on ANY output from `git status --porcelain`,
which folds together two opposite things:

    MODIFIED TRACKED FILES  the worktree is at HEAD and does not carry the
                            edit, so a difference between the trees says
                            nothing about host-dependence. Genuinely
                            uncheckable — still rc 2.
    UNTRACKED PATHS         here and not in the worktree, which is precisely
                            the condition being probed. The stimulus, not an
                            obstacle.

MEASURED, one toy gate that counts files on disk (the reduced form of
`cross_layer_reference_check`'s 46-cells-against-23), three trees at ONE commit:

    checkout carrying an UNTRACKED leftover   DIRTY_CHECKOUT   defect MISSED
    a fresh worktree of that same commit      PASS             defect MISSED
    checkout carrying an IGNORED leftover     FAIL             defect CAUGHT

Row 2 is the pre-push "run it in a clean worktree instead" habit, and it prints
`[PASS] all N corpus-scanning gate(s) give the same verdict` over a gate that
demonstrably reads local state — two pristine trees cannot exhibit the class.
Row 3 caught it only because an IGNORED file is invisible to `git status`, so
the refusal never fired on it. The refusal was rejecting the stimulus and
admitting it only in the one shape it could not see.

So the repair is not to make the probe tolerate a dirty tree by looking at
LESS. It is to run it where the stimulus lives — the working tree these
leftovers accumulate in, which is the one tree the probe used to refuse — and
to REPORT how much stimulus a run actually had, so that a comparison between
two identical trees can never again be read as coverage. A run with no stimulus
is NOT_CHECKED (rc 2), never a pass.

THE SCRATCH WORKTREE OUTLIVES THE PROBE (measured 2026-08-04)
=============================================================
The comparison needs a second tree, so this program creates one — a `mkdtemp`
plus a `git worktree add`, removed in a `finally`.  A `finally` does not run on
`SIGKILL`, and in one parallel-agent session NINETEEN `/tmp/hostindep-*/wt`
trees were left standing, each still REGISTERED as a worktree of the repository
every agent shares.  `git worktree prune` cannot clear a registration whose
directory still exists, so they do not age out; they accumulate.

The repair is not a better `finally` — there is no code the killed process gets
to run.  It is to make the NEXT run able to prove the previous one is dead and
clean up for it: each scratch directory carries an `flock`'d sidecar, which the
kernel releases on death however the process died, and `_crash_safe_scratch`
reaps every sibling whose lock it can take.  A peer that is still running holds
its lock, is skipped, and is NAMED in the output.

chip-AGNOSTIC: it compares process output, nothing else.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

import _crash_safe_scratch as _scratch

_HERE = Path(__file__).resolve().parent
_PLUGIN = _HERE.parent

if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
# THE SCRIPT IS PARSED IN ONE PLACE. This file used to carry a verbatim copy of
# the other reader's regex, with a comment saying so — and the copy is what let
# one defect hide in two files at once: neither could see a gate whose label
# embeds `$(basename "$(dirname "$_cell")")`, because the label group stopped
# at the inner quote, and neither folded `\` continuations. Fixing that in one
# copy would have left the other still blind and the two readers disagreeing
# about what the script says, which the #539 tests exist to forbid.
#
# THE COPY WAS RE-ADDED ONCE, IN A MERGE, AND THAT IS THE POINT. The crash-safe
# scratch work landed a second `_RUN_RE` here — the very regex this file had
# just stopped carrying — widened by one hand for `run_tolerating_uncheckable`
# while the other hand was rewriting the shared reader. Driven against the
# merged `tools/ci/repo_hygiene_gates.sh`, the regex saw 60 declarations and
# `parse_declarations` saw 63: the three `$_cell` loop gates were invisible to
# it, and `severity=ERROR is consumed` came back truncated at its `\`. The one
# element the regex produced that the shared reader does not is that truncation
# — same label, broken command — so nothing is lost by deleting it, and a
# second copy is exactly how the last defect stayed invisible in both files.
from gate_discloses_denominator_check import (            # noqa: E402
    parse_declarations)

#: Scratch prefix.  UNCHANGED from the leaking version on purpose — the reaper
#: keys on it, so the directories a pre-fix build already left behind are the
#: first thing a fixed run cleans up.
_SCRATCH_PREFIX = "hostindep-"

#: A gate may DECLARE itself out of this comparison, on the line above its own
#: `run` line, in the script where it is wired:
#:
#:     # host-independence: EXCLUDE — <why>
#:     run "..." "$ROOT" python3 ...
#:
#: WHY A STANDALONE LINE AND NOT A TRAILING COMMENT. `_RUN_RE` here is
#: duplicated verbatim in `gate_discloses_denominator_check`, which drives the
#: same script against a scratch empty tree. A marker appended to the gate line
#: would land inside THAT parser's command capture and be handed to the gate as
#: argv, so the two readers of one script would disagree about what the script
#: says. Anchored at `^\s*run`, neither parser can see a line above.
#:
#: WHY ANY EXCLUSION AT ALL. `sync_image_version --check --require-remote`
#: resolves a tag on a remote registry. This probe runs every gate TWICE and
#: requires the two verdicts to match, so a gate whose answer depends on a
#: network round-trip can differ between the invocations for a reason that is
#: not in the commit — which is how v1.7.92 went red on a gate whose code is
#: perfectly host-independent, and green on the identical commit when re-run.
#: Excluding it deliberately is the alternative to excluding it by luck.
#:
#: FAIL-SAFE BY SHAPE: the directive must be the line IMMEDIATELY above. If it
#: is moved or a line is inserted, the gate is PROBED again — the failure mode
#: is a returning flake, which is visible, not a silent exclusion. Every
#: exclusion is NAMED in the verdict line for the same reason.
_EXCLUDE_RE = re.compile(
    r'^\s*#\s*host-independence:\s*EXCLUDE\b[\s—:-]*(.*?)\s*$')


class Gate(NamedTuple):
    """One gate as the CI script declares it."""
    label: str
    cwd_token: str          # `$ROOT` or `$PLUGIN`
    cmd: str
    excluded: Optional[str]  # None = probed; a string = declared reason
    #: Set when the declaration carries something only bash can resolve — a
    #: loop variable, a command substitution. Such a gate is DECLARED here and
    #: cannot be DRIVEN here, and the two are different facts.
    runtime_expansion: Optional[str] = None


class Dirt(NamedTuple):
    """What the working checkout carries that a fresh worktree would not.

    `tracked` invalidates the comparison; `untracked` + `ignored` ARE the
    comparison's stimulus. Splitting them is the whole of #539.
    """
    tracked: List[str]
    untracked: List[str]
    ignored: List[str]
    ignored_reported: bool   # False when git would not report ignored paths

    @property
    def stimulus(self) -> int:
        return len(self.untracked) + len(self.ignored)

    def describe(self) -> str:
        ig = (f"{len(self.ignored)} ignored" if self.ignored_reported
              else "an unreported number of ignored")
        return (f"{len(self.untracked)} untracked + {ig} path(s) present in "
                f"the checkout and not in a fresh worktree")


class Audit(NamedTuple):
    """The probe's result, with its own denominator attached.

    `declared` vs `probed` is load-bearing and used to be absent: the verdict
    line said "all N gate(s)" using the DECLARED count while the loop had
    skipped this program itself, so the sentence was already over-claiming by
    one before any exclusion existed.
    """
    verdict: str
    findings: List[Dict]
    dirt: Optional[Dirt]
    declared: int
    probed: int
    not_probed: List[Tuple[str, str]]   # (label, why)
    #: What the scratch reaper did on the way in. Reported rather than silent:
    #: a sweep that removes another agent's live worktree and says nothing is
    #: the same class of damage as the leak it is fixing, so both the removals
    #: and the SKIPS are named.
    scratch: Optional[Dict] = None


def corpus_gates(script: Path) -> List[Gate]:
    """Every gate the CI script runs, with any EXCLUDE directive attached.

    The cwd token is LOAD-BEARING and was dropped in a first version: the
    `$PLUGIN`-scoped gates invoke a RELATIVE `programs/x.py`, so running
    them from the repo root made both trees fail to open the file and
    produced 9 identical-error "findings". A probe that reports a defect
    because it could not run the subject is worse than no probe."""
    try:
        lines = script.read_text(errors="replace").splitlines()
    except OSError:
        return []
    # NO FILTER. A first version kept only gates whose argv names
    # `benchmark-data` and parsed exactly ONE of them — most read the corpus
    # from an internal default, so the argv says nothing. Guessing which gates
    # "could" have the defect is how the defect keeps escaping; running all of
    # them costs a couple of minutes and needs no guess.
    #
    # An EXCLUDED gate is still parsed and still counted in `declared`. It
    # leaves the numerator, never the denominator.
    out: List[Gate] = []
    for decl in parse_declarations(script):
        # THE DIRECTIVE BINDS TO THE LINE IMMEDIATELY ABOVE THE `run` LINE.
        # `lineno` is the first PHYSICAL line of the declaration, so a gate
        # written across a `\` continuation still looks one line up from where
        # a reader of the script sees it start. The adjacency rule is the whole
        # fail-safe claim: if the directive drifts, the gate is probed again.
        above = lines[decl.lineno - 2] if decl.lineno >= 2 else ""
        d = _EXCLUDE_RE.match(above)
        reason = None
        if d:
            reason = d.group(1).strip() or "declared at the gate, no reason given"
        out.append(Gate(decl.label, decl.cwd_token, decl.cmd, reason,
                        decl.runtime_expansion))
    return out


def inert_exclusions(script: Path) -> List[Tuple[int, str]]:
    """EXCLUDE directives WRITTEN in the script that exclude NOTHING.

    The adjacency rule above is fail-safe for the gate — drift means the gate
    is probed again — but it is NOT fail-safe for the READER, and that half was
    unenforced. Measured on origin/main 1f3d8d067: THREE directives are written
    (lines 162, 175, 221) and only TWO take effect. The third sits one blank
    line above `run_tolerating_uncheckable "STA engines agree"`, so the parser
    reads the blank line, finds no directive, and probes the gate anyway. A
    reader of the script sees an exclusion that does not exist.

    A declaration that silently does nothing is this repo's recurring shape
    with the polarity reversed: not a check that lies about what it found, but
    a directive that lies about what it governs. It is cheap to detect —
    written count vs effective count — so it is detected.
    """
    try:
        lines = script.read_text(errors="replace").splitlines()
    except OSError:
        return []
    out: List[Tuple[int, str]] = []
    run_head = re.compile(r'^\s*run(?:_\w+)?\s')
    for i, ln in enumerate(lines):
        if not _EXCLUDE_RE.match(ln):
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if not run_head.match(nxt):
            out.append((i + 1, ln.strip()[:160]))
    return out


def _expand(cmd: str, root: Path) -> List[str]:
    c = cmd.replace('"$PG/', str(root / "vibe-ic-marketplace" / "plugins" /
                                 "vibe-ic" / "programs") + "/")
    c = c.replace('"$ROOT/', str(root) + "/").replace('"', "")
    c = c.replace("$PLUGIN", str(root / "vibe-ic-marketplace" / "plugins" /
                                 "vibe-ic"))
    c = c.replace("$ROOT", str(root))
    return c.split()


def _norm(line: str, repo_root: Path, wt: Path) -> str:
    """Replace either tree's path with a stable placeholder."""
    for root in (str(wt.resolve()), str(wt), str(repo_root.resolve()),
                 str(repo_root)):
        if root:
            line = line.replace(root, "<TREE>")
    return line


def _verdict_line(out: str) -> str:
    """The last non-empty line — the verdict a caller reads."""
    lines = [ln.rstrip() for ln in (out or "").splitlines() if ln.strip()]
    return lines[-1] if lines else "(no output)"


def checkout_dirt(repo_root: Path, timeout: int = 600) -> Optional[Dirt]:
    """Split what the checkout carries into the three categories that matter.

    Returns None when git would not answer at all — "I could not look" is its
    own state here too, and must not collapse into "the tree was clean".
    """
    def _status(extra: List[str]) -> Optional[List[str]]:
        try:
            st = subprocess.run(
                ["git", "-C", str(repo_root), "status", "--porcelain", *extra],
                capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            return None
        if st.returncode != 0:
            return None
        return [ln for ln in st.stdout.splitlines() if ln.strip()]

    # `traditional` collapses an ignored DIRECTORY into one entry instead of
    # walking into it, which keeps this cheap on a tree carrying large ignored
    # build output. The count is a disclosure, not an inventory.
    lines = _status(["--ignored=traditional"])
    ignored_reported = lines is not None
    if lines is None:                       # older/odd git: fall back
        lines = _status([])
        if lines is None:
            return None
    tracked, untracked, ignored = [], [], []
    for ln in lines:
        (untracked if ln.startswith("??")
         else ignored if ln.startswith("!!")
         else tracked).append(ln)
    return Dirt(tracked, untracked, ignored, ignored_reported)


def _unregister_worktree(scratch: Path) -> None:
    """Drop the git registration an abandoned scratch tree still holds.

    Addressed THROUGH the worktree itself (`git -C <wt> worktree remove <wt>`)
    rather than through the repo this run happens to be probing: a leftover may
    belong to any checkout on the host, and pointing the wrong repository at it
    would fail while looking like it worked.  The directory is what knows who
    owns it.
    """
    wt = scratch / "wt"
    if not wt.exists():
        return
    r = subprocess.run(["git", "-C", str(wt), "worktree", "remove", "--force",
                        str(wt)], capture_output=True, text=True, timeout=120)
    if r.returncode == 0:
        return
    # A worktree git considers LOCKED refuses a single `--force`. Measured: a
    # run killed mid-`worktree add` left the lock behind, so the very state
    # this reaper exists for is the one that can be locked. `unlock` then
    # retry; if that still fails the directory is removed anyway and the
    # registration is dropped by the `prune` the caller runs — never left
    # standing because one git subcommand was fussy.
    subprocess.run(["git", "-C", str(wt), "worktree", "unlock", str(wt)],
                   capture_output=True, text=True, timeout=120)
    subprocess.run(["git", "-C", str(wt), "worktree", "remove", "--force",
                    str(wt)], capture_output=True, text=True, timeout=120)


def _release_scratch(res, repo_root: Path) -> None:
    """The CLEAN path: unregister, unlock, delete.

    Correctness does not depend on reaching it — that is what the reaper is for
    — but a run that exits normally should not leave work for the next one.
    """
    _unregister_worktree(res.path)
    res.release()
    # Only ever removes registrations whose DIRECTORY is gone, so a worktree a
    # concurrent agent is sitting in cannot be pruned by this.
    subprocess.run(["git", "-C", str(repo_root), "worktree", "prune"],
                   capture_output=True, text=True, timeout=120)


def _setup(verdict: str, kind: str, detail: str, dirt: Optional[Dirt],
           declared: int, scratch: Optional[Dict] = None) -> Audit:
    """A result decided before any gate ran. 0 probed, and it says so."""
    return Audit(verdict,
                 [{"gate": "(setup)", "kind": kind, "detail": detail}],
                 dirt, declared, 0, [], scratch)


def peer_probes_running() -> List[int]:
    """Other live processes running THIS program, by pid.

    Needed only for the transition. A build that predates the lock sidecar
    leaves a scratch directory this reaper cannot attribute, so it falls back
    to age plus a `/proc` scan — and several agents demonstrably run against
    one host, where a probe that has been alive longer than the age threshold
    would be a candidate for deletion at the instant no child of it happens to
    be sitting in the directory. While ANY peer is alive the unlockable
    directories are simply kept; the guess is not made better, it is not made.
    """
    me = Path(__file__).name
    pids: List[int] = []
    proc = Path("/proc")
    if not proc.is_dir():
        return [-1]                     # cannot look -> assume a peer exists
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            cmd = (entry / "cmdline").read_bytes().decode("utf-8", "replace")
        except OSError:
            continue
        if me in cmd:
            pids.append(int(entry.name))
    return pids


def sweep_abandoned_scratch(repo_root: Path,
                            tmp_root: Optional[Path] = None,
                            peers: Optional[List[int]] = None) -> Dict:
    """Clean up after every PREVIOUS run of this program that was killed.

    Runs before anything else, and on every exit path including the ones that
    refuse to probe: a checkout too dirty to compare is exactly the state a
    maintainer's tree is in while the leftovers pile up, so a reaper that only
    ran on the happy path would almost never run at all.

    `tmp_root` and `peers` are test seams, and they exist for a reason this
    module is about: a test that drove this against the real `/tmp` would
    create and delete directories other agents' probes are reading, and one
    that depended on no peer being alive would either race them or skip
    whenever the host is busy — which on this host is most of the time.
    """
    if peers is None:
        peers = peer_probes_running()
    rep = _scratch.reap(_SCRATCH_PREFIX, remover=_unregister_worktree,
                        root=tmp_root, reap_unlocked=not peers)
    if rep.reaped:
        # `prune` after the removals, not instead of them: it drops the
        # registrations whose directories this sweep has just deleted, and by
        # construction cannot touch one whose directory still exists.
        subprocess.run(["git", "-C", str(repo_root), "worktree", "prune"],
                       capture_output=True, text=True, timeout=120)
    return {"reaped": rep.reaped, "live_peers": rep.live,
            "peer_probe_pids": peers,
            "vanished_under_the_sweep": rep.vanished,
            "kept": [{"path": p, "why": w} for p, w in rep.kept]}


def _checkout_dirty_paths(repo_root: Path) -> Dict[str, str]:
    """``{path: status}`` for everything git currently reports, or ``{}``.

    No ``--ignored``: `__pycache__` and `.pytest_cache` churn on every drive and
    are not what a killed mutator leaves. Including them would make this fire on
    every gate in every run, and a guard that always fires is one people route
    around.

    An unreadable tree returns ``{}``, which makes `_repair_checkout` a no-op --
    it can then only fail to repair, never repair the wrong thing.
    """
    try:
        r = subprocess.run(["git", "-C", str(repo_root), "status",
                            "--porcelain"],
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return {}
    if r.returncode != 0:
        return {}
    out: Dict[str, str] = {}
    for line in (r.stdout or "").splitlines():
        if len(line) > 3:
            out[line[3:].strip()] = line[:2]
    return out


def _repair_checkout(repo_root: Path, before: Dict[str, str],
                     label: str) -> Tuple[List[str], List[str]]:
    """Undo what THIS drive wrote. Returns ``(repaired, refused)``.

    THE BOUNDARY, because an over-eager repair here would destroy a
    maintainer's work in order to tidy up after a gate:

      * a TRACKED path that was pristine before and is modified after -- the
        difference was made by the child this loop just ran, so
        ``git checkout -- <path>`` undoes that and provably nothing else.
        REPAIRED.
      * a path that was ALREADY dirty before the drive -- somebody's in-flight
        work, possibly with the gate's write layered on top. Nothing here can
        separate the two, so it is NAMED and left exactly as it is. REFUSED.
      * an UNTRACKED path that appeared -- a gate writing its own report beside
        the code is doing the thing the corpus guard's message recommends.
        Named, never deleted: this function's licence is to undo a modification
        it can prove it caused, not to remove files.
    """
    after = _checkout_dirty_paths(repo_root)
    repaired: List[str] = []
    refused: List[str] = []
    for path, status in sorted(after.items()):
        if path in before:
            continue
        if status.strip() == "??":
            refused.append(f"{path} (untracked -- named, not deleted)")
            continue
        r = subprocess.run(
            ["git", "-C", str(repo_root), "checkout", "--", path],
            capture_output=True, text=True, timeout=120)
        if r.returncode == 0 and path not in _checkout_dirty_paths(repo_root):
            repaired.append(path)
        else:
            refused.append(f"{path} (restore failed)")
    for path in sorted(before):
        if path in after and after[path] != before[path]:
            refused.append(f"{path} (already dirty before this drive)")
    return repaired, refused


def audit(repo_root: Path, timeout: int = 600,
          tmp_root: Optional[Path] = None) -> Audit:
    """`tmp_root` overrides where the scratch lives (default: the system temp).

    A caller that needs to OBSERVE what this run left behind cannot do it in
    the shared temp: on a busy host a peer's directory appears there mid-run
    and is indistinguishable from a leak of our own. Pointing this at a private
    root is what makes "left nothing behind" a statement about THIS run.
    """
    scratch = sweep_abandoned_scratch(repo_root, tmp_root=tmp_root)
    script = repo_root / "tools" / "ci" / "repo_hygiene_gates.sh"
    gates = corpus_gates(script)
    declared = len(gates)
    if not gates:
        # This program's own denominator: reporting clean over an empty gate
        # list is the defect it exists to catch, one level up.
        return Audit("NOTHING_SCANNED", [], None, 0, 0, [], scratch)

    dirt = checkout_dirt(repo_root, timeout)
    if dirt is None:
        return _setup("STATUS_UNAVAILABLE", "STATUS_UNAVAILABLE",
                      "`git status` did not answer, so the checkout could not "
                      "be characterised and no comparison was attempted",
                      None, declared, scratch)

    # MODIFIED TRACKED FILES make the comparison meaningless: the worktree is
    # at HEAD, so every uncommitted edit shows up as a "difference" that has
    # nothing to do with the defect being probed. Measured while building this
    # — an in-progress version of THIS program made the chip-agnostic guard
    # report 1241 files against the worktree's 1240 and flagged itself as an
    # unwired checker. Reporting those as host-dependence would be a probe that
    # fires on its own author.
    #
    # Refused rather than filtered: "the comparison could not be made" is its
    # own state and must not be dressed up as a clean one.
    #
    # UNTRACKED paths used to be refused by this same branch and are not
    # refused now — see the module docstring. They are the stimulus.
    if dirt.tracked:
        return _setup(
            "DIRTY_CHECKOUT", "DIRTY_CHECKOUT",
            f"{len(dirt.tracked)} TRACKED path(s) modified/staged; the "
            f"worktree is at HEAD so each would read as a difference that is "
            f"about the edit, not about the gate. Commit or stash them and the "
            f"probe runs — untracked leftovers no longer block it "
            f"({len(dirt.untracked)} present). First few: "
            + ", ".join(x[3:][:40] for x in dirt.tracked[:4]),
            dirt, declared, scratch)

    findings: List[Dict] = []
    not_probed: List[Tuple[str, str]] = []
    for lineno, text in inert_exclusions(script):
        findings.append({
            "gate": f"(script line {lineno})", "kind": "INERT_EXCLUSION",
            "detail": ("an EXCLUDE directive is written here but is not the "
                       "line IMMEDIATELY above a `run` line, so it excludes "
                       "NOTHING — the script says one thing and the parser "
                       "reads another. Move it flush against its `run` line, "
                       "or delete it."),
            "checkout": text, "worktree": "-"})
    # A LOCKED scratch directory, not a bare `mkdtemp`. The lock is what a later
    # run reads to decide this one is dead; the `finally` below is the tidy
    # path, and the reaper is the one that holds under `SIGKILL`.
    res, _ = _scratch.reserve(_SCRATCH_PREFIX,
                              remover=_unregister_worktree,
                              root=tmp_root)
    wt = res.path / "wt"
    try:
        r = subprocess.run(
            ["git", "-C", str(repo_root), "worktree", "add", "-q",
             "--detach", str(wt), "HEAD"],
            capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            # NEVER a silent pass — "I could not look" is its own state.
            return _setup("WORKTREE_UNAVAILABLE", "WORKTREE_UNAVAILABLE",
                          (r.stderr or r.stdout or "").strip()[:300],
                          dirt, declared, scratch)

        plugin_rel = Path("vibe-ic-marketplace") / "plugins" / "vibe-ic"
        me = Path(__file__).name
        for label, wd_tok, cmd, excluded, templated in gates:
            # NEVER probe ITSELF. The gate list is unfiltered by design, so it
            # contains this program — and running it inside the worktree runs
            # it again, which creates another worktree, and so on.
            #
            # This shipped and CI caught it. Locally it was MASKED: the working
            # tree is permanently dirty, so the inner invocation returned
            # DIRTY_CHECKOUT immediately and the recursion never happened. CI
            # checks out clean, recursed, and hit the per-gate timeout — which
            # was ALSO unhandled, so the probe died with a traceback instead of
            # reporting. "It passed on my machine" was true and worthless.
            #
            # The skip is RECORDED, not silent. It used to be a bare `continue`
            # while the verdict line went on to say "all <declared> gate(s)" —
            # a denominator this program's whole subject is not over-claiming.
            if me in cmd:
                not_probed.append((label, "this probe itself — it would recurse"))
                continue
            if excluded is not None:
                not_probed.append((label, f"EXCLUDED by declaration: {excluded}"))
                continue
            # A GATE DECLARED INSIDE A LOOP CANNOT BE DRIVEN HERE, and saying
            # so is the only honest option available. This probe's evidence is
            # that ONE tree carries something the other does not; binding the
            # loop variable to some fixed path would hand BOTH invocations the
            # same input, they would agree by construction, and the agreement
            # would be counted as coverage — the NO_STIMULUS defect #539 exists
            # to refuse, reintroduced one gate at a time.
            #
            # It stays in `declared`. Before v1.9.78 the parser could not see
            # these lines at all, so the three loop gates were absent from the
            # denominator AND from this list: the verdict named neither, and a
            # reader had no way to tell they existed.
            if templated is not None:
                not_probed.append((
                    label,
                    f"declared inside a shell loop — {templated}. Driving it "
                    f"twice would need the loop's binding, and a fixed "
                    f"substitute would make both trees identical, so the "
                    f"agreement would prove nothing"))
                continue
            ca = repo_root if wd_tok == "$ROOT" else repo_root / plugin_rel
            cb = wt if wd_tok == "$ROOT" else wt / plugin_rel
            # THE KILLER CLEANS UP (vibe-ic#1029, same family).
            #
            # ARM A runs in THE WORKING CHECKOUT, and `subprocess.run(timeout=)`
            # on expiry calls `Popen.kill()` -- SIGKILL. A killed process runs
            # no `finally` and no signal handler, so a gate that was inside its
            # own mutation window when the bound landed leaves the mutation in
            # the tree, and this loop then filed `GATE_UNRUNNABLE` and carried
            # on. Everything declared after it measured the mutation.
            #
            # MEASURED 2026-08-12, reproducing a real landing run on .120
            # (candidate stack h1c, `/home/reyerchu/_pg_h1c`) byte for byte:
            #
            #   parent caught TimeoutExpired after 75s
            #   porcelain AFTER: 1
            #    M programs/phase3_one_shot_runner.py
            #   -    return _detect_pdk(project, override="sky130A")
            #   +    return _detect_pdk(project, override="nangate45")
            #
            # `an argued direction is pinned` needs 543 s here against the
            # 600 s bound, and `phase3_one_shot_runner.py:8414` is the LAST
            # site it processes in sort order -- so it is the site holding a
            # mutation when the bound lands, which is exactly the file .120 was
            # left carrying.
            #
            # WHY THE FIX IS HERE AND NOT IN THE KILLED GATE. Its `finally`
            # already works: an exception raised mid-pin restores the file
            # byte-identically (measured). SIGTERM is handled too, once #1090
            # lands. SIGKILL cannot be caught by anybody -- so the only process
            # still alive to undo the write is THIS ONE, the one that sent it.
            before_dirty = _checkout_dirty_paths(repo_root)
            drive_exc: Optional[BaseException] = None
            try:
                a = subprocess.run(_expand(cmd, repo_root), cwd=str(ca),
                                   capture_output=True, text=True,
                                   timeout=timeout)
                b = subprocess.run(_expand(cmd, wt), cwd=str(cb),
                                   capture_output=True, text=True,
                                   timeout=timeout)
            except (OSError, subprocess.SubprocessError) as exc:
                drive_exc = exc
            # ALWAYS, not only on the exception path. A gate that writes into
            # the checkout while EXITING CLEANLY corrupts the comparison just as
            # thoroughly, and would otherwise be invisible here.
            repaired, refused = _repair_checkout(repo_root, before_dirty, label)
            if repaired or refused:
                findings.append({
                    "gate": label, "kind": "GATE_CORRUPTED_CHECKOUT",
                    "detail": (
                        "this gate left the WORKING CHECKOUT modified while "
                        "being driven"
                        + (f" (killed: {type(drive_exc).__name__})"
                           if drive_exc is not None
                           else " (it exited normally)")
                        + ". Every gate declared after it would have measured "
                          "that. "
                        + (f"Restored: {', '.join(repaired)}. "
                           if repaired else "")
                        + (f"REFUSED to touch (dirty before this run): "
                           f"{', '.join(refused)}. " if refused else "")),
                    "checkout": "modified", "worktree": "-"})
            if drive_exc is not None:
                # A gate that cannot be driven is NOT host-dependence, and it
                # is NOT a clean result either. It gets its own state rather
                # than a traceback that kills the whole probe.
                findings.append({
                    "gate": label, "kind": "GATE_UNRUNNABLE",
                    "detail": f"could not be driven twice: "
                              f"{type(drive_exc).__name__}: "
                              f"{str(drive_exc)[:160]}",
                    "checkout": "-", "worktree": "-"})
                continue
            # NORMALISE THE TREE PATH OUT before comparing. A gate that echoes
            # its own root — `marketplace_version_sync_check` prints the
            # manifest paths it read — differs between the two trees for a
            # reason that has nothing to do with what it EXAMINED.
            #
            # Caught by this probe's first genuine run: CI reported it
            # HOST_DEPENDENT while both sides said "PASS: 2 manifest(s), 2
            # plugin entr(ies) — all versions in sync". A comparison that
            # reports a difference which is not one is the same defect class
            # this probe exists to find, in the probe itself.
            #
            # A REAL difference — a count, a verdict word, a finding — still
            # differs after this, so the check is not weakened.
            va = _norm(_verdict_line(a.stdout + a.stderr), repo_root, wt)
            vb = _norm(_verdict_line(b.stdout + b.stderr), repo_root, wt)
            if va != vb or a.returncode != b.returncode:
                # A DIFFERENCE MUST REPRODUCE TO BE EVIDENCE (vibe-ic#1029).
                #
                # Measured on `3febf537`, this probe reported:
                #
                #   [HOST_DEPENDENT_VERDICT] 63x8 census freshness
                #     checkout: rc=1 AssertionError: the outcome run for
                #               test_matrix_d7_outputs_list_complete.py did not
                #               finish within 60s
                #     worktree: rc=0 [PASS] 63x8 census fresh: 504 cells ...
                #
                # The arms did not disagree about the SUBJECT. One ran out of
                # wall clock: `_OUTCOME_TIMEOUT_S = 60` bounds an inner pytest,
                # and this probe drives 66 gates twice, so the checkout arm is
                # the one under load. The same tool reported 6/6 clean on one
                # run and 5/6 on the next — a verdict that depends on the
                # machine's load is the very thing this probe exists to refuse,
                # occurring in the probe itself. That is the same shape as the
                # `_norm` fix above: a reported difference which is not one.
                #
                # `TimeoutExpired` raised HERE is already GATE_UNRUNNABLE. The
                # gap is a gate that enforces its OWN deadline and therefore
                # RETURNS rc=1 with a message — indistinguishable, to a single
                # comparison, from a real verdict.
                #
                # The discriminator is NOT the text of the message; deciding a
                # tier by grepping prose is the defect `_vacuous_exit` was
                # written to end. It is REPRODUCIBILITY. A gate reading local
                # state disagrees on every round, because the leftovers are
                # still there. A gate that ran out of clock does not.
                #
                # Paid ONLY on the disagreeing minority: the agreeing majority
                # is still driven exactly twice, which matters at ~44 min.
                try:
                    a2 = subprocess.run(_expand(cmd, repo_root), cwd=str(ca),
                                        capture_output=True, text=True,
                                        timeout=timeout)
                    b2 = subprocess.run(_expand(cmd, wt), cwd=str(cb),
                                        capture_output=True, text=True,
                                        timeout=timeout)
                except (OSError, subprocess.SubprocessError) as exc:
                    findings.append({
                        "gate": label, "kind": "GATE_UNRUNNABLE",
                        "detail": f"disagreed once, then could not be re-driven "
                                  f"to confirm it: {type(exc).__name__}: "
                                  f"{str(exc)[:160]}",
                        "checkout": f"rc={a.returncode} {va[:200]}",
                        "worktree": f"rc={b.returncode} {vb[:200]}"})
                    continue
                va2 = _norm(_verdict_line(a2.stdout + a2.stderr), repo_root, wt)
                vb2 = _norm(_verdict_line(b2.stdout + b2.stderr), repo_root, wt)
                round2_differs = (va2 != vb2 or a2.returncode != b2.returncode)
                same_shape = (
                    round2_differs
                    and (va, vb, a.returncode, b.returncode)
                    == (va2, vb2, a2.returncode, b2.returncode))
                if same_shape:
                    findings.append({
                        "gate": label, "kind": "HOST_DEPENDENT_VERDICT",
                        "detail": ("the same commit gives different answers in "
                                   "a working checkout and a fresh worktree, "
                                   "and does so on BOTH rounds, so the gate is "
                                   "reading something that is not in the commit "
                                   "— almost always untracked run leftovers"),
                        "checkout": f"rc={a.returncode} {va[:200]}",
                        "worktree": f"rc={b.returncode} {vb[:200]}",
                    })
                else:
                    # NOT folded into a pass. A gate that cannot reproduce its
                    # own verdict is not usable evidence — it is a DIFFERENT
                    # defect from host dependence, and naming it as host
                    # dependence sends the reader to the wrong repair.
                    findings.append({
                        "gate": label, "kind": "NON_DETERMINISTIC_VERDICT",
                        "detail": ("the two arms disagreed once and did not "
                                   "disagree the same way when reran, so the "
                                   "difference is not a property of the commit "
                                   "— typically an inner wall-clock bound met "
                                   "under this probe's own load. NOT host "
                                   "dependence, and NOT a pass: a gate whose "
                                   "verdict is not reproducible cannot be used "
                                   "as evidence by anything downstream"),
                        "checkout": f"rc={a.returncode} {va[:200]}"
                                    f"  || second run rc={a2.returncode} "
                                    f"{va2[:120]}",
                        "worktree": f"rc={b.returncode} {vb[:200]}"
                                    f"  || second run rc={b2.returncode} "
                                    f"{vb2[:120]}",
                    })
    finally:
        _release_scratch(res, repo_root)

    probed = declared - len(not_probed)
    if findings:
        return Audit("FAIL", findings, dirt, declared, probed, not_probed,
                     scratch)
    # NO STIMULUS IS NOT A PASS (#539). Every gate agreeing across two trees
    # that carry the same bytes is arithmetic, not evidence: the leftovers this
    # probe detects a gate READING were absent from both sides, so the run had
    # nothing it could have detected. Reported at the rc-2 vacuous tier — the
    # `_vacuous_exit` convention — so a consumer sees NOT CHECKED rather than a
    # pass, and so the one configuration this probe is blind in announces
    # itself instead of printing the same green sentence as a real run.
    #
    # rc 2 and not rc 1: nothing is WRONG with the tree or the gates, and a
    # permanently red gate is a gate that gets skipped. `--ignored` unreported
    # keeps the PASS: we cannot then prove the stimulus was zero, and inventing
    # a NOT_CHECKED out of an unknown is the mirror of inventing a pass.
    if dirt is not None and dirt.ignored_reported and dirt.stimulus == 0:
        return Audit("NO_STIMULUS", [], dirt, declared, probed, not_probed,
                     scratch)
    return Audit("PASS", findings, dirt, declared, probed, not_probed, scratch)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("repo_root", nargs="?", default=None)
    ap.add_argument("--json", dest="json_out", default=None)
    a = ap.parse_args(argv)

    root = Path(a.repo_root).resolve() if a.repo_root else _PLUGIN.parents[2]
    res = audit(root)

    if a.json_out:
        Path(a.json_out).write_text(json.dumps(
            {"verdict": res.verdict,
             # DECLARED is the denominator and PROBED is what this run actually
             # drove twice. They differ by the self-skip and by every declared
             # exclusion, each of which is named — a consumer must be able to
             # tell a shrinking numerator from a shrinking population.
             "gates_declared": res.declared,
             "gates_probed": res.probed,
             "not_probed": [{"gate": g, "why": w} for g, w in res.not_probed],
             # What the entry sweep removed, and what it deliberately did not.
             "scratch_sweep": res.scratch,
             "stimulus": (None if res.dirt is None else {
                 "untracked": len(res.dirt.untracked),
                 "ignored": len(res.dirt.ignored),
                 "ignored_reported": res.dirt.ignored_reported}),
             "findings": res.findings}, indent=2) + "\n")

    # Whatever the outcome, SAY WHAT WAS NOT PROBED. A gate that left the
    # numerator without being named is how a set silently shrinks.
    for label, why in res.not_probed:
        print(f"  [NOT PROBED] {label} — {why}", file=sys.stderr)

    # And say what the entry sweep did to other people's directories. A cleanup
    # that runs silently is one nobody can audit when it removes the wrong
    # thing, and this one deletes git worktrees.
    if res.scratch:
        for p in res.scratch.get("reaped", []):
            print(f"  [REAPED] {p} — its owner was gone (the flock it held was "
                  f"released), so an interrupted run's scratch worktree was "
                  f"removed and unregistered", file=sys.stderr)
        for p in res.scratch.get("live_peers", []):
            print(f"  [LEFT ALONE] {p} — a live peer holds its lock",
                  file=sys.stderr)
        for k in res.scratch.get("kept", []):
            print(f"  [LEFT ALONE] {k['path']} — {k['why']}", file=sys.stderr)

    if res.verdict == "NOTHING_SCANNED":
        print("NOTHING_SCANNED: no corpus-scanning gate parsed from "
              f"{root}/tools/ci/repo_hygiene_gates.sh", file=sys.stderr)
        return 2
    if res.verdict in ("DIRTY_CHECKOUT", "STATUS_UNAVAILABLE",
                       "WORKTREE_UNAVAILABLE"):
        head = {
            "DIRTY_CHECKOUT":
                "DIRTY_CHECKOUT: host-independence was NOT checked — tracked "
                "files are modified, so the worktree at HEAD does not carry "
                "them and every one would read as a difference about the edit "
                "rather than about the gate. This is not a pass.",
            "STATUS_UNAVAILABLE":
                "STATUS_UNAVAILABLE: the checkout could not be characterised, "
                "so host-independence was NOT checked. This is not a pass.",
            "WORKTREE_UNAVAILABLE":
                "WORKTREE_UNAVAILABLE: could not create a scratch git "
                "worktree, so host-independence was NOT checked. This is not "
                "a pass.",
        }[res.verdict]
        print(head, file=sys.stderr)
        for f in res.findings:
            print(f"      {f['detail']}", file=sys.stderr)
        return 2

    for f in res.findings:
        print(f"  [{f['kind']}] {f['gate']}", file=sys.stderr)
        print(f"      {f['detail']}", file=sys.stderr)
        print(f"      checkout: {f['checkout']}", file=sys.stderr)
        print(f"      worktree: {f['worktree']}", file=sys.stderr)

    stim = res.dirt.describe() if res.dirt is not None else "unknown stimulus"
    if res.findings:
        # Split by KIND rather than totalling them. Reporting a gate that met
        # an inner deadline as "HOST-DEPENDENT" sends the reader to look for
        # untracked leftovers that are not there — the wrong repair, which is
        # the cost this split exists to stop.
        by_kind: dict = {}
        for f in res.findings:
            by_kind[f["kind"]] = by_kind.get(f["kind"], 0) + 1
        parts = ", ".join(f"{n} {k}" for k, n in sorted(by_kind.items()))
        print(f"[FAIL] {len(res.findings)} of {res.probed} probed corpus "
              f"gate(s) ({res.declared} declared) did not give one reproducible "
              f"verdict across two trees: {parts}.", file=sys.stderr)
        return 1
    if res.verdict == "NO_STIMULUS":
        # The sentence a two-pristine-tree run has always deserved and never
        # printed.
        print(f"NO_STIMULUS: host-independence was NOT checked — the checkout "
              f"carried no untracked and no ignored path, so it and the fresh "
              f"worktree held the same bytes and all {res.probed} probed "
              f"gate(s) agreed by construction. A comparison with nothing on "
              f"one side that is not on the other cannot detect a gate reading "
              f"local state. This is not a pass. Run it in the working tree "
              f"the leftovers accumulate in.", file=sys.stderr)
        return 2
    print(f"[PASS] all {res.probed} probed corpus-scanning gate(s) "
          f"({res.declared} declared) give the same verdict in a working "
          f"checkout and a fresh worktree; {stim}.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
