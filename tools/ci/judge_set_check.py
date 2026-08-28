#!/usr/bin/env python3
"""Did this candidate change the code that judges it?

THE WHOLE QUESTION, and the whole answer:

    the judge set is DERIVED from what the verifier actually executes.
    git says which of those files the candidate touched.
    if the answer is non-empty, a human authorises it or it does not land.

WHAT THIS REPLACES.  A 27KB hand-maintained register plus ~4200 lines of
machinery to validate it, in which:

  * the register is HAND-WRITTEN while the files it names change constantly —
    nineteen landings in one day moved twelve registered files and the register
    followed none of them;
  * "nothing needs to move" is an ILLEGAL STATE (`current` must differ from
    `next`), so a register that is up to date cannot be expressed;
  * catching up REQUIRES TWO LANDINGS by construction (PREPARE then ACTIVATE),
    so a register that falls behind cannot be fixed in one commit;
  * a missing row does not say "row missing" — it makes the verdict
    RC_CANNOT_MEASURE, which surfaces as `assert 2 == 1` in fourteen tests five
    files away.

None of that machinery answers a question git cannot. The register was a SECOND
COPY of a fact the repository already holds, and the copy went stale — which is
the same defect this repository keeps finding in its own gates and fixing by
DERIVING the fact instead of storing it.

WHAT IS *NOT* CHANGED BY THIS.  The real protection is that the verifier runs
the copy of itself from the BASE commit, which `gatekeeper-verify-merge.sh`
already does in shell, before any manifest is read.  That is what stops a
candidate grading its own homework, and it never depended on the register.

THE THREE EXIT CODES, AND WHY THEY ARE THREE
============================================
A derivation that quietly returns LESS is worse than the list it replaces:
every landing passes and nobody knows.  Five reviewers found three separate
paths to exactly that, all ending in rc 0.  So the codes are split by WHOSE
FACT they report, and "I could not look" never shares a code with "I looked and
it is clean":

    0  I LOOKED, and the candidate touches no judge (or every one is
       --authorised).
    1  I LOOKED, and the CANDIDATE is the problem: it edits a judge, or it
       REMOVES one from the set it is being judged by.  Authorisable per path.
    2  I COULD NOT LOOK.  An ENVIRONMENT fact — a ref that does not resolve, a
       base absent from a shallow clone, git failing, or a derivation that came
       back empty (which can only be a bug in this file).  NOT authorisable,
       because there is no answer to authorise.

Nothing the candidate does can produce rc 2; nothing the environment does can
produce rc 1.  That split is what lets a caller decide the dispatcher form (see
`tools/ci/_gate_dispatch.sh`: rc 2 becomes NOT_CHECKED under
`run_tolerating_uncheckable`, and NOT_CHECKED must never read as PASS).

TWO WAYS THE SET CAN SHRINK, AND WHY BOTH ARE REFUSED
=====================================================
Every member hangs off the entry points.  `git mv`-ing
`tools/gatekeeper-verify-merge.sh` — a legitimate-looking refactor — took the
set from 255 to 1 while the same commit edited `repo_hygiene_gates.sh` and
`run_plugin_self_audit.sh`, and the empty-set guard did not fire because 1 is
not 0.  So the guard is a RATCHET against the BASE COMMIT'S OWN derivation, not
a pinned number:

    lost = judge_set(base) - judge_set(head)

and `lost` non-empty is a refusal.  The asymmetry is deliberate and is the
repository's rule for ratchets: GROWING the judge set is always allowed — that
is somebody tightening the thing, and a ratchet that goes red when you tighten
it is a ratchet people route around.  Only LOSS is refused, and only loss is
authorisable.
"""
from __future__ import annotations
import argparse, ast, subprocess, sys
from pathlib import Path

RC_OK = 0
RC_REFUSED = 1        # I looked; the CANDIDATE is the problem
RC_CANNOT_LOOK = 2    # I could not look; an ENVIRONMENT fact

#: The definition of "the judge". Not a list of judges — a list of DOORS. Every
#: member of the set is found by walking out from these.
SEEDS = ("tools/gatekeeper-verify-merge.sh", "tools/gatekeeper-land.sh")
#: Where a python module name is looked up, in order.
SEARCH_DIRS = ("tools/ci", "tools",
               "vibe-ic-marketplace/plugins/vibe-ic/programs")
#: A token is only a candidate path if it lands under one of these.
PATH_PREFIXES = ("tools/", "vibe-ic-marketplace/")


class CannotLook(Exception):
    """The question could not be ASKED. Never an answer about the candidate."""


def _git(repo: Path, *args: str) -> str:
    """git, or an exception. Never a silent empty string.

    The version this replaces ran with `check=False` and returned `.stdout`,
    discarding both the exit code and stderr. An unresolvable --base then made
    `changed` empty, which printed `candidate touches none` and exited 0. A
    shallow clone hits that BY DEFAULT.
    """
    cp = subprocess.run(("git", "-C", str(repo)) + args,
                        capture_output=True, text=True, check=False)
    if cp.returncode != 0:
        detail = cp.stderr.strip().splitlines()
        raise CannotLook(
            f"`git {' '.join(args)}` exited {cp.returncode}"
            + (f": {detail[0]}" if detail else " and said nothing"))
    return cp.stdout


def _blob_exists(repo: Path, rev: str, rel: str) -> bool:
    """Is this path in that commit? Asked WITHOUT the walk.

    "the doors are missing" and "the walk returned nothing" are different
    diagnoses and must not be inferred from each other: if the seeds are read
    back out of the derived set, a derivation that silently returns nothing
    reports itself as the wrong repository.
    """
    return subprocess.run(("git", "-C", str(repo), "cat-file", "-e",
                           f"{rev}:{rel}"), capture_output=True,
                          check=False).returncode == 0


def _is_shallow(repo: Path) -> bool:
    try:
        return _git(repo, "rev-parse", "--is-shallow-repository").strip() == "true"
    except CannotLook:
        return False


def _resolve(repo: Path, flag: str, ref: str) -> str:
    """A ref, or a refusal that names which flag and why."""
    try:
        return _git(repo, "rev-parse", "--verify", "--quiet",
                    f"{ref}^{{commit}}").strip()
    except CannotLook as exc:
        hint = ""
        if _is_shallow(repo):
            hint = (" — this clone is SHALLOW, so the commit may exist upstream "
                    "and simply not be here; deepen it (`git fetch --unshallow`) "
                    "rather than believing the answer")
        raise CannotLook(
            f"{flag} {ref!r} does not resolve to a commit in {repo}{hint} "
            f"[{exc}]") from exc


class _WorkingTree:
    """Whatever is on disk. For a human inspecting a checkout (`--list`)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.what = f"the working tree at {self.root}"

    def is_file(self, rel: str) -> bool:
        return (self.root / rel).is_file()

    def read(self, rel: str) -> str | None:
        try:
            return (self.root / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None


class _CommittedTree:
    """A COMMIT, so the answer cannot depend on whose checkout asked.

    The verdict path uses this and only this. The question is about a candidate
    COMMIT; reading the working tree answered a different question and made the
    result depend on untracked and modified files.
    """

    def __init__(self, repo: Path, rev: str) -> None:
        self.repo, self.rev = Path(repo), rev
        self.what = f"commit {rev[:12]}"
        listing = _git(repo, "ls-tree", "-r", "-z", "--name-only", rev)
        self._files = {p for p in listing.split("\0") if p}

    def is_file(self, rel: str) -> bool:
        return rel in self._files

    def read(self, rel: str) -> str | None:
        cp = subprocess.run(("git", "-C", str(self.repo), "show",
                             f"{self.rev}:{rel}"), capture_output=True,
                            check=False)
        if cp.returncode != 0:
            return None
        return cp.stdout.decode("utf-8", errors="ignore")


def _shell_path_candidates(token: str) -> set[str]:
    """The repo-relative paths a shell token might name.

    The version this replaces matched by PREFIX after `lstrip("$")`, so it saw
    `tools/ci/x.sh` and `$tools/ci/x.sh` but NOT `"$ROOT/tools/ci/x.sh"` or
    `"${RUNTIME_ROOT}/tools/x.py"` — which is the DOMINANT spelling in this
    repository's own shell. Twenty-three files the judges demonstrably execute
    were outside the set, including `tools/ci/run_plugin_self_audit.sh`, the
    file a comment in it calls the home of six anti-fabrication gates.

    Both normalisations are returned and the caller takes the union, so this
    can only ADD members relative to the prefix-only match.
    """
    out = {token.lstrip("$")}
    segments = token.split("/")
    while segments and segments[0].startswith("$"):
        segments.pop(0)          # $ROOT/... and ${RUNTIME_ROOT}/... alike
    out.add("/".join(segments))
    return out


def _walk(tree) -> set[str]:
    """Every file the landing verifier executes, derived — never listed.

    Start from the entry points and follow what they RUN: the scripts they
    invoke and the python modules those import from this repo. A file is in the
    judge set because it is REACHABLE from the thing that judges, not because
    somebody remembered to write it down.

    Bounded and order-independent by construction: a reachability closure over
    a monotone predicate, with `seen` as the fixed point. A cycle and a
    4000-deep import chain both terminate with the complete answer.
    """
    seen: set[str] = set()
    queue = [s for s in SEEDS if tree.is_file(s)]
    while queue:
        rel = queue.pop()
        if rel in seen:
            continue
        seen.add(rel)
        text = tree.read(rel)
        if text is None:
            continue
        if rel.endswith(".py"):
            try:
                node_tree = ast.parse(text)
            except SyntaxError:
                continue
            for node in ast.walk(node_tree):
                names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                         else [node.module] if isinstance(node, ast.ImportFrom)
                         and node.level == 0 and node.module else [])
                for mod in names:
                    stem = mod.split(".")[0] + ".py"
                    for d in SEARCH_DIRS:
                        cand = f"{d}/{stem}"
                        if tree.is_file(cand) and cand not in seen:
                            queue.append(cand)
        else:
            # a shell script: anything it names that exists here, it may run
            for token in text.replace('"', " ").replace("'", " ").split():
                token = token.strip("(){};|&,")
                for cand in _shell_path_candidates(token):
                    if (cand.startswith(PATH_PREFIXES) and tree.is_file(cand)
                            and cand not in seen):
                        queue.append(cand)
    return seen


def judge_set(repo: Path) -> set[str]:
    """The judge set of a CHECKOUT. For `--list` and for humans.

    MEASURED 2026-08-28, and this is why the verdict path does not use it: the
    answer moves with the working tree. Fifty-six untracked files added one at a
    time took it 255 -> 259 and never removed a member; a DELETED or MODIFIED
    tracked file can remove one. `judge_set_at` reads a commit and has neither
    behaviour.
    """
    return _walk(_WorkingTree(repo))


def judge_set_at(repo: Path, rev: str) -> set[str]:
    """The judge set of a COMMIT. What the verdict is actually computed from."""
    return _walk(_CommittedTree(repo, rev))


def _describe_loss(lost: list[str]) -> list[str]:
    lines = [f"REFUSE  this candidate REMOVES {len(lost)} file(s) from the set "
             f"that judges it:"]
    for p in lost:
        lines.append(f"          {p}" + ("   <- AN ENTRY POINT" if p in SEEDS else ""))
    if any(p in SEEDS for p in lost):
        lines.append("        Every member of the set hangs off the entry points, so "
                     "moving one")
        lines.append("        collapses the set the candidate is being judged by. That "
                     "is the one")
        lines.append("        shrink an empty-set guard cannot see, because 1 is not 0.")
    lines.append("        GROWING the set is always allowed. Re-run with --authorised "
                 "<path> for")
    lines.append("        each loss a human has reviewed, or land the move separately.")
    return lines


def main(argv: list[str] | None = None) -> int:
    # allow_abbrev=False: with it on, renaming `--base` to `--baseline` leaves
    # every existing `--base` caller silently working, so the rename is
    # invisible to every guard here.
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--base", help="the commit this candidate is measured against")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--authorised", action="append", default=[],
                    help="a judge-set path this landing is allowed to change or remove")
    ap.add_argument("--list", action="store_true",
                    help="print the judge set of the working tree and exit")
    a = ap.parse_args(argv)
    repo = Path(a.repo).resolve()

    if a.list:
        for p in sorted(judge_set(repo)):
            print(p)
        return RC_OK
    if not a.base:
        print("REFUSE  --base is required: without it there is nothing to compare "
              "the candidate to,")
        print("        and 'no comparison' must not be reported as 'no change'.")
        return RC_CANNOT_LOOK

    try:
        base = _resolve(repo, "--base", a.base)
        head = _resolve(repo, "--head", a.head)
        head_judges = judge_set_at(repo, head)
        base_judges = judge_set_at(repo, base)
        changed = set(_git(repo, "diff", "--no-renames", "--name-only",
                           base, head).split())
    except CannotLook as exc:
        # The whole point of this branch. It is NOT "the candidate touches no
        # judge" — nobody looked.
        print(f"REFUSE  CANNOT LOOK — {exc}")
        print("        This is not a verdict about the candidate. No comparison was "
              "made, so")
        print("        nothing here says the judge set is untouched.")
        return RC_CANNOT_LOOK

    seeds_at_head = [s for s in SEEDS if _blob_exists(repo, head, s)]
    seeds_at_base = [s for s in SEEDS if _blob_exists(repo, base, s)]
    if not seeds_at_head and not seeds_at_base:
        print("REFUSE  CANNOT LOOK — neither entry point exists at either end:")
        for s in SEEDS:
            print(f"          {s}")
        print(f"        --repo {repo} is probably not this repository.")
        return RC_CANNOT_LOOK
    if not head_judges and seeds_at_head:
        # The entry points are RIGHT THERE and the walk still came back with
        # nothing, so the derivation is broken. Kept because an empty set would
        # authorise every change to every judge, and that must never be silent.
        print("REFUSE  the judge set derived EMPTY — the derivation is broken, "
              "and an empty set would authorise every change to every judge")
        print(f"        The entry points exist at {head[:12]}: "
              f"{', '.join(seeds_at_head)}")
        return RC_CANNOT_LOOK
    # An empty head set with the seeds GONE is not a broken derivation, it is a
    # candidate that deleted the doors. That is rc 1, and the shrink guard
    # below names every judge it took with them.

    authorised = set(a.authorised)
    lost = sorted(p for p in base_judges - head_judges if p not in authorised)
    if lost:
        for line in _describe_loss(lost):
            print(line)
        return RC_REFUSED

    touched = sorted((head_judges | base_judges) & changed)
    unauthorised = [p for p in touched if p not in authorised]
    if unauthorised:
        print(f"REFUSE  this candidate changes {len(unauthorised)} file(s) that "
              f"judge it, and they are not authorised:")
        for p in unauthorised:
            print(f"          {p}")
        print("        Re-run with --authorised <path> for each, or land them "
              "separately. The verifier still executes the BASE copy, so this "
              "is about REVIEW, not about which code ran.")
        return RC_REFUSED

    if touched:
        print(f"OK      judge set {len(head_judges)} file(s); candidate touches "
              f"{len(touched)}, all authorised")
    else:
        print(f"OK      judge set {len(head_judges)} file(s); candidate touches none")
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
