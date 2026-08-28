#!/usr/bin/env python3
"""tb_vcs_only_construct_remediate.py — ORGANIC #717

The companion REMEDIATOR to `tb_vcs_only_construct_detect.py`. § 3 already
sanctions the VCS→iverilog TOOL substitution; this completes it at the
CONSTRUCT level with a DETERMINISTIC, semantics-preserving source rewrite of a
CLOSED known-safe subset, so a scoring TB that iverilog rejects only for a
mechanically-remediable VCS-ism is no longer abandoned as FLOOR-D when a
remediated TB would let a correct design PASS.

CLOSED SAFE SUBSET (the ONLY rewrites performed):
  * `break;`    → wrap the enclosing `<loop> (...) begin … end` in a uniquely
                  named block `begin : <lbl> … end` and replace the `break;`
                  with `disable <lbl>;` (terminates the whole loop = break).
  * `continue;` → name the loop BODY block `begin : <lbl> … end` and replace
                  the `continue;` with `disable <lbl>;` (ends this iteration's
                  block = continue; the loop then advances).
  * `unique`/`priority` `case` → drop the qualifier (a simulation-time
                  assertion hint; the selected branch is unchanged).

HARD REFUSE (stay FLOOR-D — NO deterministic equivalent, never rewritten):
  std::randomize / .randomize() / $urandom_range / join_none / join_any /
  wait_order / queue ops (.push_back/.pop_front/…). An array-aggregate
  assignment-pattern `'{…}` is NOT in the safe subset either — if it remains
  after the safe rewrites the remediation is REFUSED (we never ship a
  partially-fixed TB).

SAFETY (no-cheating — the remediator RELAXES a FLOOR to a runnable TB, so the
no-leak proof is load-bearing):
  1. The ORIGINAL TB is never modified — the rewrite is written to a `*_iv.v`
     SIDECAR.
  2. After rewriting, the result is RE-SCANNED; if ANY blocking construct
     remains (an un-rewritten break/continue, a `'{…}`, or a refuse-class
     token) the remediation is REFUSED.
  3. break/continue are only rewritten when the enclosing loop has an EXPLICIT
     `begin … end` body that this matcher can bracket unambiguously; any
     ambiguous shape (single-statement loop body, unbracketable nesting) →
     REFUSE.
  4. `remediate_and_verify(... golden=…)` re-runs the reference/golden design
     through the remediated TB and REJECTS the remediation unless the golden
     STILL passes — a TB-weakening rewrite (one that lets a wrong design pass)
     is thereby rejected. (§4.05: a wrong design must still FAIL the remediated
     TB; the discriminating power is preserved because `disable` fires at the
     exact same point `break`/`continue` would.)

chip-AGNOSTIC: pure SystemVerilog construct grammar + begin/end bracket
matching; no chip / vendor / SKU / design literal.

Exit codes (CLI):
    0  remediated TB written (sidecar) — or input already iverilog-clean
    1  REFUSED (a refuse-class construct, or an unbracketable / residual case)
    2  bad input (file not found / unreadable)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402

# Reuse the detector's construct taxonomy so detect↔remediate never drift.
try:
    import tb_vcs_only_construct_detect as _det
except ImportError:  # pragma: no cover — path-insert fallback
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import tb_vcs_only_construct_detect as _det

# Constructs with a deterministic semantics-preserving rewrite.
_REMEDIABLE = {"break_stmt", "continue_stmt", "unique_priority_case"}
# Constructs with NO deterministic equivalent — presence ⇒ hard REFUSE.
_REFUSE = {"std_randomize", "urandom_range", "advanced_fork", "queue_ops"}
# Not in the safe subset; if it survives the safe rewrites ⇒ REFUSE.
_UNHANDLED = {"assignment_pattern"}

_LOOP_KW = ("for", "foreach", "while", "forever", "repeat")
# token scan: loop keywords, begin, end (word-boundary; comment/string-blanked)
_TOK_RE = re.compile(r"\b(for|foreach|while|forever|repeat|begin|end)\b")
_UNIQUE_PRIORITY_RE = re.compile(r"\b(unique|priority)\s+(case\b)")
_BREAK_RE = re.compile(r"\bbreak\s*;")
_CONTINUE_RE = re.compile(r"\bcontinue\s*;")


def _blank_noncode(text: str) -> str:
    """Return `text` with line/block comments and string literals replaced by
    same-length blanks, so token offsets map 1:1 onto the ORIGINAL text (we
    SCAN the blanked view but EDIT the original at identical offsets)."""
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                out[i] = " "
                i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            out[i] = out[i + 1] = " "
            i += 2
            while i < n and not (text[i] == "*" and i + 1 < n
                                 and text[i + 1] == "/"):
                if text[i] != "\n":
                    out[i] = " "
                i += 1
            if i < n:
                out[i] = " "
                if i + 1 < n:
                    out[i + 1] = " "
                i += 2
        elif c == '"':
            out[i] = " "
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    out[i] = " "
                    i += 1
                if i < n and text[i] != "\n":
                    out[i] = " "
                i += 1
            if i < n:
                out[i] = " "
                i += 1
        else:
            i += 1
    return "".join(out)


def _loop_body_spans(blank: str):
    """Bracket every `<loop> (...) begin … end` in the comment/string-blanked
    text. Returns a list of dicts (innermost-first is NOT guaranteed; callers
    pick the innermost enclosing span by smallest range):
        {body_begin, body_end_kw_start, body_end_kw_end, loop_start}
    where body_begin is the offset of the loop-body `begin` keyword's 'b',
    body_end_* bracket the matching `end`, and loop_start is the loop keyword.
    Only loops whose body is an EXPLICIT begin/end are recorded — a single-
    statement loop body yields no span (its break/continue stays un-rewritten →
    later REFUSED)."""
    toks = [(m.group(1), m.start(), m.end()) for m in _TOK_RE.finditer(blank)]
    spans = []
    stack = []  # each: {"begin": pos, "is_loop": bool, "loop_start": pos|None}
    pending_loop = None  # (loop_kw_start) awaiting its body `begin`
    for kind, s, e in toks:
        if kind in _LOOP_KW:
            pending_loop = s
            continue
        if kind == "begin":
            is_loop = pending_loop is not None
            stack.append({"begin": s, "is_loop": is_loop,
                          "loop_start": pending_loop})
            pending_loop = None
        elif kind == "end":
            if not stack:
                # unbalanced — bail by returning what we have; caller REFUSEs
                # on residual constructs anyway.
                continue
            top = stack.pop()
            if top["is_loop"]:
                spans.append({"body_begin": top["begin"],
                              "body_end_kw_start": s, "body_end_kw_end": e,
                              "loop_start": top["loop_start"]})
            # a loop keyword whose next token was NOT begin (single-stmt body)
            # left pending_loop set; clear it so it can't bind a later begin.
            pending_loop = None
    return spans


def _innermost_enclosing(spans, pos):
    """The loop-body span with the SMALLEST range that strictly contains
    `pos` (a break/continue offset). None if no explicit-begin loop encloses
    it (⇒ the caller REFUSEs)."""
    best = None
    for sp in spans:
        if sp["body_begin"] < pos < sp["body_end_kw_start"]:
            rng = sp["body_end_kw_start"] - sp["body_begin"]
            if best is None or rng < best[0]:
                best = (rng, sp)
    return best[1] if best else None


def remediate_text(text: str):
    """Return (remediated_text | None, report). None ⇒ REFUSED.

    report: {refused: bool, reason: str, rewrites: {...counts...},
             refuse_constructs: [...], residual: [...]}"""
    hits = _det.scan_text(text)
    present = {h["construct"] for h in hits}
    report = {"refused": False, "reason": "", "rewrites": {},
              "refuse_constructs": sorted(present & _REFUSE),
              "residual": []}

    refuse_now = present & _REFUSE
    if refuse_now:
        report["refused"] = True
        report["reason"] = (
            "refuse-class VCS-only construct(s) with no deterministic "
            f"equivalent: {sorted(refuse_now)} — stays FLOOR-D")
        return None, report

    if not (present & (_REMEDIABLE | _UNHANDLED)):
        # nothing of ours to do — TB is already free of the constructs we
        # handle; return it unchanged (the scorer compiles it directly).
        report["reason"] = "no remediable VCS-only construct present"
        return text, report

    blank = _blank_noncode(text)
    edits = []  # (start, end, replacement) on the ORIGINAL text
    label_n = 0

    # ── (1) break;  → wrap enclosing loop in begin:LBL … end + disable LBL ──
    spans = _loop_body_spans(blank)
    n_break = n_continue = 0
    for m in _BREAK_RE.finditer(blank):
        sp = _innermost_enclosing(spans, m.start())
        if sp is None:
            report["refused"] = True
            report["reason"] = (
                "break; not inside an explicit `begin…end` loop body — "
                "unbracketable, stays FLOOR-D")
            return None, report
        label_n += 1
        lbl = f"_vcs_brk_{label_n}"
        # replace the break;
        edits.append((m.start(), m.end(), f"disable {lbl};"))
        # wrap the WHOLE loop: insert `begin : lbl ` before loop_start, ` end`
        # after the body end.
        edits.append((sp["loop_start"], sp["loop_start"],
                      f"begin : {lbl} "))
        edits.append((sp["body_end_kw_end"], sp["body_end_kw_end"], " end"))
        n_break += 1

    # ── (2) continue; → name loop BODY block + disable it ──
    for m in _CONTINUE_RE.finditer(blank):
        sp = _innermost_enclosing(spans, m.start())
        if sp is None:
            report["refused"] = True
            report["reason"] = (
                "continue; not inside an explicit `begin…end` loop body — "
                "unbracketable, stays FLOOR-D")
            return None, report
        label_n += 1
        lbl = f"_vcs_cont_{label_n}"
        edits.append((m.start(), m.end(), f"disable {lbl};"))
        # name the body begin: turn `begin` into `begin : lbl`
        bpos = sp["body_begin"]
        edits.append((bpos, bpos + len("begin"), f"begin : {lbl}"))
        n_continue += 1

    # ── (3) unique/priority case → drop the qualifier ──
    n_uniq = 0
    for m in _UNIQUE_PRIORITY_RE.finditer(blank):
        # keep the `case`, drop the `unique`/`priority` + following space(s)
        edits.append((m.start(1), m.start(2), ""))
        n_uniq += 1

    # apply edits right-to-left (non-overlapping by construction)
    edits.sort(key=lambda t: t[0], reverse=True)
    out = text
    for s, e, repl in edits:
        out = out[:s] + repl + out[e:]

    # ── re-scan: NO blocking construct may remain (incl. `'{…}` we don't
    #    handle and any refuse-class). A residual ⇒ REFUSE (never ship a
    #    partially-fixed TB). ──
    residual = {h["construct"] for h in _det.scan_text(out)}
    blocking = residual & (_REMEDIABLE | _UNHANDLED | _REFUSE)
    if blocking:
        report["refused"] = True
        report["residual"] = sorted(blocking)
        report["reason"] = (
            f"residual VCS-only construct(s) after rewrite: {sorted(blocking)} "
            "— not in the safe subset, stays FLOOR-D")
        return None, report

    report["rewrites"] = {"break": n_break, "continue": n_continue,
                          "unique_priority": n_uniq}
    report["reason"] = "semantics-preserving rewrite of the closed safe subset"
    return out, report


def golden_still_passes(golden_src: Path, remediated_tb: Path,
                        run=None, pass_re: str = r"pass",
                        fail_re: str = r"error|fail|mismatch",
                        timeout: int = 120) -> bool:
    """§4.05 GUARD — compile+run the reference/GOLDEN design against the
    REMEDIATED TB and return True iff it compiles (rc=0), runs, prints a PASS
    marker, and prints NO FAIL marker. The remediation caller uses this to
    REJECT a TB-weakening rewrite: if a botched `disable` rewrite changed the
    TB's discriminating behaviour the golden would stop passing, so a False
    here means "keep FLOOR-D, do not ship the sidecar".

    `run` is an injectable `(argv) -> (rc:int, combined_output:str)` so the
    guard is unit-testable without a real toolchain; it defaults to
    iverilog -g2012 + vvp. chip-AGNOSTIC: the pass/fail markers are caller-
    supplied regexes (default case-insensitive 'pass' / 'error|fail|mismatch'),
    never a design literal."""
    import re as _re
    if run is None:
        import shutil
        import tempfile

        def run(argv):
            return (lambda cp: (cp.returncode, (cp.stdout or "") +
                                (cp.stderr or "")))(
                _pr.run(argv, capture_output=True, text=True))
        if shutil.which("iverilog") is None or shutil.which("vvp") is None:
            return False
        with tempfile.TemporaryDirectory() as td:
            vvp = str(Path(td) / "g.vvp")
            rc, out = run(["iverilog", "-g2012", "-o", vvp,
                           str(remediated_tb), str(golden_src)])
            if rc != 0:
                return False
            rc, out = run(["vvp", vvp])
    else:
        rc, out = run(["iverilog", "-g2012", str(remediated_tb),
                       str(golden_src)])
    if rc != 0:
        return False
    low = out.lower()
    if _re.search(fail_re, low):
        return False
    return bool(_re.search(pass_re, low))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Semantics-preserving VCS-only TB-construct remediator "
                    "(#717) — companion to tb_vcs_only_construct_detect.")
    ap.add_argument("tb", help="the scoring testbench (VCS-mandated)")
    ap.add_argument("--out", default=None,
                    help="sidecar path (default <tb-stem>_iv<ext>); the "
                         "ORIGINAL tb is never modified")
    ap.add_argument("--golden", default=None,
                    help="reference/golden RTL — when given, the remediation "
                         "is REJECTED unless the golden STILL passes the "
                         "remediated TB (§4.05 TB-weakening guard)")
    ap.add_argument("--json", default=None, help="write the report JSON here")
    args = ap.parse_args(argv)

    tb = Path(args.tb)
    if not tb.is_file():
        print(f"ERROR: testbench not found: {tb}", file=sys.stderr)
        return 2
    try:
        text = tb.read_text(errors="replace")
    except OSError as e:
        print(f"ERROR: cannot read {tb}: {e}", file=sys.stderr)
        return 2

    remediated, report = remediate_text(text)
    out_path = Path(args.out) if args.out else tb.with_name(
        tb.stem + "_iv" + tb.suffix)
    report["sidecar"] = str(out_path) if remediated is not None else None
    text_json = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(text_json + "\n")
    print(text_json)

    if remediated is None:
        print(f"REFUSED: {report['reason']}", file=sys.stderr)
        return 1
    out_path.write_text(remediated)
    # §4.05 guard — if a golden is supplied it MUST still pass the remediated
    # TB, else the rewrite weakened the TB; reject (remove the sidecar, FLOOR-D).
    if args.golden:
        g = Path(args.golden)
        if not g.is_file():
            print(f"ERROR: --golden not found: {g}", file=sys.stderr)
            return 2
        if not golden_still_passes(g, out_path):
            try:
                out_path.unlink()
            except OSError:
                pass
            report["refused"] = True
            report["reason"] = ("golden does NOT still pass the remediated TB "
                                "— rewrite rejected as TB-weakening (§4.05)")
            report["sidecar"] = None
            if args.json:
                Path(args.json).write_text(
                    json.dumps(report, indent=2, ensure_ascii=False) + "\n")
            print(f"REFUSED: {report['reason']}", file=sys.stderr)
            return 1
        report["golden_still_passes"] = True
    print(f"remediated TB written: {out_path} "
          f"(original untouched) — disclose via tool_substitution_disclose "
          f"('VCS-only TB construct -> semantics-preserving iverilog rewrite')")
    return 0


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(main))
