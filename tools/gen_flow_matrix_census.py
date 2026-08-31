#!/usr/bin/env python3
"""Regenerate the 63x8 census table in ``flow_matrix/README.md`` from the live
suite, so the number a reader quotes cannot drift away from the tree again.

WHY THIS EXISTS
===============
The README published this table by hand::

    | **total** |  | **483** | **9** | **12** |

Measured 2026-08-09 on ``origin/main`` at ``dee025059``, with the README's own
reproduce command::

    Counter({'ENFORCED': 481, 'NA': 12, 'WAIVED': 11})

Four of the eight rows had drifted (d2 62/0/1 -> 60/2/1, d3 52/4/7 -> 53/3/7,
d5 62/0/1 -> 61/1/1). Nothing recomputed the table, so the campaign's headline
figure was a number someone typed once — while every cell underneath it was
being recomputed live, which is the whole point of the suite. The README even
carried the command that disproves it, two lines below the table.

Editing the table to say 481 would have bought a fortnight. It is generated
instead, and a freshness test (``programs/tests/test_flow_matrix_census_freshness.py``)
diffs the regenerated block against the committed one exactly as
``test_programs_index_freshness.py`` does for ``programs/INDEX.md`` — the house
pattern for a derived artefact in this repo.

WHAT IT COMPUTES, and how
-------------------------
Everything comes from ``test_flow_matrix_coverage``, which is the module that
already asks each dimension for the state of the cells it owns and cross-checks
the answer against pytest's own collection. This program adds no opinion of its
own; it renders.

* ENFORCED / WAIVED / NA per dimension -- ``state_census()``.
* The ENFORCED split -- ``substitution_census()``: for each ENFORCED cell, did
  its predicate run against the step's OWN mechanism, against a SUBSTITUTED
  stand-in, or is the dimension UNDECLARED? See
  ``flow_matrix/substitution.py``.

WHAT IT REFUSES
---------------
It refuses to publish a single "enforcing" total.

That total is what the finding was about: dimension 8 substitutes a stand-in
gate for 45 of its 61 ENFORCED cells, discloses it honestly in its own
docstring, and the disclosure died at the moment eight rows were added up. So
the ENFORCED column is printed SPLIT, always, and the headline states the
genuinely-enforcing figure as a FLOOR with the undeclared remainder named
beside it rather than absorbed into it.

It also refuses to stamp a timestamp into the block. A generated artefact that
changes on every run cannot be diffed for drift, so ``--check`` would be
meaningless the day it was needed.

WHAT THE MARKED BLOCK DOES NOT REACH — and what now does (vibe-ic#961)
---------------------------------------------------------------------
``splice()`` returns everything outside the two markers VERBATIM, so
``--check`` compares 36 lines of a 501-line README and everything else is equal
by construction, whatever it says. Measured on ``origin/main`` at ``8ad04f45``,
five live-derived figures OUTSIDE the block were stale:

    flow_matrix/README.md:132   blocks_on present 62 / non-empty 60   (live 63/61)
    flow_matrix/README.md:141   "all 126 required_outputs entries"    (live 133)
    flow_matrix/README.md:232   "150 blocking clauses"                (live 160)
    flow_matrix/flowref.py:61   "126 entries over 61 steps"           (live 133)
    test_matrix_d2_falsifiable.py:186  "150 blocking clauses"         (live 160)

The first went stale at ``332b9985`` (#929) — the exact commit this gate's own
landing message names as the reason the gate exists. The generated block was
repaired by that landing; the prose was not, and this gate could not see it.
Measured at ``332b9985^`` the yaml gives 62/60, so the README was right before
that edit: staleness, not a figure that was always wrong.

So the figures are now DERIVED WHERE THEY SIT, using the repo's existing seam
for exactly this problem (``programs/_derived_corpus_figure.py``). Each one is
written ``63<!--figure:blocks_on_declared-->``: the digits a reader sees, plus
an anchor naming the binding that produced them. This program re-derives every
anchor in its corpus and fails on drift, and ``--fix-figures`` rewrites them.
The anchor carries no value, so drift cannot be bought by editing the anchor.

AND IT DISCLOSES ITS OWN COVERAGE
---------------------------------
A gate that prints "census fresh" while guarding 7% of the page is the defect
it was built to remove. Every verdict line here now states how many figures
this program guards and how many stated population figures it does NOT, in the
same files, graded by the SAME vocabulary the repo's figure checker uses. The
unguarded remainder is a real number a reader can act on, not an absence.

IT NOW ANSWERS FOR THE TREE IT IS POINTED AT (vibe-ic#972)
----------------------------------------------------------
Every path below used to be resolved from ``__file__`` and from ``__file__``
alone, so this program answered for its OWN checkout whatever tree the caller
was asking about. MEASURED on ``origin/main`` at ``6525cf05``, ``--check``
launched with its cwd inside an EMPTY git repository — no plugin, no flow yaml,
no matrix package::

    [PASS] 63x8 census fresh: 504 cells over 8 dimensions; ENFORCED own=16 ...
    real  1m50.203s

504 cells over a directory containing one file. That is a check whose answer
does not depend on its input, which is the exact class this campaign exists to
remove, and the 110 seconds were the visible symptom of it:
``gate_discloses_denominator_check`` drives every CI gate against a scratch tree
under a 120s bound, so this line sat 8% under the timeout that would have
reported it as unrunnable.

The subject is now an ARGUMENT — the house wiring for every other gate in
``tools/ci/repo_hygiene_gates.sh`` (``… _check.py "$ROOT"``) — and it decides
three different answers, never one:

    the subject IS this script's own checkout   census it (unchanged)
    the subject carries no matrix suite         ZERO_DENOMINATOR, rc 2, at once
    the subject is some OTHER checkout          CROSS_TREE refusal, rc 2

The middle one is the house rule (``gate_zero_denominator_refuses_check``): a
zero denominator REFUSES, it does not pass. The third exists because the census
imports the dimension modules through ``sys.path`` off ``__file__``: this
program physically cannot census a different checkout, and saying so is the only
honest option left — answering with its own numbers is what it used to do.

Omitting the argument keeps the previous default (this script's own repository),
so a human, the freshness test and the host-independence probe are unaffected.

Run::

    python3 tools/gen_flow_matrix_census.py                 # rewrite the block
    python3 tools/gen_flow_matrix_census.py --check         # exit 1 on drift
    python3 tools/gen_flow_matrix_census.py <root> --check  # …for THAT tree
    python3 tools/gen_flow_matrix_census.py --check-figures # anchors only (cheap)
    python3 tools/gen_flow_matrix_census.py --fix-figures   # rewrite the anchors
    python3 tools/gen_flow_matrix_census.py --fix          # anchors AND census block
    python3 tools/gen_flow_matrix_census.py --fix \
        --written-json /tmp/w.json                         # …and DECLARE what it wrote

WHERE THIS IS DERIVED, AND WHY IT IS NOT AT PUSH TIME (vibe-ic#1382)
-------------------------------------------------------------------
This program is run for real by two callers, and they are deliberately not the
same caller:

    tools/ci/repo_hygiene_gates.sh   `--check`  — the landing gate. JUDGES.
    gatekeeper_prepare_landing.py    `--fix`    — the batch builder. RE-DERIVES.

The re-derivation runs at LAND, not at PUSH, and that was a choice between two
readings with measurements on both sides. Moving `--check` into `pre-push` would
show a PR author the staleness in seconds instead of an hour — but the 57
anchored figures live in THREE shared files (`flow_matrix/README.md`,
`flow_matrix/flowref.py`, `test_matrix_d2_falsifiable.py`) and every one of them
carries tree-wide COUNTERS. Two branches that each add a gate rewrite the same
lines with different totals, so per-PR re-derivation converts every gate-adding
PR into a conflict with every other one. That is not a prediction: it is what
`programs/INDEX.md` already does, measured at 26 of 30 conflicting open PRs
(vibe-ic#1431), and it is why `tools/resolve_generated_conflicts.sh` exists.

So the figures are re-derived at the only moment they are published, which costs
nothing per PR, and the gate still runs `--check` independently afterwards — the
builder makes the tree consistent, it does not silence the check.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
README = PLUGIN_ROOT / "programs" / "tests" / "flow_matrix" / "README.md"

#: The tree swept for anchored figures. Not the README's own directory: the
#: figures this substrate publishes are quoted by the dimension modules that
#: sit one level up, and a corpus that stopped at the package boundary would
#: have missed two of the five stale figures above.
FIGURES_ROOT = PLUGIN_ROOT / "programs" / "tests"

#: Where each of the three roots above sits RELATIVE to a repository root.
#: Derived from the constants rather than re-typed, so pointing this program at
#: another tree cannot drift from where it looks in its own (vibe-ic#972).
PLUGIN_REL = PLUGIN_ROOT.relative_to(REPO_ROOT)
README_REL = README.relative_to(REPO_ROOT)
FIGURES_REL = FIGURES_ROOT.relative_to(REPO_ROOT)

#: The matrix package itself — the thing whose cells this program counts. Its
#: absence is what makes a tree's census denominator ZERO.
MATRIX_REL = (README.parent).relative_to(REPO_ROOT)

#: Files in FIGURES_ROOT are in the corpus when they SPEAK ABOUT the substrate
#: these figures come from. Discovered by content, never listed: a typed list
#: is a promise that nobody will add a document.
CORPUS_TOKEN = "flowref"
CORPUS_SUFFIXES = (".py", ".md")

BEGIN = ("<!-- BEGIN GENERATED CENSUS — tools/gen_flow_matrix_census.py — "
         "DO NOT EDIT BY HAND -->")
END = "<!-- END GENERATED CENSUS -->"

sys.path.insert(0, str(PLUGIN_ROOT / "programs"))

from _derived_corpus_figure import (  # noqa: E402
    ANCHOR_STALE,
    ANCHOR_UNBOUND,
    AnchoredFigure,
    CorpusFigures,
    PIN_RE,
    anchored_figures,
    paragraphs,
    population_figures,
    render_anchored,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402


# ============================================================================
# WHICH TREE IS THIS RUN ABOUT? (vibe-ic#972)
# ============================================================================
#: The three answers, as a state rather than a boolean. `OWN` is the only one
#: that can produce a census; the other two are refusals with different reasons,
#: and collapsing them would report "this tree has no suite" for a tree that has
#: one this program simply cannot reach.
SUBJECT_OWN = "OWN"
SUBJECT_ZERO_DENOMINATOR = "ZERO_DENOMINATOR"
SUBJECT_CROSS_TREE = "CROSS_TREE"


#: What `_load()` and `census_rows()` ACTUALLY import, stated as the paths that
#: have to be on disk for a census to be possible at all. Not a guess at the
#: package's shape and not a naming convention: each entry below is one of the
#: three import statements in `_load`, written as a path relative to a
#: repository root. A tree missing any of them cannot produce a cell.
CENSUS_INPUTS_REL: Tuple[Path, ...] = (
    MATRIX_REL / "cells.py",            # DIMENSIONS / NAMES / QUESTIONS
    MATRIX_REL / "substitution.py",     # the ENFORCED split buckets
    FIGURES_REL / "test_flow_matrix_coverage.py",   # enforcement_census()
)


def census_denominator(subject: Path) -> Dict[str, int]:
    """How much matrix suite `subject` carries, DISCOVERED not assumed.

    Every figure here is a count a reader can act on, because the refusal below
    has to print one: "this tree has no census" and "this program did not look"
    are the pair #447 is about, and a bare verdict cannot separate them.

    The per-dimension modules are GLOBBED off the coverage meta-test's own
    neighbour naming rather than listed, so a ninth dimension is counted here by
    existing. That figure is REPORTED and is not what decides the refusal — the
    three imports above are, because those are what actually has to load.
    """
    matrix = subject / MATRIX_REL
    figures = subject / FIGURES_REL
    try:
        text = (subject / README_REL).read_text(encoding="utf-8",
                                                errors="replace")
    except OSError:
        text = ""
    return {
        "census_inputs_present": sum(
            1 for rel in CENSUS_INPUTS_REL if (subject / rel).is_file()),
        "census_inputs_required": len(CENSUS_INPUTS_REL),
        "matrix_package_files": (
            len([p for p in matrix.rglob("*.py")
                 if "__pycache__" not in p.parts]) if matrix.is_dir() else 0),
        "dimension_modules": (
            len([p for p in figures.glob("test_matrix_d*.py")
                 if "__pycache__" not in p.parts]) if figures.is_dir() else 0),
        "generated_census_markers": int(BEGIN in text) + int(END in text),
        "flow_yaml": int(
            (subject / PLUGIN_REL / "flow" / "phase1_phase2_phase3.yaml").is_file()),
    }


def classify_subject(subject: Path) -> Tuple[str, Dict[str, int]]:
    """`(state, denominator)` for the tree this run was pointed at.

    ORDER IS LOAD-BEARING. Emptiness is decided FIRST, so a scratch tree that
    happens not to be this checkout is reported as carrying no suite — the fact
    a caller can act on — rather than as an unreachable one.
    """
    counts = census_denominator(subject)
    if (counts["census_inputs_present"] < counts["census_inputs_required"]
            or counts["generated_census_markers"] < 2):
        return SUBJECT_ZERO_DENOMINATOR, counts
    if subject == REPO_ROOT:
        return SUBJECT_OWN, counts
    return SUBJECT_CROSS_TREE, counts


def subject_refusal_lines(state: str, subject: Path,
                          counts: Dict[str, int]) -> List[str]:
    """The refusal, carrying its own denominator on every line."""
    scope = (f"{counts['census_inputs_present']} of "
             f"{counts['census_inputs_required']} required census input(s), "
             f"{counts['dimension_modules']} dimension module(s), "
             f"{counts['matrix_package_files']} file(s) in the matrix package, "
             f"{counts['generated_census_markers']} of 2 generated-census "
             f"marker(s), {counts['flow_yaml']} flow yaml")
    if state == SUBJECT_ZERO_DENOMINATOR:
        return [
            f"ZERO_DENOMINATOR: {subject} carries {scope} — there is no 63x8 "
            f"suite here to census, so NOTHING was examined and this is NOT a "
            f"pass. A census rendered over zero cells matches an empty table "
            f"trivially; the house rule (gate_zero_denominator_refuses_check) "
            f"is that a zero denominator REFUSES.",
            f"NOTHING_SCANNED: 0 of 0 cells. Point this program at a checkout "
            f"that carries {MATRIX_REL}, or omit the argument to census "
            f"{REPO_ROOT} (this script's own).",
        ]
    return [
        f"CROSS_TREE: {subject} carries {scope}, but this program is "
        f"{Path(__file__).resolve()} and its census imports the dimension "
        f"modules through sys.path anchored on {REPO_ROOT}. It cannot census "
        f"a DIFFERENT checkout, and answering with its own numbers is the "
        f"defect this refusal exists to remove (vibe-ic#972) — the figures "
        f"would describe {REPO_ROOT} under a heading naming {subject}.",
        f"NOTHING_SCANNED: 0 of 0 cells here. Run that tree's own copy "
        f"instead: python3 {subject / 'tools' / Path(__file__).name} --check",
    ]


def _load():
    """Import the coverage meta-test with the plugin's own import posture.

    ``PYTEST_DISABLE_PLUGIN_AUTOLOAD`` matches the suite's documented invocation
    (a stray third-party pytest plugin otherwise breaks the subprocess
    collection ``state_census()`` depends on).
    """
    os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    for p in (PLUGIN_ROOT / "programs" / "tests", PLUGIN_ROOT / "programs"):
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)
    import test_flow_matrix_coverage as CV  # noqa: E402
    from flow_matrix import substitution as SUB  # noqa: E402
    from flow_matrix.cells import (  # noqa: E402
        DIMENSIONS, DIMENSION_NAMES, DIMENSION_QUESTIONS,
    )
    return CV, SUB, DIMENSIONS, DIMENSION_NAMES, DIMENSION_QUESTIONS


# ============================================================================
# DERIVED FIGURES OUTSIDE THE BLOCK (vibe-ic#961)
# ============================================================================
def _flowref():
    """``flow_matrix.flowref``, with the plugin's import posture.

    Deliberately NOT ``_load()``: that one drags in the coverage meta-test and
    the 504-cell outcome run behind it. Every figure below is a property of the
    flow yaml, which flowref parses in milliseconds, so ``--check-figures`` is
    cheap enough to be worth having as its own mode.
    """
    for p in (PLUGIN_ROOT / "programs" / "tests", PLUGIN_ROOT / "programs"):
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)
    from flow_matrix import flowref as F  # noqa: E402
    return F


@contextlib.contextmanager
def _flow_scope(root: Optional[Path]):
    """Point flowref at ``root``'s flow yaml for the duration, then restore.

    The seam calls every binding with a root. Ignoring it would make the
    bindings lie about what they measure — they would answer for THIS checkout
    whatever root they were handed, which is how a figure ends up describing a
    tree nobody asked about. When ``root`` carries no flow yaml the scope is a
    no-op and flowref answers for its own plugin, which is the only other
    honest option.
    """
    F = _flowref()
    yaml_path = Path(root) / "flow" / "phase1_phase2_phase3.yaml" if root else None
    if yaml_path is None or not yaml_path.is_file() or yaml_path == F.FLOW_YAML:
        yield F
        return
    original = F.FLOW_YAML
    F.set_flow_yaml(yaml_path)
    try:
        yield F
    finally:
        F.set_flow_yaml(original)


def _binding(fn: Callable[[object], int]) -> Callable[[Path], int]:
    """Wrap a flowref-shaped counter into the seam's ``callable(root) -> int``."""
    def _run(root: Path) -> int:
        with _flow_scope(root) as F:
            return int(fn(F))
    return _run


def _build_corpus_figures() -> CorpusFigures:
    """The binding table, with its per-kind half SCRAPED, not typed.

    ``OUTPUT_KINDS`` and ``GATE_CLAUSE_KINDS`` are flowref's own vocabularies.
    Iterating them means a kind added to the substrate arrives here with a
    binding already, instead of arriving as a figure someone forgot to add.
    """
    F = _flowref()

    def _out_kind(kind: str):
        return lambda f: sum(1 for s in f.step_ids()
                             for e in f.required_outputs(s)
                             if f.classify_output(e) == kind)

    def _clause_kind(kind: str):
        return lambda f: sum(1 for s in f.step_ids()
                             for c in f.gate_clauses(s) if c.kind == kind)

    table: Dict[str, Callable[[object], int]] = {
        "flow_steps": lambda f: len(f.step_ids()),
        "flow_steps_int": lambda f: sum(1 for s in f.step_ids()
                                        if isinstance(s, int)),
        "flow_steps_str": lambda f: sum(1 for s in f.step_ids()
                                        if isinstance(s, str)),
        "gate_declared": lambda f: sum(1 for s in f.step_ids() if f.has_gate(s)),
        "gated_steps": lambda f: sum(1 for s in f.step_ids() if f.gate_clauses(s)),
        "gate_clauses_total": lambda f: sum(len(f.gate_clauses(s))
                                            for s in f.step_ids()),
        "blocking_clauses": lambda f: sum(1 for s in f.step_ids()
                                          for c in f.gate_clauses(s)
                                          if c.is_blocking),
        "required_output_declared": lambda f: sum(
            1 for s in f.step_ids() if f.declares_required_outputs(s)),
        "required_output_steps": lambda f: sum(
            1 for s in f.step_ids() if f.required_outputs(s)),
        "required_output_entries": lambda f: sum(
            len(f.required_outputs(s)) for s in f.step_ids()),
        "blocks_on_declared": lambda f: sum(
            1 for s in f.step_ids() if f.declares_blocks_on(s)),
        "blocks_on_nonempty": lambda f: sum(
            1 for s in f.step_ids() if f.blocks_on(s)),
    }
    def _top_key(key: str):
        return lambda f: sum(1 for s in f.step_ids()
                             if isinstance(f.gate(s), dict) and key in f.gate(s))

    for key in ("all_of", "program_exit_zero", "files_exist"):
        table[f"gate_shape_{key}"] = _top_key(key)

    table["gate_commands_total"] = lambda f: sum(
        len(f.gate_commands(s)) for s in f.step_ids())
    table["gate_program_tokens_distinct"] = lambda f: len(
        {t for s in f.step_ids() for t in f.gate_program_tokens(s)})
    table["gate_programs_unresolved"] = lambda f: sum(
        len(f.unresolved_gate_programs(s)) for s in f.step_ids())
    table["steps_naming_a_program"] = lambda f: sum(
        1 for s in f.step_ids() if f.gate_programs(s))
    table["blocks_on_edges"] = lambda f: sum(
        len(f.blocks_on(s)) for s in f.step_ids())
    table["blocks_on_edges_int"] = lambda f: sum(
        1 for s in f.step_ids() for e in f.blocks_on(s) if isinstance(e, int))
    table["blocks_on_edges_str"] = lambda f: sum(
        1 for s in f.step_ids() for e in f.blocks_on(s) if isinstance(e, str))

    def _dimensions():
        from flow_matrix.cells import DIMENSIONS  # noqa: E402
        return DIMENSIONS

    table["matrix_dimensions"] = lambda f: len(_dimensions())
    table["ledger_cells"] = lambda f: len(f.step_ids()) * len(_dimensions())

    def _informational_gates(_f):
        # Dimension 9's subject: the gates whose FAIL `flow_compliance_check`
        # removes from `failing`. Read off the live frozenset, never counted by
        # hand — the README publishes this number as the size of a hole, and a
        # stale "4" would read as a disclosed known gap while describing a set
        # that had grown.
        import flow_compliance_check as _fcc
        return len(_fcc.INFORMATIONAL_GATES)

    table["informational_gates"] = _informational_gates

    for kind in F.OUTPUT_KINDS:
        table[f"required_outputs_{kind.lower()}"] = _out_kind(kind)
    for kind in F.GATE_CLAUSE_KINDS:
        table[f"gate_clauses_{kind}"] = _clause_kind(kind)

    bound = {name: _binding(fn) for name, fn in table.items()}
    bound.update(_artefact_channel_figures())
    return CorpusFigures(bound)


def _artefact_channel_figures() -> Dict[str, Callable[[Path], int]]:
    """The two digits the ARTEFACT_MUTATION channel publishes about ITSELF.

    Not a property of the flow yaml, which is why these are bound separately
    from the table above and take the root through the ledger rather than
    through `_flow_scope`.

    THEY ARE HERE BECAUSE THEY ROTTED. `matrix_mutation_ledger` already
    computes this pair live — `artefact_headline()`'s docstring says the line
    is "fit for the README" — and the README carried a HAND-TYPED copy of it
    instead. The ledger's own count then moved 4 -> 2 -> 1 across `46dbf43d`
    and `fc664a57`, each time in the change that closed the gap, exactly as
    `ARTEFACT_CANNOT_REDDEN_AS_MEASURED`'s comment requires; the README went on
    publishing 4 and a four-row table naming three gates as unable to fail that
    had learned to fail. Nothing compared the two, because the replay guards the
    LEDGER and nothing guarded its PUBLICATION.

    A stale "this gate cannot fail" is the worse direction of that error: it
    reads as a disclosed known gap, so it buys the credit for honesty while
    describing a gate that is now doing its job.
    """
    def _ledger(root: Path):
        """The ledger belonging to `root`, falling back to this plugin.

        Imported under its own module name — `spec_from_file_location` with a
        synthetic name breaks the module's `@dataclass` declarations, because
        dataclasses resolves annotations through `sys.modules[cls.__module__]`.
        """
        for p in (Path(root) / "programs", PLUGIN_ROOT / "programs"):
            if (p / "matrix_mutation_ledger.py").is_file():
                sp = str(p)
                if sp not in sys.path:
                    sys.path.insert(0, sp)
                break
        import matrix_mutation_ledger as L  # noqa: E402
        return L

    return {
        "artefact_mutations_registered":
            lambda root: len(_ledger(root).ARTEFACT_MUTATIONS),
        "artefact_cannot_redden":
            lambda root: len(_ledger(root).artefact_findings()),
    }


#: The seam's adoption contract: one module-global naming every figure this
#: program is willing to be held to.
CORPUS_FIGURES = _build_corpus_figures()


#: Bound for the one subprocess this module runs. NOT a round number by
#: accident: `ci_harness_timeout_ceiling_check` resolves the harness bound from
#: `tools/gatekeeper-land.sh` — `pytest -q --timeout=180
#: --timeout-method=thread` — and permits any ONE blocking call at most
#: 180 // 3 = 60 s. A larger inner bound can never fire: pytest reaches 180 s
#: first and takes the whole SESSION down, so every other file in the run loses
#: its verdict unnamed. `git ls-files` on this tree returns in well under a
#: second; this is a ceiling, not an expectation.
_GIT_LS_TIMEOUT_S = 60


def _has_git_dir(root: Path) -> bool:
    """Is there a ``.git`` at ``root`` or above it?

    Distinguishes "no repository here" from "repository here, pointer broken",
    which git reports with the same words. A `.git` entry may be a directory
    (normal clone) or a FILE (a worktree, which is what the host-independence
    probe creates), so both count.
    """
    for parent in [root, *root.parents]:
        if (parent / ".git").exists():
            return True
    return False


class CorpusUnreadable(RuntimeError):
    """The tracked file list could not be obtained.

    Raised rather than returning an empty list, because THOSE ARE NOT THE SAME
    ANSWER. An empty corpus makes every freshness assertion below vacuously
    true — nothing to re-derive, nothing stale, `[PASS]` — which is the exact
    shape of the defect this whole census exists to find. A gate that cannot
    see its subject must refuse, not agree.
    """


def tracked_corpus_files(root: Path) -> Optional[List[Path]]:
    """Files git TRACKS under ``root``, or ``None`` if ``root`` is not in a repo.

    THREE outcomes, and the difference between the last two is the whole point:

    * a list        -- ``root`` is version-controlled; this is what the commit
                       holds, and it is identical in a checkout and a worktree.
    * ``None``      -- ``root`` is not inside a git repository at all. That is
                       the normal case for a FIXTURE: the tests build a corpus
                       under ``tmp_path`` and are entitled to an answer. The
                       caller enumerates the filesystem instead, and no
                       host-independence claim is being made about a temp dir.
    * ``CorpusUnreadable`` -- git exists, ``root`` looks like a repo, and the
                       listing FAILED. Never silently degraded to either of the
                       above, because a command that could not look has not
                       told us the answer is none.

    THIS IS THE HOST-INDEPENDENCE BOUNDARY, and it is why this is not an
    `rglob`. `gate_host_independence_check` drives every gate twice — once in
    the working checkout, once in `git worktree add --detach HEAD` — and
    demands the same verdict. A working checkout that has been USED carries
    untracked leftovers; a fresh worktree never does. So a corpus enumerated
    from the filesystem is a property of the directory, and a verdict derived
    from it is a property of the machine.

    MEASURED on 3d13e2c59, one untracked `.md` copied into the corpus root and
    nothing else changed:

        pristine        [PASS] 57 anchored figure(s) across 29 corpus file(s)
        + 1 untracked   [PASS] 74 anchored figure(s) across 30 corpus file(s)

    Both say PASS; the probe compares the verdict LINE, so that is a
    `HOST_DEPENDENT_VERDICT` and the whole hygiene tier goes red with it.

    Tracked-set membership is not a narrower question than "every file here",
    it is the correct one: this gate answers whether the figures THE REPOSITORY
    PUBLISHES are fresh, and an uncommitted file publishes nothing. A document
    still joins by being written rather than by being listed — it now joins
    when it is committed, which is also when its figures become claims anyone
    can read.

    Residual, stated rather than left for someone to rediscover: this pins the
    file SET. A tracked file whose content differs from HEAD still reads
    differently in the two trees. That divergence needs a dirty checkout, which
    a landing gate does not have, and `landing_worktree_is_clean_check` already
    owns it.
    """
    try:
        r = _pr.run(["git", "-C", str(root), "ls-files", "-z"],
                           capture_output=True, text=False)
    except FileNotFoundError:
        # No git on this machine at all. Not a repo question, and not a
        # failure to look at a repo — enumerate the filesystem and say so.
        return None
    except (OSError, subprocess.SubprocessError) as exc:
        raise CorpusUnreadable(
            f"could not list tracked files under {root}: "
            f"{type(exc).__name__}: {exc}") from exc
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace").strip()
        # `not a git repository` is what git says for BOTH "there is no repo
        # here" (a tmp_path fixture — fine, answer from the filesystem) and
        # "there is a repo here and its pointer is broken" (NOT fine — that is
        # a failure to look, and falling back would quietly restore the
        # host-dependence this function exists to remove). The message cannot
        # tell them apart, so ask the filesystem which one it is.
        if "not a git repository" in err.lower() and not _has_git_dir(root):
            return None
        raise CorpusUnreadable(
            f"git ls-files exited {r.returncode} under {root}: {err[:200]}")
    names = r.stdout.decode("utf-8", "replace").split("\0")
    return [root / n for n in names if n]


def figure_corpus(root: Path) -> List[Path]:
    """Every TRACKED document under ``root`` that speaks about the flow substrate.

    Membership is a property of the file's own text, so a module that quotes
    these figures joins the corpus by being written, not by being remembered.
    ``__pycache__`` is excluded because a .pyc is not prose; untracked files
    are excluded because they are not in the commit whose figures this judges —
    see `tracked_corpus_files`.
    """
    tracked = tracked_corpus_files(root)
    candidates = root.rglob("*") if tracked is None else tracked
    out: List[Path] = []
    for path in sorted(candidates):
        if path.suffix not in CORPUS_SUFFIXES or not path.is_file():
            continue
        if "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if CORPUS_TOKEN in text:
            out.append(path)
    return out


def _block_of(text: str) -> str:
    start, stop = text.find(BEGIN), text.find(END)
    if 0 <= start < stop:
        return text[start:stop + len(END)]
    return ""


#: Any integer inside the generated block is generated, whatever noun follows
#: it. This is a DIFFERENT rule from `population_figures` on purpose and it is
#: stated rather than blurred: inside the markers the whole region is derived,
#: so a table cell of bare digits counts as guarded; outside them nothing does.
_BARE_INT = re.compile(r"(?<![\w.])\d{1,9}(?![\w.])")


def figure_report(root: Path, figures_root: Path,
                  values: Optional[Dict[str, int]] = None) -> Dict:
    """Anchors re-derived, and everything in the corpus that is NOT guarded.

    Two numbers, always both. The first is what this program keeps true; the
    second is what a reader must still check by hand. Publishing only the
    first is the shape of the finding this function exists to answer.
    """
    if values is None:
        values = CORPUS_FIGURES.evaluate_all(root)
    files: List[Dict] = []
    for path in figure_corpus(figures_root):
        text = path.read_text(encoding="utf-8", errors="replace")
        updated, sites = render_anchored(text, values)
        block = _block_of(text)
        outside = text.replace(block, "") if block else text
        # Graded PARAGRAPH BY PARAGRAPH, because a pin binds the paragraph it
        # sits in and nothing wider. Counting the file's figures in one pass
        # and its pins in another would let one dated sentence exempt a whole
        # document, which is how "disclosed" quietly becomes "not counted".
        unguarded: List[str] = []
        pinned = 0
        for _offset, para in paragraphs(outside):
            figs = population_figures(para)
            unguarded.extend(figs)
            if figs and PIN_RE.search(para):
                pinned += len(figs)
        files.append({
            "path": str(path),
            "rel": str(path.relative_to(figures_root)),
            "anchored": [f.__dict__ for f in sites],
            "stale": [f.__dict__ for f in sites if f.blocking],
            "block_figures": len(_BARE_INT.findall(block)),
            "unguarded": unguarded,
            "unguarded_pinned": pinned,
            "rewritten": updated if updated != text else None,
        })
    guarded_anchors = sum(len(f["anchored"]) for f in files)
    guarded_block = sum(f["block_figures"] for f in files)
    unguarded = sum(len(f["unguarded"]) for f in files)
    pinned = sum(f["unguarded_pinned"] for f in files)
    return {
        "figures_root": str(figures_root),
        "corpus_files": len(files),
        "files": files,
        "bindings": sorted(values),
        "values": values,
        "guarded_anchored": guarded_anchors,
        "guarded_in_block": guarded_block,
        "guarded_total": guarded_anchors + guarded_block,
        "unguarded_total": unguarded,
        "unguarded_pinned": pinned,
        "unguarded_unpinned": unguarded - pinned,
        "stale_total": sum(len(f["stale"]) for f in files),
    }


def coverage_lines(report: Dict) -> List[str]:
    """The disclosure, in the shape a verdict line has to carry it."""
    total = report["guarded_total"] + report["unguarded_total"]
    pct = (100.0 * report["guarded_total"] / total) if total else 0.0
    files_with = sum(1 for f in report["files"]
                     if f["anchored"] or f["block_figures"])
    return [
        f"[COVERAGE] this gate guards {report['guarded_total']} figure(s) in "
        f"{files_with} of {report['corpus_files']} corpus file(s): "
        f"{report['guarded_anchored']} ANCHORED and re-derived here, "
        f"{report['guarded_in_block']} inside the generated census block.",
        f"[COVERAGE] it does NOT guard {report['unguarded_total']} further "
        f"stated population figure(s) in the same files "
        f"({report['unguarded_pinned']} carry a pin — a date, an issue, a "
        f"commit — and {report['unguarded_unpinned']} do not). "
        f"Guarded fraction {report['guarded_total']}/{total} = {pct:.0f}%. "
        f"A freshness verdict below covers the guarded figures ONLY.",
    ]


def anchor_findings(report: Dict) -> List[AnchoredFigure]:
    out: List[AnchoredFigure] = []
    for f in report["files"]:
        for site in f["stale"]:
            out.append(AnchoredFigure(**site))
    return out


def apply_anchor_rewrites(report: Dict) -> List[str]:
    """Write back every corpus file whose anchors disagree with the tree."""
    written: List[str] = []
    for f in report["files"]:
        if f["rewritten"] is None:
            continue
        Path(f["path"]).write_text(f["rewritten"], encoding="utf-8")
        written.append(f["rel"])
    return written


#: EVERY bucket a cell can land in. `render` sums exactly these and refuses when
#: they do not reach the cell count, naming what was counted — so a label added to
#: `_join_axes` without a column here fails LOUDLY and by name, instead of silently
#: shrinking the headline.
#: `not_measured` joined this tuple on 2026-08-21 with the fourth cell state.
#: It is the label of a cell that is CONFIGURED NOT_MEASURED and whose run
#: agreed by declining to look — distinct from `enforced_skipped`, which is a
#: cell configured as enforcing whose run skipped, i.e. a DISAGREEMENT. Both
#: print in the NOT MEASURED column because a reader of that column wants the
#: same thing from either, but the headline names them apart, because only one
#: of them is a cell whose configuration was wrong.
_LABEL_KEYS = ("enforced", "contradicted", "waived", "na",
               "not_measured_agreed",
               "waived_contradicted", "na_contradicted",
               "enforced_skipped", "waived_skipped", "na_skipped")

#: WHICH PRINTED COLUMN EACH LABEL LANDS IN — and the reason this mapping is
#: written down instead of being implicit in `render`'s f-string (vibe-ic#1296).
#:
#: `_LABEL_KEYS` made the HEADLINE partition. It did nothing for the TABLE, which
#: is the thing a reader actually reads per dimension, and whose own comment
#: claimed "Every one of the 504 is now in exactly one". MEASURED on `7c376e348`,
#: that sentence was false for 53 cells: the six printed columns totalled
#: `17+44+367+0+8+15 = 451` against 504, and dimension 3 published a row that
#: summed to 11 of its 63 cells — the 52 whose predicate could not run appeared
#: in no column, at no dimension, and in no total.
#:
#: A dropped cell reads as a dimension with nothing to report, which is the exact
#: opposite of what it means. So every label a cell can carry is mapped to a
#: column HERE, `render` refuses when a label has no entry, and the columns are
#: checked to partition each row as well as the total.
#:
#: `None` means "not a column of its own": the ENFORCED cells are already printed
#: SPLIT across own / substituted / undeclared, and folding them back into one
#: column is the disclosure loss #889 removed.
_LABEL_COLUMN = {
    "enforced": None,
    "contradicted": "contradicted",
    "waived_contradicted": "contradicted",
    "na_contradicted": "contradicted",
    # KEYED APART FROM ITS COLUMN ON PURPOSE. `_fold_label_columns` sums the
    # label keys that map to a column INTO that column, so a label sharing the
    # column's name makes the sum read its own destination — a KeyError on the
    # first dimension with none of them, and a self-reference on the rest.
    "not_measured_agreed": "not_measured",
    "enforced_skipped": "not_measured",
    "waived_skipped": "not_measured",
    "na_skipped": "not_measured",
    "waived": "waived",
    "na": "na",
}

#: The columns `render` prints, in printed order. The three ENFORCED columns come
#: from `substitution_census()`; the rest are folded from `_LABEL_COLUMN`.
_ENFORCED_COLUMNS = ("own", "substituted", "undeclared")
_LABEL_COLUMNS = ("contradicted", "not_measured", "waived", "na")


def census_rows() -> Tuple[List[Dict], Dict[str, int]]:
    """``([per-dimension row], totals)`` recomputed from the live suite."""
    CV, SUB, DIMENSIONS, NAMES, QUESTIONS = _load()
    # vibe-ic#898 — QUOTE THE TWO-AXIS CENSUS, NOT THE CONFIGURATION AXIS.
    #
    # This generator shipped calling state_census(), which is the exact thing
    # that function's own docstring forbids: "Quoting `ENFORCED: N` from this
    # dict is what ORGANIC-20260808 reported - on 2026-08-08 it read 481 while
    # 26 of those 481 cells were failing. Use enforcement_census() for anything
    # a reader will quote."
    #
    # So #889 (make the table generated) rebuilt the erasure #888 (a red
    # predicate cannot count as ENFORCED) had just closed, and landed in the
    # SAME batch. On one commit `--check` printed [PASS] ... 481 while
    # test_no_cell_is_counted_enforced_while_its_predicate_is_red FAILED.
    # A generated number is only better than a hand-written one if it is
    # generated from the right source.
    states = {k: v.label for k, v in CV.enforcement_census().items()}
    # THE SAME DEFECT, ONE LINE LOWER. The comment above moved `states` off the
    # configuration axis and onto the two-axis census; `subs` was left on the
    # configuration axis, and the split is what the table actually PRINTS.
    #
    # substitution_census() buckets every cell CONFIGURED as enforcing --
    # including the ones whose own predicate is currently RED. So own +
    # substituted + undeclared spanned all 481 configured cells while the
    # headline two lines above said "455 ENFORCED ... NOT folded into the 455".
    # 455 + 26 = 481: they were folded, into the very columns the sentence
    # denied. Filtering by the enforcement axis is what makes the three columns
    # add up to the figure the reader is told they add up to.
    subs = {k: v for k, v in CV.substitution_census().items()
            if states.get(k) == "ENFORCED"}
    rows: List[Dict] = []
    for dim in DIMENSIONS:
        per = [v for (s, d), v in states.items() if d == dim]
        buckets = [v for (s, d), v in subs.items() if d == dim]
        rows.append({
            "dim": dim,
            "name": NAMES[dim],
            "question": QUESTIONS[dim],
            "own": buckets.count(SUB.OWN_MECHANISM),
            "substituted": buckets.count(SUB.SUBSTITUTED),
            "undeclared": buckets.count(SUB.UNDECLARED_BUCKET),
            "enforced": per.count("ENFORCED"),
            "contradicted": per.count("ENFORCED-CONTRADICTED"),
            "waived": per.count("WAIVED"),
            "na": per.count("NA"),
            # The labels `_join_axes` can emit that this table had no column for.
            # They were counted NOWHERE, so any non-zero one fell straight out of
            # the partition and aborted the generator with a bare subtraction.
            "waived_contradicted": per.count("WAIVED-CONTRADICTED"),
            "na_contradicted": per.count("NA-CONTRADICTED"),
            "enforced_skipped": per.count("ENFORCED-SKIPPED"),
            "waived_skipped": per.count("WAIVED-SKIPPED"),
            # The cell is CONFIGURED NOT_MEASURED and its run agreed by
            # declining to look, so `_join_axes` labels it with the bare state.
            "not_measured_agreed": per.count("NOT_MEASURED"),
            "na_skipped": per.count("NA-SKIPPED"),
        })
    _fold_label_columns(rows)
    totals = {k: sum(r[k] for r in rows)
              for k in _ENFORCED_COLUMNS + _LABEL_COLUMNS + _LABEL_KEYS}
    totals["cells"] = len(states)
    totals["cells_per_dim"] = len(states) // len(DIMENSIONS) if DIMENSIONS else 0
    return rows, totals


def _fold_label_columns(rows: List[Dict]) -> None:
    """Give every census label a printed column, or refuse by name.

    This is the structural half of vibe-ic#1296. `render` used to name its
    columns inline, so a label `_join_axes` had learned to emit — `-SKIPPED` —
    was counted by the headline and printed by nothing. Folding through
    `_LABEL_COLUMN` means a tenth label cannot be added without either giving it
    a column or reddening here, which is the same contract `_LABEL_KEYS` already
    holds the headline to.
    """
    unmapped = sorted(set(_LABEL_KEYS) - set(_LABEL_COLUMN))
    if unmapped:
        raise SystemExit(
            f"census label(s) with no table column: {unmapped}. The headline "
            f"counts them and the per-dimension table would not, so every one "
            f"of them would vanish from the rows a reader reads. Map each to a "
            f"column in _LABEL_COLUMN (or to None if it is already printed "
            f"split) rather than leaving it out of the table.")
    for row in rows:
        for column in _LABEL_COLUMNS:
            row[column] = sum(row[key] for key, col in _LABEL_COLUMN.items()
                              if col == column)


def _extra_labels(totals: Dict[str, int]) -> str:
    """The buckets beyond the historical four, named in the headline when non-zero.

    A cell counted in the partition but absent from the sentence is the #898 defect
    in its quieter form: the arithmetic reconciles and the reader still cannot see
    what it reconciled over. SKIPPED is the one that matters — it says the check
    exists and could not run, which is neither enforcement nor a contradiction.

    `NOT_MEASURED` was added here on 2026-08-21 with the fourth cell state, and
    it was added because it was MISSED: the headline enumerated 539 + 0 + 8 + 19
    + 46 + 3 = 615 of 621 while the table total row correctly showed 55 in the
    NOT MEASURED column. Six cells were in the partition and absent from the
    sentence — this function's own docstring describing its own output. The
    owner's ruling requires that any figure presented as enforcement state how
    many cells it excluded; a headline that silently drops six is that
    requirement failing.
    """
    parts = []
    for key, word in (("not_measured_agreed", "NOT_MEASURED"),
                      ("waived_contradicted", "WAIVED-CONTRADICTED"),
                      ("na_contradicted", "NA-CONTRADICTED"),
                      ("enforced_skipped", "ENFORCED-SKIPPED"),
                      ("waived_skipped", "WAIVED-SKIPPED"),
                      ("na_skipped", "NA-SKIPPED")):
        if totals.get(key):
            parts.append(f"{totals[key]} {word}")
    return (", " + ", ".join(parts)) if parts else ""


def _check_table_partitions(rows: List[Dict], totals: Dict[str, int]) -> None:
    """The TABLE must account for every cell, per row and in the total.

    The headline had this guard (`_LABEL_KEYS`) and the table did not, which is
    the whole of vibe-ic#1296: the two disagreed by 53 cells and nothing said
    so. Checked per ROW as well, because a total that reconciles can still hide
    a dimension that dropped cells against another that double-counted them —
    and the row is what a reader reads.
    """
    per_dim = totals.get("cells_per_dim") or 0
    for r in rows:
        printed = sum(r[c] for c in _ENFORCED_COLUMNS + _LABEL_COLUMNS)
        if per_dim and printed != per_dim:
            raise SystemExit(
                f"the published row for dimension {r['dim']} accounts for "
                f"{printed} of its {per_dim} cells. A row that does not "
                f"partition publishes a dimension as smaller than it is; the "
                f"cells it drops are not reported anywhere. Give every label a "
                f"column in _LABEL_COLUMN rather than adjusting a figure.")
    printed = sum(totals[c] for c in _ENFORCED_COLUMNS + _LABEL_COLUMNS)
    if printed != totals["cells"]:
        raise SystemExit(
            f"the published total row accounts for {printed} of "
            f"{totals['cells']} cells. Every cell must be in exactly one "
            f"column; see _LABEL_COLUMN.")


def _verdict_partition(totals: Dict[str, int]) -> str:
    """``"504/504 accounted"`` — or a refusal a reader can act on.

    Printed on the verdict line itself so that the sum a reader would have to do
    by hand is already done. The gate's PASS line published five figures that
    summed to 451 while announcing 504, and no reader adds up a verdict line.
    """
    printed = sum(totals[c] for c in _ENFORCED_COLUMNS + _LABEL_COLUMNS)
    if printed != totals["cells"]:
        return (f"UNACCOUNTED: {totals['cells'] - printed} of "
                f"{totals['cells']} cells are in no column")
    return f"{printed}/{totals['cells']} accounted"


def corpus_identity_line() -> str:
    """One sentence naming the corpus this block was generated against.

    WHY A GENERATED BLOCK HAS TO SAY THIS. The census is a statistic, and several
    of its cells have predicates that consult the published corpus. So the block
    is a function of (this commit, that corpus) and it published only the first
    half. Two hosts at the SAME commit with DIFFERENT corpora mounted therefore
    produced two different tables, both of which read as "the census", and
    `--check` on either one called the other stale without saying why.

    It is deliberately NOT a timestamp. `WHAT IT REFUSES` above rules out a stamp
    that changes on every run, because that makes `--check` meaningless. This
    changes only when the MOUNT changes, which is exactly the drift a reader
    needs to see and the only drift this line can introduce.

    MEASURED, and this is why the line reads the way it does: with no corpus
    mounted the generator writes the block and reports `no change`; with a corpus
    mounted that it cannot use it declares the run NORECORD and writes NOTHING.
    So the generator never silently published two truths — the hazard is the
    narrower one where a DIFFERENT usable corpus moves the numbers, and that case
    is invisible without this line.
    """
    try:
        sys.path.insert(0, str(PLUGIN_ROOT / "programs" / "tests"))
        from _published_corpus import corpus_state  # noqa: E402
        state, root = corpus_state()
    except Exception as exc:  # pragma: no cover - a corpus seam that cannot be
        # asked is reported, never guessed at, and never silently omitted.
        return (f"Corpus at generation: UNRESOLVED — the corpus seam could not be "
                f"consulted ({type(exc).__name__}: {str(exc)[:120]}). This block "
                f"may or may not be a function of a mounted corpus.")
    if root is None:
        return (f"Corpus at generation: {state.upper().replace('-', '_')} — no "
                f"published cell was read. Every figure below is a function of "
                f"this commit alone.")
    return (f"Corpus at generation: {state.upper().replace('-', '_')} @ "
            f"{_corpus_commit(root)} ({root.name}). Figures whose predicate "
            f"consults the corpus are a function of THAT tree as well as of this "
            f"commit.")


def _corpus_commit(root) -> str:
    """The corpus's own HEAD, short. `unknown-commit` rather than a guess."""
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(root),
                             capture_output=True, text=True, timeout=20)
        sha = out.stdout.strip()
        return sha if out.returncode == 0 and sha else "unknown-commit"
    except Exception:  # pragma: no cover - defensive
        return "unknown-commit"


def render(rows: List[Dict], totals: Dict[str, int]) -> str:
    """The generated block, marker to marker. No timestamp: see WHAT IT REFUSES."""
    out: List[str] = [BEGIN, ""]
    # #898: the headline must RECONCILE. Printing enforced/waived/na alone left
    # the contradicted cells out of a line that reads like a partition, so the
    # numbers silently failed to add to the total — the same erasure by omission
    # the split below exists to prevent, one line higher.
    #
    # #898 FIXED THE SYMPTOM AND LEFT THE SHAPE. It enumerated FOUR buckets by
    # hand, and `_join_axes` can emit more than four labels: every state has a
    # `-CONTRADICTED` form, and now a `-SKIPPED` one. So this reconciled only while
    # `WAIVED-CONTRADICTED` and `NA-CONTRADICTED` both happened to be zero — the
    # partition held by luck, not by construction, and the first non-zero one would
    # abort the generator with a subtraction the reader cannot act on. Measured:
    # marking a handful of corpus-dependent cells as skipped gave `501 != 504`, and
    # the three missing cells were nowhere in the message.
    #
    # Sum what the census ACTUALLY produced, and name what does not fit.
    _sum = sum(v for k, v in totals.items() if k in _LABEL_KEYS)
    if _sum != totals['cells']:
        _named = ", ".join(f"{k}={totals[k]}" for k in sorted(_LABEL_KEYS)
                           if totals.get(k))
        raise SystemExit(
            f"census does not partition: {_sum} != {totals['cells']} — the "
            f"buckets that were counted are [{_named}], so "
            f"{totals['cells'] - _sum} cell(s) carry a label this generator does "
            f"not count. A cell with no bucket is a cell the headline silently "
            f"drops; add its label to _LABEL_KEYS rather than adjusting a total.")
    # The guard the headline needed and did not have. The check above proves the
    # four STATE figures partition the 504; it says nothing about whether the
    # three columns underneath add up to the ENFORCED figure they are presented
    # as splitting. They did not -- they summed to 481 under a headline of 455 --
    # and no assertion in this file or its tests could see it, because every
    # existing check compared the table to a census that was wrong the same way.
    _split = totals['own'] + totals['substituted'] + totals['undeclared']
    if _split != totals['enforced']:
        raise SystemExit(
            f"the ENFORCED split does not reconcile: own+substituted+"
            f"undeclared = {_split}, but {totals['enforced']} cells are "
            f"ENFORCED. A cell is in no column or in two.")
    out.append(
        f"**{totals['cells']} cells: {totals['enforced']} ENFORCED, "
        f"{totals['contradicted']} ENFORCED-CONTRADICTED, "
        f"{totals['waived']} WAIVED, {totals['na']} NA"
        + _extra_labels(totals) + ".**")
    out.append("")
    out.append(
        f"The {totals['contradicted']} CONTRADICTED cells are configured as "
        f"enforcing while their own predicate is currently RED. They are NOT "
        f"folded into the {totals['enforced']}: a cell whose predicate fails is "
        f"not evidence of enforcement. See vibe-ic#888.")
    out.append("")
    out.append(corpus_identity_line())
    out.append("")
    # WHAT THIS MATRIX MEASURES, printed with the number rather than filed in a
    # doc nobody re-reads. Adversarial round 2 (2026-08-10) established that NO
    # cell of the 63x8 reads artefact CONTENT: a sign-off artefact can violate
    # its own criterion -- overlapping instances in a shipped DEF, a routed DEF
    # with zero signal routing -- and not one of the 504 moves. Redirecting a
    # gate's criterion at a DIFFERENT step's artefact likewise moves zero cells.
    # The matrix is therefore a census of COVERAGE SHAPE, and 504/504 green is
    # not a claim that any design is correct. Ruled 2026-08-10: this is an
    # accepted boundary, not a defect -- so it must be STATED, not implied.
    out.append(
        f"**What these {totals['cells']} cells measure — and what they do "
        f"not.** Every cell asks whether a step is declared, wired, and reached "
        f"by a gate. NO cell reads the CONTENT of the artefact a step produces. "
        f"A shipped sign-off artefact can violate the very criterion its step is "
        f"named after and no cell here changes colour. Read this table as "
        f"COVERAGE SHAPE, never as evidence that a design is correct.")
    out.append("")
    out.append(
        f"`ENFORCED` is published SPLIT, because it is not one thing. It means "
        f"a live predicate ran and passed; it does not say WHAT it ran against, "
        f"and that turns out to be three different answers:")
    out.append("")
    out.append(
        f"* **{totals['own']}** — measured against the step's OWN mechanism. "
        f"This is the only figure that means what \"enforcing\" sounds like, "
        f"and it is a floor: the two rows below are not evidence against it, "
        f"they are the part nobody has evidence for.")
    out.append(
        f"* **{totals['substituted']}** — measured against a SUBSTITUTED "
        f"stand-in. The predicate runs and passes; what it exercises is not "
        f"the mechanism the cell is named after. Each one carries a disclosure "
        f"from the module that owns it.")
    out.append(
        f"* **{totals['undeclared']}** — in dimensions that have not answered "
        f"the question at all. NOT counted as clean: UNDECLARED is a state, "
        f"not a synonym for \"own mechanism\". See `substitution.py`, "
        f"\"WHY UNDECLARED IS A STATE AND NOT A DEFAULT\".")
    out.append("")
    out.append(
        f"The {totals['waived']} WAIVED and {totals['na']} NA cells are not "
        f"enforcing anything and enter none of those columns. There is "
        f"deliberately no single \"enforcing\" total to quote.")
    out.append("")
    # CONTRADICTED gets a column. Filtering the three ENFORCED columns onto the
    # enforcement axis (see census_rows) is only half the repair: without a
    # column of its own, a contradicted cell would appear in NO column, and a
    # row that silently drops cells is the erasure-by-omission this file warns
    # about six lines from here.
    #
    # NOT MEASURED gets one for the same reason, and vibe-ic#1296 is what it
    # cost to leave it out. `-SKIPPED` was added to `_join_axes` and to
    # `_LABEL_KEYS`, so the headline reconciled — and this table, which names its
    # columns inline, kept printing six. MEASURED on `7c376e348`: the total row
    # published 451 of 504 cells and dimension 3 published 11 of its 63, the
    # other 52 appearing nowhere. A dimension whose predicates could not run
    # reads, in that row, as a dimension with nothing to report.
    #
    # The columns are folded from `_LABEL_COLUMN` and the partition is asserted
    # below for every ROW as well as the total, so this cannot be lost again by
    # adding a label.
    _check_table_partitions(rows, totals)
    out.append("| dim | question | ENFORCED: own | ENFORCED: substituted "
               "| ENFORCED: undeclared | CONTRADICTED | NOT MEASURED "
               "| WAIVED | NA |")
    out.append("|-----|----------|--------------:|----------------------:"
               "|---------------------:|-------------:|-------------:"
               "|-------:|---:|")
    for r in rows:
        out.append(
            f"| {r['dim']} | `{r['name']}` — {r['question']} "
            f"| {r['own']} | {r['substituted']} | {r['undeclared']} "
            f"| {r['contradicted']} | {r['not_measured']} "
            f"| {r['waived']} | {r['na']} |")
    out.append(
        f"| **total** | | **{totals['own']}** | **{totals['substituted']}** "
        f"| **{totals['undeclared']}** | **{totals['contradicted']}** "
        f"| **{totals['not_measured']}** "
        f"| **{totals['waived']}** | **{totals['na']}** |")
    out.append("")
    out.append(
        f"**NOT MEASURED is not a pass and not a defect.** Those "
        f"{totals['not_measured']} cells have a predicate that declined to run, "
        f"naming a resource it could not reach — most often a published corpus "
        f"this checkout does not carry. They are counted here so a dimension "
        f"whose cells could not be driven cannot read as a dimension with "
        f"nothing to report; read them as UNKNOWN, never as coverage.")
    out.append("")
    out.append("Regenerate (never edit this block by hand, and never quote it "
               "without re-running):")
    out.append("")
    out.append("```")
    out.append("python3 tools/gen_flow_matrix_census.py          # rewrite")
    out.append("python3 tools/gen_flow_matrix_census.py --check  # exit 1 on drift")
    out.append("```")
    out.append("")
    out.append(END)
    return "\n".join(out)


def splice(text: str, block: str) -> str:
    """Replace the marked block, or raise if the markers are gone."""
    start = text.find(BEGIN)
    stop = text.find(END)
    if start < 0 or stop < 0 or stop < start:
        raise SystemExit(
            f"{README}: generated-census markers not found (looked for\n"
            f"  {BEGIN}\n  {END}\n). A hand edit that removed them would make "
            f"this generator silently write nothing, so it refuses instead.")
    return text[:start] + block + text[stop + len(END):]


def run_figures(args) -> Tuple[int, Dict, List[str]]:
    """The anchor half: ``(rc, report, lines to print)``.

    Separated from ``main`` because it is the half that costs milliseconds. The
    block half re-runs eight dimension modules inside a nested pytest and costs
    two minutes; tying a figure check to that clock is how a cheap check ends up
    running in no merge path.
    """
    figures_root = Path(args.figures_root).resolve()
    lines: List[str] = []
    if not figures_root.is_dir():
        return 2, {}, [f"[ERROR] no such --figures-root: {figures_root}"]

    report = figure_report(Path(args.root).resolve(), figures_root)

    # A PASS must say how much it examined (vibe-ic#447), and this gate is
    # subject to its own rule. A corpus with no anchors in it produces zero
    # findings for the same reason an empty corpus does, and neither is clean.
    if not report["corpus_files"] or not report["guarded_anchored"]:
        return 2, report, [
            f"NOTHING_SCANNED: {report['corpus_files']} corpus file(s) under "
            f"{figures_root} carry {report['guarded_anchored']} anchored "
            f"figure(s) — this is NOT a pass. An anchor sweep that found no "
            f"anchors reports the absence of a result, not a clean one."]

    lines.extend(coverage_lines(report))
    stale = anchor_findings(report)
    if stale:
        for f in report["files"]:
            for site in f["stale"]:
                a = AnchoredFigure(**site)
                lines.append(f"  [FAIL] {f['rel']}:{a.line}  {a.describe()}")
        lines.append(
            f"[FAIL] {len(stale)} anchored figure(s) disagree with the tree; "
            f"re-run `python3 tools/gen_flow_matrix_census.py --fix` "
            f"(--fix-figures repairs these anchors but leaves the README "
            f"census block stale, which still exits 1)")
        return 1, report, lines
    lines.append(
        f"[PASS] 63x8 derived figures fresh: {report['guarded_anchored']} "
        f"anchored figure(s) re-derived across {report['corpus_files']} "
        f"corpus file(s).")
    return 0, report, lines


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # THE SUBJECT (vibe-ic#972). Optional, and its DEFAULT is the previous
    # behaviour verbatim — this script's own repository — so nothing that
    # already worked changes. What changes is that a caller CAN point it
    # somewhere, and that when it is pointed somewhere it answers about there.
    ap.add_argument("repo_root", nargs="?", default=None,
                    help=f"the repository this run is about (default "
                         f"{REPO_ROOT}, this script's own). A tree carrying no "
                         f"63x8 suite is refused as a ZERO DENOMINATOR, not "
                         f"censused as if it were this one")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the committed block or any anchored figure "
                         "would change (CI mode)")
    ap.add_argument("--check-figures", action="store_true",
                    help="check ONLY the anchored figures and the coverage "
                         "disclosure; skips the two-minute census")
    ap.add_argument("--fix-figures", action="store_true",
                    help="rewrite every anchored figure in the corpus from the "
                         "live flow yaml, then exit")
    # BOTH HALVES IN ONE INVOCATION (vibe-ic#1382). The repair has always been
    # two commands — `--fix-figures` for the anchors, the plain run for the
    # README census block — and each failure message named only its own half.
    # Running one and stopping leaves a failure that reads exactly like the one
    # it was supposed to clear, which is worse than not having repaired at all.
    ap.add_argument("--fix", action="store_true",
                    help="rewrite the anchored figures AND the README census "
                         "block — the complete repair. `--fix-figures` alone "
                         "leaves the census block stale and still exits 1")
    # These three default to None, not to a path. A path baked in here could
    # not be told apart from one the caller chose, so `repo_root` would have
    # been unable to move them — which is how the subject came to be ignored in
    # the first place. Explicit still wins; absent now follows the subject.
    ap.add_argument("--out", default=None,
                    help=f"README to rewrite (default <repo_root>/{README_REL})")
    ap.add_argument("--figures-root", default=None,
                    help=f"tree swept for anchored figures "
                         f"(default <repo_root>/{FIGURES_REL})")
    ap.add_argument("--root", default=None,
                    help=f"plugin root every figure binding is evaluated "
                         f"against (default <repo_root>/{PLUGIN_REL})")
    ap.add_argument("--figures-json",
                    help="write the full coverage report here")
    # WHAT THIS RUN WROTE, AS DATA (vibe-ic#1382). The two write paths already
    # SAY what they wrote — "rewrote anchored figures in 3 file(s): a, b, c"
    # and "wrote <path>: …" — in prose, on stdout, interleaved with a coverage
    # disclosure. A caller that has to re-derive that by parsing sentences is
    # the "check that lies" shape this repository exists to remove, and the
    # caller that needs it is `gatekeeper_prepare_landing.py`, whose entire
    # safety property is that every path it leaves dirty was DECLARED by the
    # writer that produced it (#1029/#1089). A hand-typed allow-list there
    # would rot in the forgiving direction the moment this program gained a
    # corpus file.
    #
    # Dumped in a `finally`, and that is the load-bearing part rather than a
    # tidiness: `--fix` rewrites the anchors FIRST and only then drives the
    # census, which is the half that blows its 60 s inner bound on a loaded
    # host (vibe-ic#1277). A partial repair — anchors written, census block
    # not — is the NORMAL failure here, and a declaration emitted only on the
    # success path would leave exactly those writes unattributable.
    ap.add_argument("--written-json",
                    help="write the repo-relative paths this run WROTE here, "
                         "as a JSON list. Emitted even when the run fails, so "
                         "a partial repair is still attributable")
    args = ap.parse_args(argv)

    del _WRITTEN[:]
    try:
        return _run(args)
    finally:
        if args.written_json:
            Path(args.written_json).write_text(
                json.dumps(sorted(set(_WRITTEN)), indent=1), encoding="utf-8")


#: Repo-relative paths written by the CURRENT run. Reset by `main`, appended to
#: at each write site, published by `--written-json`. Module state rather than a
#: return value because the two write sites sit either side of the census, and
#: the census is allowed to abort between them.
_WRITTEN: List[str] = []


def _record_written(subject: Path, path: Path) -> None:
    """Record one write, repo-relative to the SUBJECT of this run."""
    try:
        _WRITTEN.append(str(Path(path).resolve().relative_to(subject)))
    except ValueError:
        # A caller pointed --out or --figures-root outside the subject. Record
        # the absolute path rather than dropping the write: an undeclared write
        # is the one thing the consumer of this list must never be handed.
        _WRITTEN.append(str(Path(path).resolve()))


def _run(args: argparse.Namespace) -> int:
    subject = (Path(args.repo_root).resolve() if args.repo_root else REPO_ROOT)
    args.out = args.out or str(subject / README_REL)
    args.figures_root = args.figures_root or str(subject / FIGURES_REL)
    args.root = args.root or str(subject / PLUGIN_REL)

    # DECIDED BEFORE ANY WORK, and that ordering is half the fix. The 110s this
    # program spent over an empty tree were spent AFTER it had everything it
    # needed to know there was nothing there: `run_figures` already refuses an
    # empty corpus, and `main` ran the two-minute census anyway.
    state, counts = classify_subject(subject)
    if state != SUBJECT_OWN:
        for line in subject_refusal_lines(state, subject, counts):
            sys.stderr.write(line + "\n")
        return 2

    if args.fix_figures or args.fix:
        figures_root = Path(args.figures_root).resolve()
        if not figures_root.is_dir():
            sys.stderr.write(f"[ERROR] no such --figures-root: {figures_root}\n")
            return 2
        report = figure_report(Path(args.root).resolve(), figures_root)
        written = apply_anchor_rewrites(report)
        # RECORDED FROM THE REPORT, NOT FROM `written`. `apply_anchor_rewrites`
        # returns paths relative to FIGURES_ROOT; the consumer needs them
        # relative to the repository, and re-joining two relative paths by hand
        # at the call site is how a declared path stops naming the file that was
        # actually written.
        for f in report["files"]:
            if f["rewritten"] is not None:
                _record_written(subject, Path(f["path"]))
        for line in coverage_lines(report):
            print(line)
        print(f"rewrote anchored figures in {len(written)} file(s)"
              + (": " + ", ".join(written) if written else ""))
        if args.fix_figures:
            return 0
        # `--fix` falls through to the census block below. The anchors are now
        # fresh, so the re-scan that follows costs a pass and returns 0.

    if args.check_figures:
        rc, report, lines = run_figures(args)
        if args.figures_json and report:
            Path(args.figures_json).write_text(json.dumps(report, indent=2,
                                                          default=str))
        for line in lines:
            (sys.stderr if rc else sys.stdout).write(line + "\n")
        return rc

    fig_rc, fig_report, fig_lines = run_figures(args)
    if args.figures_json and fig_report:
        Path(args.figures_json).write_text(json.dumps(fig_report, indent=2,
                                                      default=str))

    rows, totals = census_rows()

    # A PASS must say how much it examined (vibe-ic#447). A census rendered over
    # zero cells matches an empty table trivially, and every count below would
    # read 0 without a single assertion firing.
    if not rows or not totals["cells"]:
        sys.stderr.write(
            f"NOTHING_SCANNED: the live census produced {len(rows)} dimension "
            f"row(s) over {totals.get('cells', 0)} cell(s) — this is NOT a "
            f"pass. Check that the eight dimension modules import and that "
            f"pytest can collect them.\n")
        return 2

    path = Path(args.out)
    text = path.read_text(encoding="utf-8")
    updated = splice(text, render(rows, totals))

    # THE COVERAGE DISCLOSURE TRAVELS WITH EVERY VERDICT, red or green. A
    # verdict line that carries the guarded figure and not the unguarded one is
    # the shape this gate was found in: "[PASS] 63x8 census fresh" printed over
    # a page with five stale live-derived numbers on it (vibe-ic#961).
    for line in fig_lines:
        (sys.stderr if fig_rc else sys.stdout).write(line + "\n")

    if args.check:
        if updated != text:
            sys.stderr.write(
                f"{path} census block is stale; re-run "
                f"`python3 tools/gen_flow_matrix_census.py --fix` "
                f"(the plain run repairs this block but leaves any stale "
                f"anchored figure, which still exits 1)\n")
            return 1
        if fig_rc:
            return fig_rc
        # THE VERDICT LINE PARTITIONS TOO (vibe-ic#1296). It read
        # `own=17 substituted=44 undeclared=367; WAIVED=8 NA=15` — 451 of 504,
        # the same 53 cells the table dropped — so the one line a landing
        # reviewer actually reads carried the defect after the page was fixed.
        # A gate that prints a denominator must print the WHOLE denominator.
        print(f"[PASS] 63x8 census fresh: {totals['cells']} cells over "
              f"{len(rows)} dimensions; ENFORCED own={totals['own']} "
              f"substituted={totals['substituted']} "
              f"undeclared={totals['undeclared']}; "
              f"CONTRADICTED={totals['contradicted']} "
              f"NOT-MEASURED={totals['not_measured']} "
              f"WAIVED={totals['waived']} NA={totals['na']} "
              f"({_verdict_partition(totals)}).")
        return 0

    # The block is written FIRST and the figure verdict returned after, so a
    # stale anchor somewhere else in the corpus never silently costs the caller
    # the block regeneration they asked for. `--fix-figures` is the repair for
    # the other half and the message above names it.
    if updated == text:
        print(f"no change ({totals['cells']} cells)")
    else:
        path.write_text(updated, encoding="utf-8")
        _record_written(subject, path)
        print(f"wrote {path}: ENFORCED own={totals['own']} "
              f"substituted={totals['substituted']} "
              f"undeclared={totals['undeclared']}; "
              f"CONTRADICTED={totals['contradicted']} "
              f"NOT-MEASURED={totals['not_measured']} "
              f"WAIVED={totals['waived']} NA={totals['na']}; "
              f"{totals['cells']} cells "
              f"({_verdict_partition(totals)}).")
    return fig_rc


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(main, sys.argv[1:]))
