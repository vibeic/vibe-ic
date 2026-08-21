#!/usr/bin/env python3
"""vacuous_testbench_check.py — Phase-2 gate against VACUOUS testbenches.

A vacuous testbench prints a PASS and never drives the design. Functional
verification then silently becomes theatre: the sim log says PASS, the DUT was
never instantiated, and every downstream gate inherits a fabricated green.

WHERE THEY CAME FROM, AND WHY THIS GATE STILL LOOKS FOR THEM. The scaffolder
(`testbench_gen.emit_unit_tb`) used to EMIT this shape as a SKELETON meant to be
replaced with real stimulus; when it was not replaced — which was every time —
the campaign shipped it as verification. The scaffolder no longer emits it: it
now instantiates the DUT and asserts a falsifiable post-reset property, or emits
nothing and says why. That fix is upstream of this gate and does NOT retire it.
The corpus still holds the files the old scaffolder wrote (they are the record of
runs that already happened and are not to be rewritten), a testbench can still be
hand-written into this shape, and a detector whose only justification was one
known producer is a detector that stops working the moment there is a second.
The patterns below therefore stay exactly as broad as they were.

WHY A FILENAME GLOB CANNOT FIND THIS. The pre-existing detectors glob
`*_tb.v` / `tb_*.v` (see testbench_exists_check.TB_PATTERNS). The scaffolder
names one TB per L10 scenario, after the SCENARIO — `case_3.v`,
`corner_operand.v`, `rv32i_40.v`, `tc1_reset.v`. Not one such file matches
either glob, so a filename-driven audit reports 0 hits against a corpus of real
defects. **The DIRECTORY decides what a testbench is, not the filename.** This
gate therefore discovers TBs structurally: any `.v`/`.sv` under the sim tree
that declares a PORTLESS module (`module foo;`) is a testbench — a synthesizable
RTL module always carries a port list, a testbench never does. Filename plays no
role at all.

THREE INDEPENDENT DETECTORS. A marker string is trivially renamed, so the
marker is the weakest of the three and never the only line of defence:

  D1 `placeholder_marker` (per file) — the literal the scaffolder actually
     emits (`PASS_PLACEHOLDER`, verbatim from testbench_gen.emit_unit_tb), plus
     the same line's "replace with real stimulus" instruction. Cheap and exact;
     defeated by a rename, which is what D2/D3 exist for.

  D2 `commented_dut_instantiation` (per file) — STRUCTURAL. The scaffolder
     leaves the DUT hookup commented out (`// <top> u_dut (.clk(clk), ...);`).
     Detected by parsing COMMENT text for a module-instantiation shape, with
     comment/string-aware lexing so a `//` inside a string literal is not
     mistaken for a comment. Fires only when that same module type has NO live
     instantiation in the same file — so a TB that really drives the DUT and
     merely keeps a commented-out debug alternative is NOT flagged.

  D3 `no_live_instantiation` (per sim TREE) — the ACTUAL defect; D1/D2 are
     symptoms. The sim tree must contain at least ONE testbench that really
     instantiates something. Scoped to the TREE, not the file, because a
     legitimately-clean tree may hold a portless documentation/trace TB that
     instantiates nothing BY DESIGN (it exists to emit L10 trace markers for
     l10_tb_conformance_check) alongside the real driving TB one level up in
     `sim/`. Flagging that companion file alone would be a false positive; a
     tree in which NOTHING drives the design is unambiguously vacuous.

EVIDENCE (dual-track doctrine). Every verdict carries the raw evidence it
judged on — offending file path, matched line, and line number — so an
independent track can re-judge the same inputs instead of trusting this gate's
say-so.

chip-AGNOSTIC: no chip / vendor / SKU / design-name literal anywhere; the gate
keys purely on Verilog structure.
Contract: exit 0 = PASS / NOT_APPLICABLE, exit 1 = vacuous TB found,
exit 2 = IO error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# The marker the scaffolder actually emits. Read from testbench_gen.emit_unit_tb:
#     #1000 $display("[TB {name}] PASS_PLACEHOLDER (replace with real stimulus)");
# Both halves are matched independently so renaming one still trips the other.
PLACEHOLDER_PATTERNS = (
    re.compile(r"PASS_PLACEHOLDER"),
    re.compile(r"replace\s+with\s+real\s+stimulus", re.IGNORECASE),
)

# Verilog/SystemVerilog keywords that may begin a statement and would otherwise
# look like `<type> <name> (` . Excluding these is what keeps the instantiation
# matcher free of false positives on ordinary RTL/TB constructs.
_KEYWORDS = frozenset("""
module endmodule primitive endprimitive macromodule
always always_ff always_comb always_latch initial final
begin end fork join join_any join_none
if else for while repeat forever do case casex casez endcase default
task endtask function endfunction return void
assign deassign force release alias
reg wire logic bit byte int longint shortint integer real realtime shortreal
time genvar event struct union enum typedef string chandle
input output inout ref
parameter localparam defparam specparam
generate endgenerate
posedge negedge edge wait disable
specify endspecify table endtable
package endpackage import export
class endclass extends implements virtual local protected static automatic
interface endinterface modport clocking endclocking
property endproperty sequence endsequence
assert assume cover expect restrict bind
covergroup endcovergroup coverpoint cross
constraint randomize new this super
signed unsigned tri triand trior tri0 tri1 supply0 supply1 wand wor uwire
pullup pulldown pmos nmos cmos rpmos rnmos rcmos tran tranif0 tranif1
and or not nand nor xor xnor buf bufif0 bufif1 notif0 notif1
""".split())

_IDENT = r"[A-Za-z_]\w*"

# Compiler directives. A DUT is routinely instantiated inside `ifdef/`else, and
# its module type may itself be a macro (``DUT_TOP_NAME u_dut (...)`) so a TB can
# be retargeted at a differently-named top. Both shapes are REAL instantiations
# and must not be read as "nothing is driven".
_DIRECTIVES = frozenset("""
ifdef ifndef else elsif endif define undef undefineall include timescale
default_nettype line resetall celldefine endcelldefine pragma
unconnected_drive nounconnected_drive begin_keywords end_keywords
""".split())


# --------------------------------------------------------------------------
# comment / string aware lexing
# --------------------------------------------------------------------------
def split_code_and_comments(src: str) -> Tuple[str, str]:
    """Return (code_only, comments_only), both the SAME LENGTH as `src`.

    Every character is replaced by a space in the track it does not belong to,
    so character offsets — and therefore line numbers — stay exact in both.
    String literals are honoured: a `//` inside `$display("a // b")` is code,
    not a comment.
    """
    code = list(src)
    comm = [" "] * len(src)
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if c == '"':  # string literal — copy through, honour backslash escapes
            i += 1
            while i < n and src[i] != '"':
                i += 2 if src[i] == "\\" else 1
            i += 1
        elif c == "/" and nxt == "/":
            while i < n and src[i] != "\n":
                comm[i], code[i] = src[i], " "
                i += 1
        elif c == "/" and nxt == "*":
            end = src.find("*/", i + 2)
            end = n if end == -1 else end + 2
            for j in range(i, end):
                comm[j], code[j] = src[j], (" " if src[j] != "\n" else "\n")
            i = end
        else:
            if c == "\n":  # keep line structure in BOTH tracks
                comm[i] = "\n"
            i += 1
    return "".join(code), "".join(comm)


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _skip_balanced(text: str, i: int) -> int:
    """`text[i]` is '('. Return the index just past its matching ')'."""
    depth, n = 0, len(text)
    while i < n:
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def _match_instantiation(chunk: str, base: int) -> Tuple[str, str, int] | None:
    """Match `<type> [#(params)] <inst> (` at the start of `chunk`.

    Returns (module_type, instance_name, absolute_offset) or None. Requiring
    TWO identifiers before the '(' is what separates an instantiation from a
    task/function call (`run_one(...)`, `$display(...)`), and the keyword set
    filters the statement forms that share the shape.
    """
    m = re.match(rf"\s*(`?{_IDENT})\s*", chunk)
    if not m:
        return None
    mod, j = m.group(1), m.end()
    if mod.startswith("`"):
        if mod[1:] in _DIRECTIVES:  # a directive, not a macro module type
            return None
    elif mod in _KEYWORDS:
        return None
    if j < len(chunk) and chunk[j] == "#":  # optional parameter override
        k = j + 1
        while k < len(chunk) and chunk[k].isspace():
            k += 1
        if k >= len(chunk) or chunk[k] != "(":
            return None
        j = _skip_balanced(chunk, k)
        if j < 0:
            return None
    m2 = re.match(rf"\s*({_IDENT})\s*\(", chunk[j:])
    if not m2 or m2.group(1) in _KEYWORDS:
        return None
    return mod, m2.group(1), base + m.start(1)


def find_live_instantiations(code: str) -> List[Dict[str, Any]]:
    """Every real (uncommented) module instantiation in `code`.

    An instantiation is a STATEMENT, so candidates are taken at statement
    boundaries (`;`, `begin`, `end`, end-of-line) rather than by scanning free
    text — that stops a pattern from being matched across two unrelated
    statements. End-of-line is a boundary too, so an instantiation sitting
    directly under a `ifdef/`else directive line is still reached.
    """
    out: List[Dict[str, Any]] = []
    for m in re.finditer(r"(?:\A|[;)\n]|\bbegin\b|\bend\b)", code):
        hit = _match_instantiation(code[m.end():m.end() + 4000], m.end())
        if hit:
            mod, inst, pos = hit
            out.append({"module": mod, "instance": inst,
                        "line": _line_of(code, pos)})
    # de-duplicate on position (statement separators can overlap)
    seen, uniq = set(), []
    for d in out:
        key = (d["module"], d["instance"], d["line"])
        if key not in seen:
            seen.add(key)
            uniq.append(d)
    return uniq


def find_commented_instantiations(src: str, comments: str) -> List[Dict[str, Any]]:
    """Instantiation shapes buried in COMMENT text.

    Comment decoration (`//`, leading `*`) is stripped and consecutive comment
    lines are joined, so an instantiation whose port list continues on the next
    commented line is still recognised. Only NAMED-connection (`(.port(...)`)
    and PARAMETER-OVERRIDE (`#(...)`) shapes are accepted: a bare positional
    shape would match ordinary prose such as `// see foo bar (baz)`, and this
    gate must not manufacture false positives.
    """
    lines = comments.split("\n")
    out: List[Dict[str, Any]] = []
    for idx, raw in enumerate(lines):
        body = re.sub(r"^\s*(?://+|/\*+|\*+/?)\s*", "", raw)
        if not body.strip():
            continue
        # join following comment lines so a wrapped port list still parses
        joined, look = body, idx + 1
        while look < len(lines) and look < idx + 12:
            nxt = re.sub(r"^\s*(?://+|/\*+|\*+/?)\s*", "", lines[look])
            if not nxt.strip():
                break
            joined += " " + nxt
            look += 1
        hit = _match_instantiation(joined, 0)
        if not hit:
            continue
        mod, inst, _ = hit
        tail = joined[joined.find(inst, len(mod)) + len(inst):]
        named = re.match(r"\s*\(\s*\.", tail)
        params = re.search(rf"^\s*{re.escape(mod)}\s*#\s*\(", joined)
        if not (named or params):
            continue
        out.append({"module": mod, "instance": inst, "line": idx + 1,
                    "text": raw.strip()})
    return out


# --------------------------------------------------------------------------
# testbench discovery — the DIRECTORY decides, never the filename
# --------------------------------------------------------------------------
_PORTLESS_MODULE = re.compile(rf"^[ \t]*module\s+({_IDENT})\s*(?:\(\s*\))?\s*;",
                              re.MULTILINE)


def is_testbench(code: str) -> bool:
    """True when the source declares a PORTLESS module.

    A synthesizable RTL module always carries a port list; a testbench is the
    simulation top and never does. This is why the gate needs no filename
    convention — and why it does not mistake an RTL copy sitting inside the sim
    tree (e.g. coverage-annotated sources) for a testbench.
    """
    return bool(_PORTLESS_MODULE.search(code))


def source_drives_dut(src: str) -> bool:
    """True iff `src` contains at least one LIVE (uncommented) module
    instantiation — i.e. the testbench actually drives *something*.

    The SHARED substance primitive: the single source of truth for "does a
    testbench drive the DUT", so this gate and l10_tb_conformance_check can
    never disagree about whether a given testbench is vacuous. A commented-out
    instantiation, a bare `$display` naming a case, or a placeholder marker are
    all NOT drivers.
    """
    code, _ = split_code_and_comments(src)
    return bool(find_live_instantiations(code))


def any_source_drives_dut(sources) -> bool:
    """True iff ANY source in `sources` (an iterable of Verilog/SV text) drives
    the DUT. Tree-scope substance test shared with l10_tb_conformance_check: a
    sim tree in which nothing drives the design is vacuous, so its
    id-substring / opcode "evidence" is theatre and must not credit coverage.
    """
    return any(source_drives_dut(s) for s in sources)


def discover_testbenches(sim_root: Path) -> List[Path]:
    files = sorted(p for p in sim_root.rglob("*")
                   if p.is_file() and p.suffix in (".v", ".sv"))
    out = []
    for p in files:
        try:
            src = p.read_text(errors="ignore")
        except OSError:
            continue
        # A file under a `tb/` directory is a testbench by placement. Otherwise
        # it must LOOK portless first (cheap regex on the raw text) before the
        # comment-aware lex confirms it — that keeps a multi-MB netlist sitting
        # in the sim tree from being fully lexed just to be rejected.
        if "tb" in p.parent.name.split("_") or (
                _PORTLESS_MODULE.search(src)
                and is_testbench(split_code_and_comments(src)[0])):
            out.append(p)
    return out


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------
def check_file(path: Path, rel: Path) -> Dict[str, Any]:
    src = path.read_text(errors="ignore")
    code, comments = split_code_and_comments(src)
    live = find_live_instantiations(code)
    live_modules = {d["module"] for d in live}
    findings: List[Dict[str, Any]] = []

    seen_lines: set[int] = set()
    for pat in PLACEHOLDER_PATTERNS:
        for m in pat.finditer(src):
            ln = _line_of(src, m.start())
            if ln in seen_lines:  # both halves of the same marker line
                continue
            seen_lines.add(ln)
            findings.append({
                "detector": "placeholder_marker",
                "file": str(rel), "line": ln,
                "text": src.split("\n")[ln - 1].strip(),
                "matched": m.group(0),
            })

    for c in find_commented_instantiations(src, comments):
        if c["module"] in live_modules:
            continue  # really driven; the comment is a debug alternative
        findings.append({
            "detector": "commented_dut_instantiation",
            "file": str(rel), "line": c["line"], "text": c["text"],
            "module": c["module"], "instance": c["instance"],
        })

    return {"file": str(rel), "live_instantiations": live, "findings": findings}


def check(project: Path, sim_root: Path | None = None) -> Dict[str, Any]:
    root = sim_root or (project / "phase2" / "stage1" / "sim")
    res: Dict[str, Any] = {"gate": "vacuous_testbench", "sim_root": str(root)}
    if not root.is_dir():
        res.update(verdict="NOT_APPLICABLE",
                   reason="no sim tree (step did not run)")
        return res

    tbs = discover_testbenches(root)
    if not tbs:
        res.update(verdict="NOT_APPLICABLE",
                   reason="no testbench discovered under the sim tree")
        return res

    evidence: List[Dict[str, Any]] = []
    per_file, any_live = [], False
    for p in tbs:
        try:
            r = check_file(p, p.relative_to(root))
        except OSError as e:
            res.update(verdict="IO_ERROR", error=f"{p}: {e}")
            return res
        per_file.append(r)
        any_live = any_live or bool(r["live_instantiations"])
        evidence.extend(r["findings"])

    # D3 — tree scope: SOMETHING in this sim tree must drive the design.
    if not any_live:
        evidence.append({
            "detector": "no_live_instantiation",
            "file": str(root), "line": 0,
            "text": (f"no uncommented module instantiation in any of the "
                     f"{len(tbs)} testbench(es) under the sim tree"),
        })

    res.update(
        testbenches_scanned=len(tbs),
        files=[str(p.relative_to(root)) for p in tbs],
        offending_files=sorted({e["file"] for e in evidence
                                if e["detector"] != "no_live_instantiation"}),
        detectors_tripped=sorted({e["detector"] for e in evidence}),
        evidence=evidence,
    )
    if evidence:
        res.update(verdict="FAIL",
                   reason="vacuous testbench — prints a pass without driving "
                          "the design")
    else:
        res.update(verdict="PASS",
                   reason="every testbench drives the design")
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project", type=Path, nargs="?", default=Path("."))
    ap.add_argument("--sim-root", type=Path, default=None,
                    help="override the sim tree (default phase2/stage1/sim)")
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args(argv)
    try:
        res = check(a.project.resolve(),
                    a.sim_root.resolve() if a.sim_root else None)
    except OSError as e:
        res = {"gate": "vacuous_testbench", "verdict": "IO_ERROR",
               "error": str(e)}
    txt = json.dumps(res, indent=2)
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(txt + "\n")
    print(txt)
    verdict = res.get("verdict")
    if verdict == "NOT_APPLICABLE":
        # vibe-ic#1115 (re-implementing #1236). THE FOURTH GATE OF THE SAME
        # SHAPE #1173 repaired for `professional_tb_check`,
        # `sta_corner_record_completeness_check` and
        # `drv_promotion_corroboration_check`; this one was left out and is the
        # only member of that class still doing it.
        #
        # This gate had ALREADY DECIDED the run was inapplicable — it writes
        # `"reason": "no sim tree (step did not run)"` into its own report — and
        # then said so on no channel that changes a verdict. `_check_program_exit_zero`
        # reads the EXIT CODE and, on the passing path, exactly one stdout
        # channel: `_stdout_signals_vacuous`, which matches `VACUOUS_PASS` at
        # LINE START. A JSON blob containing `"verdict": "NOT_APPLICABLE"` does
        # not match it, so the step recorded an ordinary PASS. The producer
        # emitted nothing and the checker read the absence as consent — the
        # LibreLane `klayout.py:486-490` shape (`return {}` when the PDK has no
        # DRC deck, so `Checker.KLayoutDRC` finds nothing, warns, and passes) in
        # our own tree.
        #
        # The gate's `--json` report IS read, by `_json_report_signals_vacuous`,
        # but that channel is COUNTED and only tiers the step when EVERY gate
        # clause that dispatched a program in it disclosed the same
        # (`len(all_vacuous_cmds) >= len(ran_hints)`). This clause sits in an
        # `all_of` beside substantive siblings, so the count is never unanimous
        # and the step still records PASS — carrying a `PARTIALLY-VACUOUS`
        # reason, which names the hole rather than closing it.
        #
        # rc STAYS 0, deliberately. Flipping it would fail every legitimately
        # sim-free run, and a permanently red gate is one people route around.
        # What changes is that the flow stops recording "checked, fine" for a
        # thing nobody checked: the sentinel below is the channel
        # `check_step` promotes on, so the step becomes VACUOUS_PASS.
        print(f"VACUOUS_PASS: vacuous_testbench examined 0 testbench(es) — "
              f"{res.get('reason', 'the producing step left nothing to check')}")
        return 0
    if verdict == "PASS":
        return 0
    if verdict == "IO_ERROR":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
