"""programs/tests/_real_data.py — the ONE definition of "this path IS published
run output", and of the refusal that names what is missing when none is.

WHY THIS MODULE EXISTS  (vibe-ic#1037)
======================================
A helper named ``_real_spef()`` — whose whole contract is "return REAL
extraction output, from a published run" — selected its file like this::

    for p in _REPO_SPEF_CANDIDATES:        # three named published-run paths
        if p.is_file() and p.stat().st_size > 0:
            return p
    root = PROG.parents[2]
    for hit in root.rglob("*.spef"):       # <-- unbounded fallback
        if hit.stat().st_size > 0:
            return hit
    return None

The three named candidates lived under run roots being withdrawn from
publication (vibe-ic#1015 / #1010). The moment they go, the ``rglob`` fallback
is the ONLY branch that can return anything — and the only ``*.spef`` files
under that walk root are **this suite's own fixtures**. Two tests named
``test_real_spef_*`` then assert properties of "production extraction output"
about a file the suite wrote for itself.

THE RED WAS LUCK, AND THE LUCK IS MEASURABLE
============================================
That went red only because the assertion is ``len(pair_cc) > 0`` and the
nearest fixture happens to be zero-coupling by construction. It is not a
hypothetical that a coupling-carrying fixture would have made it PASS: on
2026-08-12, in this tree, the walk yields SIX fixture SPEFs and the THIRD of
them — ``fixtures/si_mcf_zero_coupling/coupled/design.spef``, ``pair_cc == 1``
— satisfies EVERY assertion in BOTH ``test_real_spef_*`` tests. Measured, not
argued. The only thing between this suite and a green "real extracted
parasitics" claim over a file it authored itself was ``Path.rglob``'s
directory-walk order.

So the defect is not the red. The defect is the ELIGIBILITY: a real-data
selector with no rule forbidding it from selecting non-real data.

    A selector that takes whatever the walk yields first cannot tell the
    difference between the data it was written to examine and the data the
    test harness manufactured to stand in for it.

THE RULE, AND WHY IT IS AN ALLOW-LIST
=====================================
The obvious fix — "skip any path with ``tests`` or ``fixtures`` in its parts"
— is a DENY-LIST, and a deny-list loses to the next fixture directory somebody
names something else. ``programs/tests/fixtures/real_benchmark/`` already
exists in this tree; so does ``_analog_producer_fixture.py``. The set of names
a future fixture can have is open, and an open set cannot be enumerated.

What IS closed is the shape of PUBLISHED RUN OUTPUT. This repo publishes run
artefacts into exactly one tree, under exactly one layout, and puts them in the
git index when it does. So eligibility is stated positively:

  (1) the path is inside the source monorepo;
  (2) its repo-relative path begins with ``benchmark-data/`` — the one tree
      this repo publishes run output into;
  (3) no path component is dot-prefixed — ``phase3/.phase3_held/`` and friends
      are backup/held trees, deliberately excluded from publication (the same
      exclusion ``_path_layout`` documents for the clock-plan sweep);
  (4) some path component is a flow PHASE directory (``phase1``/``phase2``/
      ``phase3``/``analog``) — the artefact is downstream of a flow phase, i.e.
      it is run OUTPUT rather than loose data that merely lives nearby;
  (5) it is GIT-TRACKED at that path — publication in this repo IS the commit.
      A file a test wrote at runtime is untracked and therefore never eligible,
      no matter where it landed (vibe-ic#1029: the suite wrote into the tree the
      next gate reads);
  (6) it is non-empty.

(1)-(4) are the allow-list of shapes; (5) is what makes "published" a checked
fact rather than a directory-naming convention; (6) is the trivial floor.

There is ALSO a test-owned-name backstop (:data:`TEST_OWNED_NAMES`), and it is
deliberately SUBORDINATE: nothing in this tree can reach it without first
satisfying (2)+(4), so it can never be the load-bearing rule. It exists to give
a sharper REASON when somebody one day puts a fixture under ``benchmark-data/``,
not to be the thing that catches it.

THE CANDIDATE SET COMES FROM THE INDEX, NOT FROM A WALK
=======================================================
:func:`published_artifacts` enumerates ``git ls-files`` and filters, instead of
walking the filesystem and filtering. That is the same rule stated once more at
the level of mechanism: the walk was the bug, so this module does not own a
walk. A path that is not in the index cannot be *reached*, never mind returned.

A ZERO DENOMINATOR REFUSES  (``gate_zero_denominator_refuses_check``)
====================================================================
When nothing qualifies, :func:`select` returns no path and a reason that
separates the two absences a reader must not confuse:

  * "REAL-DATA ANCHOR LOST" — eligible artefacts of this kind USED to be here
    and something on disk still resembles them (ineligible candidates exist).
  * "no artefact of this kind is published in this checkout" — a genuinely
    sparse tree, in which nothing has been lost.

and it NAMES the ineligible paths it refused, with the rule each one failed, so
"the selector refused a fixture" is visible rather than inferred. It never
falls back. If the honest answer is that no real artefact exists, that is the
answer; the corpus is shrinking under owner order (#1015/#1010) and "there is
no real SPEF any more" may become the permanent, correct outcome.

SELECT ON THE REQUIREMENT, NOT ON WALK ORDER
============================================
:func:`select` takes the PROPERTY THE CALLER ASSERTS and applies it during
selection. The old code returned the first non-empty file and let the caller's
assertion discover whether it was suitable — which converts a PREMISE error
into a RESULT error, and a result error is only visible when the substituted
data happens to disagree. Stating the requirement at selection makes a
substituted premise fail loudly, as a premise, every time.

PROVENANCE IS PRINTED, NOT TRUSTED
==================================
Every selection and every refusal is appended to a run-scoped :data:`LEDGER`,
which ``conftest.pytest_terminal_summary`` prints as a "real-data provenance"
section on EVERY run, pass or fail. The next reader sees which file each
real-data test actually examined instead of taking the test's name for it.

REUSE
=====
Any other real-data selector adopts this by calling :func:`select` (or
:func:`require`) with its own suffix and requirement. vibe-ic#1037 leaves the
repo-wide sweep for sibling selectors of this shape to its own change; this
module is the rule that sweep can adopt.

chip-AGNOSTIC: path shape and git index only. No design, PDK, vendor, SKU or
process token appears here, and none can — nothing in this file reads a file's
CONTENT except through the caller's own requirement callback.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import pytest

from _hostpaths import REPO_ROOT

__all__ = [
    "PUBLICATION_ROOT", "PHASE_DIRS", "TEST_OWNED_NAMES",
    "why_not_published", "is_published", "published_artifacts",
    "provenance", "Selection", "select", "require",
    "LEDGER", "ledger_lines", "reset_ledger",
]

#: The ONE tree this repo publishes run output into. Rule (2).
PUBLICATION_ROOT = "benchmark-data"

#: Flow phase directories. An artefact is run OUTPUT only if it sits downstream
#: of one of these. Rule (4). These are the flow's own phase names — the same
#: vocabulary `flow/phase1_phase2_phase3.yaml` uses — not chip or PDK tokens.
PHASE_DIRS = ("phase1", "phase2", "phase3", "analog")

#: Backstop only — see the module docstring. Subordinate to rules (2)+(4);
#: present to give a sharper reason, never to be the rule that catches a fixture.
TEST_OWNED_NAMES = frozenset({
    "test", "tests", "fixture", "fixtures", "testdata", "test_data",
    "golden", "goldens", "snapshot", "snapshots", "__pycache__",
})


# ---------------------------------------------------------------------------
# The git index — the candidate set, and rule (5)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _tracked() -> Optional[frozenset]:
    """Every path in the git index, repo-root-relative posix, or ``None``.

    ``None`` means the tracked set is UNKNOWABLE here (no repo root, no git, a
    tarball export). Callers must then refuse: an unverifiable publication
    claim is not a verified one. It is cached for the process because the index
    does not change under a test run, and re-shelling per candidate would make
    a selector over a few thousand tracked files quadratic in subprocesses.
    """
    if REPO_ROOT is None:
        return None
    try:
        r = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
            # 55s, not 120s. `ci_harness_timeout_ceiling_check` refuses any inner
            # bound above 60s, and the reason is not tidiness: the pytest harness
            # kills at 180s, so an inner bound that can outlive it takes down the
            # SESSION instead of the test — you lose every other result in the run
            # and learn nothing about the one that hung.
            # 120 was never a measurement. Measured here on 21,779 tracked files,
            # three consecutive runs: 0.00s each. 55s is still ~4 orders of
            # magnitude of headroom, and it matches the `_T = 55` convention the
            # rest of this suite already uses.
            capture_output=True, text=True, timeout=55,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return frozenset(p for p in r.stdout.split("\0") if p)


def _rel(path: Path) -> Optional[str]:
    """Repo-root-relative posix path, or ``None`` if *path* is outside it."""
    if REPO_ROOT is None:
        return None
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------
def why_not_published(path: Path) -> Optional[str]:
    """``None`` when *path* IS published run output; else WHY it is not.

    The reason is a fragment that reads correctly after the path, e.g.
    ``"<p>: not under benchmark-data/ ..."``, so a refusal can quote it
    verbatim.
    """
    path = Path(path)
    if REPO_ROOT is None:
        return ("the source monorepo is not present (no 'vibe-ic-marketplace' "
                "ancestor — running from the installed plugin cache?), so no "
                "path here can be confirmed as published run output")
    rel = _rel(path)
    if rel is None:
        return "outside the source monorepo, so it is not this repo's published output"
    parts = Path(rel).parts
    if parts[0] != PUBLICATION_ROOT:
        return (f"not under {PUBLICATION_ROOT}/ (the one tree this repo "
                f"publishes run output into); it is under {parts[0]}/")
    dotted = [p for p in parts if p.startswith(".")]
    if dotted:
        return (f"under the dot-prefixed component {dotted[0]!r} — held/backup "
                f"trees are excluded from publication")
    if not any(p in PHASE_DIRS for p in parts):
        return (f"no flow-phase component ({'/'.join(PHASE_DIRS)}) in its path, "
                f"so it is not downstream of a flow phase and is not run OUTPUT")
    owned = [p for p in parts if p.lower() in TEST_OWNED_NAMES]
    if owned:
        return (f"under the test-owned component {owned[0]!r} — a test-owned "
                f"path cannot carry a real-data claim about itself")
    tracked = _tracked()
    if tracked is None:
        return ("the git index is unreadable here, so 'published' cannot be "
                "checked; an unverifiable publication claim is not a verified one")
    if rel not in tracked:
        return ("not git-tracked at that path — publication in this repo IS the "
                "commit, so an untracked file (a runtime write, a local scratch) "
                "is never published output")
    if not path.exists():
        # The withdrawal signature (#1015/#1010/#1028), and worth its own
        # sentence: "the index still lists it" and "it is not there" is a
        # different situation from a path that was never published.
        return ("git-tracked but ABSENT from the working tree — withdrawn from "
                "publication, or a sparse/partial checkout")
    if not path.is_file():
        return "not a regular file"
    if path.stat().st_size == 0:
        return "is an empty file"
    return None


def is_published(path: Path) -> bool:
    """``True`` iff :func:`why_not_published` finds no reason to refuse *path*."""
    return why_not_published(path) is None


def provenance(path: Path) -> str:
    """Repo-relative posix path for disclosure; absolute path if outside."""
    rel = _rel(Path(path))
    return rel if rel is not None else str(Path(path))


def published_artifacts(suffix: str) -> List[Path]:
    """Every published run artefact whose name ends with *suffix*, sorted.

    Enumerated from the GIT INDEX, not from a filesystem walk — see the module
    docstring. Deterministic order, so which artefact a selector lands on never
    depends on ``scandir``.
    """
    tracked = _tracked()
    if tracked is None or REPO_ROOT is None:
        return []
    out = []
    for rel in tracked:
        if not rel.endswith(suffix) or not rel.startswith(PUBLICATION_ROOT + "/"):
            continue
        p = REPO_ROOT / rel
        if why_not_published(p) is None:
            out.append(p)
    return sorted(out)


def _index_candidates(suffix: str) -> List[Path]:
    """Every tracked path ending in *suffix*, eligible or not — the population
    a refusal reports against, so "eligible 0 of N" has a real N."""
    tracked = _tracked()
    if tracked is None or REPO_ROOT is None:
        return []
    return sorted(REPO_ROOT / rel for rel in tracked if rel.endswith(suffix))


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Selection:
    """The outcome of :func:`select`: a path, or a reason there is none."""
    path: Optional[Path]
    reason: str
    considered: int = 0
    eligible: int = 0
    refused: Tuple[Tuple[str, str], ...] = field(default=())

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return self.path is not None


def _refusal_text(suffix: str, requirement_name: str, candidates: Sequence[Path],
                  eligible: Sequence[Path], refused: Sequence[Tuple[str, str]],
                  unmet: Sequence[str]) -> str:
    head: str
    if eligible:
        head = (f"REAL-DATA REQUIREMENT UNMET: {len(eligible)} published "
                f"'{suffix}' artefact(s) are eligible, and none satisfies the "
                f"property this test asserts ({requirement_name}).")
    elif refused:
        head = (f"REAL-DATA ANCHOR LOST, not a checkout without the corpus: "
                f"0 of {len(candidates)} tracked '{suffix}' path(s) are "
                f"published run output. Every one was refused by the "
                f"publication rule below.")
    else:
        head = (f"no '{suffix}' artefact is published in this checkout: the git "
                f"index carries none at all, eligible or otherwise.")
    lines = [head]
    if refused:
        # GROUPED BY REASON, not truncated by sort order. A flat "first 8 of 15"
        # list is sorted by path, so `benchmark-data/...` fills it and the
        # refused FIXTURES — the whole point of this refusal — fall off the end
        # under "and 7 more". Every distinct reason gets a line, so the reader
        # always sees THAT a fixture was refused, not just that something was.
        by_reason: Dict[str, List[str]] = {}
        for rel, why in refused:
            by_reason.setdefault(why, []).append(rel)
        lines.append(f"  refused ({len(refused)}), because a real-data test may "
                     f"not read a file this repo did not publish:")
        for why, rels in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
            lines.append(f"    * {len(rels)}x {why}")
            for rel in rels[:2]:
                lines.append(f"        - {rel}")
            if len(rels) > 2:
                lines.append(f"        - ... and {len(rels) - 2} more")
    if unmet:
        lines.append(f"  eligible but requirement-unmet ({len(unmet)}):")
        for rel in list(unmet)[:8]:
            lines.append(f"    - {rel}")
        if len(unmet) > 8:
            lines.append(f"    - ... and {len(unmet) - 8} more")
    lines.append("  This suite's own fixtures are deliberately NOT eligible "
                 "(vibe-ic#1037); nothing here falls back to one.")
    return "\n".join(lines)


def select(suffix: str, requirement: Callable[[Path], bool],
           requirement_name: str, *, label: str = "") -> Selection:
    """Pick the published run artefact that satisfies *requirement*, or refuse.

    *requirement* is the property THE CALLER ASSERTS, applied here so a
    substituted premise fails at selection rather than at assertion. A
    *requirement* that raises on an artefact counts as unmet for that artefact —
    an unparseable file is not a suitable one — never as a selection.

    Every outcome, pass or refusal, is appended to :data:`LEDGER`.
    """
    candidates = _index_candidates(suffix)
    eligible: List[Path] = []
    refused: List[Tuple[str, str]] = []
    for p in candidates:
        why = why_not_published(p)
        if why is None:
            eligible.append(p)
        else:
            refused.append((provenance(p), why))
    unmet: List[str] = []
    for p in eligible:
        try:
            ok = bool(requirement(p))
        except Exception as exc:  # an unreadable artefact is not a suitable one
            unmet.append(f"{provenance(p)} (requirement raised {type(exc).__name__})")
            continue
        if ok:
            sel = Selection(p, provenance(p), len(candidates), len(eligible),
                            tuple(refused))
            _record(label or suffix, f"USED {provenance(p)}  "
                    f"[eligible {len(eligible)}/{len(candidates)} tracked; "
                    f"requirement: {requirement_name}]")
            return sel
        unmet.append(provenance(p))
    reason = _refusal_text(suffix, requirement_name, candidates, eligible,
                           refused, unmet)
    _record(label or suffix, f"REFUSED  [eligible {len(eligible)}/"
            f"{len(candidates)} tracked; requirement: {requirement_name}]")
    return Selection(None, reason, len(candidates), len(eligible), tuple(refused))


def require(suffix: str, requirement: Callable[[Path], bool],
            requirement_name: str, *, label: str = "") -> Path:
    """:func:`select` that ``pytest.skip``s — with the full refusal — on none."""
    sel = select(suffix, requirement, requirement_name, label=label)
    if sel.path is None:
        pytest.skip(sel.reason)
    return sel.path


# ---------------------------------------------------------------------------
# Provenance ledger — printed by conftest on EVERY run
# ---------------------------------------------------------------------------
#: ``(label, outcome)`` for every selection attempted this run, in order.
LEDGER: List[Tuple[str, str]] = []


def _record(label: str, outcome: str) -> None:
    entry = (label, outcome)
    if entry not in LEDGER:
        LEDGER.append(entry)


def ledger_lines() -> List[str]:
    """One line per real-data selection this run, for the terminal summary."""
    return [f"{label}: {outcome}" for label, outcome in LEDGER]


def reset_ledger() -> None:
    """Clear the ledger — for tests of this module itself."""
    LEDGER.clear()
