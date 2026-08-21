#!/usr/bin/env python3
"""gate_mutation_fixtures — the two-fixture protocol, and the engine that runs it.

WHY THIS FILE EXISTS
====================
A gate proven only to PASS on good input has not been shown to discriminate.
This repo has now found the stronger version of that failure twice in one day:
a check that passes until someone FORGES its input (vibe-ic#1745), and a check
that reported a decided verdict over ten gates it never ran.

`flow_step_can_fail_check` already asks this question of the 63 FLOW steps —
"does this step's gate declare any criterion capable of failing?" — and holds
the answer to a baseline that may only shrink. Nothing asked it of the 83
gates in `tools/ci/repo_hygiene_gates.sh`, which is the set that decides
whether a change LANDS.

THE PROTOCOL
============
For each gate the dispatcher declares, a fixture module
`tools/ci/gate_fixtures/<slug>.py` provides BOTH directions:

    GATE = "<the label, byte-for-byte as the dispatcher declares it>"

    def can_pass(work: Path) -> Path:
        '''Build a subject the gate ACCEPTS. Return the subject root.'''

    def can_fail(work: Path) -> tuple[Path, str]:
        '''MUTATE that same subject so the gate MUST reject it.
        Return (subject root, a fragment the refusal must contain).'''

One of the two is not half the property. A `can_pass` alone is the failure this
file exists to remove; a `can_fail` alone proves a gate is loud without proving
it is quiet on a clean tree, which is how a permanently-red gate gets routed
around.

THE FIXTURE DRIVES THE GATE **AS THE DISPATCHER DECLARES IT**
=============================================================
This is the load-bearing part, and getting it wrong would reproduce the defect
rather than catch it. The engine below does NOT re-derive a command from the
gate's name: it reads the DECLARATION out of `repo_hygiene_gates.sh` with the
repo's existing `parse_declarations`, and substitutes only the SUBJECT.

    $ROOT / $PLUGIN   -> the fixture's subject tree     (the input under test)
    $PG               -> the REAL programs directory    (the gate's own code)
    cwd               -> whichever of the two the declaration names

MEASURED, and it is why the substitution is drawn there: `container exec
deadlines` is declared WITHOUT `--strict`, and its own docstring says findings
are ADVISORY (rc 0) under that flag set. A fixture that invented
`--strict` would have proved a discrimination the landing gate does not have.
The rule is that the fixture may choose the INPUT and never the ARGV.

WHAT A CAN-FAIL FIXTURE MAY NOT DO
==================================
It may not reach its refusal by removing the gate's subject. "The file is
absent" is the vacuous-refusal path this repo already routes to NOT_CHECKED,
and a fixture that used it would prove only that the gate notices an empty
corpus. The mutation must leave the gate a corpus to look at and change the
ANSWER inside it — which is what `MUTATION` means here.

NDA: a can-fail fixture for a name-scanning gate must SYNTHESISE the forbidden
token from the gate's own deny-list at run time. Storing one in this tree would
be the very artefact the gate exists to keep out.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parents[1]
PROGRAMS = REPO_ROOT / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
HYGIENE_SCRIPT = _HERE / "repo_hygiene_gates.sh"
FIXTURE_DIR = _HERE / "gate_fixtures"
DEBT_FILE = _HERE / "gate_fixture_debt.json"

#: The gate's own code, not its subject. Never redirected at a fixture tree.
_REAL_PG = str(PROGRAMS)


def _load_parse_declarations():
    """The repo's ONE parser for `run` lines, imported rather than re-written.

    A second regex over the same script is the drift shape #527/#530/#534/#538
    each spent a version removing, and it has already been got wrong twice —
    see `gate_discloses_denominator_check` for the two ways.
    """
    if str(PROGRAMS) not in sys.path:
        sys.path.insert(0, str(PROGRAMS))
    from gate_discloses_denominator_check import parse_declarations  # noqa: E402
    return parse_declarations


def declarations(script: Optional[Path] = None):
    """Every gate the dispatcher declares, in declaration order."""
    return _load_parse_declarations()(script or HYGIENE_SCRIPT)


# --- naming -----------------------------------------------------------------
#: `$( … )` first: the four per-cell gates carry a command substitution in
#: their label, and only bash knows what it expands to. The STATIC part is the
#: gate; the expansion is the item it ran over.
_SUBST_RE = re.compile(r'\$\([^)]*(?:\([^)]*\)[^)]*)*\)')
_NONWORD_RE = re.compile(r'[^a-z0-9]+')


def slug(label: str) -> str:
    """A filesystem/module name for a gate LABEL. Stable, lossy, checked.

    Lossy on purpose — the label is prose. Two labels that slug alike are a
    REFUSAL (`slug_collisions`), never a silent merge of two gates' evidence.
    """
    s = _SUBST_RE.sub("", label).lower()
    s = _NONWORD_RE.sub("_", s).strip("_")
    if not s:
        return "_unnamed"
    if s[0].isdigit():
        s = "g_" + s
    return s


def slug_collisions(labels) -> Dict[str, List[str]]:
    """slug -> the >1 labels that produce it. Empty when every gate is distinct."""
    seen: Dict[str, List[str]] = {}
    for lb in labels:
        seen.setdefault(slug(lb), []).append(lb)
    return {k: v for k, v in seen.items() if len(v) > 1}


# --- the fixture modules ----------------------------------------------------
class Fixture(NamedTuple):
    slug: str
    path: Path
    gate: str                 # the GATE constant the module declares
    has_can_pass: bool
    has_can_fail: bool
    module: object


def _import_fixture(path: Path):
    spec = importlib.util.spec_from_file_location(
        "vibeic_gate_fixture_" + path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load fixture module: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_fixtures(fixture_dir: Optional[Path] = None) -> Dict[str, Fixture]:
    """Every fixture module present, keyed by slug. Import errors PROPAGATE.

    A fixture that will not import is not a missing fixture — it is a broken
    one, and the two must not read alike.
    """
    d = fixture_dir or FIXTURE_DIR
    out: Dict[str, Fixture] = {}
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.py")):
        if p.name.startswith("_"):
            continue
        mod = _import_fixture(p)
        out[p.stem] = Fixture(
            slug=p.stem,
            path=p,
            gate=getattr(mod, "GATE", ""),
            has_can_pass=callable(getattr(mod, "can_pass", None)),
            has_can_fail=callable(getattr(mod, "can_fail", None)),
            module=mod,
        )
    return out


# --- driving the REAL declared command --------------------------------------
class Outcome(NamedTuple):
    rc: int
    output: str
    argv: List[str]
    cwd: str


def _resolve_argv(cmd: str, subject: Path) -> List[str]:
    """The declaration's argv with the SUBJECT redirected and nothing else.

    `$PG` keeps pointing at the real programs tree: it names the gate's own
    executable, not the input. Redirecting it would run a fixture's copy of the
    gate, which proves nothing about the gate that lands.
    """
    parts = shlex.split(cmd)
    out: List[str] = []
    for tok in parts:
        tok = tok.replace("${PG}", _REAL_PG).replace("$PG", _REAL_PG)
        tok = (tok.replace("${ROOT}", str(subject)).replace("$ROOT", str(subject))
                  .replace("${PLUGIN}", str(subject)).replace("$PLUGIN", str(subject)))
        out.append(tok)
    return out


def unresolved_shell(cmd: str) -> Optional[str]:
    """The piece of this command no fixture can drive as written, or None."""
    if "$(" in cmd:
        return "a command substitution: " + cmd[cmd.index("$("):][:60]
    for m in re.finditer(r'\$\{?([A-Za-z_]\w*)\}?', cmd):
        if m.group(1) not in ("ROOT", "PLUGIN", "PG", "PJSON"):
            return f"the shell variable ${m.group(1)}, bound by the enclosing loop"
    return None


def invoke(decl, subject: Path, timeout: int = 180) -> Outcome:
    """Run the gate EXACTLY as declared, with `subject` as its input tree."""
    argv = _resolve_argv(decl.cmd, subject)
    env = dict(os.environ)
    env["VIBEIC_SUBJECT_ROOT"] = str(subject)
    env.pop("GATEKEEPER_HYGIENE_JOBS", None)
    try:
        p = subprocess.run(argv, cwd=str(subject), env=env, timeout=timeout,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, errors="replace")
        return Outcome(p.returncode, p.stdout or "", argv, str(subject))
    except subprocess.TimeoutExpired as e:
        return Outcome(-1, f"TIMEOUT after {timeout}s: {e}", argv, str(subject))


class Verdict(NamedTuple):
    ok: bool
    detail: str
    outcome: Optional[Outcome]


def run_can_pass(decl, fixture: Fixture, work: Path) -> Verdict:
    """The gate must ACCEPT the known-good subject: rc 0, and nothing else."""
    subject = Path(fixture.module.can_pass(work))
    got = invoke(decl, subject)
    if got.rc == 0:
        return Verdict(True, "accepted the known-good subject (rc 0)", got)
    return Verdict(
        False,
        f"CAN-PASS fixture was REJECTED with rc {got.rc} — a gate that cannot "
        f"pass its own good input is not discriminating, it is stuck:\n"
        + _tail(got.output),
        got)


def run_can_fail(decl, fixture: Fixture, work: Path) -> Verdict:
    """The gate must REJECT the mutated subject, and say the expected thing."""
    subject, expected = fixture.module.can_fail(work)
    subject = Path(subject)
    got = invoke(decl, subject)
    if got.rc == 0:
        return Verdict(
            False,
            f"CAN-FAIL fixture was ACCEPTED (rc 0). The mutation this fixture "
            f"applies does not move the gate's verdict, so the gate's PASS over "
            f"a real tree is not evidence about it. Expected a refusal "
            f"mentioning {expected!r}. Output:\n" + _tail(got.output),
            got)
    if expected and expected not in got.output:
        return Verdict(
            False,
            f"CAN-FAIL fixture was rejected (rc {got.rc}) but NOT for the "
            f"declared reason: the refusal never says {expected!r}. A gate that "
            f"refuses for the wrong reason is a coincidence, not a check.\n"
            + _tail(got.output),
            got)
    return Verdict(True, f"rejected the mutation (rc {got.rc}) saying "
                         f"{expected!r}", got)


def run_pair(decl, fixture: Fixture) -> Tuple[Verdict, Verdict]:
    """Both directions, each in its OWN scratch tree.

    Separate trees on purpose: sharing one would let `can_fail`'s mutation
    reach `can_pass`, and the direction that then went green would be the one
    nobody checked.
    """
    with tempfile.TemporaryDirectory(prefix="gatefix-pass-") as a:
        p = run_can_pass(decl, fixture, Path(a))
    with tempfile.TemporaryDirectory(prefix="gatefix-fail-") as b:
        f = run_can_fail(decl, fixture, Path(b))
    return p, f


def _tail(text: str, n: int = 12) -> str:
    lines = [l for l in (text or "").splitlines() if l.strip()]
    return "\n".join("        " + l for l in lines[-n:]) or "        (no output)"


# --- the debt register ------------------------------------------------------
def load_debt(path: Optional[Path] = None) -> dict:
    p = path or DEBT_FILE
    if not p.is_file():
        return {"schema": 1, "entries": []}
    return json.loads(p.read_text())


def debt_labels(debt: dict) -> Dict[str, str]:
    """label -> why, for every gate the baseline still excuses."""
    return {e["gate"]: e.get("why", "") for e in debt.get("entries", [])}


# --- git, for fixtures that need a repo -------------------------------------
def git_init(root: Path) -> Path:
    """A committed one-commit repository at `root`. Fixtures share this.

    Many gates read `git ls-files` / `git cat-file`, so their subject is a
    REPOSITORY and not merely a directory. Written once here so a fixture
    cannot get the identity wrong in a way that makes a gate refuse for a
    reason the fixture did not intend.
    """
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init")
    _git(root, "config", "user.email", "fixture@vibe-ic.invalid")
    _git(root, "config", "user.name", "gate fixture")
    return root


def git_commit(root: Path, message: str = "fixture") -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "--no-gpg-sign", "-m", message)


def _git(root: Path, *args: str) -> None:
    env = dict(os.environ)
    env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null",
               GIT_TERMINAL_PROMPT="0")
    subprocess.run(("git", "-C", str(root)) + args, env=env, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
