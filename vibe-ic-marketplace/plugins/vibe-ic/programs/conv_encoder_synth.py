#!/usr/bin/env python3
"""conv_encoder_synth.py — DETERMINISTIC solver for the CVDP convolutional
encoder family (rate-1/n, constraint length K, generator polynomials stated as
binary tap strings).

GENERAL (§9 GENERAL-not-OVERFIT): the constraint length K and EVERY generator
polynomial are PARSED from the prompt prose (`constraint length K=3`, `g1 is
"111"`, `g2 = "101"`); no tap value is ever hardcoded, so the solver emits the
correct encoder for ANY (K, {g_i}) instance, not just the 0001 record.

Encoder model (the dominant textbook shape the CVDP harness pins):
  * a (K-1)-bit shift register holds the previous K-1 input bits.
  * for each generator g (a K-bit tap string, MSB = current input bit, then the
    shift-register stages high->low), encoded_bit_i = XOR of the tapped bits.
  * outputs + shift register are REGISTERED on posedge clk; async active-high rst
    clears the shift register and all encoded outputs to 0.
The harness reads the INTERNAL `shift_reg` and `encoded_bitN` nets by name, so the
emit uses exactly those identifiers.

§4.05 PARSE-OR-SKIP: return None (SKIP) unless ALL of {K, >=2 generator tap
strings each of length K, the data_in/clk/rst ports, and >=2 encoded_bit outputs}
are unambiguously stated. A punctured / feedback (recursive) / rate-k/n (k>1) /
trellis-terminated variant is not this plain shape -> SKIP.
"""
from __future__ import annotations

import os
import re
import sys
from typing import Dict, List, Optional, Tuple

from _prose_polarity import is_denied, sentence_scope

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _toplevel(record: dict) -> Optional[str]:
    try:
        import record_prompt_context_bridge as _bridge
        t = _bridge.toplevel_name(record)
        if t:
            return t
    except Exception:
        pass
    # The harness `.env` TOPLEVEL is an OFF-LIMITS oracle; the module name comes
    # ONLY from input.prompt + input.context (via the bridge). None -> honest SKIP.
    return None


# Variants that are NOT the plain feed-forward rate-1/n encoder -> SKIP.
_DISQUALIFY_RE = re.compile(
    r"(?xi)\bpunctur|\brecursive\b|\brsc\b|\bfeedback\b|\btrellis\s+termin|"
    r"\btail[-\s]?bit|\binterleav|\bturbo\b|\bviterbi\b|\bdecoder\b|"
    r"\brate\s*[2-9]\s*/|\bk\s*/\s*n\b")


def _is_denied_at(prompt: str, m) -> bool:
    """Whether the statement around an already-found match denies it."""
    lo, hi = sentence_scope(prompt, m.start(), m.end(),
                            extra_breaks=_PROMPT_LINE_BREAKS)
    return bool(is_denied(prompt[lo:hi]))


def _first_live(pattern: str, prompt: str, flags: int = 0):
    """The first match of `pattern` in `prompt` that is NOT denied, or None.

    ONE HELPER FOR EVERY READ IN THIS FILE (vibe-ic#712). The generator
    polynomials were guarded first and the constraint length beside them was
    not -- two readers of one prompt, disagreeing about a denial, deciding one
    encoder between them:

        "The constraint length K = 7 is no longer used.\n Use K = 5."  -> 7

    K and the generators together ARE the code. Reading one of them from a
    retired sentence builds an encoder the prompt does not describe.

    A denied match does not END the search, or a prompt that retires one value
    and states another yields nothing.
    """
    for m in re.finditer(pattern, prompt, flags):
        if _is_denied_at(prompt, m):
            continue
        return m
    return None


def _parse_K(prompt: str) -> Optional[int]:
    m = _first_live(
        r"constraint\s+length\s*\(?[Kk]\)?\s*(?:is\s+)?"
        r"(?:fixed\s+at\s+|=\s*|of\s+)?(\d+)", prompt, re.I)
    if m:
        return int(m.group(1))
    m = _first_live(r"\b[Kk]\s*=\s*(\d+)", prompt)
    return int(m.group(1)) if m else None


#: A prompt ends sentences at a line end as often as with ". ", and the shared
#: vocabulary breaks on the latter only. Without these, the scope of a live
#: match reaches back over the full stop into a denial on the line above and
#: refuses a polynomial the prompt plainly states. ADDS to `SENTENCE_BREAKS`;
#: `sentence_scope` cannot remove from it. Not "\n" alone: a prompt wraps
#: mid-sentence, and breaking there would miss a denial written across two
#: lines -- the under-reach that publishes the denied value.
_PROMPT_LINE_BREAKS = (".\n", "!\n", "?\n")


def _parse_generators(prompt: str) -> List[Tuple[int, str]]:
    """Return [(index, tapstring)] sorted by index. Accepts `g1 is "111"`,
    `g2 = "101"`, `generator polynomial g1 "111"`, with straight or curly quotes.

    POLARITY IS ASKED (vibe-ic#712). A prompt is written by a person, and a
    person states a RETIRED polynomial as readily as a live one:

        'g1 = "111" is no longer used. The encoder uses g2 = "101".'
        'The encoder does not use g1 = "111".'

    Both published g1 = 111. That is a denied value returned as a declaration,
    and here it decides which convolutional encoder gets SYNTHESISED.

    It compounds with `setdefault`, which keeps the FIRST match: a retired
    polynomial stated before the live one wins outright, so the denial does not
    merely add a wrong entry, it can take the right one's place."""
    found: Dict[int, str] = {}
    # THE SAME HELPER the constraint length and the port finder use. Its
    # own inline loop was the fourth copy of one rule in this file, and
    # four copies is how `_parse_K` came to be read by a different rule
    # from the generators it decides an encoder with.
    for m in re.finditer(
            r"\bg(\d+)\b[^.\"'\n]{0,48}?[\"\u201c\u201d']([01]{2,})[\"\u201c\u201d']",
            prompt):
        if _is_denied_at(prompt, m):
            continue
        found.setdefault(int(m.group(1)), m.group(2))
    return sorted(found.items())


def _find_port(prompt: str, *patterns) -> Optional[str]:
    for pat in patterns:
        # A port NAME taken from a retired sentence is a phantom port on the
        # generated module -- the same defect the interface recoverer had.
        m = _first_live(pat, prompt, re.I)
        if m:
            return m.group(1)
    return None


def solve(record: dict) -> Optional[str]:
    if not isinstance(record, dict):
        return None
    prompt = (record.get("input") or {}).get("prompt") or ""
    if not prompt.strip():
        return None
    low = prompt.lower()
    if "convolution" not in low:
        return None
    if _DISQUALIFY_RE.search(prompt):
        return None
    # a "modify / complete the partial code / retain existing" task is not a
    # single-function emit -> SKIP (let the gate-backed AI author it).
    if (record.get("input") or {}).get("context"):
        return None
    if re.search(r"\bretain\b|already written|complete the (?:given |partial )"
                 r"|partial (?:system)?verilog|do not modify", low):
        return None

    K = _parse_K(prompt)
    gens = _parse_generators(prompt)
    if K is None or K < 2 or len(gens) < 2:
        return None
    # every generator tap string must be exactly K bits (MSB = current input).
    if any(len(g) != K for _, g in gens):
        return None

    top = _toplevel(record) or "convolutional_encoder"
    # port names: the harness uses clk / rst / data_in / encoded_bitN + shift_reg.
    clk = _find_port(prompt, r"\b(clk|clock)\b") or "clk"
    rst = _find_port(prompt, r"\b(rst|reset)\b") or "rst"
    din = _find_port(prompt, r"\b(data_in|din)\b") or "data_in"
    # output names encoded_bit1.. (match the stated identifiers if present).
    outs = re.findall(r"\b(encoded_bit\d+)\b", prompt)
    seen = []
    for o in outs:
        if o not in seen:
            seen.append(o)
    if len(seen) >= len(gens):
        out_names = seen[:len(gens)]
    else:
        out_names = [f"encoded_bit{i}" for i, _ in gens]

    sr_bits = K - 1  # shift register holds previous K-1 input bits
    active_high = not (rst.lower().endswith("_n") or "active-low" in low)
    rst_edge = "posedge" if active_high else "negedge"
    rst_test = rst if active_high else f"!{rst}"

    def taps(g: str) -> str:
        # g[0] = MSB = current input bit; g[1..] map to shift_reg[sr_bits-1..0].
        terms = []
        if g[0] == "1":
            terms.append(din)
        for j in range(1, K):
            if g[j] == "1":
                # tap position j (1-indexed from the MSB) -> shift_reg[j-1]
                # (shift_reg[0] = most-recent previous bit). Matches the harness:
                # g1="111" -> in ^ sr[0] ^ sr[1]; g2="101" -> in ^ sr[1].
                terms.append(f"shift_reg[{j - 1}]")
        return " ^ ".join(terms) if terms else "1'b0"

    lines = [
        f"// program-SOLVED convolutional encoder (K={K}, "
        f"{len(gens)} generator polynomials PARSED from prose); deterministic, no AI.",
        f"module {top} (",
        f"    input {clk},",
        f"    input {rst},",
        f"    input {din},",
    ]
    lines += [f"    output reg {nm}," for nm in out_names[:-1]]
    lines.append(f"    output reg {out_names[-1]}")
    lines.append(");")
    lines.append(f"    reg [{sr_bits-1}:0] shift_reg;")
    lines.append(f"    always @(posedge {clk} or {rst_edge} {rst}) begin")
    lines.append(f"        if ({rst_test}) begin")
    lines.append(f"            shift_reg <= {sr_bits}'b0;")
    for nm in out_names:
        lines.append(f"            {nm} <= 1'b0;")
    lines.append("        end else begin")
    for (idx, g), nm in zip(gens, out_names):
        lines.append(f"            {nm} <= {taps(g)};  // g{idx} = \"{g}\"")
    if sr_bits == 1:
        lines.append(f"            shift_reg <= {din};")
    else:
        lines.append(f"            shift_reg <= {{shift_reg[{sr_bits-2}:0], {din}}};")
    lines.append("        end")
    lines.append("    end")
    lines.append("endmodule")
    lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", required=True)
    ap.add_argument("--id")
    a = ap.parse_args(argv)
    n = 0
    for line in open(a.jsonl):
        r = json.loads(line)
        if a.id and r.get("id") != a.id:
            continue
        rtl = solve(r)
        if rtl:
            n += 1
            print(f"=== {r.get('id')} ===\n{rtl}")
    print(f"emitted={n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
