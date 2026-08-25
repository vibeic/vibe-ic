#!/usr/bin/env python3
"""prose_polarity_census.py — how many prose extractors do NOT consult polarity,
counted with a predicate sharper than the gate's, and never blocking on it.

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads, and it says the same thing NOT WIRED, DELIBERATELY
says below in prose. It is here because prose is not a decision: until a gate
states its intent in the one place the audit reads, "wired where it cannot
block" and "nobody decided" are the same record.

WHY THIS EXISTS SEPARATELY FROM THE GATE
========================================
`prose_polarity_consulted_check` refuses: a new polarity-blind extractor fails
CI, and its debt register `prose_polarity_baseline.json` MAY ONLY SHRINK. That
rule is right and it is also what seals the gate against its own improvement.

Its `_writes_a_declared_value` misses two spellings. A match bound by a `for`
TARGET never enters `_match_derived_names`, which walks only `ast.Assign`; and
`out.setdefault(KEY, set()).add(VALUE)` is read for `setdefault`'s DEFAULT and
not for the value pushed into the container it returns. Measured on the corpus
this ships in, at 769ff000ea, BEFORE the repairs listed under WHAT READING THEM
ACTUALLY FOUND:

    the gate's own census                     : 213   (= its baseline)
    + matches bound by a `for` target         : 240   (27 more)
    + setdefault(...).add(...) as a write     : 232   (19 more)
    both                                      : 259   (46 more)

EVERY FIGURE IN THIS FILE IS A SNAPSHOT, and the run prints the current ones.
Ten repairs are in flight on sibling branches and each removes an entry, so a
reader who lands some of them and sees smaller numbers is watching the
instrument work, not fail. Re-derive, never re-read: `prose_polarity_census.py`
prints the census, the split and the calibration on every run.

Sharpening the GATE would therefore fail CI on 46 extractors that predate the
change, and they cannot be recorded, because the register may only shrink. A
branch that fixes one blind extractor and blocks the tree on forty-six is not a
fix; it is the original finding multiplied.

So the sharper predicate lives here, as a CENSUS: it records the debt and it
NEVER refuses. The gate keeps the power to refuse and keeps its narrower
predicate; nothing is dropped and nothing is weakened. When one of the 46 is
repaired this number falls, and the fall is the evidence.

NOT WIRED, DELIBERATELY. Wiring is the gatekeeper's decision, and a census
wired as blocking would become the thing it was built to avoid. If it is wired
at all it belongs on a tolerant wrapper, and `test_the_census_is_not_wired_as_
blocking` fails if it ever reaches a plain `run `.

ONE VOCABULARY. The predicates are IMPORTED from the gate, never copied: three
private copies of a negation vocabulary is the defect #712 exists to answer, and
a census that re-implemented `_searches_prose` would drift from the thing that
actually decides the census.

WHAT THIS CENSUS IS NOT: THE SIZE OF THE PROBLEM
================================================
This file counts a WRITE SHAPE. Counted by INPUT instead -- every function whose
first parameter is named `prompt`, `spec`, `spec_text`, `doc`, `doc_text` or `md`
AND which matches a regex against it -- the population at 769ff000ea is:

    functions fed a prompt/spec/doc and matching on it : 262
    of those, consulting ANY polarity                  :   0

Two were checked rather than counted, and both are real:

    mealy_sequence_synth::_is_moore
        "The detector is not a Moore machine; it is Mealy."  -> True.
        A prompt that explicitly refuses Moore selects Moore synthesis.
    crc_synth::_parse_poly
        "The polynomial 0x04C11DB7 is no longer used; use 0x1021."
        -> 0x04C11DB7, the retired one. A CRC that will not interoperate.

Note the first is a PREDICATE, not a keyed write, so no widening of this
census's predicate would ever reach it. The harm is the same: a denied statement
read as an assertion.

AND 262 IS NOT 262 DEFECTS. Sampled by hand at this tip, several of these
DECLINE rather than lie, because a denial usually creates the contradiction
their own ambiguity guard already refuses:

    behavioral_fsm_synth::_parse_reset_level
        needs asynchronous XOR synchronous. A sentence retiring the async reset
        names both, so it returns None -- no value, rather than the wrong one.
    cellular_automaton_synth::_extract_rule
        "Rule 110 is no longer used. Implement rule 30." -> None, two rules
        seen and neither trusted.

That is not a fix -- a correct value is still lost, and an honest None is not a
repair -- but it is not the harm either, and counting it as one would inflate
the number the same way the HDL caveat inflates the census. Each entry needs
reading, and generic fixtures do not reach most of them: these functions have
specific phrasing contracts, and a probe that misses the pattern reports a
silence it caused itself.

THIS IS NOT A LIST TO ACT ON, and that is the point of keeping it out of the
count. 231 is unreadable, and a census nobody reads records nothing -- the
narrower predicate here is what made seven defects findable by reading 46. The
number is recorded so the next person knows the census is a WINDOW on the
problem and not its measure, and does not mistake `newly_visible` going to zero
for the problem being over.

Reproduce with `--wider`, which prints the list and the count. (An earlier
hand-written probe said 231: it required `finditer` or `re.search` literally and
missed `RX.search(text)` on a compiled pattern, which is the common spelling.
The flag is the reproducible number and this paragraph now quotes it -- two
figures for one question is the drift this file corrects everywhere else.)


A THIRD SPELLING EXISTS, AND IS REFUSED
=======================================
`out.append({...})` -- a list of records -- writes a declared value as surely as
a dict entry does, and neither the gate nor this census counts it. Widening to
it was measured rather than argued:

    census as it stands                 : 259
    + `append({...})` counted as a write: 781   (522 more)

Refused. The two spellings this census does add are KEYED writes -- a dict entry
and a set-add under a key -- and the key is where the discrimination comes from:
a function that writes `out[name] = value` is publishing THAT name's value.
`append` drops the key, so the predicate stops selecting extractors and starts
selecting every parser that builds records, most of them reading RTL, DEF or
SPICE.

The point of this file is a list short enough for a human to READ, and seven
defects came out of reading 46. Nobody reads 781, and a number nobody reads
records no debt at all -- it would convert a working instrument into a statistic.

If the keyed spellings are ever exhausted, the honest way to reach `append` is a
predicate that keeps the key -- `append({"name": X, "value": Y})` with a literal
key -- not the bare call.


WHAT READING THEM ACTUALLY FOUND
================================
The count is a shape; the defects are what a human finds by reading. Every entry
whose input could be a document was read at this branch's tip. SEVEN were real,
and all seven are repaired on their own branches:

    spec_numeric_pack_extract::_detect_width_pairs
        "The path from 8-bit to 16-bit is no longer supported." returned as an
        EXPLICIT stated width pair.
    conv_encoder_synth::_parse_generators
        'g1 = "111" is no longer used.' -> g1 = 111, deciding which encoder is
        SYNTHESISED.
    accumulate_synth, arith_variants_synth, saturate_synth, serdes_decode_synth,
    shift_counter_synth :: _param_defaults
        "parameter WIDTH = 8 is no longer used. Use parameter WIDTH = 16."
        -> WIDTH = 8.

In every one, `setdefault` keeps the FIRST match, so a retired value stated
before the live one did not add a wrong entry -- it TOOK THE RIGHT ONE'S PLACE.

THE CAVEAT CUT THE WRONG WAY FOR FIVE OF THOSE SEVEN, which is why it is printed
and never subtracted. The five `_param_defaults` were in the HDL-shaped bucket,
flagged because a pattern says `parameter`, and I had written them off as
Verilog from the regex alone. They take `prompt: str`, and their FIRST pattern
is plain English -- `WIDTH ... default value of 5`. Prose readers with a
Verilog-shaped pattern third in the list. An entry the heuristic flags is not
thereby safe, and this is the instance, not the argument.

The rest are structured input, each declined for a stated reason:

    _families                   a list of port NAMES; an identifier has no
                                surrounding sentence to deny it
    _acknowledged               an anchored commit TRAILER, whose presence is
                                the acknowledgement, like a signature. Asking
                                polarity would silently drop valid trailers
    _check_sta                  its keywords filter FILENAMES, not report prose
    parse_transcript,           anchored machine output
      parse_meas_delays,
      parse_path_meas
    _find_advanced_pointers,    RTL: non-blocking assignments, `localparam`
      _parse_state_localparams,   declarations, Verilog parameter expressions
      _parse_module_params,
      _build_sync_chain
    parse_devices               a SPICE `.subckt` / `.model` library
    _build_*_index              module paths and identifiers

Reading is the step; this file only makes the list short enough to read.


EXIT CODES
==========
    0  the corpus was read and the census is printed. ALWAYS 0 when it could
       look, however large the number -- this records debt, it does not refuse.
    2  UNDETERMINED: it could not look, and the line NAMES what it could not
       read. Never a finding about the tree.
    3  the command line was rejected.

USAGE
-----
    prose_polarity_census.py [--programs DIR] [--json OUT]
    --json -   puts the report document on stdout and the human report on
               stderr, the spelling 34 programs in this corpus share.

--json, AND WHAT IT CARRIES
---------------------------
    tool                 this program's name
    corpus               what was SCANNED: {"programs": P, "unreadable": U}
    gate_census          what the gate's own predicate finds (its baseline size)
    census               what the sharper predicate finds
    newly_visible        the difference, named -- the debt this file exists for
    newly_visible        the debt: blind, and nothing says why
    code_shaped          of `newly_visible`, those whose own literals name an
                         HDL/layout/netlist construct. A CAVEAT on the number,
                         never subtracted from it: `parameter WIDTH = 8;` cannot
                         be denied by a sentence, so the polarity question does
                         not arise -- but telling prose from code needs a human
                         read, and a heuristic that silently dropped them would
                         invent a precision it does not have.
    declared_in_place    blind, and the function's own docstring ARGUES that it
                         is deliberate. Named on every run, never hidden --
                         classified, because "designed this way" and "nobody
                         looked" are different facts and had one number.
    unreadable           sources that would not parse: "<name>: <reason>"
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

import re

import prose_polarity_consulted_check as _gate
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

#: Captured at import, BEFORE anything can patch the module attribute.
_GATE_DERIVED_NAMES = _gate._match_derived_names

#: A function may DECLARE, in its own docstring, that it deliberately does not
#: consult polarity -- and the census then reports it separately from the
#: extractors where nobody looked. Two entirely different facts had one number.
#:
#: THIS IS SAFE HERE AND WOULD NOT BE SAFE IN THE GATE, which is the whole
#: reason it lives on this side. A self-declared reason is a loophole exactly
#: when escaping the count buys something; this census cannot refuse, so it buys
#: nothing. The gate keeps a REGISTER with a reviewed reason for the same job,
#: because there the escape is worth having.
#:
#: The declared ones are still NAMED on every run. Classified, never hidden.
_DECLARED_RE = re.compile(r"NOT ASKED FOR POLARITY|POLARITY IS NOT ASKED",
                          re.I)
#: A marker on a one-line docstring is an assertion, not an argument. The gate's
#: exemption register sets its own floor at 80 characters for a reason.
_DECLARED_REASON_MIN = 200

#: The WIDER question, behind `--wider`: not "what write shape is this" but
#: "what is this function FED". A function whose first parameter is named for a
#: document and which matches a regex against it is reading prose, whatever it
#: does with the result -- including a PREDICATE, which no write-shape widening
#: can ever reach.
_DOC_ARGS = ("prompt", "spec", "spec_text", "doc", "doc_text", "md")
_CONSULT_TOKENS = ("is_denied", "sentence_scope", "NEGATION_RE",
                   "DENIAL_RETIRED_RE", "DENIAL_CORE_RE", "_negated")

#: A CAVEAT, NEVER A FILTER. The predicate above matches a SHAPE -- a regex over
#: text, a declared value written, no polarity consulted -- and that shape is
#: also what a parser of Verilog, LEF/DEF, Liberty or SPICE looks like. A
#: `parameter WIDTH = 8;` cannot be denied by a surrounding sentence, so for
#: those the polarity question does not arise at all and the entry is not debt.
#:
#: Sampled by hand at this tip: `saturate_synth::_param_defaults` matches
#: `parameter\s+...=\s*(\d+)` and `reset_discipline_check::analyse_module`
#: matches `\bif\s*\(([^)]*)\)`. Both are code. Neither is debt.
#:
#: So the census PRINTS this split and does not act on it. Judging prose from
#: code needs a human read of what the function is pointed at, and a keyword
#: heuristic that silently dropped a third of the count would be inventing a
#: precision it does not have -- while hiding any genuine prose extractor that
#: happens to mention a net or a pin.
_HDL_SHAPED = re.compile(
    r"\b(parameter|localparam|module|endmodule|always|assign|wire|reg|input|"
    r"output|posedge|negedge|instance|net|pin|via|layer|lef|liberty|spice|"
    r"subckt|measure)\b", re.I)

TOOL = "prose_polarity_census"
RC_OK, RC_UNDETERMINED, RC_USAGE = 0, 2, 3


def _exempt() -> Set[str]:
    """The gate's own exemption register, read and never extended here.

    A census that could exempt would be a register with two authors, and the
    second one is always the one in a hurry."""
    reg = getattr(_gate, "_NOT_PROSE", {})
    return set(reg) if isinstance(reg, dict) else set(reg or ())


def derived_names(fn: ast.AST) -> Set[str]:
    """The gate's derived-match names, PLUS matches bound by a `for` target.

    `_match_derived_names` walks `ast.Assign` only, so `for m in RE.finditer(s)`
    never enters it and every write derived from `m` is invisible. Widening it
    is the first of the two spellings this census exists to see."""
    names = set(_GATE_DERIVED_NAMES(fn))   # the ORIGINAL, never the
    #                                       patched attribute: calling
    #                                       through the module here
    #                                       recurses forever once this
    #                                       function is installed as it
    for n in ast.walk(fn):
        if (isinstance(n, ast.For) and isinstance(n.target, ast.Name)
                and isinstance(n.iter, ast.Call)
                and getattr(n.iter.func, "attr", "") == "finditer"):
            names.add(n.target.id)
    return names


def writes_a_declared_value(fn: ast.AST) -> bool:
    """The gate's write test, PLUS `container.setdefault(K, set()).add(V)`.

    The gate reads `setdefault`'s DEFAULT argument, which is the empty set, and
    not the value pushed into the container it returns -- so the whole
    accumulate-into-a-set idiom writes a declared value invisibly."""
    if _gate._writes_a_declared_value(fn):
        return True
    for n in ast.walk(fn):
        if (isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "add"
                and isinstance(n.func.value, ast.Call)
                and getattr(n.func.value.func, "attr", "") == "setdefault"):
            return True
    return False


def looks_like_a_code_parser(fn: ast.FunctionDef,
                            module: ast.Module | None = None) -> bool:
    """True when the text this function matches on names an HDL, layout or
    netlist construct -- a CAVEAT on the count, never a filter on it.

    THE PATTERN IS USUALLY NOT INSIDE THE FUNCTION. `PAT = re.compile(r"...")`
    at module level and `PAT.finditer(text)` in the body is the common idiom,
    and reading only the function's own literals found NOTHING for it -- the
    first version of this check missed a fixture built exactly that way and
    failed on unmutated code. So the module-level constants the function
    actually REFERENCES are resolved too.

    Referenced ones only, not every literal in the file: a module that parses
    Verilog somewhere else would otherwise tar every function in it."""
    lits = [n.value for n in ast.walk(fn)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    if module is not None:
        used = {n.id for n in ast.walk(fn)
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        for node in module.body:
            if not isinstance(node, ast.Assign):
                continue
            targets = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if not targets & used:
                continue
            lits += [c.value for c in ast.walk(node.value)
                     if isinstance(c, ast.Constant) and isinstance(c.value, str)]
    return bool(_HDL_SHAPED.search(" ".join(lits)))


def reads_a_document(fn: ast.FunctionDef) -> bool:
    """True when this function is FED a document and matches a regex on it."""
    args = [a.arg for a in fn.args.args]
    if not args or args[0] not in _DOC_ARGS:
        return False
    src = ast.unparse(fn)
    return "finditer" in src or "re.search" in src or ".search(" in src


def consults_anything(fn: ast.FunctionDef) -> bool:
    """Any polarity vocabulary at all, by any spelling this tree uses."""
    src = ast.unparse(fn)
    return any(tok in src for tok in _CONSULT_TOKENS)


def declares_a_reason(fn: ast.FunctionDef) -> bool:
    """True when this function ARGUES, in its own docstring, that it does not
    consult polarity on purpose.

    The reason lives with the code rather than in a register, so it cannot rot
    separately from the function it describes -- and it has to be an argument,
    not a marker: a bare token on a one-line docstring does not clear
    `_DECLARED_REASON_MIN`."""
    doc = ast.get_docstring(fn) or ""
    return bool(_DECLARED_RE.search(doc)) and len(doc) >= _DECLARED_REASON_MIN


def blind_in(tree: ast.Module, stem: str, *, sharp: bool) -> List[str]:
    """`[stem::fn]` for every extractor in one module that consults nothing."""
    aliases = _gate._aliases(tree)
    writes = writes_a_declared_value if sharp else _gate._writes_a_declared_value
    out: List[str] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        if not _gate._searches_prose(fn):
            continue
        if not writes(fn):
            continue
        if _gate._consults_polarity(fn, aliases):
            continue
        out.append(f"{stem}::{fn.name}")
    return out


def census_of(programs: Path) -> Tuple[List[str], List[str], List[str]]:
    """`(sharp, gate_only, unreadable)` over a directory of programs.

    THE `for`-TARGET WIDENING IS INSTALLED, NOT MERELY DEFINED. The gate's
    `_writes_a_declared_value` calls `_match_derived_names` itself, so a wider
    version has to replace the one it calls -- defining `derived_names` and
    passing it nowhere left it dead, and the census reported 19 newly visible
    instead of 46 while looking exactly as though it worked. Scoped to the sharp
    pass and restored in `finally`, because a module attribute left patched is
    the next reader's mystery."""
    exempt = _exempt()
    trees: List[Tuple[str, ast.Module]] = []
    unreadable: List[str] = []
    for p in sorted(programs.glob("*.py")):
        try:
            trees.append((p.stem,
                          ast.parse(p.read_bytes().decode("utf-8",
                                                          errors="replace"))))
        except SyntaxError as e:
            unreadable.append(f"{p.name}: line {e.lineno}: {e.msg}")
        except OSError as e:
            unreadable.append(f"{p.name}: {e.strerror or e}")

    narrow = [n for stem, t in trees
              for n in blind_in(t, stem, sharp=False) if n not in exempt]

    original = _gate._match_derived_names
    try:
        _gate._match_derived_names = derived_names
        sharp = [n for stem, t in trees
                 for n in blind_in(t, stem, sharp=True) if n not in exempt]
    finally:
        _gate._match_derived_names = original
    return sorted(sharp), sorted(narrow), unreadable


def main(argv: List[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(
        prog=TOOL, description="census of prose extractors that do not consult "
                               "polarity, with a predicate sharper than the gate's")
    ap.add_argument("--programs", type=Path, default=here)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--wider", action="store_true",
                    help="list functions FED a prompt/spec/doc that consult no "
                         "polarity — a different question from the census, and "
                         "a longer list; see THE SIZE OF THE PROBLEM")
    args = ap.parse_args(argv)

    if not args.programs.is_dir():
        print(f"USAGE_ERROR: {TOOL}: --programs {args.programs} is not a "
              f"directory", file=sys.stderr)
        return RC_USAGE
    if args.json is not None and str(args.json) != "-" and args.json.is_dir():
        print(f"USAGE_ERROR: {TOOL}: --json {args.json} is a directory",
              file=sys.stderr)
        return RC_USAGE

    sources = sorted(args.programs.glob("*.py"))
    if args.wider:
        blind_docs: List[str] = []
        for src_path in sources:
            try:
                t = ast.parse(src_path.read_bytes().decode("utf-8", "replace"))
            except (SyntaxError, OSError):
                continue
            for fn in ast.walk(t):
                if (isinstance(fn, ast.FunctionDef) and reads_a_document(fn)
                        and not consults_anything(fn)):
                    blind_docs.append(f"{src_path.stem}::{fn.name}")
        for name in sorted(blind_docs):
            print(f"  [FED A DOCUMENT] {name}")
        print(f"[WIDER] {TOOL}: {len(blind_docs)} function(s) are FED a "
              f"prompt/spec/doc and consult no polarity, over "
              f"{len(sources)} program(s). A DIFFERENT QUESTION from the census "
              f"above: this asks what a function is fed, not what shape it "
              f"writes, so it reaches PREDICATES that no write-shape widening "
              f"can. It is not a defect list -- each entry needs reading.")
        return RC_OK
    sharp, narrow, unreadable = census_of(args.programs)
    newly_all = sorted(set(sharp) - set(narrow))
    declared: List[str] = []
    code_shaped: List[str] = []
    for name in newly_all:
        stem, _, fname = name.partition("::")
        src = args.programs / f"{stem}.py"
        try:
            tree = ast.parse(src.read_bytes().decode("utf-8", errors="replace"))
        except (SyntaxError, OSError):
            continue
        fn = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                   and n.name == fname), None)
        if fn is None:
            continue
        if declares_a_reason(fn):
            declared.append(name)
        elif looks_like_a_code_parser(fn, tree):
            code_shaped.append(name)
    newly = [n for n in newly_all if n not in declared]

    report: Dict[str, object] = {
        "tool": TOOL,
        "corpus": {"programs": len(sources), "unreadable": len(unreadable)},
        "gate_census": len(narrow),
        "census": len(sharp),
        "newly_visible": newly,
        "declared_in_place": declared,
        "code_shaped": code_shaped,
        "unreadable": unreadable,
    }
    to_stderr = False
    if args.json is not None:
        if str(args.json) == "-":
            print(json.dumps(report, indent=2))
            to_stderr = True
        else:
            try:
                # ATOMIC (vibe-ic#1082): this is the DECLARED report a
                # later reader resolves, so the final name must appear
                # only once the write is complete. The helper raises the
                # same OSError this block already handles.
                atomic_write_text(args.json,
                                  json.dumps(report, indent=2) + "\n",
                                  encoding="utf-8")
            except OSError as e:
                print(f"USAGE_ERROR: {TOOL}: --json {args.json} could not be "
                      f"written: {e.strerror or e}", file=sys.stderr)
                return RC_USAGE
    out = sys.stderr if to_stderr else sys.stdout

    if not sources:
        print(f"[CANNOT DETERMINE] {TOOL}: {args.programs} holds no program at "
              f"all, so this is not a statement about any tree", file=out)
        return RC_UNDETERMINED

    for u in unreadable:
        print(f"  [UNPARSED] {u} — not examined, so it is not in the count "
              f"below", file=out)
    for n in declared:
        print(f"  [DECLARED] {n} — blind, and its own docstring argues that "
              f"this is deliberate. Counted apart from the debt, not hidden "
              f"from it", file=out)
    for n in newly:
        print(f"  [DEBT] {n} — reads prose, writes a declared value and "
              f"consults no polarity. Invisible to the gate because of how the "
              f"write is SPELLED, not because it is safe", file=out)
    print(f"[CENSUS] {TOOL}: {len(sharp)} polarity-blind extractor(s) under the "
          f"sharper predicate, {len(narrow)} under the gate's own, so "
          f"{len(newly_all)} the gate cannot see, of which {len(declared)} "
          f"DECLARE the omission in place and {len(newly)} say nothing "
          f"[{len(sources)} program(s) "
          f"SCANNED; {len(unreadable)} NOT examined because they would not "
          f"parse]. THIS RECORDS DEBT AND NEVER REFUSES.", file=out)
    if newly:
        print(f"[CALIBRATION] {len(code_shaped)} of those {len(newly)} match on "
              f"an HDL/layout/netlist construct in the text they match on, where "
              f"a denial cannot arise and the entry is not debt. This number is "
              f"an UPPER BOUND on a SHAPE. The split is printed and never "
              f"subtracted: telling prose from code needs a human read.",
              file=out)
    return RC_OK


if __name__ == "__main__":
    raise SystemExit(main())
