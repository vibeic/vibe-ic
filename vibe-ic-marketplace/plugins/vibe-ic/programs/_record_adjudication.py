#!/usr/bin/env python3
"""Re-adjudicating a PUBLISHED gate record from the record alone (#510).

WHY THIS MODULE EXISTS
======================
A landed gate fix changes what the plugin will certify FROM NOW ON. It does
nothing to the records already committed, and until #510 nothing in the repo
measured that gap. So a corpus can indefinitely carry verdicts that the gate
which produced them would no longer issue, and a reader has no way to tell a
current record from a superseded one.

That is not hypothetical. ``si_mcf_sta_check`` stopped issuing ``PASS`` for a
run that re-derived zero coupling folds in v1.7.73 (#502). Two of the seven
tracked ``si_mcf_sta_check.json`` records still say ``PASS`` beside
``coupling_pairs: 0`` — including the exact artefact #502 was filed about.

RE-RUNNING IS NOT THE REMEDY, AND THAT CONSTRAINT SHAPES EVERYTHING HERE
-----------------------------------------------------------------------
Regenerating a published result is the benchmark-agent's job and must never
share a commit with a plugin fix (NO-MIX), and the original inputs are usually
gone anyway — the older records name absolute SPEF paths on an authoring
machine that no longer exists (#506). So the adjudication has to be decidable
from THE RECORD'S OWN FIELDS, on a host that holds none of the inputs. A rule
that needs to re-run the tool is not a rule this module can carry.

    ``coupling_pairs: 0`` beside ``verdict: PASS`` is decidable on paper.
    Whether some OTHER design's timing actually closed is not.

The second kind must therefore be reported as UNDECIDABLE rather than silently
skipped — a skipped record and a clean record must not look alike, which is the
same failure ``_gate_denominator`` exists for and why the consumer of this
module reports its denominator through that type.

HOW A RULE REGISTERS, AND WHY IT CANNOT BE A HAND-MAINTAINED LIST
=================================================================
A central list of "gates that have post-hoc rules" would go stale exactly the
way the records did — the failure mode this whole mechanism exists to catch. So
there is no list. Two things are derived instead:

  * WHICH GATES NEED RULES comes from the CORPUS. Every published record names
    its producer in its own ``program`` field, so the population of gates under
    audit is read off the records themselves. A gate that starts publishing
    records is covered the moment its first record lands, with nobody
    remembering to register it.

  * WHAT THE RULES ARE lives in the GATE'S OWN MODULE, under the module-level
    attribute named by ``DECLARATION_ATTR``. The person changing a gate's
    verdict logic is editing the same file that carries the declaration.

DRIFT IS CAUGHT TWO WAYS, and neither is a promise to remember
--------------------------------------------------------------
1. SHARED PRECEDENCE (structural, the strong one). A gate is expected to
   express its verdict precedence as ONE function that both the live run and
   the post-hoc adjudicator call. ``si_mcf_sta_check.verdict_for`` is that
   function: a change to the precedence reaches the adjudicator by
   construction, because there is no second copy to update.

2. DECISION FINGERPRINT (the backstop, for what cannot be shared). The
   declaration pins a sha256 over the AST of its gate's decision functions —
   the transitive, module-local call closure of the declared roots, with
   docstrings and comments removed so only executable logic counts. Land a new
   decision rule without re-reviewing the declaration and the fingerprint no
   longer matches: the consumer reports ``RULES_UNREVIEWED``, treats that
   gate's records as undecidable, and FAILS. Silence is not one of the
   outcomes.

   The fingerprint is deliberately NOT sensitive to a gate's INPUT-gathering
   code (``audit`` and friends). That code changes constantly for parsing
   reasons and pinning it would produce a gate that cries wolf until it is
   ignored. The soundness of a rule's precondition against real input is a
   BEHAVIOURAL claim, and it is pinned behaviourally — by running the gate on
   its shipped fixtures and requiring the adjudicator to agree with the verdict
   the gate actually emitted.

chip-AGNOSTIC: everything here is keyed on gate names and record field paths.
No design, PDK, vendor or SKU name appears in this module or can appear in a
rule, because a rule never sees anything but a record's own fields.
"""
from __future__ import annotations

import ast
import hashlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

#: The module-level attribute a gate assigns its ``GateRules`` to. Named once
#: here so the declaring gate and the discovering consumer agree by
#: construction rather than by re-typing the string.
DECLARATION_ATTR = "RECORD_ADJUDICATION"

#: Every record identifies its producer here; this is what makes the population
#: of gates under audit corpus-derived instead of hand-listed.
PROGRAM_KEY = "program"

#: The field every rule adjudicates, and therefore an implicit requirement of
#: every rule whether it lists it or not.
VERDICT_KEY = "verdict"


class _Missing:
    """Distinguishes "the record does not carry this field" from a stored
    ``None``. A rule that cannot tell those apart would silently adjudicate a
    null as a value."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "MISSING"

    def __bool__(self) -> bool:
        return False


MISSING = _Missing()


def read_field(record: Any, dotted: str) -> Any:
    """Value at ``dotted`` inside ``record``, or ``MISSING``.

    Dotted paths only, and only through dicts: a rule is meant to read fields a
    record carries, not to navigate arbitrary structure. Anything richer is a
    sign the claim is not decidable on paper.
    """
    cur = record
    for part in str(dotted).split("."):
        if not isinstance(cur, dict) or part not in cur:
            return MISSING
        cur = cur[part]
    return cur


def missing_fields(record: Any, required: Sequence[str]) -> List[str]:
    """Which of ``required`` the record does not carry — its undecidability."""
    return [p for p in required if read_field(record, p) is MISSING]


@dataclass(frozen=True)
class Supersession:
    """A published verdict the gate's current rules would no longer issue.

    ``would_issue`` is what the gate WOULD answer today, derived from the
    record's own fields. ``because`` is the sentence a reader gets: it must
    name the fields it read, since the whole claim is that no re-run was
    needed.
    """

    would_issue: str
    because: str

    def __post_init__(self) -> None:
        if not str(self.would_issue).strip():
            raise ValueError("Supersession.would_issue is required")
        if not str(self.because).strip():
            raise ValueError(
                "Supersession.because is required: a superseded verdict that "
                "does not say WHY is a second unreviewable claim, not a fix "
                "for the first (#510)")


@dataclass(frozen=True)
class Undecidable:
    """A rule ran, looked, and cannot answer — the third outcome.

    Field PRESENCE is checked by the framework, but presence is not
    readability: a record can carry ``findings`` that is a string, or a
    ``coupling_pairs`` that is a word. A rule handed that must be able to say
    so, because the alternative is returning None and having the record booked
    as adjudicated-and-clean, which is the shape #510 exists to abolish.
    """

    reason: str

    def __post_init__(self) -> None:
        if not str(self.reason).strip():
            raise ValueError(
                "Undecidable.reason is required: an undisclosed skip is the "
                "defect, not the report of one (#510)")


@dataclass
class Rule:
    """One post-hoc decision a gate can make about its own published records.

    ``requires`` is the contract that makes undecidability explicit: a record
    lacking any of these paths is reported UNDECIDABLE rather than quietly
    passed over. ``decide`` is only ever called once every path is present, so
    a rule body never needs a defensive read.
    """

    rule_id: str
    landed_in: str
    requires: Tuple[str, ...]
    decide: Callable[[Dict[str, Any]], Any]  # -> Supersession | Undecidable | None
    what: str = ""

    def __post_init__(self) -> None:
        if not str(self.rule_id).strip():
            raise ValueError("Rule.rule_id is required")
        if not str(self.landed_in).strip():
            raise ValueError(
                f"{self.rule_id}: Rule.landed_in is required — a rule with no "
                "provenance cannot be reviewed against the change that "
                "introduced it")
        if not callable(self.decide):
            raise ValueError(f"{self.rule_id}: Rule.decide must be callable")
        self.requires = tuple(
            dict.fromkeys((VERDICT_KEY,) + tuple(self.requires)))

    def applies_to(self, record: Dict[str, Any]) -> List[str]:
        """Empty list = every required field is present, so the rule can run."""
        return missing_fields(record, self.requires)


@dataclass
class GateRules:
    """Everything one gate declares about re-adjudicating its own records."""

    gate: str
    decision_roots: Tuple[str, ...]
    decision_digest: str
    rules: Tuple[Rule, ...]
    module_file: str = ""
    #: Set by ``declare`` so a declaration cannot claim to describe a module it
    #: does not live in.
    _source: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if not str(self.gate).strip():
            raise ValueError("GateRules.gate is required")
        if not self.decision_roots:
            raise ValueError(
                f"{self.gate}: decision_roots is required — with no root there "
                "is nothing to fingerprint and the declaration could not go "
                "stale loudly (#510)")
        if not self.rules:
            raise ValueError(
                f"{self.gate}: declaring zero rules is indistinguishable from "
                "not declaring at all; omit the attribute instead")
        seen = set()
        for r in self.rules:
            if r.rule_id in seen:
                raise ValueError(f"{self.gate}: duplicate rule_id {r.rule_id}")
            seen.add(r.rule_id)

    def current_digest(self) -> str:
        return decision_fingerprint(self._source, self.decision_roots)

    def drift(self) -> Optional[str]:
        """Prose naming the drift, or None when the declaration is current."""
        try:
            now = self.current_digest()
        except FingerprintError as exc:
            return (f"the declared decision root(s) {list(self.decision_roots)} "
                    f"could not be fingerprinted: {exc}")
        if now == self.decision_digest:
            return None
        return (f"the decision logic reachable from "
                f"{list(self.decision_roots)} has changed since these rules "
                f"were last reviewed (declared {self.decision_digest[:12]}, "
                f"now {now[:12]}). Re-review the rules against the new logic "
                f"and update decision_digest; until then this gate's published "
                f"records cannot be adjudicated.")


def declare(module_file: str, gate: str, decision_roots: Sequence[str],
            decision_digest: str, rules: Sequence[Rule]) -> GateRules:
    """Build a ``GateRules`` bound to the source file that declares it.

    Gates call this with ``__file__``: the fingerprint is then computed from
    the declaring module's own text, so a declaration can never be pointed at
    someone else's decision logic.
    """
    src = Path(module_file).read_text(errors="replace")
    return GateRules(gate=gate, decision_roots=tuple(decision_roots),
                     decision_digest=decision_digest, rules=tuple(rules),
                     module_file=str(module_file), _source=src)


class FingerprintError(Exception):
    """A decision root does not exist, or its module does not parse."""


def _without_docstring(node: ast.AST) -> ast.AST:
    """Drop a function's leading string expression, and nothing else.

    Applied ONLY to function definitions on purpose. Several gates hold prose
    in a module-level string constant that a rule may legitimately depend on
    (a written reason, a unit name); treating those as docstrings would make
    the fingerprint blind to an edit of the very text it is pinning.
    """
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return node
    body = list(node.body)
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        node.body = body[1:]
    return node


def _module_level_defs(tree: ast.Module) -> Dict[str, ast.AST]:
    """Module-level functions and simple constant assignments, by name.

    Constants are included because a verdict precedence can live in one — an
    exit code, a category set — and a fingerprint that only watched function
    bodies would miss a rule change made by editing a frozenset.
    """
    out: Dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = node
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                out[node.target.id] = node.value
    return out


def _referenced_names(node: ast.AST) -> List[str]:
    return [n.id for n in ast.walk(node) if isinstance(n, ast.Name)]


def _normalised_source(source: str, node: ast.AST) -> str:
    """The definition's OWN SOURCE TEXT, normalised with pure string operations.

    WHY NOT AN AST SERIALISATION — v1.7.74 and v1.7.75 each shipped one and CI
    rejected both. `ast.dump` serialises node FIELDS and CPython adds fields
    between releases (3.12 gave `FunctionDef` a `type_params`). `ast.unparse` is
    a code GENERATOR whose output CPython is equally free to change, and it did.
    Either way the digest measured the logic AND the interpreter while claiming
    to measure only the logic: a declaration stamped on 3.12 read as
    RULES_UNREVIEWED on CI's 3.11, its gate's records became undecidable, the
    recorded debt then looked paid, and the gate failed. Every one of those
    steps is a correct inference from a false premise.

    The repair is to stop asking the interpreter to re-emit anything. The AST is
    used ONLY to locate the definition — line numbers are a property of the
    file, not of the parser version — and the bytes hashed are the file's own.
    Nothing CPython changes between releases can reach them.

    Normalisation is pure text: drop blank and comment-only lines, rstrip the
    rest. That absorbs the reformatting a fingerprint should not care about
    without asking a parser to normalise anything. Re-wrapping a CODE line
    does move it, unlike before; blank and comment-only lines stay free. A
    slightly noisier fingerprint that works beats a quiet one that does not.
    """
    seg = ast.get_source_segment(source, node)
    if seg is None:  # pragma: no cover - needs a node built without positions
        raise FingerprintError(
            "no source segment for %s" % getattr(node, "name", "?"))
    kept = []
    for raw in seg.splitlines():
        line = raw.rstrip()
        bare = line.lstrip()
        if not bare or bare.startswith("#"):
            continue
        kept.append(line)
    return "\n".join(kept)


def decision_fingerprint(source: str, roots: Sequence[str]) -> str:
    """sha256 over the executable logic reachable from ``roots``.

    The closure is module-local and transitive: declaring the entry point is
    enough, so an author cannot under-declare the surface by forgetting a
    helper. Docstrings are removed and positions are excluded, so prose edits
    and reformatting do not trip it — only logic does.

    THE BOUNDARY IS DELIBERATE. Cross-module calls are not followed: a gate's
    shared helpers would drag in the transitive world and the fingerprint would
    change for reasons that have nothing to do with the gate. What is inside
    the boundary is the gate's own verdict logic, which is what a declaration
    claims to have reviewed.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:  # pragma: no cover - a broken gate fails earlier
        raise FingerprintError(f"module does not parse: {exc}") from exc
    defs = _module_level_defs(tree)
    missing = [r for r in roots if r not in defs]
    if missing:
        raise FingerprintError(
            f"decision root(s) not found at module level: {missing}")

    closure: Dict[str, ast.AST] = {}
    queue = list(roots)
    while queue:
        name = queue.pop()
        if name in closure:
            continue
        node = defs.get(name)
        if node is None:
            continue
        closure[name] = node
        queue.extend(n for n in _referenced_names(node)
                     if n in defs and n not in closure)

    h = hashlib.sha256()
    for name in sorted(closure):
        h.update(name.encode())
        h.update(b"\0")
        h.update(_normalised_source(source, closure[name]).encode())
        h.update(b"\n")
    return h.hexdigest()


# ── discovery ───────────────────────────────────────────────────────────────
#: Why a gate's declaration could not be obtained. Each value is reported as an
#: undecidability reason on every record that gate produced — never dropped.
LOAD_NO_MODULE = "GATE_MODULE_ABSENT"
LOAD_UNIMPORTABLE = "GATE_MODULE_UNIMPORTABLE"
LOAD_NO_DECLARATION = "NO_RULES_REGISTERED"
LOAD_BAD_DECLARATION = "GATE_DECLARATION_INVALID"


@dataclass
class GateLoad:
    """The outcome of asking one gate module for its rules."""

    gate: str
    rules: Optional[GateRules] = None
    reason: str = ""
    detail: str = ""


def _declares(path: Path) -> bool:
    """True when the module assigns ``DECLARATION_ATTR`` at module level.

    Checked by parsing, not importing: 28 of the 29 gates that publish records
    declare nothing, and importing all of them to find that out would run
    arbitrary module bodies for no answer.
    """
    try:
        tree = ast.parse(path.read_text(errors="replace"))
    except (OSError, SyntaxError):
        return False
    for node in tree.body:
        targets: List[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for t in targets:
            if isinstance(t, ast.Name) and t.id == DECLARATION_ATTR:
                return True
    return False


def _load_by_path(gate: str, path: Path, programs_dir: Path) -> ModuleType:
    """Execute ``path`` as a module, from the SOURCE ON DISK, every time.

    TWO CACHES ARE DELIBERATELY BYPASSED, and both would hand back the wrong
    version of the very thing this module compares:

    * ``importlib.import_module(gate)`` caches by BARE NAME, so a caller
      pointed at a different ``programs_dir`` — a reviewer probing a checkout,
      a test holding a deliberately-altered copy — gets whichever copy was
      imported first. The module name here is keyed to the resolved FILE.
    * ``__pycache__`` invalidates on (mtime-seconds, size). An edit that keeps
      the byte count and lands in the same second — replacing one digest with
      another is exactly that shape — leaves the stale bytecode valid, and the
      declaration read back would be the one from BEFORE the edit. Measured:
      it made a re-reviewed declaration keep reporting drift. So the source is
      read and compiled directly and no bytecode is consulted or written.

    ``programs_dir`` goes on ``sys.path`` only while the body executes, so the
    gate's sibling bare imports resolve without the entry outliving the call.
    """
    tag = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:12]
    mod_name = f"_vibeic_gate_{tag}_{gate}"
    code = compile(path.read_text(errors="replace"), str(path), "exec")
    mod = ModuleType(mod_name)
    mod.__file__ = str(path)
    added = str(programs_dir) not in sys.path
    if added:
        sys.path.insert(0, str(programs_dir))
    sys.modules[mod_name] = mod
    try:
        exec(code, mod.__dict__)  # noqa: S102 - loading a program in this tree
    except BaseException:
        sys.modules.pop(mod_name, None)
        raise
    finally:
        if added and str(programs_dir) in sys.path:
            sys.path.remove(str(programs_dir))
    return mod


def load_gate(gate: str, programs_dir: Path) -> GateLoad:
    """Ask one gate module for its ``GateRules``, disclosing every failure."""
    path = programs_dir / f"{gate}.py"
    if not path.is_file():
        return GateLoad(gate, reason=LOAD_NO_MODULE,
                        detail=f"no {gate}.py under {programs_dir}; the "
                               f"producer of these records is not (or is no "
                               f"longer) a program in this tree")
    if not _declares(path):
        return GateLoad(gate, reason=LOAD_NO_DECLARATION,
                        detail=f"{gate}.py declares no {DECLARATION_ATTR}, so "
                               f"nothing is known about which of its published "
                               f"verdicts its current rules would still issue")
    try:
        mod = _load_by_path(gate, path, programs_dir)
    except Exception as exc:  # noqa: BLE001 - any import failure is disclosed
        return GateLoad(gate, reason=LOAD_UNIMPORTABLE,
                        detail=f"{gate}.py declares {DECLARATION_ATTR} but "
                               f"could not be imported: {exc!r}")
    decl = getattr(mod, DECLARATION_ATTR, None)
    if not isinstance(decl, GateRules):
        return GateLoad(gate, reason=LOAD_BAD_DECLARATION,
                        detail=f"{gate}.{DECLARATION_ATTR} is "
                               f"{type(decl).__name__}, expected GateRules")
    if decl.gate != gate:
        return GateLoad(gate, reason=LOAD_BAD_DECLARATION,
                        detail=f"{gate}.{DECLARATION_ATTR}.gate is "
                               f"{decl.gate!r}, which is not the program that "
                               f"wrote these records")
    return GateLoad(gate, rules=decl)
