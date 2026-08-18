#!/usr/bin/env python3
"""hamming_synth.py — a DETERMINISTIC solver for the CVDP Hamming / ECC family.

WHY: a Hamming(n,k) encoder / decoder is a CLOSED-FORM, fully-deterministic
datapath once the code geometry is pinned: the number of DATA bits (k), the
number of PARITY bits (p), the total ENCODED width (n = p + k + 1 in this
dataset's "+1 redundant LSB" convention), the parity-bit POSITIONS (the powers
of two 1, 2, 4, 8, ...), the redundant-bit POSITION (index 0), the DATA-bit
placement (sequentially LSB-first into the non-power-of-two, non-zero indices),
and the parity CONVENTION (even parity over the standard Hamming coverage set —
`parity[j]` = XOR of every encoded index whose binary value has bit j set). With
all of those pinned, there is EXACTLY ONE correct encoder and EXACTLY ONE correct
single-error-correcting decoder. The standard Hamming parity coverage is itself
DETERMINISTIC from the geometry — we never read it from a golden body; we DERIVE
it from k/p and emit the XOR trees.

  ENCODER  data_out[n-1:0]:
    * data_out[0]        = 0                       (redundant bit)
    * data_out[2^j]      = parity[j]               (parity bits)
    * data_out[other]    = next data_in bit (LSB-first)
    * parity[j]          = XOR over all indices i in [1, n-1] with ((i>>j)&1)==1
                           of the placed data_out[i]                (even parity)

  DECODER  data_out[k-1:0]:
    * syndrome[j]        = XOR over all i in [1, n-1] with ((i>>j)&1)==1 of data_in[i]
    * s = {syndrome[p-1..0]}  is the 1-based error position; if s != 0 flip data_in[s]
      (the redundant bit at index 0 is never flipped — s==0 means no error)
    * extract the corrected data bits from the non-power-of-two, non-zero indices,
      LSB-first, into data_out
    * (SECDED) if an overall parity bit is STATED, it additionally distinguishes
      single- vs double-error; we only emit it when the prompt pins it.

§4.05 PARSE-OR-SKIP / NO-CHEAT (binding):
  Hamming layout is convention-sensitive — a wrong parity coverage or a wrong
  bit-position map SILENTLY produces a plausible-but-wrong codeword that a naive
  smoke test could miss. So this solver SKIPS (returns None) unless the geometry
  is UNAMBIGUOUSLY pinned by the prose AND the layout matches the standard
  power-of-two-positional Hamming convention this dataset uses. It NEVER guesses
  the parity coverage, NEVER guesses (n, k, p), NEVER guesses the parity
  polarity (even vs odd), NEVER reads the golden RTL body.

  Recognized SKIP triggers (return None):
    * not a Hamming design (BCH / Reed-Solomon / CRC / convolutional / LDPC / turbo);
    * (n, k) or p not stated and not derivable;
    * the parity convention (even/odd) not stated / ambiguous;
    * a non-standard / unpinnable bit layout (parity not at powers of two,
      redundant not at index 0, data not sequential);
    * a COMPOSITE top (the Hamming core is split across NUM_MODULES instances /
      concatenated / wrapped with FSM / packetizer / FIFO / serializer) whose
      structure can't be pinned from the prose alone.

GENERAL: keyed on Hamming/ECC SEMANTICS (parity bits at powers of two, even-parity
XOR coverage, syndrome single-error correction), never on a design name. The same
solve() fires on a renamed copy. chip-AGNOSTIC, pure-function, deterministic.

API: solve(record: dict) -> Optional[str]   # emitted RTL (module == TOPLEVEL) | None
Also exposes pure helpers used by the solver and the tests:
    parse_hamming_spec(prompt) -> Optional[HammingSpec]
    derive_p(k) -> int
    encode(spec, data) -> int                         # golden encoder reference
    decode(spec, codeword) -> int                     # golden corrector reference
    parity_coverage(spec) -> List[List[int]]          # the derived XOR coverage sets
    emit_encoder_rtl(spec, top, data_port, out_port, parameterized) -> str
    emit_decoder_rtl(spec, top, in_port, out_port, parameterized) -> str
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import cvdp_atomic_bridge as _bridge  # noqa: E402  INTERFACE + module-name source

Port = Tuple[str, int]


# --------------------------------------------------------------------------- #
# §4.05 up-front SKIP cues
# --------------------------------------------------------------------------- #
# A NON-Hamming ECC the standard Hamming derivation would MIS-EMIT. We must never
# let a Hamming codeword stand in for a BCH / Reed-Solomon / CRC / convolutional /
# LDPC / turbo code. Keyed on the cited algorithm, never on a design name.
_FOREIGN_ECC_RE = re.compile(
    r"""(?xi)
      \breed[-\s]?solomon\b | \bbch\b | \bgolay\b | \bldpc\b | \bturbo\s+code\b |
      \bconvolutional\b | \bviterbi\b | \bpolar\s+code\b | \bfire\s+code\b |
      \bcrc\b | \bcyclic\s+redundancy\b | \bgalois\b | \bgf\s*\(\s*2 |
      \breed[-\s]?muller\b | \bhsiao\b
    """,
)

# A COMPOSITE top whose Hamming core is split across instances / concatenated /
# wrapped with control logic. The split/concat structure (NUM_MODULES, PART_WIDTH,
# generate-for of sub-instances) is not a single pinnable Hamming datapath.
_COMPOSITE_RE = re.compile(
    r"""(?xi)
      \bnum_modules\b | \bpart_width\b | \btotal_encoded\b |
      \bmultiple\s+instances\b | \bconcatenat | \bsplit\s+into\b |
      \bt_hamming\b | \bgenvar\b.*\bgenerate\b |
      \bfsm\b | \bstate\s+machine\b | \bpacket\b | \bfifo\b | \bserial\b |
      \buart\b | \bspi\b | \bi2c\b | \baxi\b
    """,
    re.S,
)

# Hamming recognition — must name Hamming AND show the power-of-two / even-parity
# / syndrome semantics (not merely a passing mention).
_HAMMING_NOUN_RE = re.compile(r"(?i)\bhamming\b")
_HAMMING_SEM_RE = re.compile(
    r"(?i)power[s]?\s+of\s+(?:2|two)|2\s*<?sup>?\s*p|parity\s+bit|syndrome|"
    r"even\s+parity|single[-\s]?bit\s+error")


# --------------------------------------------------------------------------- #
# Hamming geometry spec
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class HammingSpec:
    k: int                 # number of DATA bits
    p: int                 # number of PARITY bits
    n: int                 # total ENCODED width (= p + k + 1 here; redundant LSB)
    redundant: bool        # an index-0 redundant bit is present (+1 convention)
    even_parity: bool      # even (True) vs odd (False) parity convention
    role: str              # "encoder" | "decoder"
    parameterized: bool    # DATA_WIDTH / PARITY_BIT parameters exposed (cocotb reads them)
    secded: bool           # an overall-parity SECDED bit is stated


def derive_p(k: int) -> int:
    """Minimum parity-bit count satisfying the stated Hamming formula
    2^p >= (p + k) + 1  (i.e. 2^p >= p + k + 1). DETERMINISTIC from k."""
    p = 0
    while (1 << p) < (p + k + 1):
        p += 1
    return p


def data_indices(n: int) -> List[int]:
    """The encoded indices that carry DATA — every index in [1, n-1] that is NOT a
    power of two (index 0 is the redundant bit). LSB-first order."""
    out = []
    for i in range(1, n):
        if (i & (i - 1)) != 0:       # not a power of two
            out.append(i)
    return out


def parity_index(j: int) -> int:
    """The encoded index that holds parity bit j — the power of two 2^j."""
    return 1 << j


def parity_coverage(spec: HammingSpec) -> List[List[int]]:
    """For each parity bit j (0..p-1) the list of encoded indices it XORs over —
    every index i in [1, n-1] whose binary value has bit j set. This IS the
    standard Hamming coverage, DERIVED from the geometry (never read from a
    golden). The parity bit's own position 2^j is included (the canonical even-
    parity-over-the-group form), so the recomputed syndrome at the receiver lands
    1-based on the error position."""
    cov: List[List[int]] = []
    for j in range(spec.p):
        cov.append([i for i in range(1, spec.n) if (i >> j) & 1])
    return cov


# --------------------------------------------------------------------------- #
# golden references (Python) — the SAME datapath the RTL emits; used to cross-check
# --------------------------------------------------------------------------- #
def encode(spec: HammingSpec, data: int) -> int:
    """Encode `data` (k bits) into the n-bit Hamming codeword (int, Verilog bit i
    = bit i of the returned int). Mirrors the emitted encoder RTL exactly."""
    n, p = spec.n, spec.p
    out = [0] * n
    # place data bits LSB-first into the non-power-of-two, non-zero indices
    dz = data_indices(n)
    for c, idx in enumerate(dz):
        out[idx] = (data >> c) & 1
    # even-parity XOR coverage (the parity slot itself excluded when computing it)
    for j in range(p):
        pi = parity_index(j)
        acc = 0
        for i in range(1, n):
            if i != pi and ((i >> j) & 1):
                acc ^= out[i]
        if not spec.even_parity:
            acc ^= 1
        out[pi] = acc
    return sum(b << i for i, b in enumerate(out))


def syndrome(spec: HammingSpec, codeword: int) -> int:
    """Recompute the p-bit syndrome of `codeword`. With even parity over the full
    coverage group (parity slot included), syndrome == 0 means no error and any
    nonzero value is the 1-based index of the single erroneous bit."""
    s = 0
    for j in range(spec.p):
        acc = 0
        for i in range(1, spec.n):
            if (i >> j) & 1:
                acc ^= (codeword >> i) & 1
        if not spec.even_parity:
            acc ^= 1
        s |= (acc & 1) << j
    return s


def decode(spec: HammingSpec, codeword: int) -> int:
    """Correct a single-bit error in `codeword` (n bits) and return the corrected
    k-bit data word. Mirrors the emitted decoder RTL exactly."""
    s = syndrome(spec, codeword)
    cw = codeword
    if s != 0 and s < spec.n:
        cw ^= (1 << s)                 # flip the erroneous bit (index 0 untouched: s!=0)
    data = 0
    for c, idx in enumerate(data_indices(spec.n)):
        data |= ((cw >> idx) & 1) << c
    return data & ((1 << spec.k) - 1)


# --------------------------------------------------------------------------- #
# parse the Hamming geometry from the prompt (PARSE-OR-SKIP)
# --------------------------------------------------------------------------- #
_KW_DATA_RE = re.compile(
    r"(?i)\bencodes?\s+(\d+)\s*-?\s*bit\b|"
    r"\bfor\s+(\d+)\s+data\s+bits?\b|"
    r"\b(\d+)\s+data\s+bits?\b|"
    r"\b(\d+)\s*-?\s*bit\s+input\s+data\b")
_KW_PARITY_RE = re.compile(
    r"(?i)\b(\d+)\s+parity\s+bits?\s+(?:are\s+required|is\s+required)|"
    r"\b(\d+)\s+parity\s+bits?\b")
# `n` (total encoded width) is trusted ONLY from an explicit ENCODED_DATA / total
# OUTPUT statement — never from a bare "total of N bits" (which in this dataset
# names the 7-bit Hamming word WITHOUT the +1 redundant LSB).
_KW_ENC_RE = re.compile(
    r"(?i)\bencoded[_\s]?data\b\s*(?:is|=|:)\s*(\d+)|"
    r"\bpad\s+the\s+output\s+(\d+)\s*bits?\b|"
    r"\boutput\s+(\d+)\s*bits?\b")
# parameterized-default geometry: DATA_WIDTH / PARITY_BIT "default is N" (the
# clause may run past a sentence period, so we scope to the same bullet — up to
# the next blank line / next bold parameter heading — and take the FIRST default).
_DEF_DW_RE = re.compile(
    r"(?i)\bDATA_WIDTH\b(?:(?!\bPARITY_BIT\b|\n\s*\n).){0,200}?"
    r"default(?:\s+value)?\s+is\s+(\d+)", re.S)
_DEF_PB_RE = re.compile(
    r"(?i)\bPARITY_BIT\b(?:(?!\bENCODED_DATA\b|\bDATA_WIDTH\b|\n\s*\n).){0,200}?"
    r"default(?:\s+value)?\s+is\s+(\d+)", re.S)


def _first_int(m) -> Optional[int]:
    if not m:
        return None
    for g in m.groups():
        if g:
            return int(g)
    return None


def _detect_role(prompt: str, top: Optional[str] = None) -> Optional[str]:
    """encoder (transmitter) vs decoder (receiver/corrector). SKIP if neither is
    clearly the design's job (we never guess the direction).

    Decided by the design's STATED JOB, in priority order, never by the generic
    Hamming-purpose phrase 'detect and correct single-bit errors' (which appears
    in BOTH directions). The strongest signal is the encoded-data DATAFLOW:
      * a design that takes data and PRODUCES the wider encoded codeword  => encoder
      * a design that takes the encoded codeword and PRODUCES corrected data => decoder
    """
    name = (top or "").lower()
    # (1) module-name / title hard signal (tx vs rx / transmitter vs receiver).
    if re.search(r"(?i)\btransmitter\b|_tx\b|\btx_", name + " " + prompt[:200]):
        name_enc = True
    else:
        name_enc = False
    if re.search(r"(?i)\breceiver\b|_rx\b|\brx_", name + " " + prompt[:200]):
        name_dec = True
    else:
        name_dec = False
    # (2) dataflow signal — what the design CONSUMES vs PRODUCES.
    produces_encoded = re.search(
        r"(?i)(?:output|outputs|produces?|generat\w+|final|encoded\s+output|"
        r"transmit\w*)[^.\n]{0,60}?encoded|encodes?\s+[^.\n]{0,40}?into\b|"
        r"outputs?\s+the\s+(?:final\s+)?\d*\s*-?\s*bit\s+encoded", prompt)
    produces_corrected = re.search(
        r"(?i)(?:provides?|assign\w*|output\w*|produces?)[^.\n]{0,60}?corrected|"
        r"corrected\s+data\s+to\s+(?:the\s+)?output|decodes?\s+|receiver", prompt)
    consumes_encoded = re.search(
        r"(?i)takes?\s+(?:a\s+)?(?:signal|input|the\s+encoded)|decodes?\s+an?\b|"
        r"input[^.\n]{0,40}?(?:containing|encoded)", prompt)

    enc_score = int(name_enc) + (1 if produces_encoded else 0)
    dec_score = int(name_dec) + (1 if produces_corrected else 0) + (1 if consumes_encoded else 0)
    if enc_score > dec_score:
        return "encoder"
    if dec_score > enc_score:
        return "decoder"
    # tie / unclear -> SKIP (never guess the direction).
    return None


def parse_hamming_spec(prompt: str, top: Optional[str] = None) -> Optional[HammingSpec]:
    """Parse a fully-determined Hamming geometry from the prompt, or None (SKIP).
    Requires: it READS as Hamming with power-of-two / even-parity semantics, the
    layout is the standard power-of-two-positional convention, and (k, p, n) are
    pinned (stated or derivable). Never guesses geometry or parity polarity."""
    if not prompt or not _HAMMING_NOUN_RE.search(prompt):
        return None
    if not _HAMMING_SEM_RE.search(prompt):
        return None
    # §4.05: foreign ECC or composite split structure -> SKIP.
    if _FOREIGN_ECC_RE.search(prompt) or _COMPOSITE_RE.search(prompt):
        return None

    # parity convention must be EVEN and STATED (this dataset's convention). If odd
    # is stated we honor it; if neither even nor odd is stated -> SKIP (no guess).
    even = re.search(r"(?i)even\s+parity", prompt)
    odd = re.search(r"(?i)odd\s+parity", prompt)
    if not even and not odd:
        return None
    if even and odd:
        return None                     # contradictory -> SKIP
    even_parity = bool(even)

    # layout must be the standard power-of-two-positional Hamming convention:
    # parity bits at powers of two AND a redundant LSB at index 0.
    pow2 = re.search(r"(?i)power[s]?\s+of\s+(?:2|two)|2\s*<?sup>?\s*[p0-9]|"
                     r"positions?\s+1,?\s*2,?\s*(?:and\s+)?4", prompt)
    if not pow2:
        return None
    redundant = bool(re.search(r"(?i)redundant\s+bit", prompt))
    if not redundant:
        return None                     # the +1 LSB convention must be stated

    role = _detect_role(prompt, top)
    if role is None:
        return None

    parameterized = bool(re.search(r"(?i)\bDATA_WIDTH\b", prompt) and
                         re.search(r"(?i)\bPARITY_BIT\b", prompt))

    # geometry: k (data), p (parity), n (encoded). For a PARAMETERIZED design the
    # geometry is the stated DEFAULT (DATA_WIDTH / PARITY_BIT); for a FIXED design
    # it is the stated counts. We never read an output width as `n` for a decoder
    # (its data_out is k-bit), nor as `k` for an encoder.
    k = p = n = None
    if parameterized:
        k = _first_int(_DEF_DW_RE.search(prompt))
        p = _first_int(_DEF_PB_RE.search(prompt))
    if k is None:
        k = _first_int(_KW_DATA_RE.search(prompt))
    if p is None:
        p = _first_int(_KW_PARITY_RE.search(prompt))
    # `n` is only trusted from an explicit encoded-width statement (never from a
    # bare "N-bit output", which is the encoder's codeword OR the decoder's data).
    n = _first_int(_KW_ENC_RE.search(prompt))

    # cross-derive: with the +1-redundant convention, n = p + k + 1; and p is the
    # minimum satisfying 2^p >= p + k + 1.
    if k is not None:
        dp = derive_p(k)
        if p is None:
            p = dp
        elif p != dp:
            return None                 # stated p contradicts the formula -> SKIP
        dn = p + k + 1
        if n is None:
            n = dn
        elif n != dn:
            return None
    elif p is not None and n is not None:
        k = n - p - 1
        if k <= 0 or derive_p(k) != p:
            return None
    else:
        return None                     # can't pin geometry -> SKIP

    if k is None or p is None or n is None or k <= 0 or p <= 0 or n != p + k + 1:
        return None
    if derive_p(k) != p:
        return None
    # sanity: the standard layout must have room for exactly k data slots.
    if len(data_indices(n)) != k:
        return None

    secded = bool(re.search(r"(?i)\bsecded\b|\bsec[-\s]?ded\b|overall\s+parity|"
                            r"double[-\s]?bit\s+error\s+detect", prompt))

    return HammingSpec(k=k, p=p, n=n, redundant=redundant, even_parity=even_parity,
                       role=role, parameterized=parameterized, secded=secded)


# --------------------------------------------------------------------------- #
# RTL emit — fully-combinational, parameter-exposing when the harness reads params
# --------------------------------------------------------------------------- #
def _enc_param_header(top: str, data_port: str, out_port: str) -> List[str]:
    return [
        f"module {top} #(",
        f"    parameter DATA_WIDTH       = 4,",
        f"    parameter PARITY_BIT       = 3,",
        f"    parameter ENCODED_DATA     = PARITY_BIT + DATA_WIDTH + 1,",
        f"    parameter ENCODED_DATA_BIT = $clog2(ENCODED_DATA)",
        f")(",
        f"    input  [DATA_WIDTH-1:0]   {data_port},",
        f"    output reg [ENCODED_DATA-1:0] {out_port}",
        f");",
    ]


def emit_encoder_rtl(spec: HammingSpec, top: str, data_port: str, out_port: str,
                     parameterized: bool) -> str:
    lines: List[str] = []
    lines.append("// Auto-emitted deterministic Hamming encoder (hamming_synth).")
    lines.append(f"// k={spec.k} p={spec.p} n={spec.n} even_parity={int(spec.even_parity)} "
                 f"redundant_lsb=1 parity_at_powers_of_two=1")
    if parameterized:
        lines += _enc_param_header(top, data_port, out_port)
        lines.append("    integer i, j, count;")
        lines.append("    reg [PARITY_BIT-1:0] parity;")
        lines.append("    reg [ENCODED_DATA_BIT:0] pos;")
        lines.append("    always @(*) begin")
        lines.append(f"        {out_port} = {{ENCODED_DATA{{1'b0}}}};")
        lines.append("        parity     = {PARITY_BIT{1'b0}};")
        lines.append("        count      = 0;")
        lines.append("        // place data bits at non-power-of-two, non-zero indices (LSB-first)")
        lines.append("        for (pos = 1; pos < ENCODED_DATA; pos = pos + 1) begin")
        lines.append("            if (count < DATA_WIDTH) begin")
        lines.append("                if ((pos & (pos - 1)) != 0) begin")
        lines.append(f"                    {out_port}[pos] = {data_port}[count];")
        lines.append("                    count = count + 1;")
        lines.append("                end")
        lines.append("            end")
        lines.append("        end")
        lines.append("        // even-parity XOR coverage: parity[j] over indices with bit j set")
        lines.append("        for (j = 0; j < PARITY_BIT; j = j + 1) begin")
        lines.append("            for (i = 1; i <= ENCODED_DATA-1; i = i + 1) begin")
        lines.append("                if ((i & (1 << j)) != 0) begin")
        lines.append(f"                    parity[j] = parity[j] ^ {out_port}[i];")
        lines.append("                end")
        lines.append("            end")
        if not spec.even_parity:
            lines.append("            parity[j] = ~parity[j];")
        lines.append("        end")
        lines.append("        // drop parity bits into the power-of-two positions")
        lines.append("        for (j = 0; j < PARITY_BIT; j = j + 1) begin")
        lines.append(f"            {out_port}[(1 << j)] = parity[j];")
        lines.append("        end")
        lines.append("    end")
        lines.append("endmodule")
        return "\n".join(lines) + "\n"

    # fixed-width explicit form: emit each parity bit as an explicit XOR tree.
    n, k = spec.n, spec.k
    lines.append(f"module {top} (")
    lines.append(f"    input  wire [{k-1}:0] {data_port},")
    lines.append(f"    output wire [{n-1}:0] {out_port}")
    lines.append(");")
    dz = data_indices(n)
    # data placement
    for c, idx in enumerate(dz):
        lines.append(f"    assign {out_port}[{idx}] = {data_port}[{c}];")
    lines.append(f"    assign {out_port}[0] = 1'b0;   // redundant bit")
    # parity XOR trees (exclude the parity slot itself)
    data_of = {idx: c for c, idx in enumerate(dz)}
    for j in range(spec.p):
        pi = 1 << j
        terms = [f"{data_port}[{data_of[i]}]"
                 for i in range(1, n) if i != pi and ((i >> j) & 1) and i in data_of]
        expr = " ^ ".join(terms) if terms else "1'b0"
        if not spec.even_parity:
            expr = f"~({expr})"
        lines.append(f"    assign {out_port}[{pi}] = {expr};   // parity[{j}]")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def _dec_param_header(top: str, in_port: str, out_port: str) -> List[str]:
    return [
        f"module {top} #(",
        f"    parameter DATA_WIDTH       = 4,",
        f"    parameter PARITY_BIT       = 3,",
        f"    parameter ENCODED_DATA     = PARITY_BIT + DATA_WIDTH + 1,",
        f"    parameter ENCODED_DATA_BIT = $clog2(ENCODED_DATA)",
        f")(",
        f"    input  [ENCODED_DATA-1:0] {in_port},",
        f"    output reg [DATA_WIDTH-1:0]   {out_port}",
        f");",
    ]


def emit_decoder_rtl(spec: HammingSpec, top: str, in_port: str, out_port: str,
                     parameterized: bool) -> str:
    lines: List[str] = []
    lines.append("// Auto-emitted deterministic Hamming decoder/corrector (hamming_synth).")
    lines.append(f"// k={spec.k} p={spec.p} n={spec.n} even_parity={int(spec.even_parity)} "
                 f"single-error-correct (syndrome = 1-based error index)")
    if parameterized:
        lines += _dec_param_header(top, in_port, out_port)
        lines.append("    integer i, j, count;")
        lines.append("    reg [PARITY_BIT-1:0] parity;")
        lines.append("    reg [ENCODED_DATA-1:0] corrected;")
        lines.append("    reg [ENCODED_DATA_BIT:0] err_pos;")
        lines.append("    always @(*) begin")
        lines.append("        parity = {PARITY_BIT{1'b0}};")
        lines.append(f"        corrected = {in_port};")
        lines.append("        // recompute syndrome: parity[j] over indices with bit j set")
        lines.append("        for (j = 0; j < PARITY_BIT; j = j + 1) begin")
        lines.append("            for (i = 1; i <= ENCODED_DATA-1; i = i + 1) begin")
        lines.append("                if ((i & (1 << j)) != 0) begin")
        lines.append(f"                    parity[j] = parity[j] ^ {in_port}[i];")
        lines.append("                end")
        lines.append("            end")
        if not spec.even_parity:
            lines.append("            parity[j] = ~parity[j];")
        lines.append("        end")
        lines.append("        err_pos = parity;   // 1-based error index (0 = no error)")
        lines.append("        // correct the single-bit error (the redundant bit at 0 is never flipped)")
        lines.append("        if (err_pos != 0 && err_pos < ENCODED_DATA)")
        lines.append("            corrected[err_pos] = ~corrected[err_pos];")
        lines.append("        // extract corrected data bits (non-power-of-two, non-zero indices)")
        lines.append(f"        {out_port} = {{DATA_WIDTH{{1'b0}}}};")
        lines.append("        count = 0;")
        lines.append("        for (i = 1; i < ENCODED_DATA; i = i + 1) begin")
        lines.append("            if (((i & (i - 1)) != 0) && (count < DATA_WIDTH)) begin")
        lines.append(f"                {out_port}[count] = corrected[i];")
        lines.append("                count = count + 1;")
        lines.append("            end")
        lines.append("        end")
        lines.append("    end")
        lines.append("endmodule")
        return "\n".join(lines) + "\n"

    # fixed-width explicit form.
    n, k, p = spec.n, spec.k, spec.p
    lines.append(f"module {top} (")
    lines.append(f"    input  wire [{n-1}:0] {in_port},")
    lines.append(f"    output wire [{k-1}:0] {out_port}")
    lines.append(");")
    # syndrome bits
    for j in range(p):
        terms = [f"{in_port}[{i}]" for i in range(1, n) if (i >> j) & 1]
        expr = " ^ ".join(terms) if terms else "1'b0"
        if not spec.even_parity:
            expr = f"~({expr})"
        lines.append(f"    wire s{j} = {expr};")
    syn = "{" + ", ".join(f"s{j}" for j in range(p - 1, -1, -1)) + "}"
    lines.append(f"    wire [{p-1}:0] err_pos = {syn};")
    lines.append(f"    wire [{n-1}:0] corrected = "
                 f"(err_pos != 0 && err_pos < {n}) ? "
                 f"({in_port} ^ ({n}'b1 << err_pos)) : {in_port};")
    dz = data_indices(n)
    for c, idx in enumerate(dz):
        lines.append(f"    assign {out_port}[{c}] = corrected[{idx}];")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# interface — robust cocotb dut-signal reader (the bridge's `test_*` filename
# matcher misses `tx_test.py` / `rx_test.py`, so the Hamming family reads the
# cocotb signals directly: a `dut.X.value = ...` is an INPUT, a read-only
# `... = dut.X.value` / `int(dut.X.value)` is an OUTPUT; ALL-CAPS cocotb
# PARAMETERS (DATA_WIDTH / PARITY_BIT / ENCODED_DATA) are filtered out). The
# port WIDTHS are not guessed — they come from the pinned geometry.
# --------------------------------------------------------------------------- #
_ALLCAPS_PARAM_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _pick_io_pair(record: dict, top: str) -> Optional[Tuple[str, str]]:
    """The single (data-in, data-out) port pair from the PROMPT+CONTEXT interface
    (`cvdp_atomic_bridge.extract_interface`) — NOT the cocotb harness (OFF-LIMITS
    oracle). A clean Hamming encoder/decoder is exactly 1 non-sequential input and
    1 non-sequential output; anything else SKIPs. Mirrors the compliant
    `crc_synth.solve` interface-source pattern (prompt+context only)."""
    iface = _bridge.extract_interface(record, top)
    if not iface:
        return None
    ins, outs = iface
    seq = _bridge._SEQ_PORTS
    ins = [n for n, _ in ins if n.lower() not in seq]
    outs = [n for n, _ in outs if n.lower() not in seq]
    if len(ins) != 1 or len(outs) != 1:
        return None                     # a clean encoder/decoder is exactly 1-in/1-out
    return ins[0], outs[0]


# --------------------------------------------------------------------------- #
# solve()
# --------------------------------------------------------------------------- #
def solve(record: dict) -> Optional[str]:
    """Emit a deterministic Hamming encoder or decoder (module named per the PROMPT)
    for a stand-alone Hamming design whose geometry is fully stated, else None
    (SKIP). Reads ONLY input.prompt + input.context — never the harness or golden."""
    if not isinstance(record, dict):
        return None
    prompt = (record.get("input") or {}).get("prompt") or ""
    if not prompt.strip():
        return None
    if not _HAMMING_NOUN_RE.search(prompt):
        return None
    top = _bridge.toplevel_name(record)
    if not top:
        return None
    spec = parse_hamming_spec(prompt, top)
    if spec is None:
        return None

    picked = _pick_io_pair(record, top)
    if picked is None:
        return None
    in_port, out_port = picked
    if spec.role == "encoder":
        return emit_encoder_rtl(spec, top, in_port, out_port, spec.parameterized)
    return emit_decoder_rtl(spec, top, in_port, out_port, spec.parameterized)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--jsonl", required=True)
    ap.add_argument("--id")
    ap.add_argument("--emit", action="store_true")
    a = ap.parse_args(argv)
    recs = [json.loads(l) for l in open(a.jsonl)]
    found = emitted = 0
    ids: List[str] = []
    for r in recs:
        if a.id and r.get("id") != a.id:
            continue
        prompt = (r.get("input") or {}).get("prompt") or ""
        if _HAMMING_NOUN_RE.search(prompt):
            found += 1
        rtl = solve(r)
        if rtl:
            emitted += 1
            ids.append(r.get("id"))
            if a.emit or a.id:
                print(f"=== {r.get('id')} ===")
                print(rtl)
    print(f"found={found}  emitted={emitted}  ids={ids}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
