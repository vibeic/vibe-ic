#!/usr/bin/env python3
"""spec_worked_example_extract.py — PROGRAM-FIRST structural worked-example /
latency extractor for CVDP worked-example-style prompts.

WHY THIS EXISTS
  A WORKED EXAMPLE — a STATED concrete `input X -> output Y` pair (a real numeric
  vector, or an `| in | out |` example-table row) — is the STRONGEST coverage
  anchor (§3.9): it becomes, verbatim, a TB golden assertion. The prose-heuristic
  `worked_example` / `latency` kinds already in `spec_coverage_check.py` catch the
  bare `X -> Y` / `X = Y` micro-pattern, but they are NOT anchored to the LABELED
  example STRUCTURE that CVDP "worked-example" prompts actually use:

    * an "Example N" / "Example of Usage" block whose **Input:** lines list the
      stimulus values and whose **Output:** lines list the expected results;
    * a step-of-operation block "Clock Cycle k: ... after the edge fib_out = 1";
    * a markdown example table `| input | output |` with concrete value rows.

  This program is the STRUCTURALLY-anchored counterpart: each emitted
  `worked_example` item's evidence is a concrete input->output example, and its
  `requirement` is the golden TB assertion ("TB must assert in=X produces out=Y").

WHAT IT DOES  (DETERMINISTIC, pure-structural; chip-AGNOSTIC)
  extract(prompt_text) -> list[dict], each dict shaped like a `ChecklistItem`
  (kind / requirement / evidence, plus structural extras), for:

  (1) WORKED EXAMPLES — one `worked_example` item per stated input->output pair:
        a. labeled blocks: an "Example"/"Outputs After ..."/"Clock Cycle k"
           heading that groups `name = VALUE` input assignments with
           `name = VALUE` output assignments (or an `Operation: a x b = c` line);
        b. inline arrows: `for input 0x3, the output is 0b1010`, `a=5,b=3 => sum=8`,
           `f(3) = 9`;
        c. example tables: a markdown `| in | out |` table whose data rows hold
           concrete numeric literals.
      evidence = the exact example text; requirement = "TB must assert ... =>...".

  (2) LATENCY — one `latency` item per stated cycle count:
        "output valid after N clock cycles", "the pipeline latency is 1 clock
        cycle", "latency is three clock cycles", "L-cycle pipeline",
        "multiplication takes 1 clock cycle". The number N (digit or number-word)
        is recorded in `latency_cycles`.

  §4.05 NO-LEAK: emit ONLY for a CONCRETE stated example/number. Vague
  "produces the result" / "compute the output" with NO numeric pair and NO stated
  cycle count -> return []. Every emitted item is anchored to a structural feature
  (a real value pair / a digit-or-number-word cycle count), never invented from
  free prose.

chip-AGNOSTIC: pure example/latency grammar; NO chip / vendor / SKU literal
(enforced by `programs/source_chip_agnostic_check.py .`).

CLI
    python3 spec_worked_example_extract.py PROMPT_FILE [PROMPT_FILE ...]
    python3 spec_worked_example_extract.py --text "for input 0x3 the output is 5"
    (add --json for machine-readable output)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Dict, List, Optional, Tuple

# A concrete VALUE literal: sized Verilog (16'd10, 32'h00000005, 2'b10), hex/bin
# (0x3, 0b1010), or a plain decimal (possibly negative). This is the structural
# anchor for "concrete" — a worked-example pair is emitted only when both halves
# carry such a literal. chip-AGNOSTIC.
_NUM = (
    r"(?:[-+]?\d+'[sS]?[bdhoBDHO][0-9A-Fa-fxXzZ_]+"   # 16'd10 / 2'b10 / 32'h0F
    r"|[-+]?0[xXbB][0-9A-Fa-f_]+"                      # 0x3 / 0b1010
    r"|[-+]?\d+(?![\d']))"                              # plain decimal / -7;
    # the (?![\d']) forces a MAXIMAL digit run AND rejects a MALFORMED sized
    # literal missing its base char ("16'200", a source typo) — preventing a
    # bogus partial value `1` from being back-tracked out of `16'200`.
)
_NUM_RE = re.compile(_NUM)
# A `{ a, b, c }` packed value list (each member a literal) — used in the LPF
# "Example of Usage" `data_in = {16'd10, ...}` form. Treated as ONE value blob.
_BRACE_VALUES_RE = re.compile(r"\{[^{}]*\}")
# An assignment `name = VALUE` (VALUE = a literal or a brace value-list). The name
# is an identifier; the value side must START with a literal/brace so prose
# ("state = IDLE") is rejected unless IDLE-like — handled by the value test.
_ASSIGN_RE = re.compile(
    r"`?([A-Za-z_]\w*)`?\s*(?:=|:)\s*"
    r"(\{[^{}]*\}|" + _NUM + r")")

# Inline arrow form: `<X> -> <Y>` / `=>` / `→`, or the worded
# "for input X, the output is Y" / "input X produces output Y".
_ARROW_RE = re.compile(
    r"(" + _NUM + r")\s*(?:->|=>|→|⇒)\s*(" + _NUM + r")")
_WORDED_IO_RE = re.compile(
    r"\b(?:for\s+)?(?:input|in)\b[^.;:\n]*?(" + _NUM + r")"
    r"[^.;:\n]*?\b(?:the\s+)?(?:output|out|result|gives?|yields?|produces?|"
    r"becomes?|is)\b[^.;:\n]*?(" + _NUM + r")",
    re.IGNORECASE)
# An arithmetic worked example `a x b = c`, `5 * 4 = 20`, `f(3) = 9`, `1 + 0 = 1`.
# Both operands and the result are concrete literals joined by an arithmetic
# operator and an '='. (The plain `X = Y` with NO operator is an encoding legend,
# not a data pair — excluded; the arrow / labeled-block forms cover real pairs.)
_ARITH_OP = r"(?:[x×*+\-/]|<<|>>|&|\||\^)"
_ARITH_EXAMPLE_RE = re.compile(
    r"((?:" + _NUM + r"\s*" + _ARITH_OP + r"\s*)+" + _NUM + r")"
    r"\s*=\s*(" + _NUM + r")")
# `f(3) = 9`, `F(2) = 1` — a function-application example (arg -> result).
_FUNC_EXAMPLE_RE = re.compile(
    r"\b([A-Za-z_]\w*)\s*\(\s*(" + _NUM + r")\s*\)\s*=\s*(" + _NUM + r")")

# --- Latency -------------------------------------------------------------
_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12,
}
_NUMWORD = r"(?:\d+|" + "|".join(_NUMBER_WORDS) + r")"
# "<N> clock cycle(s)" / "latency ... is <N> cycle(s)" / "<N>-cycle pipeline" /
# "takes <N> cycle(s)" / "after <N> clock cycles" / "every <N> cycles".
_LATENCY_RES: Tuple[re.Pattern, ...] = (
    re.compile(
        r"\blatency\b[^.;:\n]*?\bis\b[^.;:\n]*?(" + _NUMWORD +
        r")\s*[- ]?(?:clock\s+)?cycles?\b", re.IGNORECASE),
    re.compile(
        r"\b(?:after|over|takes?|within|in)\b\s+(" + _NUMWORD +
        r")\s*[- ]?(?:clock\s+)?cycles?\b", re.IGNORECASE),
    re.compile(
        r"\bvalid\b[^.;:\n]*?\bafter\b\s+(" + _NUMWORD +
        r")\s*[- ]?(?:clock\s+)?cycles?\b", re.IGNORECASE),
    re.compile(
        r"\b(" + _NUMWORD + r")\s*[- ]?(?:clock\s+)?cycles?\s+"
        r"(?:of\s+)?(?:latency|pipeline)\b", re.IGNORECASE),
    re.compile(
        r"\b(" + _NUMWORD + r")\s*[- ]?cycle\s+pipeline\b", re.IGNORECASE),
    re.compile(
        r"\b(?:latency|pipeline\s+latency)\b[^.;:\n]{0,40}?(" + _NUMWORD +
        r")\s*[- ]?(?:clock\s+)?cycles?\b", re.IGNORECASE),
)
# A "Outputs After N Clock Cycles" heading is a WORKED-EXAMPLE sub-label (it scopes
# which output values apply), NOT a pipeline-latency statement. A latency match
# whose own line is such a heading is suppressed (§4.05: don't manufacture a
# phantom latency from an example sub-heading). chip-AGNOSTIC.
_OUTPUTS_AFTER_HEADING_RE = re.compile(
    r"\boutputs?\s+after\b", re.IGNORECASE)
# A latency statement is only meaningful when the surrounding text actually talks
# about cycles/latency/pipeline — guaranteed by the patterns above (each names
# "cycle"/"latency"/"pipeline"), so §4.05 holds: a bare number never becomes a
# latency item.


def _norm_num(tok: str) -> str:
    """Canonicalise a numeric token for de-duplication (strip backticks/space)."""
    return tok.strip().strip("`").replace(" ", "")


def _word_to_int(tok: str) -> Optional[int]:
    t = tok.strip().lower()
    if t.isdigit():
        return int(t)
    return _NUMBER_WORDS.get(t)


def _looks_like_value(s: str) -> bool:
    """True iff `s` is a concrete value literal or a brace value-list of them."""
    s = s.strip()
    if _BRACE_VALUES_RE.fullmatch(s):
        return bool(_NUM_RE.search(s))
    return bool(_NUM_RE.fullmatch(s))


# Output-side port-name hints, so a labeled block's assignments can be split into
# inputs vs outputs WITHOUT a chip-specific name list: an assignment is an OUTPUT
# when it sits under an "Output(s)" sub-heading/label, else an INPUT under
# "Input(s)". The heading words are generic English, not design literals.
_INPUT_LABEL_RE = re.compile(r"\b(?:input|inputs|stimulus|operand)\b", re.IGNORECASE)
_OUTPUT_LABEL_RE = re.compile(
    r"\b(?:output|outputs|result|results|expected|after\s+\d|"
    r"after\s+(?:one|two|three|four|five)\s+clock)\b", re.IGNORECASE)
# An "Example"/worked block heading — starts a TOP-LEVEL worked-example region.
# Deliberately does NOT include "Outputs After ..." — that is a SUB-label INSIDE
# an "Example of Usage" block (it scopes which outputs apply at cycle k); starting
# a new block there would split the example's Inputs from its Outputs.
_EXAMPLE_HEADING_RE = re.compile(
    r"^\s*(?:[#*\-\s]*)?(?:\*{0,2})\s*"
    r"(?:example(?:\s+(?:of\s+usage|operations?))?|"
    r"worked\s+example|clock\s+cycle|"
    r"initial\s+state)\b",
    re.IGNORECASE | re.MULTILINE)


def _heading_level(line: str) -> int:
    """Markdown ATX heading level (1..6), or 0 if the line is not a heading."""
    m = re.match(r"\s*(#{1,6})\s+\S", line)
    return len(m.group(1)) if m else 0


def _block_body_end(seg: str) -> int:
    """Cut a sliced block body at its natural terminator so the example does not
    swallow a trailing code fence or an unrelated sibling/parent section. The body
    ends at:
      * the first ``` code-fence line (a partial-code / answer block); OR
      * a markdown heading at a level <= the block's OWN heading level (a sibling
        or parent section) that is NOT itself an Example / Initial-state heading.
    A DEEPER sub-heading (`#### Parameters`, `#### Inputs`, `#### Outputs` under a
    `### Example of Usage`) is PART of the example and never terminates it.
    chip-AGNOSTIC: pure markdown-structure grammar."""
    lines = seg.splitlines(keepends=True)
    own_level = _heading_level(lines[0]) if lines else 0
    pos = 0
    for idx, line in enumerate(lines):
        s = line.strip()
        if idx > 0 and s.startswith("```"):
            return pos
        lvl = _heading_level(line)
        if idx > 0 and lvl and own_level and lvl <= own_level:
            head = s.lstrip("#").strip().lower()
            if not re.search(r"\bexample|clock\s+cycle|initial\s+state", head):
                return pos
        pos += len(line)
    return len(seg)


def _split_blocks(text: str) -> List[Tuple[str, str]]:
    """Slice the prompt at each Example/worked-block heading; return
    (heading_line, block_body) pairs. The body runs to the next example heading,
    bounded by the first code fence / unrelated section heading. chip-AGNOSTIC."""
    starts = [m.start() for m in _EXAMPLE_HEADING_RE.finditer(text)]
    if not starts:
        return []
    starts.append(len(text))
    blocks: List[Tuple[str, str]] = []
    for i in range(len(starts) - 1):
        seg = text[starts[i]:starts[i + 1]]
        seg = seg[:_block_body_end(seg)]
        nl = seg.find("\n")
        heading = seg[:nl] if nl >= 0 else seg
        blocks.append((heading.strip(), seg))
    return blocks


def _is_gloss_enclosed(line: str, pos: int) -> bool:
    """True iff the assignment starting at `pos` sits inside a parenthetical /
    brace-legend gloss — `(A_im = 3, A_re = 2)` or `{Imaginary = 0x14, Real = 0xF9}`.
    Counts unbalanced `(`/`{...=...}` openers before `pos` on the same line. A
    pure value-list brace `{16'd10, 16'd50}` carries NO `=` inside, so it is not
    an enclosure for the OUTER assignment's value. chip-AGNOSTIC."""
    prefix = line[:pos]
    if prefix.count("(") > prefix.count(")"):
        return True
    # an open brace whose content holds an '=' (a legend gloss), not a value-list.
    depth = 0
    for i, ch in enumerate(prefix):
        if ch == "{":
            depth += 1
            close = line.find("}", i)
            seg = line[i:close] if close >= 0 else line[i:]
            if depth > 0 and "=" in seg and i < pos and (close < 0 or close > pos):
                return True
        elif ch == "}":
            depth = max(0, depth - 1)
    return False


def _block_pairs(block: str) -> List[Tuple[List[str], List[str], str]]:
    """From one worked-example block, pair the INPUT assignments with the OUTPUT
    assignments, splitting by Input:/Output: sub-labels (line-scoped). Returns a
    list of (input_strs, output_strs, evidence) — usually ONE pair per block, but
    an `Operation: a x b = c` line is emitted as its own arrow-style pair too.
    chip-AGNOSTIC: generic Input/Output label grammar + literal assignments."""
    inputs: List[str] = []
    cur_out: List[str] = []
    cur_out_label = ""
    out: List[Tuple[List[str], List[str], str]] = []
    mode = "input"   # blocks usually list inputs then outputs

    def _flush_outputs():
        # pair the accumulated inputs with ONE output sub-group (so distinct
        # "Outputs After 1/2 Clock Cycles" snapshots become DISTINCT examples).
        if inputs and cur_out:
            ev = (cur_out_label + ": " if cur_out_label else "") + \
                ", ".join(inputs) + " => " + ", ".join(cur_out)
            out.append((list(inputs), list(cur_out), ev))

    for line in block.splitlines():
        low = line.lower()
        has_assign = bool(_ASSIGN_RE.search(line))
        if _OUTPUT_LABEL_RE.search(low) and not has_assign:
            # a NEW output sub-group begins — flush the previous one.
            _flush_outputs()
            cur_out = []
            cur_out_label = re.sub(r"\s+", " ", line.strip().strip("#*-: ")).strip()
            mode = "output"
            continue
        if _INPUT_LABEL_RE.search(low) and not has_assign:
            mode = "input"
            continue
        for am in _ASSIGN_RE.finditer(line):
            val = am.group(2)
            if not _looks_like_value(val):
                continue
            # §4.05: an assignment ENCLOSED in (...) is an explanatory gloss of an
            # already-stated port value ("vector_a_in = 32'h00030002 (A_im = 3,
            # A_re = 2)"), not an independent port stimulus — skip it so the golden
            # vector is the real top-level ports only. A brace value-LIST is itself
            # a value, so the assignment's OWN braces don't count as enclosure;
            # only `(...)` and a `{ ... = ... }` legend gloss are stripped.
            if _is_gloss_enclosed(line, am.start()):
                continue
            entry = f"{am.group(1)} = {val.strip()}"
            (cur_out if mode == "output" else inputs).append(entry)
    _flush_outputs()
    return out


def _example_id(heading: str, n: int) -> str:
    m = re.search(r"example\s*\d*|clock\s+cycle\s*\d*|outputs?\s+after[^,\n]*",
                  heading, re.IGNORECASE)
    label = m.group(0).strip() if m else f"example {n}"
    return re.sub(r"\s+", " ", label)


# --- Example tables ------------------------------------------------------
def _table_examples(text: str) -> List[Dict]:
    """Markdown `| in | out |` example tables: a header row whose columns name
    an input and an output, then data rows that hold concrete value literals.
    One worked_example item per data row. chip-AGNOSTIC."""
    items: List[Dict] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.count("|") < 2:
            i += 1
            continue
        header = [c.strip() for c in line.strip().strip("|").split("|")]
        low = [h.lower() for h in header]
        in_cols = [j for j, h in enumerate(low)
                   if re.search(r"\b(in|input|inputs|stimulus|operand|a|b|x)\b", h)]
        out_cols = [j for j, h in enumerate(low)
                    if re.search(r"\b(out|output|outputs|result|expected|y|sum)\b", h)]
        # need a separator row of dashes next, and at least one in + one out col
        if (in_cols and out_cols and i + 1 < len(lines)
                and re.fullmatch(r"[\s|:\-]+", lines[i + 1].strip())):
            j = i + 2
            while j < len(lines) and lines[j].count("|") >= 2:
                cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
                if len(cells) == len(header):
                    in_vals = [cells[k] for k in in_cols
                               if k < len(cells) and _NUM_RE.search(cells[k])]
                    out_vals = [cells[k] for k in out_cols
                                if k < len(cells) and _NUM_RE.search(cells[k])]
                    if in_vals and out_vals:
                        items.append(_mk_we(
                            in_vals, out_vals, lines[j].strip(), source="table"))
                j += 1
            i = j
            continue
        i += 1
    return items


# --- Item constructors ---------------------------------------------------
def _mk_we(inputs: List[str], outputs: List[str], evidence: str,
           source: str) -> Dict:
    """Build one structurally-anchored worked_example checklist dict."""
    in_s = ", ".join(inputs)
    out_s = ", ".join(outputs)
    return {
        "kind": "worked_example",
        "requirement": f"TB must assert in={{{in_s}}} produces out={{{out_s}}}",
        "evidence": evidence.strip(),
        "example_input": inputs,
        "example_output": outputs,
        "coverage_tokens": [_norm_num(v.split("=")[-1]) for v in inputs + outputs],
        "provenance": "STRUCTURAL",
        "source": source,
    }


def _mk_latency(n: int, evidence: str) -> Dict:
    return {
        "kind": "latency",
        "requirement": f"TB must observe output latency of {n} clock cycle(s)",
        "evidence": evidence.strip(),
        "latency_cycles": n,
        "coverage_tokens": [str(n), "cycle", "@(posedge", "@(negedge"],
        "provenance": "STRUCTURAL",
        "source": "latency",
    }


# --- Public API ----------------------------------------------------------
def extract(prompt_text: str) -> List[Dict]:
    """Structurally extract worked-example input->output pairs and stated cycle
    latencies from a CVDP prompt. Returns a list of ChecklistItem-shaped dicts
    (kind / requirement / evidence + structural extras). Returns [] for a vague
    spec with no concrete example pair and no stated cycle count (§4.05)."""
    if not prompt_text:
        return []
    items: List[Dict] = []
    seen_we: set = set()
    seen_lat: set = set()

    def _add_we(inputs, outputs, evidence, source):
        in_key = tuple(_norm_num(v.split("=")[-1]) for v in inputs)
        out_key = tuple(_norm_num(v.split("=")[-1]) for v in outputs)
        key = (in_key, out_key)
        if not in_key or not out_key or key in seen_we:
            return
        seen_we.add(key)
        items.append(_mk_we(inputs, outputs, evidence, source))

    # (1a) labeled worked-example blocks (Input:/Output: grouped assignments).
    for n, (heading, body) in enumerate(_split_blocks(prompt_text), 1):
        label = _example_id(heading, n)
        for inputs, outputs, evidence in _block_pairs(body):
            ev = f"{label}: " + evidence if label.lower() not in evidence.lower() else evidence
            _add_we(inputs, outputs, ev, source="labeled_block")

    # (1b) example tables.
    for it in _table_examples(prompt_text):
        in_key = tuple(_norm_num(v) for v in it["example_input"])
        out_key = tuple(_norm_num(v) for v in it["example_output"])
        if (in_key, out_key) not in seen_we:
            seen_we.add((in_key, out_key))
            items.append(it)

    # (1c) inline arrows / worded I/O / arithmetic / function-application.
    for m in _ARROW_RE.finditer(prompt_text):
        # §4.05 STRUCTURAL-ARTIFACT suppression — when the LHS value is the SUFFIX
        # of a larger grouped / identifier token (the char immediately before it is
        # [A-Za-z_]), the `X -> Y` pair is a NOTATIONAL ARTIFACT of that token, not
        # a real input->output vector: e.g. the trailing `0111` of a grouped binary
        # `0010_0101_0111 -> 257` (the underscore breaks the numeric run so the
        # arrow regex pairs only the last nibble with the full decimal). The real
        # grouped value and its per-segment glosses are extracted elsewhere; emitting
        # this phantom as a block-eligible coverage requirement HARD-BLOCKS correct
        # RTL (ORGANIC #780 binary-to-BCD). Mirrors the legacy detector's case (A).
        s = m.start(1)
        if s > 0 and re.match(r"[A-Za-z_]", prompt_text[s - 1]):
            continue
        _add_we([m.group(1)], [m.group(2)],
                _line_of(prompt_text, m.start()), source="inline_arrow")
    for m in _WORDED_IO_RE.finditer(prompt_text):
        _add_we([m.group(1)], [m.group(2)],
                _line_of(prompt_text, m.start()), source="worded_io")
    for m in _ARITH_EXAMPLE_RE.finditer(prompt_text):
        _add_we([m.group(1).strip()], [m.group(2)],
                _line_of(prompt_text, m.start()), source="arithmetic")
    for m in _FUNC_EXAMPLE_RE.finditer(prompt_text):
        _add_we([f"{m.group(1)}({m.group(2)})"], [m.group(3)],
                _line_of(prompt_text, m.start()), source="function_apply")

    # (2) latency statements.
    for rx in _LATENCY_RES:
        for m in rx.finditer(prompt_text):
            n = _word_to_int(m.group(1))
            if n is None or n in seen_lat:
                continue
            evidence = _line_of(prompt_text, m.start())
            # §4.05: "Outputs After N Clock Cycles" is an example sub-heading, not
            # a stated pipeline latency — don't manufacture a phantom latency item.
            if _OUTPUTS_AFTER_HEADING_RE.search(evidence):
                continue
            seen_lat.add(n)
            items.append(_mk_latency(n, evidence))

    return items


def _line_of(text: str, pos: int) -> str:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    if end < 0:
        end = len(text)
    return text[start:end].strip()


# --- CLI -----------------------------------------------------------------
def _run_one(name: str, text: str, as_json: bool) -> List[Dict]:
    items = extract(text)
    if as_json:
        return items
    we = [it for it in items if it["kind"] == "worked_example"]
    lat = [it for it in items if it["kind"] == "latency"]
    print(f"=== {name} ===")
    print(f"  worked_example pairs: {len(we)}   latency items: {len(lat)}")
    for it in we:
        print(f"    [WE/{it['source']}] in={it['example_input']} "
              f"out={it['example_output']}")
        print(f"        evidence: {it['evidence'][:90]}")
    for it in lat:
        print(f"    [LATENCY] {it['latency_cycles']} cycle(s) :: "
              f"{it['evidence'][:80]}")
    print(f"  recovered: {len(items)} item(s)\n")
    return items


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Structural worked-example / latency extractor (CVDP).")
    ap.add_argument("prompts", nargs="*", help="prompt file(s)")
    ap.add_argument("--text", help="extract from a literal string instead")
    ap.add_argument("--json", action="store_true",
                    help="emit machine-readable JSON")
    args = ap.parse_args(argv)

    total = 0
    out_json: Dict[str, List[Dict]] = {}
    if args.text is not None:
        items = _run_one("<text>", args.text, args.json)
        out_json["<text>"] = items
        total += len(items)
    for p in args.prompts:
        try:
            text = open(p, encoding="utf-8", errors="replace").read()
        except OSError as e:
            print(f"ERROR reading {p}: {e}", file=sys.stderr)
            return 2
        import os
        items = _run_one(os.path.basename(p), text, args.json)
        out_json[p] = items
        total += len(items)
    if args.json:
        print(json.dumps(out_json, indent=2))
    elif args.prompts or args.text is not None:
        print(f"TOTAL recovered across {len(out_json)} prompt(s): {total} item(s)")
    else:
        ap.print_help()
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
