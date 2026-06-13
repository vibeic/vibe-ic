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
    return files or None


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


def yosys_smoke(code: str, workdir: Path,
                stubs_text: str = "") -> Tuple[bool, str]:
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
    for top in own_modules:
        # NOTE: no -q — quiet mode suppresses the stat table itself.
        rc, out, err = _run(
            ["yosys", "-p",
             f"read_verilog -sv {f}; synth -top {top}; stat"], timeout=300)
        blob = (out or "") + "\n" + (err or "")
        if rc != 0:
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
    return True, "yosys-smoke ok (" + "; ".join(details) + ")"


def gate_record(rec: Dict, workdir: Path) -> Tuple[bool, Dict, Dict]:
    """Gate one {id, completion} record → (ok, out_record, report_entry).

    Hygiene runs PER CODE FENCE and the write-back substitutes each fence
    with ITS OWN fixed body (adversarial-review HIGH: a single concatenated
    blob substituted into every fence duplicated all modules into each
    fence and turned a clean 2-fence completion into a guaranteed
    duplicate-declaration scorer FAIL)."""
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
        ok2, why2 = yosys_smoke(combined, workdir, stubs)
        entry["synth"] = why2
        if not ok2:
            entry["verdict"] = "BLOCKED"
            return False, rec, entry
        entry["verdict"] = "PASS"
        out_rec = dict(rec)
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
        return True, out_rec, entry
    if kind == "bare":
        fixed, notes = hygiene_fix(code, workdir)
        entry["notes"].extend(notes)
        ok, why, stubs = iverilog_gate(fixed, workdir)
        entry["compile"] = why
        if not ok:
            entry["verdict"] = "BLOCKED"
            return False, rec, entry
        ok2, why2 = yosys_smoke(fixed, workdir, stubs)
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
    ok2, why2 = yosys_smoke(combined, workdir, stubs)
    entry["synth"] = why2
    if not ok2:
        entry["verdict"] = "BLOCKED"
        return False, rec, entry
    entry["verdict"] = "PASS"
    out_rec = dict(rec)
    if fixed_bodies != [m.group(2) for m in fences]:
        # splice each fence's OWN fixed body back, end-to-start so spans
        # stay valid.
        new_completion = completion
        for m, fb in sorted(zip(fences, fixed_bodies),
                            key=lambda x: -x[0].start(2)):
            new_completion = (new_completion[:m.start(2)] + fb
                              + new_completion[m.end(2):])
        out_rec["completion"] = new_completion
    return True, out_rec, entry


_REQ_FILENAME_RE = re.compile(
    r"(?:rtl|src|hdl|verilog)/([A-Za-z_]\w*)\.s?v\b"
    r"|(?:file|named|save\s+(?:it\s+)?(?:to|as)|create)\b[^\n]{0,40}?"
    r"\b([A-Za-z_]\w*)\.s?v\b",
    re.IGNORECASE)


def required_module_names_from_prompt(prompt_text):
    """ORGANIC #559 — extract the set of filename STEMS the prompt asks the
    author to save (rtl/<name>.sv, 'save it to foo.sv', 'a file named
    bar.v'). The CVDP harness derives TOPLEVEL from the file layout, so the
    completion must declare a module of the same name. Pure structural
    parse — chip-AGNOSTIC. Returns a set of stems (possibly empty)."""
    stems = set()
    for m in _REQ_FILENAME_RE.finditer(prompt_text or ""):
        nm = m.group(1) or m.group(2)
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
    args = ap.parse_args(argv)
    if not args.batch and not args.batch_dir:
        print("ERROR: one of --batch / --batch-dir is required",
              file=sys.stderr)
        return 2

    if shutil.which("iverilog") is None:
        print("ERROR: iverilog not available — the gate cannot enforce; "
              "refusing to emit ungated responses (#528)", file=sys.stderr)
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
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    passed: List[Dict] = []
    report: List[Dict] = []
    blocked = 0
    with tempfile.TemporaryDirectory(prefix="cvdp_gate_") as td:
        wd = Path(td)
        for rec in records:
            ok, out_rec, entry = gate_record(rec, wd)
            # ORGANIC #559 — filename/module-name conformance (only when a
            # prompt for this id states a required rtl/<name>.sv). The
            # harness builds TOPLEVEL from the file layout, so a completion
            # that declares no module matching the requested filename
            # ELAB_ERRORs. Advisory mode WARNs instead of blocking.
            if ok and prompts:
                req = required_module_names_from_prompt(
                    prompts.get(str(rec.get("id")), ""))
                if req:
                    mods = completion_module_names(out_rec.get("completion"))
                    if mods and not (req & mods):
                        msg = (f"prompt requires a module named {sorted(req)} "
                               f"(per the requested rtl/<name>.sv); completion "
                               f"declares {sorted(mods)} — the harness derives "
                               f"TOPLEVEL from the filename so this ELAB_ERRORs")
                        if args.prompts_advisory:
                            entry.setdefault("notes", []).append(
                                "WARN filename-module-mismatch: " + msg)
                        else:
                            entry["verdict"] = "BLOCKED"
                            entry["filename_conformance"] = msg
                            ok = False
            report.append(entry)
            if ok:
                passed.append(out_rec)
            else:
                blocked += 1
                # ORGANIC #539 — name the stage that actually blocked:
                # gate_record returns on the FIRST failing stage, so the
                # last stage field written carries the real reason (a
                # synth-stage block used to print "compile clean" here).
                why = (entry.get("filename_conformance")
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
                        "official_scorer": "icarus 13 (cvdp-sim)",
                        "records": report},
                       indent=2, ensure_ascii=False) + "\n")
    print(f"cvdp_gate: {len(passed)}/{len(records)} gated in"
          f" ({blocked} blocked)")
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
