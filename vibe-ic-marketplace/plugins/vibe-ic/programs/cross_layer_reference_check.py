#!/usr/bin/env python3
"""cross_layer_reference_check.py — ONE general gate over cross-layer ids.

ENFORCEMENT: advisory
VERDICT MODE: **ADVISES**. Measured, and the promotion condition is stated
below rather than left to the next reader's judgement. See ENFORCEMENT.

THE DEFECT CLASS (vibe-ic#376)
==============================
    A value is present in the layer that PRODUCES it, and unreachable by
    the layer that CONSUMES it — while both layers individually pass.

Hand-written ``*_consistency_check.py`` gates each cover one slice of this,
and each was written after someone was bitten once. This program is the
first general mechanism: a *reference* is declared as DATA in
``cross_layer_references.json``, and one resolver judges every declared
reference the same way.

HOW MANY OF THOSE GATES THIS SUBSUMES — MEASURED, AND THE ANSWER IS ZERO
------------------------------------------------------------------------
The issue's headline calls 23 pairwise gates the symptom of this missing
mechanism. Re-counted on the tree: **25** files match
``*consistency_check.py``. Counting the layer documents each one addresses
— string constants under AST, so a layer code inside a prose comment is not
counted — gives

    addresses 0 layers : 13     addresses 2 : 5     addresses  5 : 2
    addresses 1 layer  :  3     addresses 4 : 1     addresses 11 : 1

so **9 of 25** relate two or more layers at all. Of those 9, four read the
RTL as one of their two sides (they walk ``*.v``/``*.sv``), which is a
layer-to-ARTEFACT relation no resolver over layer documents can express.
The remaining **5** have both sides in the L-doc corpus, and the relations
they assert are set MEMBERSHIP (names on one side must appear on the
other), scalar EQUALITY (two layers each state the same value), and
DERIVATION (one value is a function of others). **None is a REFERENCE**,
so this mechanism subsumes 0 of the 25 and none is retired. That is not a
scoping decision to be revisited with more effort; it is what the relations
are.

The distinction that makes a general mechanism possible for references is
the same one that stops it absorbing the others. An equality needs a
per-pair canonicaliser (a polynomial written three ways, a frequency in MHz
vs Hz); a membership needs the pair's own alias and escape-valve rules —
the shipped pin-to-port membership relation carries 4 alias fields
(``name``/``rtl_name``/``board_name``/``aliases[]``) and 5
``no_<field>_in_input`` escape flags, none of which generalise to any other
pair. Both are code. A reference needs a GRAMMAR for the address and a
SCOPE for the namespace, and both are data.

And the mechanism cannot grow by data alone on this corpus. Every string in
every collection of every L-doc across the 106 tracked cells was tested
against the one shipped grammar: outside ``width_symbolic`` itself, every
symbolic-range-shaped hit is prose — a standards citation, an FSM state
name, a package-qualified type. There is no second reference to declare.
A second row therefore waits on a second grammar, which is code, and that
cost is the mechanism's honest boundary rather than a gap in the manifest.

WHAT A REFERENCE IS, AND WHY IT IS NOT AN EQUALITY
--------------------------------------------------
Almost every existing pairwise gate asserts an EQUALITY (two layers each
state the same value; they must agree) or a MEMBERSHIP (element names on
one side must appear on the other). A REFERENCE is a third thing: one
side's value *names* an element that lives on the other side. It is a
pointer, not a copy. Nothing can compare two copies here, because there
is only one copy — the other side holds an address.

That distinction is the whole reason a general mechanism is possible at
all. An equality needs a per-pair canonicaliser (a CRC poly written three
ways, a frequency in MHz vs Hz), which is code. A reference needs only a
GRAMMAR for the address and a SCOPE for the namespace, and both of those
are data.

THE ID SCHEME
-------------
    L<layer>:<kind>:<name>          e.g. L9:port:acc_o, L8:parameter:ACC_W

Keyed on the element's own identity field, never on its array index — an
index moves when an emitter re-orders and the reference then silently
addresses a different element.

THE THREE LEGS
--------------
For each declared reference row, for each producer element that carries a
non-empty reference field:

  1. PARSE   the reference value under the row's grammar, yielding the set
             of identifiers it addresses.
  2. RESOLVE each identifier to an id inside the row's declared
             ``target.scope_layers``, and evaluate the row's value.
  3. OBSERVE what the CONSUMING derivation produces for the same element,
             and compare.

Leg 3 is what separates this from the layer gates that already exist. A
layer gate can only ask whether a layer's own content is well formed. Both
layers here ARE well formed — that is the premise of the defect class. The
disagreement is only visible from the consuming side, so the gate runs that
derivation's real code (imported, not reimplemented) and diffs the result.

WHAT "CONSUMER" MEANS HERE (#509). The one registered adapter drives
``phase2_scaffold_gen.derive_signals``, which is a CONTRACT ORACLE and not a
flow step: no runner and no step of ``flow/phase1_phase2_phase3.yaml`` calls
it, at any version. So a finding on leg 3 says the reference is unreachable
by the derivation a conforming phase 2 owes — not that some running program
read a wrong number. That is the stronger claim of the two, because it holds
for every phase 2 that satisfies the contract.

SCOPE IS LOAD-BEARING — READ THIS BEFORE ADDING A ROW
------------------------------------------------------
``skills/layer-contract-doctrine/SKILL.md`` §7 records the measurement that
killed the first attempt at this join:

    "The L-doc corpus declares ``parameters[]`` under many layers with no
     module or layer qualifier, so a corpus-global join by bare name lets
     an unrelated layer size another layer's bus. Reproduced with an L12
     DFT plan declaring ``N = 4`` (a scan-chain count) and an L1 port
     ``width_symbolic: "N-1:0"``: the port was written 4 bits wide and the
     gate went green."

So every row must NAME the layers whose namespace legitimately scopes its
identifiers. An identifier that resolves only OUTSIDE that set produces
``OUT_OF_SCOPE_REFERENCE`` — the join is refused and reported, never used.
That is the difference between a mechanism that can be extended safely and
one that quietly invents values. It is covered by a test that reproduces
§7's exact fixture.

WHY THIS GATE IS NOT THE REPAIR, AND DOES NOT PRETEND TO BE
------------------------------------------------------------
The same doctrine says a join that nobody performed is Bucket A — write
the resolver — and that "a gate is never the answer". Correct, and this
gate is not offered as one. The resolver for the shipped row is still open
by an explicit owner decision recorded in §6.

What was missing was different: on the corpus this gate ships against, the
one-off gate for that exact defect (``l1_pin_bus_width_actionable_check``)
returns **PASS**, because it resolves the symbolic width from the design's
own INPUT files and finds the parameter there. The value really is
resolvable. Nothing anywhere asked the next question — whether the CONSUMER
gets it — and the answer is no. A defect that every gate reports clean is
worse than one that fails loudly, and that is the hole this fills.

It also satisfies §7's acceptance condition for a future repair: this gate
reads the CONSUMER's derived value and the TARGET layer's parameter table.
A resolver that writes ``L1.pin_table[].width`` — the field the one-off gate
reads — cannot turn this gate green by writing a wrong value, because the
wrong value would then disagree with the parameter table. The verifier is
independently derived from a source the repair does not touch.

ENFORCEMENT — WHY ADVISORY, AND WHAT WOULD PROMOTE IT
------------------------------------------------------
Measured over the PUBLISHED cells under ``benchmark-data/ic/`` before this
was wired anywhere: 3 cells FAIL (all three are the SAME producer-side
defect on the same design family), the rest return VACUOUS_PASS because they
declare no symbolic reference at all. "Published" means git-TRACKED, and
that qualifier is load-bearing rather than pedantic — see ``corpus_cells``:
counting what is on disk gives 46 L1 documents in a working checkout and 23
in a worktree, which would make this gate's baseline depend on whether the
person running it had ever run the flow locally. Every one of the 3 is a true finding,
and the repair for it is deliberately open. Wired BLOCKING, this would fail
100% of runs on that family for a defect nobody is allowed to fix yet —
which, measured across this repo, is how a gate gets turned off within a
week (the same argument, with the same shape of measurement, is recorded in
``l17_channel_catalog_consumer_contract_check``).

  PROMOTION CONDITION, stated so it needs no judgement call: flip the
  ``ENFORCEMENT``/``verdict_mode`` declaration and move the flow entry from
  ``advisory_program_exit_zero`` to ``program_exit_zero`` when a corpus
  re-measurement (``--corpus benchmark-data/ic``) returns 0
  ``CONSUMER_CANNOT_REACH`` findings. Argue it from that re-measurement,
  not from this docstring.

The advisory declaration is about which SLOT the flow may wire it in. The
process still exits 1 on a finding, and ``--corpus`` mode below is
BLOCKING in CI.

TWO MODES
---------
  PROJECT  ``cross_layer_reference_check.py <project_dir>``
           The per-design verdict. Wired into the flow's phase-1 advisory
           gate block.

  CORPUS   ``cross_layer_reference_check.py --corpus <dir>``
           Regression over every published cell, compared against
           ``cross_layer_reference_baseline.json``. A NEW break — a finding
           code this row has never produced, or MORE occurrences of one it
           has — exits 1. This is the mode wired into
           ``tools/ci/repo_hygiene_gates.sh``, and it is what stops the
           repo growing a 24th instance of the class silently.

           The baseline records ``row id -> {finding code: count}`` and
           deliberately NOT which cell produced it: published cell paths
           carry design and PDK names, and this file lives under
           ``programs/`` where ``source_chip_agnostic_check`` scans .json.
           The cost is that a defect MOVING between cells keeps the count
           and does not fire; the cell identity is in the ``--json`` report
           on every run, which is where a reader who needs it should look.

           It also records ``examined`` — the DENOMINATOR those counts were
           measured over. A findings count on its own cannot say whether the
           sweep still reaches what it reached, and for a while this one did
           not: renaming the producer's reference field, renaming its
           collection, or moving its layer each took the sweep from 9
           records to 0 and printed ``~ improved: ... 3 -> 0`` before exiting
           0. See ``compare_denominator``.

WHERE THE CORPUS IS, NOW THAT IT IS NOT HERE (vibe-ic#1710's treatment)
-----------------------------------------------------------------------
``tools/ci/repo_hygiene_gates.sh`` sweeps ``--corpus "$ROOT/benchmark-data/ic"``.
v1.10.56 moved the published corpus into its own repository, so that directory
is gone from this repo and the gate answered

    [SKIP] corpus not found: <repo>/benchmark-data/ic                    rc 2

That refusal was CORRECT for what it was asked — a sweep that found no corpus
has judged nothing — and ``run`` in ``_gate_dispatch.sh`` maps rc 2 to FAIL, so
it blocked every landing. What was wrong is WHERE it was told to look.
``_corpus_location`` resolves it now, the override is ANNOUNCED, and the four
outcomes stay distinct (see that module).

AND THE REGISTER IS NOT EXCUSED WITH THE SWEEP
----------------------------------------------
``cross_layer_reference_baseline.json`` is this gate's own debt register and it
lives in THIS repository — it did not move with the corpus. Its header says a
findings count may SHRINK freely and any INCREASE fails CI, so widening the
register is the cheapest way to make a real break stop being NEW.

That is why ``repo_hygiene_gates.sh`` withdrew this gate's ``gate_scope`` in
v1.10.55: a scope naming ``benchmark-data/ic/`` excludes the checker's own body
and its own register, so a commit that only widens the register touches nothing
in scope and the one gate guarding it does not run.

A NO_CORPUS that returned rc 0 without opening the register would reintroduce
exactly that hole through the other door. So under NO_CORPUS the SWEEP is
excused and the REGISTER IS STILL ADJUDICATED:

    register absent / unparseable / malformed  -> UNDETERMINED (rc 2)
    register carries no `seal`                 -> UNDETERMINED (rc 2): without a
                                                  corpus the seal is the ONLY
                                                  evidence the numbers are the
                                                  ones a sweep measured
    `seal` does not match the numbers beside it -> FAIL (rc 1): the register was
                                                  edited after it was written
    seal verifies                              -> rc 0, printing what it holds
                                                  and stating the counts were
                                                  NOT re-measured

``--write-baseline`` is the only thing that writes a seal, and it REFUSES a
sweep that reached no cell (the vibe-ic#1025 shape, which this program still
carried: a write over an empty corpus recorded ``{}`` and destroyed the
register while reporting success). So re-sealing a widened register requires a
corpus that actually reaches, which is what makes the numbers a measurement.

DEGRADE LOUDLY
--------------
A layer file that EXISTS and does not parse is exit 2, never a quiet pass.
A producer layer that is simply ABSENT is not an error — no design carries
all 27 layers — but if a reference then resolves nowhere it is reported as
``DANGLING_REFERENCE`` with the layers that were searched, so "absent" can
never be read as "clean".

chip-AGNOSTIC: this file and its manifest name layer codes, JSON field
names and a bit-range grammar. No design, vendor, PDK or part number
appears in either.

EXIT CODES
----------
    0 = PASS — the design's layers carry declared references and they resolve
    1 = FAIL — a finding, or a corpus sweep that LOST REACH
    2 = NOT CHECKED — SKIP, an I/O error, a corpus sweep that found no cell
        at all, a baseline carrying no denominator to compare against, or
        VACUOUS_PASS (per-project mode): the layers carry no declared
        cross-layer reference, so nothing was examined

    #528 — the VACUOUS_PASS line used to exit 0. Two branches above it (SKIP,
    ERROR) already exited 2 for the same "nothing to examine" situation, and
    the printed token was `[VACUOUS_PASS]`, which
    `flow_compliance_check._stdout_signals_vacuous` does not match (it wants
    the token at line start, unbracketed). So neither channel the tier-deciding
    consumer reads was live, and a design carrying no declared reference at all
    was credited a plain PASS. The `--corpus` regression mode returns before
    this branch and is UNCHANGED — that is the mode
    `tools/ci/repo_hygiene_gates.sh` runs through its `run` helper, which
    treats any non-zero rc as a hard FAILED.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys

import _corpus_location as _cloc
import _published_tree
import _vacuous_exit as _vx
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import l_doc_consumer_contract as _ldc  # noqa: E402

GATE = "cross_layer_reference_check"
WAIVER_KEY = "cross_layer_reference_unresolved"
WAIVER_MIN_LEN = 40
MANIFEST_NAME = "cross_layer_references.json"
BASELINE_NAME = "cross_layer_reference_baseline.json"

# Finding codes. Ordered from "the reference is broken in the layer set"
# to "the reference is fine and the consumer cannot see it".
UNPARSEABLE = "UNPARSEABLE_REFERENCE"
DANGLING = "DANGLING_REFERENCE"
OUT_OF_SCOPE = "OUT_OF_SCOPE_REFERENCE"
UNUSABLE_TARGET = "UNUSABLE_TARGET_VALUE"
CONSUMER_BLIND = "CONSUMER_CANNOT_REACH"

# The four states are kept APART on purpose. The gate this mechanism most
# overlaps (l17_channel_catalog_consumer_contract_check) emits one
# byte-identical finding for all of them — measured — and which one it is
# decides which layer an author repairs: the extractor, the producing layer,
# the scope declaration, or the consumer.
_FINDING_CODES = (UNPARSEABLE, DANGLING, OUT_OF_SCOPE, UNUSABLE_TARGET,
                  CONSUMER_BLIND)

# Grammars this resolver implements. A row naming anything else is a manifest
# error at LOAD, never a per-element finding: an unknown grammar means the
# gate cannot judge that row at all, and reporting it once per element would
# dress a configuration mistake up as a design defect.
_GRAMMARS = frozenset({"symbolic_range"})

# One identifier with an optional integer offset: `size-1`, `W`, `N+1`.
# Deliberately not an expression evaluator — one identifier plus an offset
# covers the port-declaration grammar, and anything richer is left
# UNRESOLVED rather than guessed. (The same restraint, and the same shape
# of pattern, is used by l1_pin_bus_width_actionable_check over the design's
# INPUT files; this one resolves over LAYERS, which is a different source,
# so the two are not a duplicated join.)
_TERM_RE = re.compile(r"^\s*`?([A-Za-z_]\w*)`?\s*(?:([+-])\s*(\d+)\s*)?$")
_INT_RE = re.compile(r"^\s*`?(\d+)`?\s*$")


# ─────────────────────────────────────────────────────────────────────
# Manifest
# ─────────────────────────────────────────────────────────────────────

class ManifestError(RuntimeError):
    pass


def load_manifest(path: Optional[Path] = None) -> List[dict]:
    """Parse the reference manifest. A malformed manifest is fatal — a
    reference table that silently reads as empty is a gate that judges
    nothing while reporting clean."""
    p = path or (_HERE / MANIFEST_NAME)
    if not p.is_file():
        raise ManifestError(f"manifest not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ManifestError(f"manifest unparseable: {p}: {exc}") from exc
    rows = data.get("references")
    if not isinstance(rows, list) or not rows:
        raise ManifestError(f"manifest declares no references: {p}")
    for row in rows:
        for key in ("id", "grammar", "producer", "target"):
            if key not in row:
                raise ManifestError(
                    f"manifest row missing '{key}': {row.get('id', row)!r}")
        if not row["target"].get("scope_layers"):
            # §7: a row with no declared scope is a corpus-global join by
            # bare identifier, which is the thing that was measured wrong.
            raise ManifestError(
                f"row {row['id']!r} declares no target.scope_layers")
        if row["grammar"] not in _GRAMMARS:
            raise ManifestError(
                f"row {row['id']!r} names grammar {row['grammar']!r}; "
                f"this resolver implements {sorted(_GRAMMARS)}")
        cons = row.get("consumer") or {}
        if cons.get("adapter") and cons["adapter"] not in CONSUMER_ADAPTERS:
            raise ManifestError(
                f"row {row['id']!r} names consumer adapter "
                f"{cons['adapter']!r}, which is not registered")
    return rows


# ─────────────────────────────────────────────────────────────────────
# Layer access + id index
# ─────────────────────────────────────────────────────────────────────

class LayerLoadError(RuntimeError):
    pass


def load_layers(project: Path) -> Dict[str, List[Tuple[Path, dict]]]:
    """code -> [(path, payload)] for every L-doc in the project.

    ALL files sharing a code are returned, not the first: L8 is emitted as
    both L8_RTL_CONSTANTS.json and L8_TIMING_WAVEFORM.json, and taking one
    of them would make the parameter namespace depend on filename sort
    order.

    A file that exists and does not parse raises — see DEGRADE LOUDLY.
    """
    gd = _ldc.generated_docs_dir(project)
    out: Dict[str, List[Tuple[Path, dict]]] = {}
    if not gd.is_dir():
        return out
    for hit in sorted(gd.glob("L*.json")):
        m = re.match(r"^(L\d+)_", hit.name)
        if not m:
            continue
        try:
            payload = json.loads(hit.read_text(encoding="utf-8",
                                               errors="ignore"))
        except Exception as exc:  # noqa: BLE001
            raise LayerLoadError(f"{hit.name}: {exc}") from exc
        if isinstance(payload, dict):
            out.setdefault(m.group(1), []).append(
                (hit, _ldc.l_doc_fields(payload)))
    return out


def element_id(layer: str, kind: str, name: str) -> str:
    return f"{layer}:{kind}:{name}"


def index_elements(layers: Dict[str, List[Tuple[Path, dict]]],
                   codes: Iterable[str],
                   collections: Iterable[str],
                   kind: str,
                   key_field: str) -> Dict[str, List[dict]]:
    """id -> [element, ...] over the requested layers/collections.

    A list, not a scalar: the same name can be declared in more than one
    layer (phase1 promotes one parameter extraction into both L8 and L9),
    and collapsing that would hide a genuine disagreement between two
    declarations of the same id.
    """
    idx: Dict[str, List[dict]] = {}
    codes = list(codes)
    collections = list(collections)
    for code in codes:
        for path, payload in layers.get(code, []):
            for coll in collections:
                val = payload.get(coll)
                if not isinstance(val, list):
                    continue
                for el in val:
                    if not isinstance(el, dict):
                        continue
                    name = el.get(key_field)
                    if not isinstance(name, str) or not name.strip():
                        continue
                    rec = dict(el)
                    rec["__layer"] = code
                    rec["__file"] = path.name
                    rec["__collection"] = coll
                    idx.setdefault(
                        element_id(code, kind, name.strip()), []).append(rec)
    return idx


def _index_by_name(idx: Dict[str, List[dict]]) -> Dict[str, List[dict]]:
    """Collapse `L<n>:<kind>:<name>` -> `<name>` for scope-membership tests."""
    out: Dict[str, List[dict]] = {}
    for eid, recs in idx.items():
        out.setdefault(eid.rsplit(":", 1)[-1], []).extend(recs)
    return out


# ─────────────────────────────────────────────────────────────────────
# Grammars — how a reference VALUE names ids
# ─────────────────────────────────────────────────────────────────────

def parse_symbolic_range(value: Any) -> Optional[Tuple[str, str]]:
    """`"size-1:0"` / `"[ACC_W-1:0]"` -> ("size-1", "0"). None if not a range."""
    if not isinstance(value, str) or ":" not in value:
        return None
    hi, _, lo = value.strip().strip("[]").partition(":")
    if not hi.strip() or not lo.strip():
        return None
    return hi, lo


def term_identifier(term: str) -> Optional[str]:
    """The free identifier a range term names, or None for a literal."""
    if _INT_RE.match(term):
        return None
    m = _TERM_RE.match(term)
    return m.group(1) if m else None


def eval_term(term: str, env: Dict[str, int]) -> Optional[int]:
    m = _INT_RE.match(term)
    if m:
        return int(m.group(1))
    m = _TERM_RE.match(term)
    if not m:
        return None
    base = env.get(m.group(1))
    if base is None:
        return None
    if m.group(2):
        off = int(m.group(3))
        return base + off if m.group(2) == "+" else base - off
    return base


def target_int(value: Any) -> Optional[int]:
    """A declared default usable as a NUMBER, or None.

    Strict on purpose. The corpus carries defaults like ``"**8**"`` (markdown
    bold survived extraction) and ``"1(...prose...)"``. Digging a number out
    of those would be guessing which number the design meant, and a
    mechanism that guesses is the one nobody can trust to extend.
    ``UNUSABLE_TARGET_VALUE`` says so instead.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and _INT_RE.match(value):
        return int(_INT_RE.match(value).group(1))
    return None


# ─────────────────────────────────────────────────────────────────────
# Consumer adapters — leg 3
# ─────────────────────────────────────────────────────────────────────
# An adapter runs the CONSUMER's own code and returns
# {element key: {value_name: observed}}. It is code and not data on
# purpose: a consumer IS code, and pretending its call shape is data would
# mean shipping an eval() over a JSON file. Adding a reference row over an
# ALREADY-ADAPTED consumer is a pure data edit; a new consumer costs one
# adapter of roughly this size, and that cost is the mechanism's honest
# boundary.

def _adapter_scaffold_derive_signals(
        project: Path, layers: Dict[str, List[Tuple[Path, dict]]]
) -> Optional[Dict[str, Dict[str, Any]]]:
    """`phase2_scaffold_gen.derive_signals(L17, L9)` -> {port: {"width": n}}.

    This is the derivation that DEFINES the top-module port list a conforming
    phase 2 owes. `phase2_scaffold_gen` is a CONTRACT ORACLE and not a flow
    step — no runner and no step of `flow/phase1_phase2_phase3.yaml` calls it,
    at any version (#509) — so leg 3 below observes what that specification
    produces, never what a running phase 2 produced. That is what makes the
    disagreement it reports meaningful: the reference is unreachable BY THE
    CONTRACT, which every conforming phase 2 must satisfy.

    Returns None when the oracle cannot be imported, which is reported
    rather than silently treated as agreement.
    """
    src = _HERE / "phase2_scaffold_gen.py"
    if not src.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location(
            "_clr_phase2_scaffold_gen", src)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception:  # noqa: BLE001
        return None
    l9 = layers.get("L9", [(None, {})])[0][1]
    l17 = layers.get("L17", [(None, {})])[0][1]
    try:
        signals = mod.derive_signals(l17, l9)
    except Exception:  # noqa: BLE001
        return None
    out: Dict[str, Dict[str, Any]] = {}
    for sig in signals or []:
        if isinstance(sig, dict) and isinstance(sig.get("name"), str):
            out[sig["name"]] = {"width": sig.get("width")}
    return out


CONSUMER_ADAPTERS = {
    "phase2_scaffold_gen.derive_signals": _adapter_scaffold_derive_signals,
}


# ─────────────────────────────────────────────────────────────────────
# The resolver
# ─────────────────────────────────────────────────────────────────────

def evaluate_row(row: dict,
                 project: Path,
                 layers: Dict[str, List[Tuple[Path, dict]]]
                 ) -> Tuple[List[dict], int, int]:
    """Return (findings, records examined, elements judged) for one row.

    TWO denominators, deliberately, because they answer different questions
    and one of them was being reported as if it were the other. RECORDS is
    how many producer entries carried the reference field — the same element
    is counted once per collection that carries it, and on the shipped corpus
    that is 3 records for 1 port. ELEMENTS is how many distinct
    (identity, reference value) pairs were actually judged. A PASS line that
    says "3 declared reference(s)" over one port overstates its own reach by
    3x, and the reader who trusts it concludes the mechanism covers more than
    it does.

    RECORDS is what the corpus baseline regresses on, because it is the
    strictly more sensitive of the two: elements can only shrink by records
    shrinking, while records can shrink on their own when a producer
    collection stops carrying the field. See `compare_denominator`.
    """
    prod = row["producer"]
    tgt = row["target"]
    findings: List[dict] = []

    producers = index_elements(
        layers, prod["layers"], prod["collections"],
        prod.get("kind", "element"), prod.get("key_field", "name"))
    if not producers:
        return [], 0, 0

    scope_idx = index_elements(
        layers, tgt["scope_layers"], tgt["collections"],
        tgt.get("kind", "element"), tgt.get("key_field", "name"))
    scope_by_name = _index_by_name(scope_idx)

    # Everything the corpus declares under the SAME collections in ANY layer.
    # Used only to tell "nothing declares this name" (DANGLING) apart from
    # "something declares it, in a layer whose namespace does not scope this
    # reference" (OUT_OF_SCOPE). The out-of-scope hit is never USED.
    all_idx = index_elements(
        layers, layers.keys(), tgt["collections"],
        tgt.get("kind", "element"), tgt.get("key_field", "name"))
    all_by_name = _index_by_name(all_idx)

    consumer_cfg = row.get("consumer") or {}
    observed: Optional[Dict[str, Dict[str, Any]]] = None
    consumer_error: Optional[str] = None
    if consumer_cfg.get("adapter"):
        adapter = CONSUMER_ADAPTERS.get(consumer_cfg["adapter"])
        if adapter is None:
            consumer_error = f"no adapter registered: {consumer_cfg['adapter']}"
        else:
            observed = adapter(project, layers)
            if observed is None:
                consumer_error = (
                    f"adapter {consumer_cfg['adapter']} could not run")

    ref_field = prod["reference_field"]
    examined = 0
    # The SAME element is carried by several collections and promoted across
    # layers: one port object is shared by L9.top_ports / .ports /
    # .top_module_pins and promoted into L1.pin_table. That is one element
    # with one reference, so it is judged once — but every id that carries it
    # is named in the finding, because "which layers hold this" is the first
    # thing a reader needs and re-deriving it by hand is how #404 cost a day.
    grouped: Dict[Tuple[str, str], List[Tuple[str, dict]]] = {}
    order: List[Tuple[str, str]] = []
    for eid, recs in sorted(producers.items()):
        for rec in recs:
            raw = rec.get(ref_field)
            if not isinstance(raw, str) or not raw.strip():
                continue
            examined += 1
            key = (eid.rsplit(":", 1)[-1], raw.strip())
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            grouped[key].append((eid, rec))
    for key in order:
        members = grouped[key]
        eid, rec = members[0]
        producer_ids = sorted({m[0] for m in members})
        producer_files = sorted({m[1].get("__file") for m in members
                                 if m[1].get("__file")})
        for finding in _judge_element(
                row, eid, rec, key[1], scope_by_name, all_by_name,
                tgt, observed, consumer_error, consumer_cfg):
            finding["producer_ids"] = producer_ids
            finding["producer_files"] = producer_files
            findings.append(finding)
    return findings, examined, len(order)


def _judge_element(row, eid, rec, raw, scope_by_name, all_by_name,
                   tgt, observed, consumer_error, consumer_cfg) -> List[dict]:
    grammar = row["grammar"]
    name = eid.rsplit(":", 1)[-1]
    base = {
        "row": row["id"],
        "producer_id": eid,
        "producer_layer": rec.get("__layer"),
        "producer_file": rec.get("__file"),
        "reference_value": raw,
        "grammar": grammar,
    }

    parsed = parse_symbolic_range(raw)
    if parsed is None:
        # NOT folded into DANGLING. "the id does not exist" and "this value
        # is not an address in the first place" send an author to different
        # files. A bare-identifier width (`"W"` rather than `"W-1:0"`) lands
        # here on purpose: widening the grammar to accept it is a new named
        # grammar and a new measurement, not a silent relaxation of this one.
        return [dict(base, code=UNPARSEABLE,
                     detail=(f"{raw!r} is not an address under grammar "
                             f"{grammar!r}, so nothing can be resolved from "
                             f"it — this is a producer/extractor defect, not "
                             f"a missing target"))]
    hi_s, lo_s = parsed

    env: Dict[str, int] = {}
    out: List[dict] = []
    value_field = tgt.get("value_field", "default")
    for term in (hi_s, lo_s):
        ident = term_identifier(term)
        if ident is None or ident in env:
            continue
        in_scope = scope_by_name.get(ident) or []
        if not in_scope:
            elsewhere = all_by_name.get(ident) or []
            if elsewhere:
                out.append(dict(
                    base, code=OUT_OF_SCOPE, identifier=ident,
                    target_id=element_id(
                        elsewhere[0].get("__layer", "L?"),
                        tgt.get("kind", "element"), ident),
                    scope_layers=list(tgt["scope_layers"]),
                    detail=(
                        f"{ident!r} is declared only in "
                        f"{sorted({e.get('__layer') for e in elsewhere})}, "
                        f"outside the namespace that scopes this reference "
                        f"({list(tgt['scope_layers'])}); the join is refused, "
                        f"not used")))
            else:
                out.append(dict(
                    base, code=DANGLING, identifier=ident,
                    searched_layers=list(tgt["scope_layers"]),
                    detail=(
                        f"{ident!r} resolves to no "
                        f"{tgt.get('kind', 'element')} in "
                        f"{list(tgt['scope_layers'])}")))
            continue
        val = None
        for cand in in_scope:
            val = target_int(cand.get(value_field))
            if val is not None:
                break
        if val is None:
            out.append(dict(
                base, code=UNUSABLE_TARGET, identifier=ident,
                target_id=element_id(in_scope[0].get("__layer", "L?"),
                                     tgt.get("kind", "element"), ident),
                declared_value=in_scope[0].get(value_field),
                detail=(
                    f"{ident!r} resolves, but its {value_field!r} "
                    f"({in_scope[0].get(value_field)!r}) is not a number "
                    f"this reference can evaluate")))
            continue
        env[ident] = val

    if out:
        return out

    hi, lo = eval_term(hi_s, env), eval_term(lo_s, env)
    if hi is None or lo is None:
        return [dict(base, code=DANGLING,
                     detail=f"range terms {hi_s!r}:{lo_s!r} did not evaluate")]
    resolved = abs(hi - lo) + 1

    if not consumer_cfg.get("adapter"):
        return []
    if consumer_error:
        return [dict(base, code=CONSUMER_BLIND, resolved_value=resolved,
                     consumer=consumer_cfg["adapter"],
                     detail=f"consumer not observable: {consumer_error}")]
    seen_val = (observed or {}).get(name)
    value_name = consumer_cfg.get("value_name", "value")
    if seen_val is None:
        return [dict(
            base, code=CONSUMER_BLIND, resolved_value=resolved,
            consumer=consumer_cfg["adapter"], observed_value=None,
            resolved_from=sorted(env.items()),
            detail=(
                f"the reference resolves to {resolved} from "
                f"{sorted(env.items())}, and {consumer_cfg['adapter']} "
                f"derives no element named {name!r} at all"))]
    got = seen_val.get(value_name)
    if got == resolved:
        return []
    return [dict(
        base, code=CONSUMER_BLIND, resolved_value=resolved,
        consumer=consumer_cfg["adapter"], observed_value=got,
        resolved_from=sorted(env.items()),
        detail=(
            f"{eid} references {sorted(env.items())} and resolves to "
            f"{value_name}={resolved}; {consumer_cfg['adapter']} — the "
            f"derivation that would consume it — yields {value_name}={got}. "
            f"The value is present in the layer that produces it and "
            f"unreachable by the derivation that would consume it."))]


# ─────────────────────────────────────────────────────────────────────
# Project mode
# ─────────────────────────────────────────────────────────────────────

def check_project(project: Path, rows: List[dict]) -> dict:
    report = {
        "gate": GATE,
        "verdict_mode": "ADVISES",
        "project": str(project),
        "id_scheme": "L<layer>:<kind>:<name>",
        "rows_evaluated": [],
        "findings": [],
        "elements_examined": 0,
        "elements_judged": 0,
        "verdict": "VACUOUS_PASS",
    }
    if not _ldc.generated_docs_dir(project).is_dir():
        report["verdict"] = "SKIP"
        report["detail"] = "no phase1/generated_docs"
        return report
    try:
        layers = load_layers(project)
    except LayerLoadError as exc:
        report["verdict"] = "ERROR"
        report["detail"] = f"layer file present and unparseable: {exc}"
        return report
    report["layers_present"] = sorted(layers)
    for row in rows:
        findings, examined, judged = evaluate_row(row, project, layers)
        report["rows_evaluated"].append(
            {"id": row["id"], "elements_with_reference": examined,
             "elements_judged": judged, "findings": len(findings)})
        report["elements_examined"] += examined
        report["elements_judged"] += judged
        report["findings"].extend(findings)
    if report["findings"]:
        report["verdict"] = "FAIL"
    elif report["elements_examined"]:
        report["verdict"] = "PASS"
    waiver = _ldc.waiver_rationale(project, WAIVER_KEY, WAIVER_MIN_LEN)
    if waiver and report["verdict"] == "FAIL":
        report["verdict"] = "PASS_WITH_WAIVER"
        report["waiver"] = waiver
    return report


# ─────────────────────────────────────────────────────────────────────
# Corpus mode
# ─────────────────────────────────────────────────────────────────────

def corpus_cells(corpus: Path) -> List[Path]:
    """The PUBLISHED cells, not whatever this machine happens to have on disk.

    Gatekeeper finding at land time, and the second instance of this shape in
    one day (see `provenance_output_hash_completeness_check._published_paths`).
    A plain `rglob` counted 46 L1 documents in a working checkout and 23 in a
    git worktree, which materialises tracked files only — the difference is
    leftover `clean_run_*` directories from local runs that no reader who
    clones ever receives.

    That made this gate's BASELINE machine-dependent: recorded as 3 in a
    worktree, it reads 4 here and CI would read a third number. A regression
    baseline whose value depends on the host is not a baseline; it fails for
    whoever has run the flow locally and passes for whoever has not.

    So the corpus is what git tracks. Outside a repository — a run tree handed
    over on its own — the disk is still the honest answer, because nothing has
    been published and tracked-ness is not a question that applies.
    """
    dirs = sorted({p for p in corpus.rglob("phase1/generated_docs")})
    published = _published_tree.published_paths(corpus)
    if published is None:
        return sorted({d.parent.parent for d in dirs})
    root = corpus.resolve()
    keep = set()
    for d in dirs:
        try:
            rel = d.resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        # A generated_docs DIRECTORY is published when the tree tracks any
        # file inside it — git tracks files, never directories.
        if any(t.startswith(rel + "/") for t in published):
            keep.add(d.parent.parent)
    return sorted(keep)


def check_corpus(corpus: Path, rows: List[dict]) -> dict:
    out = {
        "gate": GATE,
        "mode": "corpus",
        "corpus": str(corpus),
        "cells": [],
        "counts": {},
        # The DENOMINATOR, per row, alongside the findings. Without it the
        # sweep cannot tell "no findings because nothing is broken" from
        # "no findings because the mechanism examined nothing" — see
        # compare_denominator.
        "examined": {},
        "judged": {},
        "errors": [],
    }
    for cell in corpus_cells(corpus):
        # `check_project` is pure — the per-project verdict artefact is
        # written by main()'s project branch, never here. A CI sweep must
        # not leave a file inside every published cell it judged; the
        # corpus report goes to --json, which is one path the caller chose.
        rep = check_project(cell, rows)
        rel = str(cell.relative_to(corpus))
        out["cells"].append(
            {"cell": rel, "verdict": rep["verdict"],
             "findings": rep["findings"]})
        if rep["verdict"] == "ERROR":
            out["errors"].append({"cell": rel, "detail": rep.get("detail")})
        for f in rep["findings"]:
            bucket = out["counts"].setdefault(f["row"], {})
            bucket[f["code"]] = bucket.get(f["code"], 0) + 1
        for rowrep in rep["rows_evaluated"]:
            rid = rowrep["id"]
            out["examined"][rid] = (out["examined"].get(rid, 0)
                                    + rowrep["elements_with_reference"])
            out["judged"][rid] = (out["judged"].get(rid, 0)
                                  + rowrep.get("elements_judged", 0))
    out["cells_swept"] = len(out["cells"])
    return out


def baseline_path(explicit: Optional[str]) -> Path:
    return Path(explicit) if explicit else (_HERE / BASELINE_NAME)


def load_baseline(path: Path) -> Dict[str, Dict[str, int]]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    recorded = data.get("recorded")
    return recorded if isinstance(recorded, dict) else {}


def load_baseline_examined(path: Path) -> Optional[Dict[str, int]]:
    """The recorded DENOMINATOR per row, or None when the file records none.

    None and {} are different answers and are kept apart: {} means the sweep
    that wrote this baseline examined nothing, None means the baseline
    predates the denominator record and cannot be compared against. The
    second is NOT CHECKED, never a quiet pass.
    """
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ex = data.get("examined")
    if not isinstance(ex, dict):
        return None
    return {k: int(v) for k, v in ex.items() if isinstance(v, int)}


# ─────────────────────────────────────────────────────────────────────
# The register's own seal
# ─────────────────────────────────────────────────────────────────────
#
# WHAT IT IS FOR. `recorded` may only grow with a corpus that says so, and the
# only thing that ever checked that was a live sweep. Once the corpus can be
# absent, a run with no corpus opens the register, cannot re-measure it, and
# would otherwise have nothing to say about whether the numbers in it are the
# numbers a sweep produced. The seal is that evidence, and it is the reason the
# NO_CORPUS row can return rc 0 without the register going unguarded.
#
# WHAT IT IS NOT FOR. It is not a secret and it stops nobody who runs
# `--write-baseline` over a reaching corpus — that is the SUPPORTED way to move
# these numbers, and it makes them a measurement again. What it removes is the
# silent hand-edit: adding 300 to a count in a text editor to stop a real break
# being NEW now requires deliberately recomputing a digest, which is a false
# statement rather than an omission nothing measures. Same bar
# `published_record_staleness_check` sets for its own register (#922).

SEAL_KEY = "seal"
_SEAL_ALGO = "sha256"


def register_seal(doc: Dict[str, Any]) -> str:
    """The digest of the MEASURED half of a register document.

    Over `recorded` and `examined` only: `_comment` is prose a maintainer may
    improve, and sealing it would make an editorial fix indistinguishable from
    a tampered count — which trains readers to re-seal without looking, and a
    seal nobody reads is not a seal.
    """
    payload = json.dumps(
        {"recorded": doc.get("recorded") or {},
         "examined": doc.get("examined") or {}},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"{_SEAL_ALGO}:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def seal_status(path: Path) -> Tuple[str, str]:
    """``(status, detail)`` for the register at `path`.

    Statuses: ``ABSENT_FILE``, ``UNREADABLE``, ``MALFORMED``, ``NO_SEAL``,
    ``MISMATCH``, ``OK``. Every one of them is a different fact and the caller
    maps them to different exit codes; collapsing any two is the shape this
    whole program argues against.
    """
    if not path.is_file():
        return "ABSENT_FILE", f"{path} does not exist"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:                    # noqa: BLE001
        return "UNREADABLE", f"{path} could not be read as JSON ({exc})"
    if not isinstance(doc, dict) or not isinstance(doc.get("recorded"), dict):
        return "MALFORMED", (f"{path} carries no `recorded` object, so there is "
                             f"no register in it to adjudicate")
    have = doc.get(SEAL_KEY)
    if not isinstance(have, str) or not have:
        return "NO_SEAL", (
            f"{path} records no `{SEAL_KEY}`. It predates the seal, or it was "
            f"written by hand. Re-record it with --write-baseline over a corpus "
            f"that reaches; the seal is what a run with no corpus has instead "
            f"of a measurement.")
    want = register_seal(doc)
    if have != want:
        return "MISMATCH", (
            f"{path} records {SEAL_KEY}={have} and its own `recorded`/"
            f"`examined` numbers digest to {want}. The register was EDITED "
            f"after it was written. A count raised by hand stops a real break "
            f"being NEW, which is the one thing this ratchet exists to make "
            f"impossible; re-record it with --write-baseline over a corpus that "
            f"reaches, or restore the numbers the seal was taken over.")
    return "OK", f"{path} matches its own seal"


def compare_denominator(examined: Dict[str, int],
                        recorded: Optional[Dict[str, int]]) -> List[str]:
    """Rows whose REACH shrank since the baseline was recorded.

    MEASURED, and the reason this exists (vibe-ic#376). Rename the producer's
    reference field, rename its collection, or move its layer — three ways an
    emitter changes underneath a manifest row — and the sweep goes from 9
    records examined to 0. Before this arm, every one of the three printed

        ~ improved: <row>/CONSUMER_CANNOT_REACH: 3 -> 0
        [PASS] no NEW cross-layer reference break

    and exited 0. The one BLOCKING wiring of this whole mechanism reported
    SUCCESS, and called it an improvement, at the moment the mechanism
    stopped working. That is the defect class this program exists for,
    turned on the program itself: the value is still in the layer that
    produces it, and the layer that consumes it can no longer reach it,
    while both individually pass.

    A findings count may still SHRINK freely while the denominator holds —
    that is a repair, and it stays rc 0. What may not happen silently is the
    denominator shrinking, because that means the sweep is measuring LESS
    than it was, and no verdict computed over a smaller denominator is
    comparable to the one recorded. Removing a cell from the corpus lands
    here too, and should: it is a deliberate act, and `--write-baseline`
    is how it is declared.
    """
    if recorded is None:
        return []
    out: List[str] = []
    for row in sorted(set(examined) | set(recorded)):
        now, was = examined.get(row, 0), recorded.get(row, 0)
        if now < was:
            out.append(
                f"{row}: examined {was} -> {now} producer record(s). The "
                f"sweep is reaching LESS than when the baseline was "
                f"recorded — an emitter renamed the field or the "
                f"collection, moved the layer, or the corpus shrank. Any "
                f"drop in findings across this change is not a repair.")
    return out


def compare_baseline(counts: Dict[str, Dict[str, int]],
                     recorded: Dict[str, Dict[str, int]]
                     ) -> Tuple[List[str], List[str]]:
    """(regressions, improvements) as human-readable lines."""
    regressions, improvements = [], []
    for row in sorted(set(counts) | set(recorded)):
        now = counts.get(row, {})
        was = recorded.get(row, {})
        for code in sorted(set(now) | set(was)):
            n, w = now.get(code, 0), was.get(code, 0)
            if n > w:
                regressions.append(f"{row}/{code}: {w} -> {n}")
            elif n < w:
                improvements.append(f"{row}/{code}: {w} -> {n}")
    return regressions, improvements


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────

def _print_findings(findings: List[dict]) -> None:
    for f in findings:
        ids = f.get("producer_ids") or [f.get("producer_id")]
        files = f.get("producer_files") or [f.get("producer_file")]
        print(f"  [{f['code']}] {', '.join(str(i) for i in ids)}")
        print(f"      carried by: {', '.join(str(x) for x in files)}")
        print(f"      {f.get('detail')}")


def _adjudicate_register_without_a_corpus(bpath: Path) -> int:
    """NO_CORPUS has been decided; now answer for the register itself.

    The sweep is excused because the corpus moved to its own repository. The
    register did NOT move: it sits beside this program, and widening it is the
    cheapest way to stop a real break being NEW. `repo_hygiene_gates.sh`
    withdrew this gate's `gate_scope` in v1.10.55 precisely so a commit that
    touches only the register still runs this gate — an rc 0 that never opened
    the file would give that hole back.

    So the ONE thing still checkable with no corpus is checked: are these the
    numbers a sweep wrote? Nothing here re-measures anything, and the printed
    verdict says so in those words.
    """
    status, detail = seal_status(bpath)
    if status == "MISMATCH":
        print(f"[FAIL] {GATE}: no corpus was scanned, and the debt register "
              f"beside this program was EDITED after it was written. {detail}",
              file=sys.stderr)
        return 1
    if status != "OK":
        print(f"[NOT CHECKED] {GATE}: no corpus was scanned, so the debt "
              f"register is the only thing left to adjudicate, and it cannot "
              f"be: {detail} Until it can, this run has judged NOTHING — "
              f"neither the corpus nor the register — and that is not a pass.",
              file=sys.stderr)
        return 2
    recorded = load_baseline(bpath)
    examined = load_baseline_examined(bpath) or {}
    total = sum(sum(v.values()) for v in recorded.values())
    print(f"[{GATE}] register: {total} recorded break(s) across "
          f"{len(recorded)} row(s), measured over "
          f"{sum(examined.values())} producer record(s); seal verifies.",
          file=sys.stderr)
    for row in sorted(recorded):
        for code in sorted(recorded[row]):
            print(f"   recorded {row}/{code}: {recorded[row][code]} "
                  f"(of {examined.get(row, 0)} examined)", file=sys.stderr)
    print(f"[{GATE}] NO_CORPUS: 0 cell(s) swept. The counts above were NOT "
          f"RE-MEASURED by this run and nothing is claimed about whether they "
          f"are still true of the corpus — only that they are unchanged since "
          f"the sweep that recorded them. Point "
          f"${_cloc.CORPUS_ENV} at a clone to re-measure.", file=sys.stderr)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=("one general gate over declared cross-layer references "
                     "(vibe-ic#376)"))
    ap.add_argument("project", nargs="?",
                    help="project directory carrying phase1/generated_docs/")
    ap.add_argument("--corpus",
                    help="judge every cell under DIR against the baseline")
    ap.add_argument("--manifest", help="override the reference manifest path")
    ap.add_argument("--baseline", help="override the baseline path")
    ap.add_argument("--write-baseline", action="store_true",
                    help="record the current corpus counts as the baseline")
    ap.add_argument("--corpus-may-be-absent", action="store_true",
                    help="the caller asserts this repo need not carry the "
                         "published corpus. Turns 'no corpus discoverable "
                         "anywhere' from UNDETERMINED into NO_CORPUS (rc 0), "
                         "which STATES that 0 cells were swept. It does NOT "
                         f"excuse a ${_cloc.CORPUS_ENV} that is set and broken, "
                         "and it does NOT excuse the debt register: that lives "
                         "in this repo, did not move with the corpus, and is "
                         "still adjudicated against its own seal.")
    ap.add_argument("--json", help="write the machine-readable report here")
    args = ap.parse_args(argv)

    try:
        rows = load_manifest(Path(args.manifest) if args.manifest else None)
    except ManifestError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    if args.corpus:
        named = Path(args.corpus)
        bpath = baseline_path(args.baseline)
        corpus, origin = _cloc.resolve(named, subdir="ic", gate=GATE,
                                       announce=True)
        if not corpus.is_dir():
            rc = _cloc.refuse(GATE, named, corpus, origin,
                              args.corpus_may_be_absent, "published cell(s)")
            if rc != 0:
                return rc
            # NO_CORPUS EXCUSES THE SWEEP, NEVER THE REGISTER. See the module
            # docstring: the register did not move with the corpus, and an rc 0
            # that never opened it is the gate_scope hole of v1.10.55 walked in
            # through the other door.
            return _adjudicate_register_without_a_corpus(bpath)
        if origin == _cloc.ENV:
            # THIS GATE'S POPULATION IS WHAT GIT TRACKS (`corpus_cells` ->
            # `_published_tree.published_paths`), and that function falls back
            # to the DISK when it cannot read an index. Over a corpus that is
            # present but not a checkout, the sweep would silently change
            # population and compare the result against a baseline measured
            # over the tracked one.
            why = _cloc.not_a_checkout_reason(corpus, "published cells")
            if why is None and _published_tree.published_paths(corpus) is None:
                # A CHECKOUT THAT TRACKS NOTHING IS THE SAME EMPTY RESULT WITH
                # a `.git` beside it. `published_paths` returns None for BOTH
                # "git could not answer" and "the index is empty", and
                # `corpus_cells` sends both to the disk — so a clone that
                # delivered no content would be swept from whatever is lying in
                # it. The pointer says a corpus is there; a tree tracking
                # nothing is not one.
                why = (f"{corpus} is a git checkout that tracks NOTHING, so "
                       f"the published population is empty and "
                       f"`corpus_cells` would fall back to a disk walk.")
            if why:
                print(f"[{GATE}] UNDETERMINED: {why} The baseline records "
                      f"counts measured over the TRACKED population, so a "
                      f"verdict from a disk walk here would compare two "
                      f"different populations.", file=sys.stderr)
                return 2
        report = check_corpus(corpus, rows)
        if args.write_baseline:
            # REFUSE TO RECORD A NUMBER A SWEEP DID NOT MEASURE (vibe-ic#1025's
            # shape, which this program still had). The write used to happen
            # unconditionally and BEFORE the "no cell swept" branch below, so
            #     --corpus <empty> --baseline <the register> --write-baseline
            # rewrote `recorded` and `examined` to {} and printed [WROTE].
            # That satisfies MAY-ONLY-SHRINK while proving the opposite of what
            # the rule exists to prove, and now that the register is also the
            # thing a corpus-less run adjudicates, it would additionally mint a
            # valid seal over nothing. No --force: an escape hatch here puts the
            # same destruction one flag away.
            if not report["cells"]:
                print(f"[REFUSED] {GATE} --corpus: the sweep found 0 published "
                      f"cell(s) under {corpus}, so it examined NOTHING. "
                      f"Writing a baseline from it would record empty counts "
                      f"as a measurement, destroy the recorded reference "
                      f"point, and seal the result. Fix the corpus/reach "
                      f"first (vibe-ic#1025).", file=sys.stderr)
                return 2
            doc: Dict[str, Any] = {
                "_comment": (
                    "Measured cross-layer reference breaks on the published "
                    "corpus. Counts only, never cell identity — cell paths "
                    "carry design/PDK names and this file is scanned by "
                    "source_chip_agnostic_check. A findings count may SHRINK "
                    "freely; any increase, or a new row/code pair, FAILs CI. "
                    "`examined` is the DENOMINATOR those counts were measured "
                    "over: it may not shrink silently, because a sweep that "
                    "reaches less than the recorded one produces a smaller "
                    "findings count for a reason that is not a repair."),
                "_seal_comment": (
                    "`seal` digests `recorded` + `examined` and NOTHING ELSE. "
                    "It is what a run with NO CORPUS has instead of a "
                    "measurement: since v1.10.56 the corpus lives in its own "
                    "repository and this register does not, so a sweep can be "
                    "excused while the register still has to be adjudicated. "
                    "Written only by --write-baseline, which refuses a sweep "
                    "that reached no cell — so re-sealing these numbers costs a "
                    "corpus that actually reaches. Editing a count by hand does "
                    "not."),
                "recorded": report["counts"],
                "examined": report["examined"],
            }
            doc[SEAL_KEY] = register_seal(doc)
            bpath.write_text(json.dumps(doc, indent=2) + "\n",
                             encoding="utf-8")
            print(f"[WROTE] {bpath} ({doc[SEAL_KEY]})")
        if args.json:
            Path(args.json).write_text(
                json.dumps(report, indent=2, ensure_ascii=False),
                encoding="utf-8")
        recorded = load_baseline(bpath)
        recorded_examined = load_baseline_examined(bpath)
        regressions, improvements = compare_baseline(report["counts"], recorded)
        shrunk = compare_denominator(report["examined"], recorded_examined)
        n_cells = len(report["cells"])
        n_find = sum(len(c["findings"]) for c in report["cells"])
        n_exam = sum(report["examined"].values())
        n_judged = sum(report["judged"].values())
        print(f"{GATE} --corpus: {n_cells} cell(s), {n_exam} producer "
              f"record(s) carrying a declared reference ({n_judged} distinct "
              f"element(s)), {n_find} finding(s)")
        for cell in report["cells"]:
            if cell["findings"]:
                print(f"── {cell['cell']}: {cell['verdict']}")
                _print_findings(cell["findings"])
        # An improvement is only an improvement at constant reach. When the
        # denominator shrank, the SAME findings drop is the symptom, and
        # printing it as a win directly above the failure is how a reader
        # ends up believing the wrong half of the output.
        if not shrunk:
            for line in improvements:
                print(f"  ~ improved: {line}")
        if report["errors"]:
            for e in report["errors"]:
                print(f"[ERROR] {e['cell']}: {e['detail']}", file=sys.stderr)
            return 2
        # A sweep that found no cells has not judged this corpus clean; it has
        # not judged it at all. Reported as NOT CHECKED (2) so it can never be
        # read as, or counted as, a PASS.
        if not report["cells"]:
            print(f"[NOT CHECKED] {GATE} --corpus: no published cell under "
                  f"{corpus} carries phase1/generated_docs — 0 cell(s) swept, "
                  f"so nothing about this corpus has been judged.",
                  file=sys.stderr)
            return 2
        # A baseline that records findings but no denominator cannot be
        # compared against: the whole point of the denominator is that a
        # findings count alone does not say whether the sweep still reaches
        # what it reached. Say so instead of assuming it does.
        if recorded and recorded_examined is None:
            print(f"[NOT CHECKED] {GATE} --corpus: the baseline at {bpath} "
                  f"records findings but no `examined` denominator, so a "
                  f"drop in findings cannot be told apart from the sweep "
                  f"losing its reach. Re-record it with --write-baseline.",
                  file=sys.stderr)
            return 2
        # THE REGISTER IS ADJUDICATED WHETHER OR NOT A CORPUS TURNED UP.
        # Here a sweep DID happen, so a missing seal is only reported: the live
        # counts are the measurement and the register is being compared against
        # them. A seal that is present and WRONG is a different fact — somebody
        # edited the file after it was written — and no sweep can tell whether
        # the edit was the one hiding a break, so it FAILs in both modes.
        sstatus, sdetail = seal_status(bpath)
        if sstatus == "MISMATCH":
            print(f"[FAIL] {GATE}: the debt register was EDITED after it was "
                  f"written. {sdetail}", file=sys.stderr)
            return 1
        if sstatus == "NO_SEAL":
            print(f"  (register) {sdetail} A sweep ran here, so the counts "
                  f"above are the measurement; a run with NO corpus has only "
                  f"the seal and will refuse.", file=sys.stderr)
        if shrunk:
            for line in shrunk:
                print(f"[FAIL] cross-layer reference sweep LOST REACH: {line}",
                      file=sys.stderr)
            return 1
        if regressions:
            for line in regressions:
                print(f"[FAIL] NEW cross-layer break: {line}", file=sys.stderr)
            return 1
        recorded_total = sum(sum(v.values()) for v in recorded.values())
        print(f"[PASS] no NEW cross-layer reference break over {n_exam} "
              f"producer record(s) in {n_cells} cell(s) "
              f"({recorded_total} recorded, unchanged or shrunk).")
        return 0

    if not args.project:
        ap.error("give a project directory, or --corpus DIR")
    project = Path(args.project)
    if not project.is_dir():
        print(f"[SKIP] project not found: {project}")
        return 2
    report = check_project(project, rows)
    if args.json:
        Path(args.json).write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    _ldc.write_report(project, GATE, report)

    verdict = report["verdict"]
    if verdict == "SKIP":
        print(f"[SKIP] {report.get('detail')}")
        return 2
    if verdict == "ERROR":
        print(f"[ERROR] {report.get('detail')}", file=sys.stderr)
        return 2
    if verdict == "VACUOUS_PASS":
        # #528 — this branch announced the vacuous tier as `[VACUOUS_PASS]`,
        # and `flow_compliance_check._stdout_signals_vacuous` matches
        # `line.lstrip().startswith("VACUOUS_PASS")` — the bracket defeats it.
        # So the gate exited 0 with a disclosure nothing read, over a design
        # whose layers carry no declared cross-layer reference at all. Its own
        # two neighbours above (`SKIP`, `ERROR`) are already rc 2. The
        # `--corpus` regression path returns earlier and is untouched, which is
        # the mode `tools/ci/repo_hygiene_gates.sh` runs.
        reason = "no-declared-cross-layer-reference"
        _vx.announce_vacuous(GATE, reason)
        print(_vx.verdict_line(GATE, passed=True, skipped=True, reason=reason))
        return _vx.exit_code(passed=True, skipped=True)
    if verdict == "PASS":
        # BOTH denominators. The record count alone reads as reach this
        # mechanism does not have: on the shipped corpus one port carried by
        # L1.pin_table, L9.top_ports and L9.ports is 3 records and 1 element,
        # and the old line called that "3 declared reference(s)".
        print(f"[PASS] {GATE}: {report['elements_judged']} declared "
              f"reference(s) — carried by {report['elements_examined']} "
              f"producer record(s) — resolve in scope and reach the "
              f"derivation that would consume them.")
        return 0
    if verdict == "PASS_WITH_WAIVER":
        print(f"[PASS_WITH_WAIVER] {GATE}: {len(report['findings'])} "
              f"finding(s) waived — {report.get('waiver', '')[:100]}")
        return 0
    print(f"[FAIL] {GATE}: {len(report['findings'])} cross-layer reference "
          f"finding(s) over {report['elements_examined']} declared "
          f"reference(s).")
    _print_findings(report["findings"])
    return 1


if __name__ == "__main__":
    sys.exit(main())
