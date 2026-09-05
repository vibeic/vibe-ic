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
    $RUNTIME_ROOT     -> the REAL repo root             (the gate's own code)
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

#: The RUNTIME checkout the dispatcher computes at its line 29, and the root
#: `$PG` is itself spelled relative to (`$RUNTIME_ROOT/.../programs`). A gate
#: whose executable lives outside `programs/` -- `vibe-ic-marketplace/tools/`
#: -- can only name it through this variable, so it resolves the same way
#: `$PG` does: to the gate's OWN code, never to the fixture subject.
_REAL_RUNTIME_ROOT = str(REPO_ROOT)


def _synthetic_nda_tokens() -> str:
    """A complete private-token panel whose values exist only in fixture runs.

    `source_chip_agnostic_check` correctly refuses when the host has no private
    NDA-token store.  That host state is not part of a fixture's subject, and
    letting it reach the subprocess makes both the direct source-guard pair and
    the plugin-self-audit pair stop before their mutations are judged.

    Derive the public role set from the gate's own provider, then replace every
    value.  Filling every role prevents a real private config from supplying a
    residual value and making this supposedly synthetic run host-dependent.
    """
    if str(PROGRAMS) not in sys.path:
        sys.path.insert(0, str(PROGRAMS))
    import _commercial_pdk as commercial_pdk  # noqa: E402
    return json.dumps({
        role: f"gate_fixture_private_value_{index}_{role}"
        for index, role in enumerate(commercial_pdk.NDA_ROLES)
    }, sort_keys=True)


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


class SubjectPathNotDeclared(LookupError):
    """This row does not name a `$ROOT`-anchored path ending in that tail.

    RAISED, NEVER DEFAULTED. A fixture that silently fell back to a guess would
    build its subject somewhere the gate does not look, and the gate would then
    answer rc 2 about an absent corpus instead of rc 0/1 about the record — a
    fixture pair that has stopped discriminating while still executing. That is
    exactly the state this helper exists to end, so the failure is loud.
    """


def declared_subject_path(gate: str, tail: str,
                          script: Optional[Path] = None) -> str:
    """The repo-relative path THIS ROW passes, ending in `tail`.

    WHY A FIXTURE MAY NOT SPELL ITS OWN CORPUS PATH (vibe-ic#2019 fallout)
    =====================================================================
    Eleven PPA fixtures each carried a literal — `CORPUS = "ppa-crosslayer"`,
    `_REL = "ppa-crosslayer/records/trials/z23/candidates.json"` — that had to
    stay equal to the `--corpus` argument on its row in
    `repo_hygiene_gates.sh`. When the campaign trees moved to
    `docs/campaigns/`, the rows moved and the eleven literals did not.

    MEASURED at 85338ac71308102dd957f95f4d12cd5290a02943, before this change::

        $ python3 -m pytest tools/ci/test_gate_fixtures_discriminate.py -q
        11 failed, 77 passed

        PPA ablation records (within-project): CAN-PASS fixture was REJECTED
        with rc 2 — a gate that cannot pass its own good input is not
        discriminating, it is stuck:
          [ppa_ablation_check] UNDETERMINED: no corpus at
          /tmp/gatefix-pass-…/subject_pass/docs/campaigns/ppa-crosslayer

    Every one of the eleven failed for that one reason: the subject was built
    at `ppa-crosslayer/…` and the gate was pointed at
    `docs/campaigns/ppa-crosslayer`. Note what the reds are NOT — not one of
    them is a gate that stopped refusing bad input. They are eleven gates whose
    good input had become unreachable, which is the quieter half: a fixture
    pair can go dark without a single check becoming permissive.

    THE REPAIR IS NOT ELEVEN NEW LITERALS. Re-typing `docs/campaigns/` in
    eleven files reproduces the defect one directory over and buys one more
    move before it happens again. `test_gate_fixtures_discriminate`'s own
    docstring already states the rule — "The gate is driven EXACTLY as
    `repo_hygiene_gates.sh` declares it" — and the declaration is already
    parsed here. So the fixture ASKS the row where its subject goes, and the
    two cannot disagree because there is only one of them.

    `tail` is the part the fixture owns and the row ends with: the campaign
    directory name, or the record path beneath it. The match is on a path
    COMPONENT boundary, so `ppa-e2e` never matches a row naming
    `ppa-e2e-secondary`.

    Returns the path WITHOUT the `$ROOT/` prefix, because a fixture builds its
    subject at its own scratch root and never at this repository's.
    """
    tail = tail.strip("/")
    for decl in declarations(script):
        if decl.label != gate:
            continue
        for token in shlex.split(decl.cmd):
            if not token.startswith("$ROOT/"):
                continue
            rel = token[len("$ROOT/"):]
            if rel == tail or rel.endswith("/" + tail):
                return rel
        raise SubjectPathNotDeclared(
            f"the row {gate!r} declares no $ROOT-anchored path ending in "
            f"{tail!r}; its command is {decl.cmd!r}. A fixture must build its "
            f"subject where its own row looks, so this is not something to "
            f"guess around.")
    raise SubjectPathNotDeclared(
        f"no gate labelled {gate!r} is declared in {script or HYGIENE_SCRIPT}")


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
        # Resolved BEFORE $ROOT so the two variables stay independent.
        tok = (tok.replace("${RUNTIME_ROOT}", _REAL_RUNTIME_ROOT)
                  .replace("$RUNTIME_ROOT", _REAL_RUNTIME_ROOT))
        tok = (tok.replace("${ROOT}", str(subject)).replace("$ROOT", str(subject))
                  .replace("${PLUGIN}", str(subject)).replace("$PLUGIN", str(subject)))
        out.append(tok)
    return out


def unresolved_shell(cmd: str) -> Optional[str]:
    """The piece of this command no fixture can drive as written, or None."""
    if "$(" in cmd:
        return "a command substitution: " + cmd[cmd.index("$("):][:60]
    for m in re.finditer(r'\$\{?([A-Za-z_]\w*)\}?', cmd):
        if m.group(1) not in ("ROOT", "PLUGIN", "PG", "PJSON", "RUNTIME_ROOT"):
            return f"the shell variable ${m.group(1)}, bound by the enclosing loop"
    return None


def invoke(decl, subject: Path, timeout: int = 180) -> Outcome:
    """Run the gate EXACTLY as declared, with `subject` as its input tree."""
    argv = _resolve_argv(decl.cmd, subject)
    env = dict(os.environ)
    env["VIBEIC_SUBJECT_ROOT"] = str(subject)
    # The gate's refusal on an unavailable private token store is load-bearing:
    # an empty detector must never report PASS.  A two-arm fixture nevertheless
    # has to present the private INPUT so both arms reach the behavior they are
    # meant to distinguish.  Override rather than inherit: the operator's real
    # token values must neither decide this test nor enter its child process.
    env["VIBEIC_NDA_TOKENS"] = _synthetic_nda_tokens()
    env.pop("GATEKEEPER_HYGIENE_JOBS", None)
    # THE SUBJECT IS `subject`, AND THE AMBIENT CORPUS BINDING IS NOT IT. A
    # landing exports BOTH `VIBE_IC_BENCHMARK_DATA` and its attested
    # `GATEKEEPER_BENCHMARK_DATA_SHA`. A corpus gate reads that pair in
    # preference to the `--subdir`/`--root` it was handed. In a fixture arm
    # retaining the pointer makes the gate answer about the operator's corpus;
    # clearing only the pointer leaves a half-binding that `_corpus_location`
    # correctly refuses as UNDETERMINED. Drop the pair together in the child.
    # MEASURED on d2b8a9d13d in the pinned image: with the variable set,
    # `test_fixture_pair_discriminates` is 1 failed / 81 passed
    # (tracked_symlink_target_present, "CAN-FAIL fixture was ACCEPTED (rc 0)",
    # its own output carrying "note: VIBE_IC_BENCHMARK_DATA overrides --subdir
    # benchmark-data -> ..."); with it unset, 82 passed.
    env.pop("VIBE_IC_BENCHMARK_DATA", None)
    env.pop("GATEKEEPER_BENCHMARK_DATA_SHA", None)
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
