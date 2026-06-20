#!/usr/bin/env python3
"""cvdp_gate.py — the SOLE EMIT PATH for CVDP copilot (nonagentic) authoring.

ORGANIC #528. The official HF-open CVDP local-inference flow is
`local_export` (id/prompt JSONL out) → blind authoring → `local_import`
(id/completion JSONL back). The plugin's gate family (gates_atomic /
blind_instructions / scorer front doors) only covered the VE/RTLLM/4-IC
shapes, so CVDP authoring agents were left with FREE-TEXT self-verification
expectations — and v0.1.25 + the 2026-06-10 CVDP open-run (31 fresh agents,
zero spontaneous program calls; a remedial sweep caught 20 hygiene fixes +
4 real compile breaks) prove free-text ALWAYS regresses. This program is the
deterministic bridge: an author's draft completion can ONLY reach the
responses JSONL through this gate.

Per draft record {id, completion}:
  1. extract the Verilog payload (fenced ```verilog/systemverilog blocks
     preferred; whole completion when it is bare code carrying `module`/
     `endmodule`); a doc/SVA-only completion (no code to compile) is
     TOLERATED and passes through marked `doc_only`;
  2. ENFORCED `rtl_hygiene_lint.py --fix` (the v0.1.24/v0.1.25 lesson —
     in-gate fixes hold across fresh agents, prose does not);
  3. `iverilog -g2012 -t null` parse/elaboration gate. Elaboration errors
     caused ONLY by unknown context modules (`Unknown module type`) are
     TOLERATED — a copilot completion legitimately instantiates modules
     that live in the problem's context files. Syntax errors and
     icarus-unsupported constructs (`sorry:` — e.g. whole-array assignment,
     fatal on the official icarus-13 cvdp-sim scorer too) BLOCK the record;
  4. only a gate-PASS record is written to the output responses JSONL
     (disk-truth: the scoring artifact is written BY THE GATE, never by
     the agent).

Exit codes:
    0  every record gated in (possibly after --fix)
    1  ≥1 record BLOCKED (blocked ids + reasons in the report / stderr)
    2  bad input / iverilog unavailable (the gate cannot enforce → refuse)

chip-AGNOSTIC: pure structure (code-fence/module parsing, tool exit codes);
no benchmark-specific problem knowledge, no dataset access.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HARNESS_DIR = Path(__file__).resolve().parent
PROGRAMS_DIR = HARNESS_DIR.parent / "programs"

# ORGANIC #695 — prompt→interface conformance (module-name case + missing-port
# + port-direction, all prompt-derivable). Imported lazily so the gate still
# runs if the program is absent (the stage simply no-ops with a note). ADVISORY
# only — heuristic prompt extraction must never hard-block an emit.
try:
    sys.path.insert(0, str(PROGRAMS_DIR))
    import iface_conformance_v2 as _ifacev2  # type: ignore
except Exception:  # pragma: no cover - defensive (program missing)
    _ifacev2 = None

# ORGANIC #705 — DETERMINISTIC latency-conformance gate. Imported lazily so the
# gate still runs if the program is absent (the stage simply no-ops). This is a
# PRE-EMIT hook that only fires for an id whose latency spec (event / output /
# expected-expr) is SUPPLIED via --latency-specs — the canonical event→output
# latency literal is NOT derivable from a CVDP record's prose, so the gate
# cannot infer it. When a spec IS supplied for an id, the gate MEASURES the
# emitted RTL's real latency (its OWN canonical TB, the way a scorer counts) and
# BLOCKS a mismatch BEFORE that record is written out — the self-TB an author
# improvises around the wrong RTL would not catch the off-by-one (#705).
try:
    import latency_conformance_check as _latconf  # type: ignore
except Exception:  # pragma: no cover - defensive (program missing)
    _latconf = None

# ANY-info-string fence tokenizer (adversarial-review HIGH): an opener whose
# tag is not verilog-ish (```text / ```python / untagged prose) must STILL
# anchor a fence, or pairing skews — the closing ``` of a text block pairs
# with the opening ``` of the verilog block, the real code is dropped and
# inter-fence PROSE gets compiled (reproduced both as a block-evasion and as
# a false-block). Pair ALL fences first, classify each by tag/content after.
_ANY_FENCE_RE = re.compile(r"```([^\n`]*)\n(.*?)```", re.DOTALL)
_CODE_TAG_RE = re.compile(r"^\s*(?:system)?verilog\s*$|^\s*sv\s*$|^\s*v\s*$",
                          re.IGNORECASE)
_MODULE_RE = re.compile(r"\bmodule\s+[A-Za-z_]\w*", re.MULTILINE)
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_STRING_LIT_RE = re.compile(r'"(?:[^"\\\n]|\\.)*"')


def _detection_text(code: str) -> str:
    """Comment- and string-stripped VIEW for module-name detection only (the
    payload itself is never modified). ORGANIC #531 round-3: a leading block
    comment `/* This module implements an FSM ... */` yielded the phantom
    module name 'implements' → `synth -top implements` → false BLOCK of
    officially-PASSing completions."""
    t = _BLOCK_COMMENT_RE.sub(" ", code)
    t = _LINE_COMMENT_RE.sub(" ", t)
    return _STRING_LIT_RE.sub('""', t)
# icarus stderr classification
_UNKNOWN_MOD_RE = re.compile(r"Unknown module type", re.IGNORECASE)
_ELAB_COUNT_RE = re.compile(r"^\s*\d+ error\(s\) during elaboration",
                            re.IGNORECASE)
_SORRY_RE = re.compile(r"\bsorry:", re.IGNORECASE)


def code_fences(completion: str) -> List["re.Match"]:
    """All paired fences whose TAG is verilog-ish, or that are untagged and
    carry a module declaration. Pairing uses the any-info-string tokenizer
    so a preceding ```text block can never skew the alignment."""
    out = []
    for m in _ANY_FENCE_RE.finditer(completion):
        tag, body = m.group(1), m.group(2)
        if _CODE_TAG_RE.match(tag or ""):
            out.append(m)
        elif not (tag or "").strip() \
                and _MODULE_RE.search(_detection_text(body)):
            out.append(m)
    return out


_RTL_SUFFIXES = (".sv", ".v", ".svh", ".vh")


def json_code_files(completion: str) -> Optional[Dict[str, str]]:
    """ORGANIC #528 round-2 — the OFFICIAL CVDP completion shape is a JSON
    code-dict: `{"code": [{"rtl/foo.sv": "module foo..."}, ...]}` (list of
    single-key dicts, or a flat dict). The official
    `model_helpers.parse_model_response` parses first-`{` → last-`}` →
    json.loads → unwrap `code`; this mirrors it. Returns {path: content} or
    None when the completion is not that shape. Without this, the raw JSON
    string was fed to iverilog as bare Verilog and LEGAL completions were
    falsely BLOCKED (field round-2 counter-evidence: 3 harness-PASSing
    records mis-blocked)."""
    i = completion.find("{")
    j = completion.rfind("}")
    if i == -1 or j <= i:
        return None
    try:
        obj = json.loads(completion[i:j + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    code = obj.get("code")
    files: Dict[str, str] = {}
    if isinstance(code, list):
        for entry in code:
            if isinstance(entry, dict):
                for k, v in entry.items():
                    if isinstance(k, str) and isinstance(v, str):
                        files[k] = v
    elif isinstance(code, dict):
        for k, v in code.items():
            if isinstance(k, str) and isinstance(v, str):
                files[k] = v
    # FLAT FILE-MAP fallback — a `{"rtl/foo.sv": "module foo...", ...}` object
    # with NO "code" wrapper key. Agents (especially on multi-file problems)
    # repeatedly emit this shape; the official `parse_model_response` only
    # unwraps a "code" key, so the raw JSON was written verbatim as the .sv →
    # a line-1 `{` syntax error → ELAB_ERROR even though clean RTL was inside.
    # Recover the files here so the gate's #680 emit-normalization re-emits the
    # format the harness decodes. TIGHT GUARD (must not misread a JSON-schema /
    # doc-only answer object as code): fire ONLY when there is no "code" key AND
    # at least one value carries a REAL Verilog module (a `module` declaration
    # AND `endmodule`); a SystemRDL/JSON-schema deliverable carries neither.
    if not files and "code" not in obj:
        cand: Dict[str, str] = {}
        for k, v in obj.items():
            if (isinstance(k, str) and isinstance(v, str)
                    and (k.lower().endswith(_RTL_SUFFIXES)
                         or _MODULE_RE.search(_detection_text(v)))):
                cand[k] = v
        if any(_MODULE_RE.search(_detection_text(v))
               and re.search(r"\bendmodule\b", _detection_text(v))
               for v in cand.values()):
            files = cand
    return files or None


# ORGANIC #680 — the official harness `model_helpers.determine_schema` decides,
# per problem, whether the model response is parsed under the MULTI-FILE JSON
# schema (`no_schema=False` → the `{"code":[{path:content},…]}` dict is decoded
# file-by-file) or under NO schema (`no_schema=True` → `parse_model_response`
# calls only `extract_code_blocks`, which on a completion carrying NO ```fence
# FALLS BACK to `res.strip()` and writes the ENTIRE completion verbatim as the
# single RTL file). Field-measured 297/302 nonagentic copilot problems are
# single-file (`no_schema=True`). So a JSON code-dict emitted verbatim for a
# single-file problem is written LITERALLY (`{"code": […`) as the .sv → line-1
# `iverilog` syntax error → scorer ELAB_ERROR, even though the gate extracted
# clean RTL and PASSed it. The gate must therefore NORMALIZE its emit to the
# format the harness decodes for THIS problem's schema, never echo the author's
# format. We mirror determine_schema's single-vs-multi signal structurally (no
# vendored harness source in-repo): a problem is MULTI-FILE when the prompt
# carries an explicit JSON `{"code":…}` response-schema directive, or when the
# completion's JSON dict legitimately spans MORE THAN ONE RTL file (a true
# multi-file deliverable). Pure prompt-prose / file-count structure —
# chip-AGNOSTIC, no chip/vendor/SKU literal.
#
# The directive signal is the LITERAL `{"code": [` response-envelope the
# schema'd prompt demonstrates — NOT fuzzy prose like "json schema". Fuzzy
# prose false-fires on a NEGATED or incidental mention ("single-file, NO json
# schema" wrongly read as needing a schema), so it is deliberately excluded;
# only the actual envelope (or an explicit positive "respond with a JSON
# object of the form …code…" directive that shows the envelope key) counts.
_JSON_SCHEMA_DIRECTIVE_RE = re.compile(
    r"[{\[]\s*[\"']code[\"']\s*:\s*\[",          # the literal {"code":[ envelope
    re.IGNORECASE)
# An explicit positive instruction to RESPOND with a JSON object/dict (a
# response-FORMAT directive, not an incidental noun) — the harness gives a
# schema only when it tells the author to emit JSON. Negations ("no json",
# "without json", "not in json") must NOT satisfy it.
_RESPOND_JSON_RE = re.compile(
    r"\b(?:respond|reply|answer|return|provide|output|format|give)\b"
    r"[^.\n]{0,40}?\b(?:in|with|as|using)\b\s+(?:a\s+|an\s+|the\s+)?"
    r"json\b[^.\n]{0,30}?\b(?:object|dict|schema|format|response|code)\b",
    re.IGNORECASE)
_JSON_NEGATION_RE = re.compile(
    r"\b(?:no|not|without|don'?t|do\s+not|avoid|never|single[- ]?file)\b"
    r"[^.\n]{0,20}?\bjson\b",
    re.IGNORECASE)


def prompt_requires_json_schema(prompt_text: Optional[str]) -> bool:
    """ORGANIC #680 — True when the prompt explicitly asks for a multi-file
    JSON `{"code":[{path:content},…]}` response (the harness then parses it
    under the schema, so the JSON dict is the format to keep). Two positive
    signals — the literal `{"code":[` envelope, or an explicit positive
    "respond with a JSON object/code …" directive — and an OVERRIDING negation
    guard so "single-file, NO json schema" is correctly read as no-schema.
    Structural, chip-AGNOSTIC."""
    t = prompt_text or ""
    if _JSON_SCHEMA_DIRECTIVE_RE.search(t):
        return True            # the literal envelope is unambiguous
    if _JSON_NEGATION_RE.search(t):
        return False           # an explicit negation overrides fuzzy prose
    return bool(_RESPOND_JSON_RE.search(t))


def json_dict_is_multifile(files: Dict[str, str],
                           prompt_text: Optional[str] = None) -> bool:
    """ORGANIC #680 — single-vs-multi decision mirroring determine_schema's
    signal: a JSON code-dict completion is MULTI-FILE (keep the JSON, the
    harness decodes it under the schema) when the prompt carries an explicit
    JSON-schema directive, OR the dict legitimately spans MORE THAN ONE RTL
    file. Otherwise it is the dominant SINGLE-FILE shape (`no_schema=True`,
    297/302) and the emit must be NORMALIZED to a fenced/bare RTL block the
    harness's `extract_code_blocks` decodes — never the raw JSON verbatim."""
    if prompt_requires_json_schema(prompt_text):
        return True
    rtl = [k for k in files if k.lower().endswith(_RTL_SUFFIXES)]
    return len(rtl) > 1


def extract_code(completion: str) -> Tuple[Optional[str], str]:
    """Return (code, kind). kind ∈ {'json_dict','fenced','bare','doc_only'}.

    The official JSON code-dict shape is checked FIRST (#528 round-2): its
    RTL-suffixed file contents are concatenated as the compile payload; a
    JSON answer whose files carry no Verilog module (JSON-schema / doc
    problems) is doc_only (tolerated). Then code fences (concatenated in
    order), then bare module-carrying text; anything else is doc/SVA-prose
    (tolerated, not compiled)."""
    jf = json_code_files(completion)
    if jf is not None:
        rtl = [v for k, v in jf.items()
               if k.lower().endswith(_RTL_SUFFIXES)]
        if not rtl:  # be permissive: any file content carrying a module
            rtl = [v for v in jf.values()
                   if _MODULE_RE.search(_detection_text(v))]
        code = "\n\n".join(rtl)
        if rtl and _MODULE_RE.search(_detection_text(code)):
            return code, "json_dict"
        return None, "doc_only"
    cf = code_fences(completion)
    if cf:
        code = "\n\n".join(m.group(2) for m in cf)
        if _MODULE_RE.search(_detection_text(code)):
            return code, "fenced"
        return None, "doc_only"
    # bare = fence-less COMPILABLE code: require both a module declaration
    # AND `endmodule` in the stripped view — plain prose saying "the module
    # implements ..." must stay doc_only (#531 round-3 family).
    if not _ANY_FENCE_RE.search(completion):
        det = _detection_text(completion)
        if _MODULE_RE.search(det) and re.search(r"\bendmodule\b", det):
            return completion, "bare"
    return None, "doc_only"


def _run(cmd: List[str], timeout: int = 120) -> Tuple[int, str, str]:
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True,
                            timeout=timeout)
        return cp.returncode, cp.stdout, cp.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError as e:
        return 127, "", str(e)


def hygiene_fix(code: str, workdir: Path) -> Tuple[str, List[str]]:
    """ENFORCED rtl_hygiene_lint --fix; returns (possibly-fixed code, notes).
    Best-effort: a hygiene tool failure never blocks (the compile gate is
    the hard one) but is surfaced as a note."""
    notes: List[str] = []
    tool = PROGRAMS_DIR / "rtl_hygiene_lint.py"
    if not tool.is_file():
        return code, ["rtl_hygiene_lint.py not found — hygiene step skipped"]
    f = workdir / "draft.sv"
    f.write_text(code)
    rc, out, err = _run([sys.executable, str(tool), "--fix", str(f)])
    if rc in (0, 1):  # 0 clean / 1 findings (fixed in place where fixable)
        fixed = f.read_text()
        if fixed != code:
            notes.append("rtl_hygiene_lint --fix applied")
        return fixed, notes
    notes.append(f"rtl_hygiene_lint rc={rc} — hygiene step inconclusive")
    return code, notes


def _offending_lines(blob: str) -> Tuple[List[str], List[str]]:
    """Split iverilog stderr into (offending, missing_module_names)."""
    offending: List[str] = []
    missing: List[str] = []
    for line in blob.splitlines():
        s = line.strip()
        if not s:
            continue
        m = re.search(r"Unknown module type\s*:\s*([A-Za-z_]\w*)", s)
        if m:
            missing.append(m.group(1))
            continue                       # tolerated: context module
        if s.startswith("*** These modules were missing"):
            continue
        m2 = re.match(r"^([A-Za-z_]\w*)\s*referenced\s+\d+\s+time", s)
        if m2:
            missing.append(m2.group(1))
            continue
        if _ELAB_COUNT_RE.match(s):
            continue                       # the count line for the above
        if _SORRY_RE.search(s) or "error" in s.lower() \
                or "give up" in s.lower():
            offending.append(s)
    return offending, sorted(set(missing))


def _stub_for(code: str, name: str) -> Optional[str]:
    """Synthesize an all-input stub for missing context module `name` from
    its instantiation shape in the author's code (named or positional
    connections; named parameters get defaults). None when the shape is not
    confidently parseable (caller then falls back to tolerance)."""
    m = re.search(
        rf"\b{re.escape(name)}\b\s*"
        rf"(#\s*\((?:[^()]|\([^()]*\))*\)\s*)?"
        rf"[A-Za-z_]\w*\s*\(((?:[^();]|\([^()]*\))*)\)\s*;",
        code, re.DOTALL)
    if not m:
        return None
    params: List[str] = []
    if m.group(1):
        params = re.findall(r"\.([A-Za-z_]\w*)\s*\(", m.group(1))
    conns = m.group(2)
    if ".*" in conns:
        return None                        # implicit .* — cannot stub safely
    named = re.findall(r"\.([A-Za-z_]\w*)\s*\(", conns)
    if named:
        ports = named
    else:
        n = len([a for a in conns.split(",") if a.strip()])
        ports = [f"_p{i}" for i in range(n)]
    phdr = (" #(" + ", ".join(f"parameter {p} = 0" for p in params) + ")"
            if params else "")
    plist = ", ".join(f"input {p}" for p in ports)
    return f"module {name}{phdr}({plist});\nendmodule\n"


def iverilog_gate(code: str, workdir: Path) -> Tuple[bool, str, str]:
    """`iverilog -g2012 -t null` parse/elab gate.

    PASS when the only errors are unknown-context-module elaboration errors
    (`Unknown module type`). BLOCK on syntax errors, `sorry:` (icarus-
    unsupported constructs — fatal on the official icarus scorer too) and
    any other error class.

    MASKING GUARD (adversarial-review MED): when unknown context modules
    are present, icarus aborts elaboration BEFORE reporting genuine errors
    in the author's own code (e.g. an undeclared-signal bind). So the gate
    synthesizes all-input stubs for the missing modules (shapes derived
    from the instantiations themselves) and re-runs; a genuine error then
    surfaces and BLOCKS. When stubbing cannot resolve cleanly the gate
    stays conservatively tolerant (never false-blocks a legal context
    instantiation)."""
    f = workdir / "gate.sv"
    f.write_text(code)
    rc, out, err = _run(["iverilog", "-g2012", "-t", "null", str(f)])
    if rc == 0:
        return True, "compile clean", ""
    offending, missing = _offending_lines((out or "") + "\n" + (err or ""))
    if offending:
        return False, "; ".join(offending[:4]), ""
    if not missing:
        return True, "elaboration-only tolerated diagnostics", ""
    # unknown-context-modules only → stub + re-run to unmask genuine errors
    stubs = []
    for name in missing:
        s = _stub_for(code, name)
        if s is None:
            return True, ("elaboration-only unknown context modules "
                          "(tolerated; stub not derivable)"), ""
        stubs.append(s)
    stubs_text = ("\n\n// gate-synthesized context stubs\n"
                  + "\n".join(stubs))
    f2 = workdir / "gate_stubbed.sv"
    f2.write_text(code + stubs_text)
    rc2, out2, err2 = _run(["iverilog", "-g2012", "-t", "null", str(f2)])
    if rc2 == 0:
        return True, ("elaboration clean with synthesized context stubs "
                      f"({', '.join(missing)})"), stubs_text
    off2, miss2 = _offending_lines((out2 or "") + "\n" + (err2 or ""))
    if off2:
        # the stub run surfaced a genuine author-code error — but make sure
        # it is not an artifact of the stub itself (port/parameter shape).
        stub_artifacts = [s for s in off2
                          if "gate_stubbed.sv" in s and any(
                              n in s for n in missing)]
        genuine = [s for s in off2 if s not in stub_artifacts]
        if genuine:
            return False, "; ".join(genuine[:4]) + " [unmasked via stubs]", ""
    return True, ("elaboration-only unknown context modules (tolerated)"
                  ), stubs_text


_YOSYS_CELLS_RE = re.compile(
    r"Number of cells:\s+(\d+)"        # yosys ≤0.4x / 0.33 format
    r"|^\s*(\d+)\s+cells\b",          # yosys 0.6x columnar format (#536)
    re.MULTILINE)


_MODULE_NAMES_RE = re.compile(r"\bmodule\s+([A-Za-z_]\w*)", re.MULTILINE)

_CTX_MODULE_RE = re.compile(
    r"referenced in module .* is not part of the design")
_LATCH_ERROR_RE = re.compile(
    r"ERROR:.*(?:No latch inferred for signal"
    r"|Latch inferred for signal)")


def _confirming_rerun(code_text: str, top: str, workdir: Path,
                      tolerable_names=()) -> Tuple[bool, str]:
    """#531 round-5 (adversarial-review HIGH) — yosys aborts at the FIRST
    error, and both tolerated classes fire in EARLY passes (HIERARCHY /
    PROC_DLATCH): a later-pass fatal (e.g. PROC_DFF multiple-edge) never
    prints, so the tolerated error being the only ERROR line proves
    nothing about the rest of the module. Before tolerating, re-run yosys
    on a smoke COPY with the tolerated obstacle neutralized (latch
    keywords relaxed / missing context modules stubbed) so any
    INDEPENDENT fatal gets the chance to surface. Only a clearly
    independent, non-tolerable ERROR blocks; an inconclusive re-run
    (clean, stub-connection errors, no ERROR lines at all) keeps the
    field-accepted tolerance — the re-run may only ADD blocking power,
    never widen the tolerance."""
    f2 = workdir / "smoke_confirm.sv"
    f2.write_text(code_text)
    rc, out, err = _run(
        ["yosys", "-p",
         f"read_verilog -sv {f2}; synth -top {top}; stat"], timeout=300)
    blob = (out or "") + "\n" + (err or "")
    if rc == 0:
        return True, "confirming re-run clean"
    err_lines = [ln for ln in blob.splitlines() if "ERROR:" in ln]
    pat = (r"ERROR:.*(?:No latch inferred for signal"
           r"|Latch inferred for signal"
           r"|referenced in module .* is not part of the design")
    for n in sorted(tolerable_names):
        pat += "|" + re.escape(n)
    pat += ")"
    tolerable = re.compile(pat)
    if not err_lines or all(tolerable.search(ln) for ln in err_lines):
        return True, "confirming re-run inconclusive (no independent fatal)"
    tail = [s for s in blob.splitlines() if s.strip()][-3:]
    return False, (f"yosys-smoke failed on module {top!r} (confirming "
                   f"re-run surfaced a fatal the early-pass abort had "
                   f"masked): " + "; ".join(tail))


# A synthesis-AREA noun — the anchor that distinguishes a cid007 area-opt prompt
# ("reduce the cell AREA by N%") from an incidental "reduce <latency|power> by N%"
# functional prompt. Required in addition to the #729 threshold parse (which alone
# fires on the bare verb "reduce"). "gating" (a clock-gating verb) deliberately does
# NOT match `\bgates?\b`. chip-AGNOSTIC: pure synthesis vocabulary.
_AREA_NOUN_RE = re.compile(
    r'\b(?:area|cells?|wires?|gates?|luts?|netlist|'
    r'logic\s+elements?|slices?)\b', re.I)
# An area-OPTIMISATION verb — paired with `_AREA_NOUN_RE` it recognises a
# qualitative (no-`%`) cid007 directive. chip-AGNOSTIC synthesis vocabulary.
_AREA_OPT_VERB_RE = re.compile(
    r'\b(?:reduce\w*|minimi[sz]\w*|optimi[sz]\w*|shrink\w*|'
    r'smaller|fewer|lower|decreas\w*)\b', re.I)
# A CVDP category code (`cidNNN`) — used to tell a KNOWN non-synth category from
# an UNKNOWN one (no category metadata) for the fail-safe tri-state.
_CID_RE = re.compile(r'^cid\d{3}$', re.I)


def _problem_is_synth_scored(prompt_text: Optional[str] = None,
                             rec: Optional[Dict] = None) -> bool:
    """True iff this CVDP problem's OFFICIAL harness runs yosys `synth` on the
    completion — the area-optimization / synth-quality category (cid007), whose
    scorer IS yosys 0.40, NOT cocotb/iverilog (cvdp_fail_triage SYNTH_GATE /
    SYNTH_THRESHOLD official fail modes; cvdp_env_preflight #714 __OSS_PNR_IMAGE__
    synth Dockerfile; ppa_area_threshold_check #729 "reduce the area of this RTL").

    This gates the synth-TIMEOUT tolerance in `yosys_smoke`: for a synth-scored
    problem a tolerated timeout would EMIT a design the official synth gate may
    FAIL and lose the re-author the #531 smoke exists to trigger — a §4.05
    false-SKIP — so the timeout must BLOCK (fail-safe), whereas for the dominant
    cocotb/iverilog functional population yosys is never scored and the timeout is
    a true false-fail to be tolerated. Three corroborating SINGLE-SOURCE signals;
    ANY positive ⇒ synth-scored:
      (1) the prompt parses an area-reduction threshold — the #729 detector
          (a cid007 task definition is literally "reduce the area … by N%");
      (2) the record's `categories` carries `cid007`;
      (3) the record's `input.context` harness references `__OSS_PNR_IMAGE__` (#714).
    Absence of all three ⇒ treated as non-synth-scored. chip-AGNOSTIC: pure
    CVDP-category structure (no design name / problem-id / oracle value)."""
    # (1) area-reduction threshold in the prompt — reuse the #729 gate (single-source),
    # BUT additionally require an explicit SYNTHESIS-AREA noun. The #729 parser treats
    # the bare verb "reduce" as an area word, so "reduce latency/power by N%" would
    # otherwise false-fire and OVER-BLOCK a functional (cocotb-scored) problem's
    # synth-timeout (Step-2.7 round-2: a synthesis-area noun anchors it to cid007).
    if isinstance(prompt_text, str) and _AREA_NOUN_RE.search(prompt_text):
        # (1a) a parseable area-reduction `%` threshold (#729), OR
        try:
            if str(PROGRAMS_DIR) not in sys.path:
                sys.path.insert(0, str(PROGRAMS_DIR))
            from ppa_area_threshold_check import (  # noqa: E402
                parse_threshold_from_prompt, ThresholdParseError)
            try:
                parse_threshold_from_prompt(prompt_text)
                return True
            except ThresholdParseError:
                pass
        except Exception:  # noqa: BLE001 — detector import/parse is best-effort
            pass
        # (1b) a QUALITATIVE area-optimization directive (no literal `%` / a
        # word-fraction / a far-apart threshold the #729 window misses): an
        # area-opt VERB together with the synthesis-area noun gate above —
        # "minimize the silicon area / use as few cells as possible / reduce the
        # gate count". Over-detecting synth-scored here is the §4.05-SAFE
        # direction (block-and-re-author, never under-detect → leak).
        if _AREA_OPT_VERB_RE.search(prompt_text):
            return True
    if isinstance(rec, dict):
        # (2) categories cid007
        cats = rec.get("categories") or []
        if isinstance(cats, (list, tuple)) and any(
                str(c).strip().lower() == "cid007" for c in cats):
            return True
        # (3) __OSS_PNR_IMAGE__ in the harness-provided input.context (#714)
        ctx = rec.get("input", {})
        ctx = ctx.get("context") if isinstance(ctx, dict) else None
        if isinstance(ctx, dict):
            if any("__OSS_PNR_IMAGE__" in str(v) for v in ctx.values()):
                return True
        elif isinstance(ctx, str) and "__OSS_PNR_IMAGE__" in ctx:
            return True
    return False


def _rec_categories_known(rec: Optional[Dict]) -> bool:
    """True iff this record carries a parseable CVDP category code (`cidNNN`) —
    i.e. the gate KNOWS the problem's category (so a non-cid007 value is a
    POSITIVE confirmation of non-synth-scored, distinct from 'no metadata')."""
    if not isinstance(rec, dict):
        return False
    cats = rec.get("categories") or []
    return isinstance(cats, (list, tuple)) and any(
        _CID_RE.match(str(c).strip()) for c in cats)


def _resolve_synth_scored(prompt_text: Optional[str] = None,
                          rec: Optional[Dict] = None,
                          hint: Optional[bool] = None) -> Optional[bool]:
    """Tri-state synth-scored resolution for the yosys-smoke timeout fail-safe:
      * True  — POSITIVELY synth-scored (area-opt/cid007: the `hint` from
                --dataset/--prompts, or an in-rec/prompt signal) → BLOCK a timeout.
      * False — POSITIVELY non-synth-scored (a known CVDP category that is NOT
                cid007, OR a hint of False) → TOLERATE a timeout (no false-fail).
      * None  — UNKNOWN (no category metadata reached the gate) → fail-safe BLOCK.
    The `hint` is the authoritative per-id value the operator's --dataset/--prompts
    supplies (`_load_synth_scored_map`); the in-rec/prompt detector is the fallback
    when no dataset/prompts metadata is available for this id."""
    if hint is True or _problem_is_synth_scored(prompt_text, rec):
        return True
    if hint is False or _rec_categories_known(rec):
        return False
    return None


def _load_synth_scored_map(path) -> Dict[str, bool]:
    """{id: True|False} from a CVDP dataset / prompts JSONL — the AUTHORITATIVE
    per-id synth-scored signal the documented {id, completion} draft record lacks
    (Step-2.7 round-2: without this the detector is structurally signal-1-only).
    True  iff the source record is area-opt/cid007 (categories cid007, an
          `input.context` referencing `__OSS_PNR_IMAGE__` #714, or an area-opt
          prompt); False iff its categories are KNOWN and exclude cid007 (a
          positive non-synth confirmation). Ids with no category metadata are
          OMITTED (→ the tri-state resolves them to None = fail-safe BLOCK).
    chip-AGNOSTIC: pure CVDP-category structure."""
    out: Dict[str, bool] = {}
    p = Path(path)
    if not p.is_file():
        return out
    for ln in p.read_text(errors="replace").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if not isinstance(d, dict):     # a JSON array / scalar line, not a record
            continue
        rid = d.get("id")
        if rid is None:
            continue
        rid = str(rid)
        prompt = d.get("prompt") or d.get("input") if isinstance(
            d.get("input"), str) else d.get("prompt")
        # "True WINS" union — intra-file too (Step-2.7 round-3): a positive
        # synth-scored signal must never be DOWNGRADED to False by a later
        # duplicate-id line (a multi-record-per-problem dataset, or a cat'd
        # prompts+dataset file). A True is unconditional; a False only
        # `setdefault`s, so it can seed but never overwrite a True.
        if _problem_is_synth_scored(prompt if isinstance(prompt, str) else None, d):
            out[rid] = True
        elif _rec_categories_known(d):
            out.setdefault(rid, False)
        # else: no metadata → omit (resolves to None = fail-safe)
    return out


def yosys_smoke(code: str, workdir: Path,
                stubs_text: str = "",
                synth_scored: Optional[bool] = None) -> Tuple[bool, str]:
    """ORGANIC #531 — synthesizability smoke. 13/92 first-round CVDP fails
    were harness synth-gate failures the emit gate never caught.

    PER-MODULE (adversarial-review MED): `synth -auto-top` keeps ONE root
    module and silently REMOVES sibling roots as unused — an unsynthesizable
    DUT next to a trivial helper evaded the smoke entirely. Every module
    declared in the completion is synthesized as its own top.

    FRONTEND-GAP TOLERANCE (adversarial-review MED): the host yosys SV
    frontend may be NARROWER than the official scorer's (host 0.33 rejects
    `parameter type`; official 0.40 accepts it). A read_verilog FRONTEND
    parse error on code iverilog already accepted is therefore tolerated
    with a note — only SYNTH-stage failures (proc/memory/check errors after
    the frontend) and stat-absence block. Cell-count parsing is version-
    robust (`Number of cells:` and the 0.6x columnar `N cells` — the #536
    format-drift lesson). Context stubs from the iverilog gate are appended
    so unknown context modules don't abort hierarchy elaboration."""
    full = code + (stubs_text or "")
    f = workdir / "smoke.sv"
    f.write_text(full)
    stub_names = set(_MODULE_NAMES_RE.findall(stubs_text or ""))
    # #531 round-3: detect module names on the comment/string-stripped VIEW —
    # prose inside comments must never become a phantom synth -top target.
    own_modules = [m for m in _MODULE_NAMES_RE.findall(_detection_text(code))
                   if m not in stub_names]
    if not own_modules:
        return False, ("yosys-smoke: no module declaration found in the "
                       "code payload")
    details: List[str] = []
    timed_out: List[str] = []          # modules whose synth only TIMED OUT (unverified)
    synth_timeout = 300
    for top in own_modules:
        # NOTE: no -q — quiet mode suppresses the stat table itself.
        rc, out, err = _run(
            ["yosys", "-p",
             f"read_verilog -sv {f}; synth -top {top}; stat"],
            timeout=synth_timeout)
        blob = (out or "") + "\n" + (err or "")
        if rc != 0:
            # A genuine `synth` TIMEOUT is _run's TimeoutExpired sentinel — the
            # EXACT empty-blob SHAPE `(124, "", "timeout")` — NOT the #604 "yosys
            # absent" case (rc==127). It is matched on that shape, NOT bare rc==124:
            # a PRESENT yosys exiting 124 WITH output (e.g. via a `timeout(N)`
            # PATH wrapper enforcing a site synth budget) carries a real banner /
            # ERROR (`out != ""`), so it does NOT match here and falls through to
            # the #604 banner guard, which blocks the real synth ERROR (Step-2.7
            # round-1 lens B: keying on bare 124 mis-tolerated a wrapped real error).
            #
            # A genuine synth-timeout is INCONCLUSIVE about synthesizability. Whether
            # tolerating it is §4.05-SAFE depends on the problem CATEGORY:
            #  * SYNTH-SCORED (area-opt / cid007) — the OFFICIAL harness runs yosys
            #    0.40 on the completion (cvdp_fail_triage SYNTH_GATE/SYNTH_THRESHOLD;
            #    #714 __OSS_PNR_IMAGE__; #729 area-threshold). Tolerating would EMIT a
            #    design the official synth gate may FAIL and lose the re-author the
            #    #531 smoke exists to trigger — a §4.05 false-SKIP. So it BLOCKS
            #    (fail-safe → re-author). (Step-2.7 round-1 lens A: the prior blanket
            #    "official scorer never runs yosys" was FALSE for this category.)
            #  * NON-synth-scored (the dominant cocotb/iverilog functional set) —
            #    yosys is NEVER scored, so a synth-timeout is a true false-fail of a
            #    SCORABLE design (observed clean-room: a 44-line parameterized
            #    barrel_shifter / a binary-search-tree sorter parse in <1s but synth
            #    does not converge in 300s). It is tolerated as INCONCLUSIVE rather
            #    than manufacture a guaranteed false fail.
            is_timeout = (rc == 124 and (out or "") == ""
                          and (err or "").strip() == "timeout")
            if is_timeout and shutil.which("yosys") is not None:
                # FAIL-SAFE tri-state (Step-2.7 round-2: the category signals
                # are structurally absent on a bare {id,completion} draft, so a
                # bool default would tolerate EVERY cid007 timeout in a no-dataset
                # run = §4.05 false-SKIP). Tolerate ONLY when the problem is
                # POSITIVELY confirmed NON-synth-scored (`synth_scored is False`);
                # BLOCK on synth-scored (`True`) AND on UNKNOWN (`None`) — a
                # synth-timeout is tolerated only when we can prove the official
                # scorer ignores yosys for this problem.
                if synth_scored is not False:
                    reason = ("a SYNTH-SCORED (area-opt/cid007) problem whose "
                              "OFFICIAL harness runs yosys" if synth_scored
                              else "a problem whose category is UNKNOWN here "
                              "(supply --dataset/--prompts so a non-synth-scored "
                              "problem can be confirmed)")
                    return False, (
                        f"yosys-smoke BLOCK on module {top!r}: `synth` timed out "
                        f"(>{synth_timeout}s) on {reason} — tolerating would emit "
                        f"a design the official synth gate may fail and lose the "
                        f"re-author (§4.05 fail-safe; NOT the #604 absent-yosys "
                        f"case).")
                timed_out.append(top)
                details.append(
                    f"{top}: yosys-smoke INCONCLUSIVE — `synth` timed out "
                    f"(>{synth_timeout}s); yosys IS present and iverilog already "
                    f"elaborated the design, and this is NOT a synth-scored "
                    f"(cid007) problem (the official scorer is cocotb+iverilog for "
                    f"this category), so the timeout is tolerated rather than a "
                    f"false fail. NOT the #604 absent-yosys case.")
                continue
            # #604: yosys binary ENTIRELY ABSENT (rc=127 is _run's
            # FileNotFoundError sentinel) — or any case with NO evidence that
            # yosys actually started — must NOT be misread as a frontend-gap and
            # silently tolerated. Doing so degrades the synth smoke to a no-op
            # while the report still reads PASS (the exact #531 silent
            # false-PASS class this smoke exists to catch). The frontend-gap
            # tolerance below therefore REQUIRES a real yosys start banner; a
            # FileNotFoundError blob (which merely contains the literal 'yosys'
            # command name) does not qualify as "yosys started".
            yosys_started = bool(re.search(
                r"Yosys\s+[\d.]|Executing\s+\w+\s+pass|/----", blob))
            if rc == 127 or not yosys_started:
                return False, (
                    f"yosys-smoke CANNOT ENFORCE on module {top!r}: yosys did "
                    f"not run (rc={rc}; no yosys start banner) — install yosys "
                    f"or run on a host that has it. Refusing to tolerate as a "
                    f"frontend-gap (#604).")
            # frontend vs synth-stage: the SYNTH pass header only appears
            # once the frontend parsed the file.
            frontend = "Executing SYNTH pass" not in blob \
                and "Executing HIERARCHY pass" not in blob
            if frontend:
                details.append(f"{top}: yosys-frontend-gap tolerated "
                               f"(iverilog accepted; host yosys SV frontend "
                               f"may trail the official 0.40)")
                continue
            # #531 round-4 (field full-corpus regression) — two synth-stage
            # error classes must be TOLERATED, not blocked. Both abort
            # yosys in an EARLY pass, so each tolerance first runs a
            # confirming re-run (_confirming_rerun) that neutralizes the
            # tolerated obstacle and blocks only on an INDEPENDENT fatal
            # the abort had masked (#531 round-5 adversarial review).
            # (a) hierarchy unknown CONTEXT module — the compile path
            #     tolerates unknown context modules (with or without a
            #     derivable stub) but the synth hierarchy pass hard-fails on
            #     them; mirror the compile-path tolerance (the official
            #     harness supplies those context files at scoring time).
            if _CTX_MODULE_RE.search(blob):
                missing = set(re.findall(
                    r"Module `\\?(\w+)' referenced in module", blob))
                missing -= set(own_modules) | stub_names
                if missing:
                    # prefer a port-aware _stub_for stub (named/positional
                    # connections elaborate past hierarchy so later-pass
                    # fatals can print); port-less fallback otherwise.
                    stubbed = full + "\n" + "\n".join(
                        _stub_for(code, m) or f"module {m}(); endmodule"
                        for m in sorted(missing))
                    ok2, why2 = _confirming_rerun(stubbed, top, workdir,
                                                  tolerable_names=missing)
                    if not ok2:
                        return False, why2
                details.append(f"{top}: unknown context module(s) at synth "
                               f"hierarchy tolerated (mirrors the compile-"
                               f"path context tolerance)")
                continue
            # (b) yosys latch-semantics strictness (`ERROR: Latch inferred
            #     for signal … from always_comb` / mem2reg latch checks) —
            #     stricter than the official harness for sim-only problems
            #     (no synth gate there); downgrade to an ADVISORY note so
            #     the author still sees it, never a block.
            #     #531 round-5 (field leak repro): the tolerance anchors on
            #     the ERROR LINES themselves, never the whole blob —
            #     "Latch inferred for signal" ALSO prints as a PROC_DLATCH
            #     info line (plain `always @*` missing-else, no ERROR:
            #     prefix), and a blob-wide search let that info line mask a
            #     co-occurring REAL fatal ERROR (e.g. PROC_DFF "Multiple
            #     edge sensitive events") as PASS. Tolerate ONLY when every
            #     ERROR: line is latch-class; any non-latch ERROR → block.
            #     The confirming re-run relaxes always_comb/always_latch to
            #     plain `always @*` (smoke COPY only — never written back)
            #     so the inferred latch becomes a benign INFO and synthesis
            #     proceeds past PROC_DLATCH to surface later-pass fatals.
            error_lines = [ln for ln in blob.splitlines()
                           if "ERROR:" in ln]
            if error_lines and all(_LATCH_ERROR_RE.search(ln)
                                   for ln in error_lines):
                relaxed = re.sub(r"\balways_(?:comb|latch)\b",
                                 "always @*", full)
                ok2, why2 = _confirming_rerun(relaxed, top, workdir)
                if not ok2:
                    return False, why2
                details.append(f"{top}: latch-inference strictness "
                               f"tolerated as ADVISORY (yosys always_comb/"
                               f"latch semantic check exceeds the official "
                               f"sim-only harness; review for intent)")
                continue
            tail = [s for s in blob.splitlines() if s.strip()][-3:]
            return False, (f"yosys-smoke failed on module {top!r}: "
                           + "; ".join(tail))
        matches = list(_YOSYS_CELLS_RE.finditer(blob))
        if not matches:
            return False, (f"yosys-smoke: module {top!r} synthesized to "
                           f"nothing — stat reported no module (the silent "
                           f"downstream harness KeyError trap)")
        cells = max(int(m.group(1) or m.group(2)) for m in matches)
        details.append(f"{top}: {cells} cells")
    # HONEST VERDICT (Step-2.7 round-1 lens C): when one or more modules were only
    # TIMEOUT-tolerated (zero real synth verification), the top-line must read
    # INCONCLUSIVE — NOT a clean "yosys-smoke ok" — so a run audit / verdict-token
    # consumer can see the synth coverage was incomplete, not a verified PASS.
    headline = "yosys-smoke INCONCLUSIVE" if timed_out else "yosys-smoke ok"
    return True, headline + " (" + "; ".join(details) + ")"


def gate_record(rec: Dict, workdir: Path,
                prompt_text: Optional[str] = None,
                synth_scored: Optional[bool] = None) -> Tuple[bool, Dict, Dict]:
    """Gate one {id, completion} record → (ok, out_record, report_entry).

    Hygiene runs PER CODE FENCE (each fence body is fixed separately — a
    single concatenated blob re-fixed per fence would duplicate every module
    into each fence and turn a clean 2-fence completion into a guaranteed
    duplicate-declaration scorer FAIL). For the FENCED kind the emitted
    completion is the de-fenced concatenation of those fixed bodies — the
    EXACT bytes the gate compiled — never the original text with the fence
    markers retained (ORGANIC #626: a retained ```verilog marker is a line-1
    backtick macro directive that ELAB_ERRORs the verbatim-written .sv at
    official scoring).

    ORGANIC #680: a JSON code-dict completion is likewise NORMALIZED to the
    format the harness decodes for THIS problem's schema. For the dominant
    SINGLE-FILE shape (`no_schema=True`, 297/302) the harness writes the
    completion verbatim, so the JSON dict must be re-serialized as a FENCED
    RTL block (the EXACT bytes the gate compiled); only a genuinely MULTI-FILE
    problem (prompt JSON-schema directive, or >1 RTL file) keeps the JSON dict.
    `prompt_text` (this id's prompt) supplies determine_schema's signal; when
    absent only the file-count signal applies (a >1-RTL-file dict stays JSON,
    a single-RTL-file dict normalizes — the safe 297/302 default)."""
    rid = rec.get("id", "")
    completion = rec.get("completion", "") or ""
    # ORGANIC #535 round-2 — an EMPTY / whitespace-only / trivially-short
    # completion is the classic transmission-corruption shape (escaping ate
    # the payload); it used to slip through as PASS_DOC_ONLY. The doc_only
    # tolerance is for SUBSTANTIVE documentation answers only.
    if len(completion.strip()) < 20:
        entry = {"id": rid, "kind": "empty", "notes": [],
                 "compile": ("empty-or-blank completion "
                             "(empty-after-roundtrip corruption shape, "
                             "#535)"),
                 "verdict": "BLOCKED"}
        return False, rec, entry
    code, kind = extract_code(completion)
    entry: Dict = {"id": rid, "kind": kind, "notes": []}
    # Does THIS problem's official harness run yosys synth (area-opt/cid007)? — gates
    # the yosys-smoke synth-TIMEOUT tolerance (tri-state fail-safe): tolerate a
    # timeout ONLY for a POSITIVELY non-synth-scored problem; BLOCK for synth-scored
    # AND for unknown-category. `synth_scored` (if passed) is the authoritative
    # per-id hint from the operator's --dataset/--prompts (`_load_synth_scored_map`).
    synth_scored = _resolve_synth_scored(prompt_text, rec, synth_scored)
    if kind == "doc_only":
        entry["verdict"] = "PASS_DOC_ONLY"
        return True, rec, entry
    if kind == "json_dict":
        # #528 round-2 — official JSON code-dict: hygiene each RTL file
        # body separately, gate the concatenation, and write fixes back by
        # re-serializing the SAME JSON structure (prefix/suffix prose kept)
        # so the official harness re-parses it identically.
        files = json_code_files(completion) or {}
        rtl_keys = [k for k in files
                    if k.lower().endswith(_RTL_SUFFIXES)]
        if not rtl_keys:
            rtl_keys = [k for k, v in files.items()
                        if _MODULE_RE.search(v)]
        fixed_map: Dict[str, str] = {}
        for idx, k in enumerate(rtl_keys):
            fwd = workdir / f"j{idx}"
            fwd.mkdir(parents=True, exist_ok=True)
            fb, notes = hygiene_fix(files[k], fwd)
            entry["notes"].extend(notes)
            fixed_map[k] = fb
        combined = "\n\n".join(fixed_map[k] for k in rtl_keys)
        ok, why, stubs = iverilog_gate(combined, workdir)
        entry["compile"] = why
        if not ok:
            entry["verdict"] = "BLOCKED"
            return False, rec, entry
        ok2, why2 = yosys_smoke(combined, workdir, stubs, synth_scored=synth_scored)
        entry["synth"] = why2
        if not ok2:
            entry["verdict"] = "BLOCKED"
            return False, rec, entry
        entry["verdict"] = "PASS"
        out_rec = dict(rec)
        if json_dict_is_multifile(files, prompt_text):
            # MULTI-FILE: the harness decodes the JSON under its schema — keep
            # the JSON dict (re-serialize ONLY when hygiene changed a body so
            # the harness re-parses identically; prefix/suffix prose kept).
            entry["emit_format"] = "json_dict (multi-file schema)"
            if any(fixed_map[k] != files[k] for k in rtl_keys):
                i = completion.find("{")
                j = completion.rfind("}")
                obj = json.loads(completion[i:j + 1])
                code_field = obj.get("code")
                if isinstance(code_field, list):
                    for d in code_field:
                        if isinstance(d, dict):
                            for k in list(d):
                                if k in fixed_map:
                                    d[k] = fixed_map[k]
                elif isinstance(code_field, dict):
                    for k in list(code_field):
                        if k in fixed_map:
                            code_field[k] = fixed_map[k]
                out_rec["completion"] = (completion[:i]
                                         + json.dumps(obj, ensure_ascii=False)
                                         + completion[j + 1:])
        else:
            # ORGANIC #680 SINGLE-FILE (`no_schema=True`, 297/302): the harness
            # `parse_model_response` runs `extract_code_blocks`, which on a
            # completion with NO ```fence FALLS BACK to `res.strip()` and writes
            # the WHOLE completion verbatim as the single .sv. A JSON dict would
            # then land as `{"code": […` on line 1 → scorer ELAB_ERROR. Emit the
            # EXACT RTL bytes the gate just compiled (`combined`) as BARE,
            # DE-FENCED RTL — the same robust shape #626 settled on for the
            # fenced kind: `extract_code_blocks` finds no fence and `res.strip()`
            # writes clean `module…endmodule` that compiles, AND were the harness
            # to look for a fence there is none to become a line-1 backtick macro
            # directive (the #626 ELAB_ERROR shape). Invariant: the bytes the
            # gate COMPILED == the bytes the scorer compiles from the emit.
            entry["emit_format"] = ("bare RTL (single-file no_schema "
                                    "normalize, #680)")
            out_rec["completion"] = combined
        return True, out_rec, entry
    if kind == "bare":
        fixed, notes = hygiene_fix(code, workdir)
        entry["notes"].extend(notes)
        ok, why, stubs = iverilog_gate(fixed, workdir)
        entry["compile"] = why
        if not ok:
            entry["verdict"] = "BLOCKED"
            return False, rec, entry
        ok2, why2 = yosys_smoke(fixed, workdir, stubs, synth_scored=synth_scored)
        entry["synth"] = why2
        if not ok2:
            entry["verdict"] = "BLOCKED"
            return False, rec, entry
        entry["verdict"] = "PASS"
        out_rec = dict(rec)
        if fixed != code:
            out_rec["completion"] = fixed
        return True, out_rec, entry
    # fenced: hygiene each code fence separately, compile the concatenation
    fences = code_fences(completion)
    fixed_bodies: List[str] = []
    for i, m in enumerate(fences):
        fence_wd = workdir / f"f{i}"
        fence_wd.mkdir(parents=True, exist_ok=True)
        fb, notes = hygiene_fix(m.group(2), fence_wd)
        entry["notes"].extend(notes)
        fixed_bodies.append(fb)
    combined = "\n\n".join(fixed_bodies)
    ok, why, stubs = iverilog_gate(combined, workdir)
    entry["compile"] = why
    if not ok:
        entry["verdict"] = "BLOCKED"
        return False, rec, entry
    ok2, why2 = yosys_smoke(combined, workdir, stubs, synth_scored=synth_scored)
    entry["synth"] = why2
    if not ok2:
        entry["verdict"] = "BLOCKED"
        return False, rec, entry
    entry["verdict"] = "PASS"
    out_rec = dict(rec)
    # ORGANIC #626 — EMIT the de-fenced extracted payload (`combined`: the EXACT
    # bytes the gate just compiled), NOT the original completion with the code-
    # fence MARKERS (```verilog / ```) retained. The official scorer writes the
    # emitted completion VERBATIM to rtl/<id>.sv; a retained ```verilog opener
    # makes line 1 a backtick macro directive → ":1: macro verilog undefined" +
    # ":1: syntax error" → the problem ELAB_ERRORs at scoring even though the
    # de-fenced code the gate proved compiles clean (~2.6% of completions
    # silently broken). The invariant: the bytes the gate COMPILED == the bytes
    # the scorer compiles from the emitted completion. `combined` already
    # concatenates ALL hygiene-fixed fence bodies (multi-fence safe) and drops
    # any inter-fence prose that would itself break a verbatim-written .sv.
    # Unconditional (not gated on a hygiene diff): an unchanged fenced draft was
    # the dominant ELAB_ERROR shape — it kept the fence verbatim.
    out_rec["completion"] = combined
    return True, out_rec, entry


_REQ_FILENAME_RE = re.compile(
    r"(?:rtl|src|hdl|verilog)/([A-Za-z_]\w*)\.s?v\b"
    r"|(?:file|named|save\s+(?:it\s+)?(?:to|as)|create)\b[^\n]{0,40}?"
    r"\b([A-Za-z_]\w*)\.s?v\b",
    re.IGNORECASE)

# ORGANIC #642 round-2 (field-agent reopen) — the CVDP harness derives its
# cocotb TOPLEVEL from the prompt's stated module name, NOT only from an
# `rtl/<name>.sv` filename line. Field-measured: of 302 nonagentic problems
# only 9 carry an `rtl/cvdp_copilot_<id>.sv` filename line; the other 293
# state the required top via a `Module Name:` declaration (markdown
# `### Module Name:` / `Module Name:` followed by a backtick-quoted or plain
# identifier). The #559 filename-only extractor missed those 293, so the gate
# fell through to the id-derived fallback and false-BLOCKED 97% of correct
# completions (directly contradicting the official scorer — counter-example
# `cvdp_copilot_16qam_mapper_0001`, top `qam16_mapper_interpolated`, which the
# scorer PASSes but the gate BLOCKed). Recognising the `Module Name:`
# declaration recovers the real prompt-derived top so it (not the id stem) is
# the authoritative conformance target. chip-AGNOSTIC: pure prompt-prose
# structure, no chip / vendor / SKU literal.
_REQ_MODULE_NAME_RE = re.compile(
    r"module\s+name\s*[`'\"*]*\s*[:\-]?\s*\n?\s*"
    r"(?:[`'\"*]+\s*)?([A-Za-z_]\w*)",
    re.IGNORECASE)


def required_module_names_from_prompt(prompt_text):
    """ORGANIC #559 / #642 round-2 — extract the set of module-name STEMS the
    prompt asks the author to implement. Two structural sources, both used by
    the CVDP harness to derive its cocotb TOPLEVEL:
      (a) #559 — a saved filename `rtl/<name>.sv` ('save it to foo.sv', 'a
          file named bar.v');
      (b) #642 round-2 — a `Module Name:` declaration (markdown
          `### Module Name:` / `Module Name:` then a backtick-quoted or plain
          identifier), the form 293/302 nonagentic problems actually use.
    Pure structural parse — chip-AGNOSTIC. Returns a set of stems (possibly
    empty)."""
    stems = set()
    for m in _REQ_FILENAME_RE.finditer(prompt_text or ""):
        nm = m.group(1) or m.group(2)
        if nm:
            stems.add(nm)
    for m in _REQ_MODULE_NAME_RE.finditer(prompt_text or ""):
        nm = m.group(1)
        if nm:
            stems.add(nm)
    return stems


def completion_module_names(completion):
    """Module names declared in a completion (comment/string-stripped view,
    reusing the same detection path the synth smoke uses)."""
    code, kind = extract_code(completion or "")
    if kind == "doc_only" or not code:
        return set()
    return set(_MODULE_NAMES_RE.findall(_detection_text(code)))


# ORGANIC #715 — SV/Verilog keywords + gate primitives that match the
# `<type> <name> (` instantiation shape but are NOT module instantiations.
_NON_INSTANCE_KEYWORDS = frozenset({
    "module", "macromodule", "function", "task", "if", "else", "for", "while",
    "case", "casez", "casex", "always", "always_ff", "always_comb",
    "always_latch", "initial", "final", "assign", "wire", "reg", "logic",
    "bit", "byte", "int", "integer", "longint", "shortint", "genvar",
    "generate", "endgenerate", "begin", "end", "posedge", "negedge", "input",
    "output", "inout", "parameter", "localparam", "typedef", "struct",
    "union", "enum", "import", "package", "endpackage", "interface", "modport",
    "property", "sequence", "assert", "assume", "cover", "return", "break",
    "continue", "repeat", "forever", "fork", "join", "disable", "wait", "do",
    "real", "time", "string", "event", "signed", "unsigned", "and", "or",
    "not", "nand", "nor", "xor", "xnor", "buf", "bufif0", "bufif1", "notif0",
    "notif1", "pmos", "nmos", "cmos", "tran", "tranif0", "tranif1", "pullup",
    "pulldown", "supply0", "supply1", "defparam", "specify", "endspecify",
})
_INSTANCE_RE = re.compile(
    r"^\s*([A-Za-z_]\w*)\s+(?:#\s*\([^;]*?\)\s*)?[A-Za-z_]\w*\s*\(",
    re.MULTILINE)


def instantiated_module_names(code: str) -> set:
    """ORGANIC #715 — module-TYPE names INSTANTIATED in `code` (the
    `<type> [#(params)] <inst> (` shape), comment/string-stripped, minus SV
    keywords / gate primitives. chip-AGNOSTIC: pure instantiation grammar."""
    det = _detection_text(code or "")
    out: set = set()
    for m in _INSTANCE_RE.finditer(det):
        nm = m.group(1)
        if nm and nm not in _NON_INSTANCE_KEYWORDS:
            out.add(nm)
    return out


def context_module_names(context_files) -> set:
    """ORGANIC #715 round-2 — the module-name STEMS the prompt's `input.context`
    ALREADY PROVIDES (a CVDP record's `input.context` is a dict whose keys are
    `rtl/<name>.sv` / `verif/<name>.sv` paths the harness compiles ALONGSIDE the
    author's completion). A module instantiated by the author but supplied here
    is a CONTEXT module — the author must NOT (and need not) re-emit it, so it is
    NEVER an INCOMPLETE-file block. chip-AGNOSTIC: pure filename-stem parse.
    Accepts the dict (keys used) or an iterable of path strings."""
    out: set = set()
    if isinstance(context_files, dict):
        names = context_files.keys()
    elif context_files:
        names = context_files
    else:
        names = []
    _RTL_EXTS = (".sv", ".svh", ".v", ".vh")
    for k in names:
        if not isinstance(k, str):
            continue
        base = Path(k).name
        # only RTL files name a module; a docs/spec.md context entry is not a
        # module and must NOT be added (it would never collide with an
        # instantiated module name, but keep the set clean + intent-correct).
        matched = next((e for e in _RTL_EXTS if base.endswith(e)), None)
        if not matched:
            continue
        stem = base[: -len(matched)]
        if stem:
            out.add(stem)
    return out


def multifile_incompleteness(completion, prompt_text, context_modules=None):
    """ORGANIC #715 (round-2 #715-overfire fix) — detect a completion that
    INSTANTIATES a submodule whose definition file was DROPPED. Returns
    (block, warn):
      - block: instantiated modules the PROMPT requires the author to deliver
        (required_module_names_from_prompt) AND that are NOT already provided by
        the prompt's `input.context` (context_modules) AND that NO emitted file
        defines → a definite dropped-required-file; the hidden harness compiles
        every `rtl/*.sv` it implies and ELAB-fails 'Unknown module type'. Safe to
        BLOCK (the scorer would fail it anyway; re-emitting the file PASSes).
      - warn: instantiated-but-undefined modules NOT in the required set — these
        MAY be harness/context-supplied modules (legitimately instantiated), so
        they are advisory only (§4.05: never false-BLOCK a context-module use).
    ROUND-2 §4.05 no-leak: a module the prompt's `input.context` ALREADY PROVIDES
    (e.g. a `gf_multiplier` context module the author correctly instantiates from
    a top `gf_mac`) must be EXCLUDED from `block` — it is the harness's file, not
    a dropped author file. Only an author-responsible module that is required,
    undefined, AND not context-provided blocks. chip-AGNOSTIC: instantiation +
    prompt-required + context-provided + defined-module parse."""
    code, kind = extract_code(completion or "")
    if kind == "doc_only" or not code:
        return [], []
    defined = completion_module_names(completion)
    instantiated = instantiated_module_names(code)
    undefined = instantiated - defined
    required = required_module_names_from_prompt(prompt_text or "")
    context = set(context_modules or ())
    # a context-provided module is the harness's responsibility, never a dropped
    # author file → exclude from BOTH the block set and the required set.
    block = sorted((undefined & required) - context)
    warn = sorted(undefined - required - context)
    return block, warn


# ORGANIC #642 — a CVDP draft id follows the harness's universal naming
# scheme `cvdp_copilot_<problem>` plus an optional trailing `_NNNN` variant
# suffix. The id stem `cvdp_copilot_<problem>` is the harness TOPLEVEL for the
# MINORITY of problems whose prompt also pins `rtl/cvdp_copilot_<problem>.sv`
# (field-measured 9/302); for the other 293/302 the harness TOPLEVEL is the
# prompt's stated functional `Module Name:`, NOT the id stem.
#
# v1.0.27 (round-1) wrongly treated the id stem as a HARD harness-top
# requirement BY DEFAULT (without --prompts), which BLOCKED 97% of correct
# completions — directly contradicting the official scorer (counter-example
# `cvdp_copilot_16qam_mapper_0001`, top `qam16_mapper_interpolated`, scorer
# PASS but gate BLOCK). Field-agent reopen: the id-derived stem must be
# ADVISORY-only (it cannot prove the harness top without prompt evidence), and
# only a PROMPT-derived name (filename or `Module Name:`) may hard-block. The
# genuine 9/302 still hard-block correctly because their prompt carries
# `rtl/cvdp_copilot_<problem>.sv` → required_module_names_from_prompt extracts
# the stem from the prompt (prompt-derived, not id-derived). chip-AGNOSTIC:
# pure id-string structure (the harness's own naming convention) — no chip /
# vendor / SKU literal.
_V642_VARIANT_SUFFIX_RE = re.compile(r"^(cvdp_copilot_.+?)_\d{3,}$")


def required_top_from_id(rid):
    """ORGANIC #642 — the id-derived top-module name `cvdp_copilot_<stem>` for
    a CVDP draft id (the id minus a trailing `_NNNN` variant suffix), or None
    when the id does not follow the `cvdp_copilot_` convention. ADVISORY-only
    (round-2 field-agent reopen): the harness TOPLEVEL is the prompt's stated
    `Module Name:` for 293/302 problems, so a mismatch against this id-derived
    name is a WARN note, never a hard BLOCK — only a PROMPT-derived name
    (required_module_names_from_prompt) is authoritative enough to block."""
    rid = (rid or "").strip()
    if not rid.startswith("cvdp_copilot_"):
        return None
    m = _V642_VARIANT_SUFFIX_RE.match(rid)
    return m.group(1) if m else rid


def _load_prompts(path):
    """Return {id: prompt_text} from a prompts JSONL ({id, prompt|input|...})."""
    out = {}
    p = Path(path)
    if not p.is_file():
        return out
    for ln in p.read_text(errors="replace").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            continue
        rid = d.get("id")
        txt = (d.get("prompt") or d.get("input") or d.get("question")
               or d.get("text") or "")
        if rid is not None:
            out[str(rid)] = txt
    return out


def _load_context_modules(path):
    """ORGANIC #715 round-2 — {id: set(context-module-stems)} from a prompts /
    dataset JSONL whose records carry `input.context` (a CVDP record's
    harness-provided files). Tolerates `input.context` as a dict (path keys) or
    a list of path strings; also a top-level `context`. Empty when absent (no
    relaxation → the round-1 behaviour, so a dataset without context info still
    blocks a genuine dropped file). chip-AGNOSTIC: pure filename-stem parse."""
    out = {}
    p = Path(path)
    if not p.is_file():
        return out
    for ln in p.read_text(errors="replace").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            continue
        rid = d.get("id")
        if rid is None:
            continue
        ctx = None
        inp = d.get("input")
        if isinstance(inp, dict):
            ctx = inp.get("context")
        if ctx is None:
            ctx = d.get("context")
        stems = context_module_names(ctx) if ctx else set()
        if stems:
            out[str(rid)] = stems
    return out


def _load_context_rtl(path):
    """ORGANIC #740 (G5) — {id: [rtl_text, ...]} of the FULL RTL CONTENT the
    record's `input.context` provides (a CVDP `input.context` is a dict whose
    keys are `rtl/<name>.sv` paths and whose values are the file CONTENTS the
    harness compiles alongside the author's completion).

    The embedded iface-conformance ADVISORY stage feeds these as `context_rtl`
    to `iface_conformance_v2.check_conformance`, so a prompt-named port that the
    author legitimately omits because it lives on a harness-supplied / context /
    instantiated sub-module is SATISFIED — exactly the owning-module scoping the
    STANDALONE gate already gets via `--context`. Only `.sv/.svh/.v/.vh` values
    are returned (a docs/spec.md context entry declares no module). Empty when
    absent. chip-AGNOSTIC: pure path-suffix structural parse, no SKU literal."""
    out = {}
    p = Path(path)
    if not p.is_file():
        return out
    _RTL_EXTS = (".sv", ".svh", ".v", ".vh")
    for ln in p.read_text(errors="replace").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            continue
        rid = d.get("id")
        if rid is None:
            continue
        inp = d.get("input")
        ctx = inp.get("context") if isinstance(inp, dict) else None
        if ctx is None:
            ctx = d.get("context")
        if not isinstance(ctx, dict):
            continue
        texts = [v for k, v in ctx.items()
                 if isinstance(k, str) and isinstance(v, str)
                 and Path(k).name.endswith(_RTL_EXTS)]
        if texts:
            out[str(rid)] = texts
    return out


def _load_context_available(path):
    """ORGANIC #734 — the SET of ids whose record actually CARRIES an
    `input.context` key (a dict or list, even if empty), i.e. ids for which the
    gate KNOWS the harness-provided context files and can therefore safely tell
    a dropped author file apart from a legitimately-instantiated context module.

    This is distinct from `_load_context_modules` (which returns only ids with a
    NON-EMPTY RTL context): an id may carry `input.context = {}` (no context
    files) — context is then KNOWN-EMPTY, so a dropped required submodule is
    genuinely the author's and a hard-BLOCK is safe. The documented local_export
    prompts JSONL ({id, prompt, system, user}) carries NO `input.context` key at
    all, so NO id is context-available and the #715 protection must degrade to a
    WARN instead of silently false-blocking (§4.05). chip-AGNOSTIC: pure
    key-presence structural parse, no chip/vendor/SKU literal."""
    out = set()
    p = Path(path)
    if not p.is_file():
        return out
    for ln in p.read_text(errors="replace").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            continue
        rid = d.get("id")
        if rid is None:
            continue
        inp = d.get("input")
        ctx = inp.get("context") if isinstance(inp, dict) else None
        if ctx is None:
            ctx = d.get("context")
        # ORGANIC #734 — a PRESENT context value (dict/list, even EMPTY =
        # known-empty) makes the id context-available; an ABSENT key OR an
        # explicit `null` value means context is UNKNOWN → NOT available. This
        # mirrors `_load_context_modules`' own `if ctx else …` extraction EXACTLY
        # (same two-step inp.context / top-level context lookup, same None
        # rejection) so the two loaders can never disagree — in particular a
        # `context: null` record is NOT mis-read as known-empty and false-blocked.
        if ctx is not None:
            out.add(str(rid))
    return out


def _load_latency_specs(path):
    """ORGANIC #705 — return {id: spec} from a latency-spec JSONL.

    Each line: {"id": "<id>", "top": "<module>", "event": "<port>",
                "output": "<port>", "expect": "<expr>",
                "param": {"WIDTH": 8}}   (param optional)
    `top` is optional (defaults to the emitted RTL's first module). The
    canonical event→output latency literal is NOT derivable from a CVDP
    record's prose, so this file is how a curator hands the gate the literal
    to enforce — the gate cannot invent it."""
    out = {}
    p = Path(path)
    if not p.is_file():
        return out
    for ln in p.read_text(errors="replace").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            continue
        rid = d.get("id")
        if rid is not None and d.get("event") and d.get("output") \
                and d.get("expect"):
            out[str(rid)] = d
    return out


def latency_gate_record(rid, completion, spec, workdir):
    """ORGANIC #705 — PRE-EMIT latency-conformance check for one record.

    Extracts the emitted RTL, writes it to a temp .sv, and runs the
    DETERMINISTIC latency gate (its OWN canonical measurement TB) against the
    supplied spec. Returns (ok, note):
      * ok=True,  note=str  — conformance ok / SKIP (no iverilog) / spec n/a.
      * ok=False, note=str  — a measured!=spec MISMATCH or a TIMEOUT (BLOCK).
    A setup/parse error (rc 2) is NON-blocking advisory (the gate cannot
    prove the latency → it must not false-block a correct emit; §4.05
    asymmetry). The canonical event/output/expect literal is the curator's
    judgment input; the MEASUREMENT + comparison is this deterministic gate."""
    if _latconf is None:  # pragma: no cover - program absent
        return True, "latency gate unavailable (program missing) — skipped"
    code, _kind = extract_code(completion or "")
    if not (code or "").strip():
        return True, "no RTL to measure — skipped"
    rtl_path = workdir / "lat_dut.sv"
    rtl_path.write_text(code)
    overrides = {}
    for k, v in (spec.get("param") or {}).items():
        try:
            overrides[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    try:
        rc, report = _latconf.run_latency_conformance(
            rtl_path=rtl_path, top=spec.get("top"),
            event=spec["event"], output=spec["output"],
            expect=spec["expect"], params_override=overrides,
            reset_override=spec.get("reset"),
            reset_active_low_flag=spec.get("reset_active_low"),
            input_const=int(spec.get("input_const", -1)),
            max_cycles_override=spec.get("max_cycles"))
    except Exception as e:  # pragma: no cover - defensive
        return True, f"latency gate raised (advisory): {e}"
    verdict = report.get("verdict")
    if verdict in ("MISMATCH", "TIMEOUT"):
        return False, f"latency {verdict}: {report.get('reason')}"
    if verdict in ("ERROR", "PRECONDITION_HIGH"):
        # the gate could not trustworthily MEASURE (bad port / unresolved
        # expect / output already HIGH before the event): ADVISORY, never a
        # false-BLOCK of a possibly-correct emit (§4.05 asymmetry — a wrong
        # event/output/expect in the curator's spec must not discard a good
        # answer; the scorer remains the arbiter).
        return True, f"latency check inconclusive (advisory): {report.get('reason')}"
    # PASS or SKIP (no iverilog) — emit.
    return True, f"latency {verdict}: {report.get('reason')}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="CVDP copilot SOLE-EMIT gate (#528): drafts JSONL in, "
                    "gated responses JSONL out.")
    ap.add_argument("--batch", default=None,
                    help="author drafts JSONL ({id, completion} per line)")
    ap.add_argument("--batch-dir", default=None,
                    help="ORGANIC #535 — directory of raw draft files "
                         "(<id>.md/.sv/.txt, content = the completion "
                         "bytes); the gate does its OWN json assembly so "
                         "hand-built JSON escaping can never corrupt the "
                         "payload")
    ap.add_argument("--out", required=True,
                    help="gated responses JSONL (written ONLY by this gate)")
    ap.add_argument("--report", default=None,
                    help="optional JSON gate report path")
    ap.add_argument("--prompts", default=None,
                    help="ORGANIC #559 — optional prompts JSONL ({id, "
                         "prompt}); when given, a completion whose modules "
                         "do not include the filename the prompt asks the "
                         "author to save (rtl/<name>.sv) is BLOCKED — the "
                         "CVDP harness derives TOPLEVEL from the file layout "
                         "so a module-name/filename mismatch ELAB_ERRORs")
    ap.add_argument("--prompts-advisory", action="store_true",
                    help="with --prompts, WARN instead of BLOCK on a "
                         "filename/module-name mismatch (strict-advisory)")
    ap.add_argument("--dataset", default=None,
                    help="ORGANIC #734 — optional source JSONL carrying each "
                         "record's `input.context` (the original CVDP dataset). "
                         "The documented local_export prompts JSONL omits "
                         "input.context, so the #715 context-module protection "
                         "is silently inactive there and correct completions "
                         "that instantiate a harness-supplied context module "
                         "are false-BLOCKED. Point --dataset at a JSONL with "
                         "input.context to RE-ENABLE that protection (it is "
                         "unioned with any context found in --prompts). When "
                         "context is unavailable for an id from BOTH sources, "
                         "the multi-file hard-BLOCK is downgraded to an advisory "
                         "WARN rather than silently false-blocking (§4.05).")
    ap.add_argument("--latency-specs", default=None,
                    help="ORGANIC #705 — optional latency-spec JSONL ({id, "
                         "event, output, expect[, top, param, reset]}); for "
                         "each id present, the gate MEASURES the emitted RTL's "
                         "real event→output latency (its OWN canonical TB) and "
                         "BLOCKS a measured!=spec MISMATCH / TIMEOUT before the "
                         "record is emitted. The canonical latency literal is "
                         "NOT derivable from a CVDP record's prose, so the gate "
                         "only enforces ids the curator supplies here.")
    args = ap.parse_args(argv)
    if not args.batch and not args.batch_dir:
        print("ERROR: one of --batch / --batch-dir is required",
              file=sys.stderr)
        return 2

    if shutil.which("iverilog") is None:
        print("ERROR: iverilog not available — the gate cannot enforce; "
              "refusing to emit ungated responses (#528)", file=sys.stderr)
        return 2
    # #604: the synthesizability smoke (#531) is a HARD part of the gate. A
    # host without yosys silently degraded that smoke to a no-op while the
    # report still read PASS (yosys-absent rc=127 was misread as a tolerated
    # frontend-gap). Mirror the iverilog guard: refuse rather than emit
    # responses gated on iverilog parse/elab ALONE.
    if shutil.which("yosys") is None:
        print("ERROR: yosys not available — the synthesizability smoke (#531) "
              "cannot be enforced; refusing to emit responses gated on iverilog "
              "alone (a yosys-absent host degraded the synth gate to a silent "
              "no-op PASS, #604)", file=sys.stderr)
        return 2
    # version-parity disclosure (adversarial-review MED): the official
    # cvdp-sim scorer runs icarus 13; a different host major version means
    # the accepted-syntax / `sorry:` sets may diverge — disclose, don't hide.
    _vrc, _vout, _verr = _run(["iverilog", "-V"])
    iverilog_version = ((_vout or _verr or "").splitlines() or ["unknown"])[0]
    _vm = re.search(r"version\s+(\d+)", iverilog_version, re.I)
    if _vm and _vm.group(1) != "13":
        print(f"WARN: host {iverilog_version!r} differs from the official "
              f"cvdp-sim icarus 13 — accepted-syntax sets may diverge "
              f"(disclosed in the gate report)", file=sys.stderr)
    # #604: disclose the yosys the synth smoke ran against (symmetric with the
    # iverilog disclosure; proves the synth gate was actually enforced).
    _yrc, _yout, _yerr = _run(["yosys", "-V"])
    yosys_version = ((_yout or _yerr or "").splitlines() or ["unknown"])[0]
    records: List[Dict] = []
    if args.batch_dir:
        bdir = Path(args.batch_dir)
        if not bdir.is_dir():
            print(f"ERROR: batch dir not found: {bdir}", file=sys.stderr)
            return 2
        for f in sorted(bdir.iterdir()):
            if f.is_file() and f.suffix in (".md", ".sv", ".v", ".txt"):
                records.append({"id": f.stem,
                                "completion": f.read_text(errors="replace")})
        if not records:
            print(f"ERROR: no draft files in {bdir}", file=sys.stderr)
            return 2
    else:
        batch = Path(args.batch)
        if not batch.is_file():
            print(f"ERROR: batch not found: {batch}", file=sys.stderr)
            return 2
        for ln in batch.read_text(errors="replace").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                records.append(json.loads(ln))
            except json.JSONDecodeError as e:
                print(f"ERROR: bad JSONL line: {e}", file=sys.stderr)
                return 2
    # ORGANIC #535 round-2 (adversarial review) — ids must be PRESENT and
    # UNIQUE: local_import keys responses by id (a duplicate silently
    # overwrites its twin downstream) and the round-trip purge needs an
    # unambiguous identity. Refuse ambiguous batches outright.
    ids = [r.get("id") for r in records]
    missing = [i for i, v in enumerate(ids) if not v]
    if missing:
        print(f"ERROR: record(s) at line(s) {missing} carry no id — "
              f"refusing (responses are id-keyed downstream)",
              file=sys.stderr)
        return 2
    dupes = sorted({v for v in ids if ids.count(v) > 1})
    if dupes:
        print(f"ERROR: duplicate id(s) {dupes} — refusing an ambiguous "
              f"batch (local_import would overwrite one twin; for "
              f"--batch-dir, two files share a stem)", file=sys.stderr)
        return 2
    # ORGANIC #535 — CRLF normalization at intake: editor/transport CRLF in a
    # completion corrupts the harness-side file write; normalize before any
    # gating so the gated bytes == the delivered bytes.
    for rec in records:
        c = rec.get("completion")
        if isinstance(c, str) and "\r" in c:
            rec["completion"] = c.replace("\r\n", "\n").replace("\r", "\n")
    # ORGANIC #559 — optional prompt-aware filename↔module-name conformance.
    prompts = _load_prompts(args.prompts) if args.prompts else {}
    # ORGANIC #715 round-2 + #734 — per-id context-module stems from the prompts
    # AND/OR the --dataset `input.context` so multi-file completeness never
    # false-BLOCKs a harness-provided context module the author correctly
    # instantiates. The documented local_export prompts JSONL omits
    # input.context, so --dataset is how the operator re-supplies it; the two
    # sources are UNIONED (dataset is the authoritative superset). We ALSO track
    # which ids actually carry an input.context key (context_available) — for an
    # id with NO context source the gate cannot tell a dropped author file from a
    # context module, so the multi-file hard-BLOCK degrades to an advisory WARN
    # (§4.05: never silently false-block) rather than firing blind.
    context_modules = {}
    context_available = set()
    # ORGANIC #740 (G5) — full context RTL CONTENT per id (not just module-name
    # stems), so the embedded iface-conformance ADVISORY stage scopes a
    # prompt-named port to its OWNING context/instantiated sub-module exactly the
    # way the STANDALONE gate does with `--context`.
    context_rtl = {}
    for _ctx_src in (args.prompts, args.dataset):
        if not _ctx_src:
            continue
        for _rid, _stems in _load_context_modules(_ctx_src).items():
            context_modules.setdefault(_rid, set()).update(_stems)
        for _rid, _texts in _load_context_rtl(_ctx_src).items():
            context_rtl.setdefault(_rid, []).extend(_texts)
        context_available |= _load_context_available(_ctx_src)
    # ORGANIC #734 — if the operator passed --dataset specifically to re-enable
    # the #715 protection but it yields NO input.context for any id (a wrong file
    # / typo'd path / non-CVDP JSONL), the protection silently stays inactive.
    # Surface that misconfiguration LOUDLY on stderr so it is not mistaken for
    # "protection active" — the failure direction is always relax, never block.
    if args.dataset and not _load_context_available(args.dataset):
        print("WARN (#734): --dataset carried NO input.context for any id "
              "(wrong file / path / non-CVDP JSONL?) — the #715 context "
              "protection stays INACTIVE and multi-file hard-blocks degrade to "
              "advisory WARNs.", file=sys.stderr)
    # PR #29 remediation — AUTHORITATIVE per-id synth-scored map from --prompts
    # AND/OR --dataset (the documented {id, completion} draft carries no category
    # metadata, so without this the yosys-smoke timeout fail-safe has no live
    # category signal). {id: True=area-opt/cid007, False=known-non-cid007}; an id
    # absent from BOTH sources resolves to None = fail-safe BLOCK of a synth-timeout.
    synth_scored_map: Dict[str, bool] = {}
    for _ss_src in (args.prompts, args.dataset):
        if _ss_src:
            for _rid, _ss in _load_synth_scored_map(_ss_src).items():
                # a positive synth-scored (True) from EITHER source wins
                synth_scored_map[_rid] = synth_scored_map.get(_rid, False) or _ss
    if (args.prompts or args.dataset) and not synth_scored_map:
        print("WARN (PR#29): --prompts/--dataset carried NO category metadata for "
              "any id — the yosys-smoke synth-timeout fail-safe will BLOCK every "
              "timeout (cannot confirm a problem is non-synth-scored).",
              file=sys.stderr)
    # ORGANIC #705 — optional per-id latency specs the gate ENFORCES (measured
    # vs spec literal) as a pre-emit BLOCK.
    latency_specs = (_load_latency_specs(args.latency_specs)
                     if args.latency_specs else {})
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    passed: List[Dict] = []
    report: List[Dict] = []
    blocked = 0
    with tempfile.TemporaryDirectory(prefix="cvdp_gate_") as td:
        wd = Path(td)
        for rec in records:
            # ORGANIC #680 — pass this id's prompt so gate_record can mirror
            # determine_schema's single-vs-multi signal when normalizing a
            # JSON code-dict emit (single-file → bare RTL, multi-file → JSON).
            ok, out_rec, entry = gate_record(
                rec, wd, prompt_text=prompts.get(str(rec.get("id"))),
                synth_scored=synth_scored_map.get(str(rec.get("id"))))
            # ORGANIC #559 — filename/module-name conformance (only when a
            # prompt for this id states a required rtl/<name>.sv). The
            # harness builds TOPLEVEL from the file layout, so a completion
            # that declares no module matching the requested filename
            # ELAB_ERRORs. Advisory mode WARNs instead of blocking.
            if ok:
                # #559 / #642 round-2 — module-name conformance. TWO tiers:
                #   • PROMPT-derived (filename rtl/<name>.sv OR `Module Name:`
                #     declaration) — AUTHORITATIVE: the harness derives its
                #     cocotb TOPLEVEL from exactly this, so a mismatch
                #     ELAB_ERRORs at scoring → hard BLOCK (unless
                #     --prompts-advisory). This is the form 293/302 nonagentic
                #     problems use, and it also catches the genuine 9/302
                #     `rtl/cvdp_copilot_<id>.sv` cases (their stem is
                #     prompt-stated, so it lands here, not in the id fallback).
                #   • id-DERIVED (`cvdp_copilot_<stem>`, used only when no
                #     prompt-derived name is available) — ADVISORY-only: the
                #     id stem is NOT the harness top for 293/302, so v1.0.27's
                #     hard-BLOCK-by-default false-blocked 97% of correct
                #     completions (round-2 field-agent reopen). Without prompt
                #     evidence the gate cannot prove the harness top, so it
                #     only WARNs — never blocks — on an id-stem mismatch.
                req = (required_module_names_from_prompt(
                    prompts.get(str(rec.get("id")), "")) if prompts else set())
                if not req:
                    _derived_top = required_top_from_id(str(rec.get("id")))
                    if _derived_top:
                        req = {_derived_top}
                if req:
                    mods = completion_module_names(out_rec.get("completion"))
                    if mods and not (req & mods):
                        # ORGANIC #642 round-2 — name-conformance is ADVISORY
                        # (WARN) ONLY, NEVER a hard-BLOCK. The CVDP harness's
                        # cocotb TOPLEVEL is fixed by the HIDDEN test harness
                        # from the module DECLARATION name — which is NOT
                        # reliably the prompt's save-filename stem (`rtl/<X>.sv`)
                        # NOR any prose hint NOR the id stem. Field round-2
                        # measured 7/302 correct answers whose filename-stem !=
                        # module-name == harness TOPLEVEL == scorer PASS, yet
                        # were hard-blocked and dropped from the scoring set.
                        # §4.05 asymmetry: a false-BLOCK discards a PASSING
                        # answer irreversibly, whereas a genuine module mismatch
                        # is emitted-and-WARNed and the SCORER ELAB_ERRORs it
                        # anyway (identical final outcome). So surface the
                        # potential mismatch as advisory and ALWAYS emit — the
                        # scorer remains the sole arbiter of TOPLEVEL. (The
                        # `--prompts-advisory` flag is retained for compat but
                        # is now a no-op: conformance is always advisory.)
                        msg = (f"a prompt name hint suggests the harness top may "
                               f"be {sorted(req)}; completion declares "
                               f"{sorted(mods)} — if these disagree with the "
                               f"hidden harness TOPLEVEL the scorer ELAB_ERRORs "
                               f"it (advisory; the gate cannot prove the harness "
                               f"TOPLEVEL — #642 round-2)")
                        entry.setdefault("notes", []).append(
                            "WARN module-name-conformance: " + msg)
                # ORGANIC #715 — multi-file completeness. A completion that
                # INSTANTIATES a submodule whose file was dropped passes the
                # single-file emit gate (the missing module is tolerated as
                # 'context') but ELAB-fails at scoring (Unknown module type).
                # Hard-BLOCK ONLY when the dropped module is one the PROMPT
                # requires the author to deliver (definite incomplete; the
                # scorer would fail it anyway and re-emitting the file PASSes);
                # an instantiated-but-undefined module NOT in the required set
                # MAY be a harness-supplied context module → advisory WARN only
                # (§4.05: never false-BLOCK a legitimate context-module use).
                _rid_s = str(rec.get("id"))
                _mf_block, _mf_warn = multifile_incompleteness(
                    out_rec.get("completion", ""),
                    prompts.get(_rid_s, "") if prompts else "",
                    context_modules=context_modules.get(_rid_s))
                if _mf_block and _rid_s not in context_available:
                    # ORGANIC #734 — context is UNAVAILABLE for this id (no
                    # input.context fed via --prompts or --dataset, e.g. the
                    # documented local_export prompts JSONL). The gate cannot
                    # tell a dropped author file apart from a legitimately-
                    # instantiated harness context module, so the #715 hard-BLOCK
                    # would silently false-block a correct context-module
                    # completion (proven: gf_multiplier / elevator_control /
                    # scrambler). §4.05: a false-BLOCK discards a PASSING answer
                    # irreversibly, whereas a genuine dropped file is emitted-and-
                    # WARNed and the scorer ELAB-fails it anyway (same final
                    # outcome). So DOWNGRADE to an advisory WARN naming how to
                    # re-enable the hard block, rather than firing blind.
                    entry.setdefault("notes", []).append(
                        f"WARN multi-file (#715/#734): instantiates undefined "
                        f"module(s) {_mf_block} the prompt names, but input.context "
                        f"is UNAVAILABLE for this id — #715 context protection is "
                        f"INACTIVE, so the gate cannot prove these are dropped "
                        f"author files vs harness-supplied context modules and "
                        f"does NOT hard-block (§4.05). Pass --dataset with this "
                        f"record's input.context to re-enable the hard block.")
                    _mf_block = []
                if _mf_block:
                    ok = False
                    entry["verdict"] = "BLOCKED"
                    entry.setdefault("notes", []).append(
                        f"multi-file INCOMPLETE (#715): instantiates "
                        f"prompt-required module(s) {_mf_block} but no emitted "
                        f"file defines them — the hidden harness ELAB-fails "
                        f"'Unknown module type'. Emit every required submodule "
                        f"as a JSON code-dict file.")
                if _mf_warn:
                    entry.setdefault("notes", []).append(
                        f"WARN multi-file (#715): instantiates undefined "
                        f"module(s) {_mf_warn} not in the prompt-required set "
                        f"— if these are NOT harness-supplied context modules, "
                        f"the scorer will ELAB-fail (advisory; cannot prove "
                        f"context vs author-submodule without the prompt).")
                # ORGANIC #695 — prompt→interface conformance ADVISORY stage:
                # module-name CASE + missing-port + port-direction, all derived
                # from the PROMPT + the emitted RTL only (BLIND — never reads
                # the oracle / hidden TB). WARN-only here; it NEVER hard-blocks
                # (heuristic prompt extraction would otherwise false-block a
                # correct emit on an internal-signal mention — §4.05 asymmetry).
                # The standalone program's --strict mode is the blocking front
                # door; inside the SOLE-EMIT gate it stays advisory.
                if _ifacev2 is not None:
                    _ptext = prompts.get(str(rec.get("id")), "")
                    _comp = out_rec.get("completion", "") or ""
                    if _ptext and _comp.strip():
                        # ORGANIC #740 (G5) — feed the EXTRACTED RTL (all author
                        # modules parse cleanly even from a JSON code-dict emit,
                        # not the raw completion blob) AND the record's full
                        # context RTL, so a prompt-named port whose OWNING module
                        # is a harness-supplied / instantiated sub-module is
                        # SATISFIED — the same owning-module scoping the
                        # standalone gate gets via `--context`. Fall back to the
                        # raw completion if extraction yields no compilable code
                        # (doc-only emits), so behaviour is never WORSE than
                        # before. Advisory-only — never a hard-block.
                        try:
                            _xcode, _ = extract_code(_comp)
                        except Exception:
                            _xcode = None
                        _rtl_for_iface = _xcode or _comp
                        _ctx_rtl = context_rtl.get(str(rec.get("id"))) or None
                        try:
                            _findings = _ifacev2.check_conformance(
                                str(rec.get("id")), _ptext, _rtl_for_iface,
                                _ctx_rtl)
                        except Exception:
                            _findings = []
                        for _f in _findings:
                            entry.setdefault("notes", []).append(
                                "WARN iface-conformance (#695): " + _f.message)
                # ORGANIC #705 — DETERMINISTIC latency-conformance PRE-EMIT
                # gate. UNLIKE the advisory #642/#695 stages above, this one
                # CAN hard-BLOCK: a measured!=spec latency MISMATCH (or a
                # TIMEOUT) is a definite off-by-one the scorer's hidden TB
                # would also fail, so emitting it wastes a scoring slot. It
                # ONLY fires for an id whose canonical event/output/expect
                # literal was supplied via --latency-specs (the gate cannot
                # infer the latency literal from a CVDP record's prose); a
                # setup/parse error stays advisory inside latency_gate_record
                # (never a false-BLOCK — §4.05 asymmetry).
                _lspec = latency_specs.get(str(rec.get("id")))
                if _lspec is not None:
                    _lwd = wd / f"lat_{rec.get('id')}"
                    _lwd.mkdir(parents=True, exist_ok=True)
                    _lok, _lnote = latency_gate_record(
                        str(rec.get("id")), out_rec.get("completion", ""),
                        _lspec, _lwd)
                    entry["latency"] = _lnote
                    if not _lok:
                        ok = False
                        entry["verdict"] = "BLOCKED"
            report.append(entry)
            if ok:
                passed.append(out_rec)
            else:
                blocked += 1
                # ORGANIC #539 — name the stage that actually blocked:
                # gate_record returns on the FIRST failing stage, so the
                # last stage field written carries the real reason (a
                # synth-stage block used to print "compile clean" here).
                # #705 — a latency BLOCK names the latency reason.
                why = (entry.get("latency") if entry.get("verdict") == "BLOCKED"
                       and "latency" in entry and entry.get("latency", "")
                       .startswith("latency ") else None)
                why = why or (entry.get("filename_conformance")
                              or entry.get("synth") or entry.get("compile"))
                print(f"BLOCKED {entry['id']}: {why}", file=sys.stderr)
    out_path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in passed))
    # ── ORGANIC #535 — TRANSMISSION-integrity round-trip ────────────────
    # The scoring harness consumes the DELIVERED JSONL, not the author's
    # draft: re-read the bytes just written, re-parse each line, re-extract
    # the code, and verify it is byte-identical to what the gate passed
    # (plus a fast re-parse). Escaping/CRLF corruption lands as an EMPTY or
    # truncated extraction — caught HERE, not as a downstream KeyError
    # (yosys exits 0 on a zero-module file, so the corruption is silent).
    rt_failed_idx: set = set()
    rt_lines = out_path.read_text(errors="replace").splitlines()
    rt_records = []
    for ln in rt_lines:
        try:
            rt_records.append(json.loads(ln))
        except json.JSONDecodeError:
            rt_records.append(None)
    with tempfile.TemporaryDirectory(prefix="cvdp_gate_rt_") as td:
        rwd = Path(td)
        for i, (orig, rt) in enumerate(zip(passed, rt_records)):
            rid = orig.get("id", f"line{i}")
            reason = None
            if rt is None:
                reason = "roundtrip-unparseable"
            elif rt.get("completion") != orig.get("completion"):
                reason = "roundtrip-mismatch"
            else:
                code, kind = extract_code(rt.get("completion") or "")
                ocode, okind = extract_code(orig.get("completion") or "")
                if kind != okind or (code or "") != (ocode or ""):
                    reason = "roundtrip-extraction-drift"
                elif kind != "doc_only":
                    if not (code or "").strip():
                        reason = "empty-after-roundtrip"
                    else:
                        rok, _why, _st = iverilog_gate(code, rwd)
                        if not rok:
                            reason = "roundtrip-reparse-failed"
            if reason:
                # purge by POSITION (adversarial review round-2: an id-keyed
                # purge collateral-dropped a good same-id twin).
                rt_failed_idx.add(i)
                blocked += 1
                for e in report:
                    if e.get("id") == rid:
                        e["verdict"] = "BLOCKED"
                        e["roundtrip"] = reason
                print(f"BLOCKED {rid}: {reason} (#535 transmission "
                      f"integrity)", file=sys.stderr)
    if rt_failed_idx:
        passed = [r for i, r in enumerate(passed) if i not in rt_failed_idx]
        out_path.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n"
                    for r in passed))
    if args.report:
        Path(args.report).write_text(
            json.dumps({"total": len(records), "passed": len(passed),
                        "blocked": blocked,
                        "iverilog_version": iverilog_version,
                        "yosys_version": yosys_version,
                        "official_scorer": "icarus 13 (cvdp-sim)",
                        "records": report},
                       indent=2, ensure_ascii=False) + "\n")
    print(f"cvdp_gate: {len(passed)}/{len(records)} gated in"
          f" ({blocked} blocked)")
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
