#!/usr/bin/env python3
"""iface_conformance_v2.py — prompt→interface conformance gate (ORGANIC #695).

PROBLEM (Oracle-RCA on the CVDP cvdp-open residual): a recurring class of
blind-author miss is PROMPT-DERIVABLE and PROGRAM-CHECKABLE, yet no gate
catches it before the completion is emitted. The hidden cocotb harness binds
to the DUT by EXACT signal names + directions and derives its TOPLEVEL from
the canonical problem / file name, so any of:

  (1) MODULE-NAME-CASE — the RTL module name differs (often only in CASE)
      from the canonical id stem the harness uses as TOPLEVEL
      (RTL `FindFasterClock` vs harness top `findfasterclock`) → the harness
      `-s findfasterclock` finds no such module → elaboration fail;
  (2) MISSING-PORT — an interface port NAMED in the prompt (a markdown table
      row, a backtick signal name with a nearby direction word, a given-code
      module header, a wavedrom `{"name":…}` entry) is ABSENT from the RTL
      port list (AXI master omitting `ar*`/`aw*`; `s_ready`; a
      `register_addr_i` named only in a wavedrom) → the harness drive/read of
      that net does not bind → elab / functional fail;
  (3) PORT-DIRECTION — a port whose DIRECTION disagrees with the prompt's
      signal table (the harness DRIVES `sram_valid` as a DUT input but the
      RTL declares it `output`) → functional fail.

All three are derivable from the PROMPT ALONE (table rows / backtick signal
names / a given-code module header / wavedrom name entries / the canonical
id), so a DETERMINISTIC gate reading ONLY the prompt + the authored RTL can
flag them at emit time. Run-time stays BLIND: this gate NEVER opens the
oracle / hidden testbench / reference RTL — only the two files it is handed.

ADVISORY by default (prompt extraction is heuristic — a prompt mentions
internal signals that are legitimately NOT ports, so a false positive must
NOT hard-block an otherwise-correct emit). `--strict` exits 1 on any finding.

SCOPING (ORGANIC #726): the gate scopes prompt-named identifiers to their
OWNING module so it does not false-fire. A prompt token is SATISFIED if it is a
declared port of ANY module in the completion (top OR sub-module) or of a
harness-supplied context module; a token equal to a declared MODULE name (a
markdown `### Module: Foo` heading, a backtick wrapping a sub-module name) is
EXCLUDED from the signal/direction comparison; and MODULE-NAME-CASE is
SUPPRESSED when the prompt's RTL skeleton declares the module name verbatim
(the harness instantiates that exact name).

CLI:
    python3 iface_conformance_v2.py --id <problem_id> \
        --prompt <prompt.txt> --rtl <design.sv> \
        [--context <ctx.sv> ...] [--strict] [--json OUT]

  --id      the canonical problem id; the harness TOPLEVEL stem is derived
            from it (`cvdp_copilot_findfasterclock_0001` → `findfasterclock`).
            Optional — when absent only port name/direction checks run.
  --prompt  the prompt / spec text the author was given (the ONLY interface
            source other than the id).
  --rtl     the authored RTL the author is about to emit.
  --context a harness-supplied context RTL file (`input.context` rtl/*.sv); the
            ports and module names it declares count as SATISFIED, not
            author-missing (the #715 family). Repeatable.
  --strict  exit 1 on any finding (default: advisory, always exit 0).

Exit codes:
    0  no finding, OR findings in advisory (default) mode
    1  ≥1 finding AND --strict
    2  bad input (missing/empty file)

Stdout: one line per finding (`MODULE-NAME-CASE: …`, `MISSING-PORT: …`,
`PORT-DIRECTION: …`); `interface-conformance ok` when conformant.

chip-AGNOSTIC: pure prompt-prose + RTL structure; no chip / vendor / SKU
literal, no dataset / oracle access.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# ── id → canonical harness TOPLEVEL stem ────────────────────────────────────
# Mirrors cvdp_gate.required_top_from_id but kept self-contained so this gate
# has no import-time dependency on the benchmark harness. The CVDP id follows
# `cvdp_copilot_<stem>[_NNNN]`; the harness TOPLEVEL stem is `<stem>` (the id
# minus the `cvdp_copilot_` prefix and any trailing `_NNNN` variant suffix).
# For a non-CVDP id we fall back to the id minus a trailing `_NNNN`.
_CVDP_VARIANT_RE = re.compile(r"^cvdp_copilot_(.+?)_\d{3,}$")
_CVDP_PLAIN_RE = re.compile(r"^cvdp_copilot_(.+)$")
_TRAILING_NUM_RE = re.compile(r"^(.+?)_\d{3,}$")


def harness_top_from_id(rid: Optional[str]) -> Optional[str]:
    """The canonical harness TOPLEVEL stem derived from the problem id, or
    None when no id is given. The harness derives its cocotb TOPLEVEL from
    this canonical name, so the RTL module must match it CASE-EXACTLY."""
    rid = (rid or "").strip()
    if not rid:
        return None
    m = _CVDP_VARIANT_RE.match(rid)
    if m:
        return m.group(1)
    m = _CVDP_PLAIN_RE.match(rid)
    if m:
        return m.group(1)
    m = _TRAILING_NUM_RE.match(rid)
    if m:
        return m.group(1)
    return rid


# ── RTL parsing (case-PRESERVING) ───────────────────────────────────────────
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_STRING_LIT_RE = re.compile(r'"(?:[^"\\\n]|\\.)*"')


def _strip_comments(text: str) -> str:
    t = _BLOCK_COMMENT_RE.sub(" ", text)
    t = _LINE_COMMENT_RE.sub(" ", t)
    return _STRING_LIT_RE.sub('""', t)


_MODULE_HDR_RE = re.compile(
    r"\bmodule\s+([A-Za-z_]\w*)\s*"
    r"(?:#\s*\((?:[^()]|\([^()]*\))*\)\s*)?"   # optional #(params)
    r"(?:\((?P<ports>(?:[^()]|\([^()]*\))*)\))?\s*;",
    re.DOTALL)

# ANSI port declaration inside the header port list, e.g.
# `input wire [3:0] foo`, `output reg bar`, `inout baz`.
_ANSI_PORT_RE = re.compile(
    r"\b(input|output|inout)\b"
    r"(?:\s+(?:wire|reg|logic|bit|signed|unsigned))*"
    r"(?:\s*\[[^\]]*\])?\s*"
    r"([A-Za-z_]\w*)")

# non-ANSI body declaration: `input [3:0] foo, bar;` / `output reg q;`
_NONANSI_PORT_RE = re.compile(
    r"\b(input|output|inout)\b"
    r"(?:\s+(?:wire|reg|logic|bit|signed|unsigned))*"
    r"(?:\s*\[[^\]]*\])?\s*"
    r"((?:[A-Za-z_]\w*\s*,\s*)*[A-Za-z_]\w*)\s*;")


@dataclass
class RtlIface:
    module_name: Optional[str] = None
    # direction by ORIGINAL-CASE port name
    ports: Dict[str, str] = field(default_factory=dict)

    @property
    def port_names_lower(self) -> Dict[str, str]:
        """lower(name) → original-case name (for case-insensitive lookup)."""
        return {k.lower(): k for k in self.ports}


def _parse_module_match(src: str, m: "re.Match") -> RtlIface:
    """Build an RtlIface from a single _MODULE_HDR_RE match `m` over `src`."""
    iface = RtlIface(module_name=m.group(1))
    ports_blob = m.group("ports") or ""
    # ANSI directions in the header
    for pm in _ANSI_PORT_RE.finditer(ports_blob):
        iface.ports[pm.group(2)] = pm.group(1).lower()
    # bare names in the header (non-ANSI: directions are in the body)
    header_names: List[str] = []
    if ports_blob.strip():
        # tokens that look like identifiers not already captured as ANSI ports
        for nm in re.findall(r"[A-Za-z_]\w*", ports_blob):
            if nm in ("input", "output", "inout", "wire", "reg", "logic",
                      "bit", "signed", "unsigned"):
                continue
            header_names.append(nm)
    # non-ANSI body declarations — scan ONLY this module's body (header → its
    # matching endmodule), so a sub-module's body decls aren't attributed here.
    body = src[m.end():]
    em = re.search(r"\bendmodule\b", body)
    if em:
        body = body[:em.start()]
    for pm in _NONANSI_PORT_RE.finditer(body):
        direction = pm.group(1).lower()
        for nm in re.split(r"\s*,\s*", pm.group(2).strip()):
            nm = nm.strip()
            if nm and nm not in iface.ports:
                iface.ports[nm] = direction
    # any header bare-name with no direction found → record as unknown so it's
    # still counted as a declared port (prevents false MISSING-PORT)
    for nm in header_names:
        iface.ports.setdefault(nm, "unknown")
    return iface


def parse_rtl(text: str) -> RtlIface:
    """Parse the FIRST module declaration: name (case-preserved) + ports with
    directions. Handles ANSI (directions in the header) and non-ANSI
    (directions in the body) port styles. This is the TOP the harness binds."""
    src = _strip_comments(text)
    m = _MODULE_HDR_RE.search(src)
    if not m:
        return RtlIface()
    return _parse_module_match(src, m)


def parse_all_rtl(text: str) -> List[RtlIface]:
    """Parse EVERY module declaration in `text`. The first is the TOP; the rest
    are sub-modules. Used so a port declared on ANY module (top OR sub-module)
    counts as SATISFIED — the prompt's given-code may name a sub-module's ports
    that are legitimately declared on that sub-module, not the top (#726)."""
    src = _strip_comments(text)
    return [_parse_module_match(src, m) for m in _MODULE_HDR_RE.finditer(src)]


# ── prompt interface extraction ─────────────────────────────────────────────
# A markdown table row whose first backtick-quoted cell is a signal name and a
# later cell is a direction word: `| \`clk_A\` | input | ... |`.
_DIR_WORD_RE = re.compile(r"\b(input|output|inout)\b", re.IGNORECASE)
_BACKTICK_RE = re.compile(r"`([A-Za-z_]\w*)`")

# A backtick signal name followed (within a short window) by a direction word,
# or preceded by one — covers prose like "`s_ready` is an output" and
# "input `register_addr_i`". The window is intentionally tight so unrelated
# prose mentions don't fabricate ports (advisory anyway).
_DIR_NEAR_BEFORE_RE = re.compile(
    r"\b(input|output|inout)\b[^\n`]{0,40}?`([A-Za-z_]\w*)`",
    re.IGNORECASE)
_DIR_NEAR_AFTER_RE = re.compile(
    r"`([A-Za-z_]\w*)`[^\n`]{0,40}?\b(?:is\s+(?:an?\s+)?)?(input|output|inout)\b",
    re.IGNORECASE)

# A given-code module header inside the prompt (e.g. a fenced template the
# author must complete) — its ports are the authoritative interface.
_WAVEDROM_NAME_RE = re.compile(r'["\']name["\']\s*:\s*["\']([A-Za-z_]\w*)["\']')


def _table_ports(prompt: str) -> Dict[str, str]:
    """Markdown table rows: first backtick cell = name, a later cell carrying
    a direction word = direction. Returns name→direction (lower, '' if no
    direction word in the row)."""
    out: Dict[str, str] = {}
    # Split on the pipe so an inline single-line table (the acceptance shape)
    # and a true multi-row markdown table both work: scan windows of
    # `\`name\` | dir` regardless of line boundaries.
    for cell_m in re.finditer(r"`([A-Za-z_]\w*)`\s*\|\s*([A-Za-z]+)", prompt):
        name = cell_m.group(1)
        word = cell_m.group(2).lower()
        if word in ("input", "output", "inout"):
            out[name] = word
        else:
            out.setdefault(name, "")
    return out


def _given_code_ports(prompt: str) -> Tuple[Optional[str], Dict[str, str]]:
    """A module header given INSIDE the prompt (a code template). Returns the
    template module name (if any) and its ports."""
    iface = parse_rtl(prompt)
    if iface.module_name is None and not iface.ports:
        return None, {}
    return iface.module_name, dict(iface.ports)


@dataclass
class PromptIface:
    # port name → direction ('' / 'input' / 'output' / 'inout')
    ports: Dict[str, str] = field(default_factory=dict)
    given_module: Optional[str] = None
    sources: Dict[str, Set[str]] = field(default_factory=dict)

    def add(self, name: str, direction: str, source: str) -> None:
        cur = self.ports.get(name, "")
        # a concrete direction wins over an empty one; conflicting concrete
        # directions are left as the first-seen (table is most authoritative)
        if not cur and direction:
            self.ports[name] = direction
        elif name not in self.ports:
            self.ports[name] = direction
        self.sources.setdefault(name, set()).add(source)


def extract_prompt_iface(prompt: str) -> PromptIface:
    """Extract the named interface from the PROMPT alone. Sources, in order of
    authority for direction: markdown table rows, a given-code module header,
    backtick-name-with-nearby-direction prose, wavedrom name entries (names
    only — no direction)."""
    pif = PromptIface()
    # (a) markdown table rows — most authoritative for direction
    for name, direction in _table_ports(prompt).items():
        pif.add(name, direction, "table")
    # (b) given-code module header (a template the author completes)
    gm_name, gm_ports = _given_code_ports(prompt)
    if gm_name is not None:
        pif.given_module = gm_name
    for name, direction in gm_ports.items():
        pif.add(name, "" if direction == "unknown" else direction,
                "given_code")
    # (c) backtick name + nearby direction word (prose)
    for m in _DIR_NEAR_BEFORE_RE.finditer(prompt):
        pif.add(m.group(2), m.group(1).lower(), "prose")
    for m in _DIR_NEAR_AFTER_RE.finditer(prompt):
        pif.add(m.group(1), m.group(2).lower(), "prose")
    # (d) wavedrom signal names (names only, no direction)
    for m in _WAVEDROM_NAME_RE.finditer(prompt):
        pif.add(m.group(1), "", "wavedrom")
    return pif


# ── conformance ─────────────────────────────────────────────────────────────
@dataclass
class Finding:
    kind: str       # MODULE-NAME-CASE | MISSING-PORT | PORT-DIRECTION
    message: str


def check_conformance(rid: Optional[str], prompt: str, rtl_text: str,
                      context_rtl: Optional[List[str]] = None) -> List[Finding]:
    findings: List[Finding] = []
    # The TOP is the first module the author emitted; the harness binds to it.
    modules = parse_all_rtl(rtl_text)
    rtl = modules[0] if modules else RtlIface()
    pif = extract_prompt_iface(prompt)
    rtl_lower = rtl.port_names_lower

    # (#726a/#726d) A port name is SATISFIED if it is declared on ANY module in
    # the completion (top OR sub-module) OR on any CONTEXT module the harness
    # provides via input.context rtl/*.sv — not only the top. The prompt's
    # given-code may name a sub-module's ports, and context-RTL ports are
    # harness-supplied, not author-missing (the #715 family). Union over all.
    context_modules: List[RtlIface] = []
    for ctx in (context_rtl or []):
        context_modules.extend(parse_all_rtl(ctx))
    all_port_names_lower: Set[str] = set()
    for mod in modules + context_modules:
        all_port_names_lower.update(mod.port_names_lower.keys())

    # (#726b/#726c) The set of declared MODULE names — across the completion AND
    # the prompt's given-code AND context RTL. A prompt token equal to a module
    # name (a markdown heading like `### Module: Foo`, or a backtick wrapping a
    # sub-module name) is NOT an interface signal and must be EXCLUDED from the
    # missing-port / direction comparison entirely.
    module_names_lower: Set[str] = set()
    for mod in modules + context_modules:
        if mod.module_name:
            module_names_lower.add(mod.module_name.lower())
    if pif.given_module:
        module_names_lower.add(pif.given_module.lower())

    # (1) MODULE-NAME-CASE: harness top from id must match the RTL module name
    # CASE-EXACTLY. Only flag when the names match case-INSENSITIVELY but
    # differ in case (a genuinely different name is the author's design freedom
    # / the prompt's `Module Name:` may legitimately rename — that is NOT this
    # gate's concern, and flagging it would false-fire constantly).
    #
    # (#726c) SUPPRESS when the prompt's RTL block LITERALLY declares the module
    # name verbatim (case-exact): a code-completion skeleton instantiates that
    # exact name, so the harness uses it as-is — the lowercase id stem is then
    # NOT the elaboration top, and flagging a "case mismatch" pushes a WRONG
    # rename that breaks the harness.
    top = harness_top_from_id(rid)
    prompt_declares_verbatim = (
        pif.given_module is not None and rtl.module_name is not None
        and pif.given_module == rtl.module_name)
    if top and rtl.module_name and rtl.module_name != top \
            and rtl.module_name.lower() == top.lower() \
            and not prompt_declares_verbatim:
        findings.append(Finding(
            "MODULE-NAME-CASE",
            f"MODULE-NAME-CASE: harness top is '{top}' (derived from the "
            f"canonical id) but the RTL declares '{rtl.module_name}' — the "
            f"hidden harness elaborates `-s {top}` CASE-EXACTLY, so this "
            f"ELAB_ERRORs at scoring"))

    # (2) MISSING-PORT: a prompt-named port absent from EVERY module's port list
    # (case-insensitive — the harness binds by name; case is checked only for
    # the module-top above). Internal-signal false positives are why this is
    # ADVISORY by default.
    for name in sorted(pif.ports):
        if name.lower() in module_names_lower:
            continue  # (#726b) a module name, not an interface signal
        if name.lower() not in all_port_names_lower:
            srcs = ",".join(sorted(pif.sources.get(name, set())))
            findings.append(Finding(
                "MISSING-PORT",
                f"MISSING-PORT: prompt names interface signal '{name}' "
                f"(source: {srcs}) but the RTL port list does not declare it "
                f"— the harness binds to this net by name (advisory: confirm "
                f"it is a port, not an internal signal)"))

    # (3) PORT-DIRECTION: a TOP port the RTL declares with a direction that
    # disagrees with the prompt's signal table. The harness binds the top, so
    # direction is checked against the top only.
    for name, want in sorted(pif.ports.items()):
        if not want or want == "unknown":
            continue
        if name.lower() in module_names_lower:
            continue  # (#726b) a module name, not an interface signal
        rtl_orig = rtl_lower.get(name.lower())
        if rtl_orig is None:
            continue  # not a top port (satisfied elsewhere or reported missing)
        have = rtl.ports.get(rtl_orig, "unknown")
        if have in ("unknown", ""):
            continue
        if have != want:
            findings.append(Finding(
                "PORT-DIRECTION",
                f"PORT-DIRECTION: prompt declares '{name}' as {want} but the "
                f"RTL declares it {have} — the harness drives/reads it as "
                f"{want}, so the opposite direction FAILs functionally"))
    return findings


def run(rid: Optional[str], prompt_path: Path, rtl_path: Path,
        context_paths: Optional[List[Path]] = None
        ) -> Tuple[List[Finding], Dict]:
    prompt = prompt_path.read_text(errors="replace")
    rtl_text = rtl_path.read_text(errors="replace")
    context_paths = context_paths or []
    context_rtl = [p.read_text(errors="replace") for p in context_paths]
    findings = check_conformance(rid, prompt, rtl_text, context_rtl)
    rtl = parse_rtl(rtl_text)
    report = {
        "program": "iface_conformance_v2",
        "version": "1.0.0",
        "id": rid,
        "harness_top": harness_top_from_id(rid),
        "rtl_module": rtl.module_name,
        "rtl_ports": rtl.ports,
        "findings": [{"kind": f.kind, "message": f.message} for f in findings],
        "conformant": not findings,
        # provenance: prove the gate only read the handed-in files (blind) —
        # the prompt, the authored RTL, and any harness-supplied context RTL.
        "files_read": [str(prompt_path), str(rtl_path)]
        + [str(p) for p in context_paths],
    }
    return findings, report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="prompt→interface conformance gate (#695): module-name "
                    "case + missing-port + port-direction, all "
                    "prompt-derivable, BLIND (no oracle read).")
    ap.add_argument("--id", default=None,
                    help="canonical problem id; the harness TOPLEVEL stem is "
                         "derived from it")
    ap.add_argument("--prompt", required=True,
                    help="prompt / spec text the author was given")
    ap.add_argument("--rtl", required=True, help="the authored RTL")
    ap.add_argument("--context", action="append", default=None,
                    help="a harness-supplied context RTL file "
                         "(input.context rtl/*.sv); ports/modules it declares "
                         "count as SATISFIED, not author-missing. Repeatable.")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on any finding (default: advisory, exit 0)")
    ap.add_argument("--json", default=None, help="optional JSON report path")
    args = ap.parse_args(argv)

    pp = Path(args.prompt)
    rp = Path(args.rtl)
    for label, p in (("--prompt", pp), ("--rtl", rp)):
        if not p.is_file():
            print(f"ERROR: {label} file not found: {p}", file=sys.stderr)
            return 2
    ctx_paths: List[Path] = []
    for c in (args.context or []):
        cp = Path(c)
        if not cp.is_file():
            print(f"ERROR: --context file not found: {cp}", file=sys.stderr)
            return 2
        ctx_paths.append(cp)
    if not rp.read_text(errors="replace").strip():
        print(f"ERROR: --rtl file is empty: {rp}", file=sys.stderr)
        return 2

    findings, report = run(args.id, pp, rp, ctx_paths)
    if args.json:
        Path(args.json).write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    if not findings:
        print("interface-conformance ok")
        return 0
    for f in findings:
        print(f.message)
    mode = "strict" if args.strict else "advisory"
    print(f"interface-conformance: {len(findings)} finding(s) [{mode}]",
          file=sys.stderr)
    return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
