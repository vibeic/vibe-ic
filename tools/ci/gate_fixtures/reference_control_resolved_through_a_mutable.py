"""`reference control resolved through a mutable` — a negative control whose
reference version is fetched by a branch name.

THE MUTATION IS THE DEFECT THE GATE NAMES
=========================================
Straight from the gate's docstring: "When the reference version is fetched by a
BRANCH name, the reference moves the moment the fix lands there, and the
control begins asserting that a repaired program is still broken." So the
mutation moves ONE revision argument, in one `git show`, from the working-tree
pointer to the remote-tracking name:

    git show HEAD~1:<path>        ->      git show origin/main:<path>

Nothing else in the subject changes. Same files, same spawn calls, same
subcommands, same argument counts.

SAME DENOMINATOR, BOTH ARMS
===========================
The gate prints its population before the verdict, and the mutation moves none
of it:

    modules parsed            4    (3 under programs/, 1 under tools/ — the
                                    gate walks both bases, and both are
                                    populated in both arms)
    git process calls         5    (the SAME five spawns; the mutation edits a
                                    revision string inside one of them, it does
                                    not add or remove a call)
    inventory rows applied    0    (no inventory ships beside the gate)

Only `branch-shaped revisions` moves, 0 -> 1. An emptied subject would instead
take the gate's own explicit vacuity branch — "modules parsed is 0 ... NOT a
pass", rc 2 — which proves the refusal of an empty corpus and nothing about the
predicate.

THE ACCEPTED CASES ARE CARRIED TOO, because they are the discriminator
=====================================================================
The can-pass arm is not merely "no git". It contains the three shapes the gate
says must stay silent, so a gate that had degraded to "any git revision is a
finding" would fail the can-pass direction rather than sail through it:

  * `HEAD~1` / `HEAD` — a working-tree pointer against a fixture repository,
    immutable in context;
  * a bare 40-hex sha — an object named directly;
  * `git rev-parse --abbrev-ref origin/main` — out of scope BY CONSTRUCTION:
    it returns the NAME of a ref, not an object, so it can be neither a
    reference version nor a subject set. It carries the forbidden token
    `origin/main` in the can-PASS arm, which is what makes it a real test of
    the exemption rather than of its absence.

KNOWN FRAGILITY, STATED RATHER THAN HIDDEN
==========================================
`--inventory` is not in the declaration, so the gate defaults it to a file
beside its OWN code — under `$PG`, which the fixture protocol deliberately
keeps pointed at the real programs tree. No such file exists today, so `known`
is empty and no row can go stale against this synthetic subject. If one is ever
added there, every row in it becomes stale here and the CAN-PASS direction goes
red. That failure is loud and self-announcing, and the repair is to scope the
input to the subject in the declaration:

    --inventory "$ROOT/vibe-ic-marketplace/plugins/vibe-ic/programs/mutable_ref_reference_inventory.json"

which names the identical file when $ROOT is the real repository.

chip-AGNOSTIC: no IC, vendor, SKU or process appears here.
"""
from pathlib import Path

GATE = "reference control resolved through a mutable"

#: The one token that moves between the arms, and the immutable pointer it
#: replaces. Everything else in the subject is byte-identical.
_IMMUTABLE_REV = "HEAD~1"
_MUTABLE_REV = "origin/main"

_SHA = "9f1c0a4d3b7e2f5081c6a9d4e73b2058fa16c3d7"

_CONTROL = '''"""A negative control: fetch the reference version of one file."""

import subprocess


def reference_text(path):
    """The bytes the control asserts are still broken."""
    return subprocess.check_output(
        ["git", "show", f"{rev}:{path}"], text=True)


def working_text(path):
    return subprocess.check_output(["git", "show", f"HEAD:{path}"], text=True)
'''

_COVERAGE = '''"""Derive the subject set from a diff, then measure only those files."""

import subprocess


def changed_files():
    out = subprocess.run(
        ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
        capture_output=True, text=True)
    return out.stdout.split()


def pinned_tree():
    """A bare object name: the pin cannot move."""
    return subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", "%s"], text=True)
''' % _SHA

#: Out of scope BY CONSTRUCTION, and it carries the forbidden token in the
#: CAN-PASS arm on purpose — see the module docstring.
_UPSTREAM_NAME = '''"""Ask which branch the upstream is. A NAME, never an object."""

import subprocess


def upstream_branch():
    return subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "origin/main"], text=True).strip()
'''

_TOOLS_HELPER = '''"""Under tools/, which is the gate's second base. No spawn at all."""


def normalise(rows):
    return sorted(set(rows))
'''


def _tree(work: Path, rev: str) -> Path:
    root = work / "subject"
    progs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    progs.mkdir(parents=True, exist_ok=True)
    (progs / "negative_control.py").write_text(
        _CONTROL.replace("{rev}", rev), encoding="utf-8")
    (progs / "coverage_subject.py").write_text(_COVERAGE, encoding="utf-8")
    (progs / "upstream_name_query.py").write_text(_UPSTREAM_NAME, encoding="utf-8")
    tools = root / "tools" / "ci"
    tools.mkdir(parents=True, exist_ok=True)
    (tools / "row_helper.py").write_text(_TOOLS_HELPER, encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """Every revision read names an object or a working-tree pointer."""
    return _tree(work, _IMMUTABLE_REV)


def can_fail(work: Path):
    """The control's reference version is fetched through a name that moves."""
    return _tree(work, _MUTABLE_REV), "resolve through a name that moves"
