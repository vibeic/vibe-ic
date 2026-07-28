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

chip-AGNOSTIC: it compares process output, nothing else.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

_HERE = Path(__file__).resolve().parent
_PLUGIN = _HERE.parent

_RUN_RE = re.compile(
    # Accepts BOTH `run` and its `run_*` variants. A wrapper added for one
    # gate (`run_tolerating_uncheckable`) silently escaped this parser, so any
    # gate wired through it would not be covered — a coverage hole in the very
    # check that exists to close coverage holes.
    r'^\s*run(?:_\w+)?\s+"([^"]+)"\s+"?(\$ROOT|\$PLUGIN)"?\s+(.+)$', re.M)

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


def corpus_gates(script: Path) -> List[Gate]:
    """Every gate the CI script runs, with any EXCLUDE directive attached.

    The cwd token is LOAD-BEARING and was dropped in a first version: the
    `$PLUGIN`-scoped gates invoke a RELATIVE `programs/x.py`, so running
    them from the repo root made both trees fail to open the file and
    produced 9 identical-error "findings". A probe that reports a defect
    because it could not run the subject is worse than no probe."""
    try:
        text = script.read_text(errors="replace")
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
    for m in _RUN_RE.finditer(text):
        # THE LINE THE GATE IS ON, derived from the LABEL's offset and not from
        # `m.start()`. `_RUN_RE` opens with `^\s*` under `re.M`, and `\s`
        # matches a newline — so on a blank line followed by `run ...` the
        # match STARTS at the blank line, and a naive "text before the match"
        # would hand back the directive as if it were adjacent. Both that and
        # a `.rstrip("\n")` (which swallows any number of blank lines) were
        # written here and both were caught by the detached-directive test:
        # the whole fail-safe claim above is that drift STOPS the exclusion.
        line_start = text.rfind("\n", 0, m.start(1)) + 1
        head = text[:line_start]
        if head.endswith("\n"):
            head = head[:-1]
        d = _EXCLUDE_RE.match(head.rsplit("\n", 1)[-1])
        reason = None
        if d:
            reason = d.group(1).strip() or "declared at the gate, no reason given"
        out.append(Gate(m.group(1), m.group(2), m.group(3).strip(), reason))
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


def _setup(verdict: str, kind: str, detail: str, dirt: Optional[Dirt],
           declared: int) -> Audit:
    """A result decided before any gate ran. 0 probed, and it says so."""
    return Audit(verdict,
                 [{"gate": "(setup)", "kind": kind, "detail": detail}],
                 dirt, declared, 0, [])


def audit(repo_root: Path, timeout: int = 600) -> Audit:
    script = repo_root / "tools" / "ci" / "repo_hygiene_gates.sh"
    gates = corpus_gates(script)
    declared = len(gates)
    if not gates:
        # This program's own denominator: reporting clean over an empty gate
        # list is the defect it exists to catch, one level up.
        return Audit("NOTHING_SCANNED", [], None, 0, 0, [])

    dirt = checkout_dirt(repo_root, timeout)
    if dirt is None:
        return _setup("STATUS_UNAVAILABLE", "STATUS_UNAVAILABLE",
                      "`git status` did not answer, so the checkout could not "
                      "be characterised and no comparison was attempted",
                      None, declared)

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
            dirt, declared)

    findings: List[Dict] = []
    not_probed: List[Tuple[str, str]] = []
    td = tempfile.mkdtemp(prefix="hostindep-")
    wt = Path(td) / "wt"
    try:
        r = subprocess.run(
            ["git", "-C", str(repo_root), "worktree", "add", "-q",
             "--detach", str(wt), "HEAD"],
            capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            # NEVER a silent pass — "I could not look" is its own state.
            return _setup("WORKTREE_UNAVAILABLE", "WORKTREE_UNAVAILABLE",
                          (r.stderr or r.stdout or "").strip()[:300],
                          dirt, declared)

        plugin_rel = Path("vibe-ic-marketplace") / "plugins" / "vibe-ic"
        me = Path(__file__).name
        for label, wd_tok, cmd, excluded in gates:
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
            ca = repo_root if wd_tok == "$ROOT" else repo_root / plugin_rel
            cb = wt if wd_tok == "$ROOT" else wt / plugin_rel
            try:
                a = subprocess.run(_expand(cmd, repo_root), cwd=str(ca),
                                   capture_output=True, text=True,
                                   timeout=timeout)
                b = subprocess.run(_expand(cmd, wt), cwd=str(cb),
                                   capture_output=True, text=True,
                                   timeout=timeout)
            except (OSError, subprocess.SubprocessError) as exc:
                # A gate that cannot be driven is NOT host-dependence, and it
                # is NOT a clean result either. It gets its own state rather
                # than a traceback that kills the whole probe.
                findings.append({
                    "gate": label, "kind": "GATE_UNRUNNABLE",
                    "detail": f"could not be driven twice: "
                              f"{type(exc).__name__}: {str(exc)[:160]}",
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
                findings.append({
                    "gate": label, "kind": "HOST_DEPENDENT_VERDICT",
                    "detail": ("the same commit gives different answers in a "
                               "working checkout and a fresh worktree, so the "
                               "gate is reading something that is not in the "
                               "commit — almost always untracked run leftovers"),
                    "checkout": f"rc={a.returncode} {va[:200]}",
                    "worktree": f"rc={b.returncode} {vb[:200]}",
                })
    finally:
        subprocess.run(["git", "-C", str(repo_root), "worktree", "remove",
                        "--force", str(wt)], capture_output=True, text=True)
        shutil.rmtree(td, ignore_errors=True)

    probed = declared - len(not_probed)
    if findings:
        return Audit("FAIL", findings, dirt, declared, probed, not_probed)
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
        return Audit("NO_STIMULUS", [], dirt, declared, probed, not_probed)
    return Audit("PASS", findings, dirt, declared, probed, not_probed)


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
             "stimulus": (None if res.dirt is None else {
                 "untracked": len(res.dirt.untracked),
                 "ignored": len(res.dirt.ignored),
                 "ignored_reported": res.dirt.ignored_reported}),
             "findings": res.findings}, indent=2) + "\n")

    # Whatever the outcome, SAY WHAT WAS NOT PROBED. A gate that left the
    # numerator without being named is how a set silently shrinks.
    for label, why in res.not_probed:
        print(f"  [NOT PROBED] {label} — {why}", file=sys.stderr)

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
        print(f"[FAIL] {len(res.findings)} of {res.probed} probed corpus "
              f"gate(s) ({res.declared} declared) give a HOST-DEPENDENT "
              f"verdict.", file=sys.stderr)
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
