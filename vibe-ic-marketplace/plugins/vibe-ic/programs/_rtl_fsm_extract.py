#!/usr/bin/env python3
"""The ONE reader of "what state machines does this RTL declare?".

WHY THIS MODULE EXISTS — the structural FSM predicate had THREE copies and no
producer.

  * ``l6_fsm_scaffold_actionable_check._enum_fsm_state_count`` — used to
    CONTRADICT an L6 that declares no FSM;
  * ``l_doc_structured_field_count_check._harvest_staged_fsm_state_count`` —
    used to CREDIT a reused-IP design's L6 floor;
  * ``phase1_doc_one_shot_runner`` — had none. Phase 1 reads ``input/docs/``
    only, so for a REUSED-IP design (one whose input STAGES the implementation
    it will be built from) the states the design declares in its own RTL were
    invisible to the layer whose subject they are.

The measured consequence, on ``opentitan_aes`` (2026-09-02, plugin v1.15.50):
``L6_CONTROL_LOGIC.json`` carried ``fsm_states: []`` and
``no_fsm_in_input: true`` while the staged tree declared FOUR closed state
enums totalling 28 states in one package. Two gates then read the same tree
with the same rule and reached opposite verdicts about it, and Phase 1 halted
on the contradiction — an EXTRACTION defect reported as a design deficiency.

Two consumers and no producer is the shape that makes that possible. This
module is the rule, written once, and it is now BOTH: the gates import the
predicate they used to each own a copy of, and the Phase-1 producer imports the
extractor so the document and the gates cannot disagree by construction.

THE RULE — structural, never a name vocabulary about the design
==============================================================
An enum is a STATE TYPE iff the RTL uses it to DECLARE a state register:

  1. ``typedef enum ... { A, B, ... } <T>;`` with >= 2 members — a one-member
     enum is not a state machine; and
  2. some signal is declared ``<T> <ident>;`` where ``<ident>`` carries a
     STRONG state-register suffix (``_fsm_cs`` / ``_fsm_ns`` / ``_fsm_state`` /
     ``_fsm``), or a WEAK one (``_state`` / ``_state_q`` / ``_state_d`` /
     ``_cs`` / ``_ns``) that is ALSO the subject of a ``case (<ident>)``.

The weak/strong split is #748's hardening and is preserved verbatim: a data
signal can be called ``req_state``; only a ``case`` over it makes it a
controller. No chip, vendor, PDK or state-name literal participates — a design
becomes eligible by declaring a state register and by nothing else.

TRANSITIONS — the same evidence, and no more
============================================
An edge is emitted only when BOTH endpoints are members of the SAME declared
enum: inside a ``case`` arm labelled by member ``S`` (a LINE-ANCHORED label, so
the ``A`` of a ternary ``cond ? A : B`` is never mistaken for an arm), an
assignment to one of that enum's own state signals whose right-hand side names
member ``D`` yields ``S -> D``. Both endpoints are already published states, so
the edge asserts the relation between two facts and never a third fact.

MEASURED LIMIT, stated because it is real: arm attribution is by NEAREST
PRECEDING line-anchored label, so an assignment inside a nested ``case`` over a
DIFFERENT enum is attributed to the outer arm it is lexically inside. That is
the correct answer for the outer machine (the outer arm is where the design put
it) and it can never invent a state — ``_l6_attach_declared_transitions`` drops
any edge whose endpoints are not both in the final state list.

WHAT THIS MODULE WILL NOT DO
============================
It does not parse SystemVerilog. It reads declarations, not semantics: a state
unreachable in the design is still a declared state, and a transition guarded
by a condition that can never hold is still a declared transition. The document
this feeds says what the RTL DECLARES, which is exactly what L6 is for.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

#: `typedef enum [...] { A, B, C } name_e;` — brace body + typedef name.
#: DOTALL so a multi-line enum body is captured. The body is `[^}]*`, so a
#: nested brace inside an enum body (there is no legal one) ends the match
#: early rather than swallowing the file.
TYPEDEF_ENUM_RE = re.compile(
    r"typedef\s+enum\b[^\{]*\{(?P<body>[^}]*)\}\s*"
    r"(?P<tname>[A-Za-z_]\w*)\s*;", re.S)

#: Identifier suffixes that NAME a state register on their own.
FSM_SIGNAL_STRONG: Tuple[str, ...] = ("_fsm_cs", "_fsm_ns", "_fsm_state",
                                      "_fsm")
#: Suffixes a non-FSM data signal can also carry — these need a
#: `case (<signal>)` before the enum is credited (#748).
FSM_SIGNAL_WEAK: Tuple[str, ...] = ("_state", "_state_q", "_state_d",
                                    "_cs", "_ns")

#: The extensions that carry RTL, in a deterministic harvest order.
RTL_GLOBS: Tuple[str, ...] = ("*.v", "*.sv")

#: Named so the producer's evidence line and any consumer agree by
#: construction instead of by re-typing the string.
EXTRACTION_STRATEGY = "staged_rtl_declared_state_enum_v1_15_51"


def strip_verilog_comments(text: str) -> str:
    """`//` line and `/* */` block comments removed, line count preserved, so a
    commented-out FSM is never harvested."""
    if not isinstance(text, str) or not text:
        return ""
    text = re.sub(r"/\*.*?\*/",
                  lambda match: "\n" * match.group(0).count("\n"),
                  text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def _member_names(body: str) -> List[str]:
    """The member identifiers an enum body declares, in declaration order."""
    out: List[str] = []
    for seg in body.split(","):
        name = seg.split("=", 1)[0].strip()
        if re.fullmatch(r"[A-Za-z_]\w*", name or ""):
            out.append(name)
    return out


def _member_literals(body: str) -> Dict[str, str]:
    """member -> the literal it is declared equal to, for members that state
    one. A member with no literal is absent: SystemVerilog's implicit numbering
    is a language default, not something the design said."""
    out: Dict[str, str] = {}
    for seg in body.split(","):
        if "=" not in seg:
            continue
        name, _, lit = seg.partition("=")
        name = name.strip()
        lit = lit.strip()
        if re.fullmatch(r"[A-Za-z_]\w*", name or "") and lit:
            out[name] = lit
    return out


def _typed_signals(clean: str, type_name: str) -> List[str]:
    """Every identifier in `clean` declared of type `type_name`, in
    declaration order.

    Eligibility is decided by `_fsm_bound_signals` (a NAMED state register);
    this wider set is what an ASSIGNMENT may target. The split is load-bearing:
    a design declares `<T> foo_ns, foo_cs;` and only `foo_cs` is `case`-ed, so
    the eligibility rule sees `foo_cs` while every next-state assignment in the
    file writes `foo_ns`. Reading edges off the eligible subset alone found
    ZERO transitions in a file carrying twelve — measured on opentitan_aes
    before this split existed.
    """
    decl = re.compile(r"\b" + re.escape(type_name) + r"\b\s+(?P<ids>[^;{}=]+);")
    found: List[str] = []
    for match in decl.finditer(clean):
        for ident in re.findall(r"[A-Za-z_]\w*", match.group("ids")):
            if ident not in found:
                found.append(ident)
    return found


def _fsm_bound_signals(clean: str, type_name: str) -> List[str]:
    """Every identifier in `clean` declared of type `type_name` whose name
    makes it a state register under THE RULE. Declaration order, de-duplicated.
    """
    decl = re.compile(r"\b" + re.escape(type_name) + r"\b\s+(?P<ids>[^;{}=]+);")
    found: List[str] = []
    for match in decl.finditer(clean):
        for ident in re.findall(r"[A-Za-z_]\w*", match.group("ids")):
            low = ident.lower()
            strong = any(low.endswith(token) for token in FSM_SIGNAL_STRONG)
            weak = (any(low.endswith(token) for token in FSM_SIGNAL_WEAK)
                    and re.search(r"\bcase\s*\(\s*" + re.escape(ident)
                                  + r"\s*\)", clean, re.I))
            if (strong or weak) and ident not in found:
                found.append(ident)
    return found


def enum_fsm_state_count(text: str) -> int:
    """States in the WIDEST enum in `text` that is structurally bound to a
    state register there, or 0.

    This is `l6_fsm_scaffold_actionable_check._enum_fsm_state_count`, moved
    here unchanged so the gate and the producer share one implementation.
    """
    clean = strip_verilog_comments(text)
    best = 0
    for enum in TYPEDEF_ENUM_RE.finditer(clean):
        members = [item.strip() for item in enum.group("body").split(",")]
        state_count = sum(bool(item.split("=", 1)[0].strip())
                          for item in members)
        if state_count < 2:
            continue
        if _fsm_bound_signals(clean, enum.group("tname")):
            best = max(best, state_count)
    return best


def _arm_edges(clean: str, members: List[str],
               signals: List[str]) -> List[Tuple[str, str]]:
    """`(from, to)` for every state-to-state assignment `clean` declares.

    `from` is the nearest preceding LINE-ANCHORED `case` arm label naming a
    member of this enum; `to` is every member named on the right-hand side of
    an assignment to one of this enum's own state signals. Self-edges are
    dropped — `emit_fsm_v` scaffolds movement, and `S -> S` is not movement.
    """
    if not members or not signals:
        return []
    alt = "|".join(sorted((re.escape(m) for m in members), key=len,
                          reverse=True))
    # An arm label starts a line. A ternary's `? A : B` never does, which is
    # what keeps `A` from being read as the arm the assignment sits in.
    label_re = re.compile(
        r"^[ \t]*(" + alt + r")(?:[ \t]*,[ \t]*(?:" + alt + r"))*[ \t]*:",
        re.M)
    labels = [(m.start(), m.group(1)) for m in label_re.finditer(clean)]
    if not labels:
        return []
    sig_alt = "|".join(sorted((re.escape(s) for s in signals), key=len,
                              reverse=True))
    assign_re = re.compile(
        r"\b(?:" + sig_alt + r")\b\s*(?:<=|=(?!=))\s*(?P<rhs>[^;]{0,400});")
    member_re = re.compile(r"\b(" + alt + r")\b")
    out: List[Tuple[str, str]] = []
    seen = set()
    for match in assign_re.finditer(clean):
        prior = [pos for pos, _ in labels if pos < match.start()]
        if not prior:
            continue
        src = labels[len(prior) - 1][1]
        for dst in member_re.findall(match.group("rhs")):
            if dst == src or (src, dst) in seen:
                continue
            seen.add((src, dst))
            out.append((src, dst))
    return out


def declared_state_machines(
        sources: Dict[str, str]) -> List[Dict[str, Any]]:
    """Every state machine the `{relpath: text}` map DECLARES.

    One record per `typedef enum` that THE RULE credits, in
    (declaring-path, declaration-order) order — deterministic, so two runs
    over the same tree emit the same document:

        {"type_name", "source_file", "states": [{"name", "literal"?}],
         "state_signals": [...], "binding_files": [...],
         "transitions": [{"from", "to", "evidence"}]}

    A type declared in one file and bound in another (the package/module split
    every real design uses) is found: eligibility is decided over the WHOLE
    map, and `source_file` names where the declaration is.
    """
    if not isinstance(sources, dict):
        return []
    clean: Dict[str, str] = {}
    for rel, text in sources.items():
        if isinstance(rel, str) and isinstance(text, str):
            clean[rel] = strip_verilog_comments(text)

    # 1. every enum, keyed by type name, remembering where it is declared.
    declared: List[Tuple[str, str, str]] = []   # (rel, tname, body)
    seen_types = set()
    for rel in sorted(clean):
        for enum in TYPEDEF_ENUM_RE.finditer(clean[rel]):
            tname = enum.group("tname")
            if tname in seen_types:
                continue
            if len(_member_names(enum.group("body"))) < 2:
                continue
            seen_types.add(tname)
            declared.append((rel, tname, enum.group("body")))

    # 2. keep the ones bound to a state register ANYWHERE in the map.
    out: List[Dict[str, Any]] = []
    for rel, tname, body in declared:
        signals: List[str] = []
        binding_files: List[str] = []
        for brel in sorted(clean):
            found = _fsm_bound_signals(clean[brel], tname)
            if not found:
                continue
            binding_files.append(brel)
            for ident in found:
                if ident not in signals:
                    signals.append(ident)
        if not signals:
            continue
        members = _member_names(body)
        literals = _member_literals(body)
        states = [{"name": m} for m in members]
        for st in states:
            lit = literals.get(st["name"])
            if lit:
                st["literal"] = lit
        transitions: List[Dict[str, str]] = []
        seen_edge = set()
        for brel in binding_files:
            targets = _typed_signals(clean[brel], tname) or signals
            for src, dst in _arm_edges(clean[brel], members, targets):
                if (src, dst) in seen_edge:
                    continue
                seen_edge.add((src, dst))
                transitions.append({"from": src, "to": dst,
                                    "evidence": brel})
        out.append({
            "type_name": tname,
            "source_file": rel,
            "states": states,
            "state_signals": signals,
            "binding_files": binding_files,
            "transitions": transitions,
        })
    return out


def read_rtl_tree(root, *, rel_to=None) -> Dict[str, str]:
    """`{relpath: text}` for every `.v`/`.sv` under `root`, or `{}`.

    Paths are relative to `rel_to` (default: `root`) so the evidence a caller
    writes into a document is a project-relative path and not this host's."""
    try:
        root_path = Path(root)
    except Exception:                       # noqa: BLE001 — unusable root
        return {}
    if not root_path.is_dir():
        return {}
    base = Path(rel_to) if rel_to is not None else root_path
    out: Dict[str, str] = {}
    files: List[Path] = []
    for pat in RTL_GLOBS:
        files.extend(sorted(root_path.rglob(pat)))
    for path in files:
        try:
            rel = path.relative_to(base).as_posix()
        except ValueError:
            rel = path.name
        try:
            out[rel] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return out


def machines_from_tree(root, *, rel_to=None) -> List[Dict[str, Any]]:
    """`declared_state_machines()` over an on-disk RTL tree."""
    return declared_state_machines(read_rtl_tree(root, rel_to=rel_to))
