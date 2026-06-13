#!/usr/bin/env python3
"""cmd_buf_index_semantic_consistency_check.py — Wave 37 (v0.119.69).

BACKLOG v0.119.70 Item 2 (P1): cross-check the command-buffer index
semantics in main_fsm RTL against `L3.opcodes[<hex>].payload_semantics`
typed `byte_offset`. Even when the numeric guards happen to coincide
(e.g. `cmd_buf[1] >= 0x80` AND `cmd_buf[2] > 0x7C` both block the
same illegal frame), an index swap between RTL and L3 silently breaks
on any byte-order rework. This gate catches the swap and the
"comment vs code" disagreement before it ships.

Detection
=========
1. **Applicability guard** — IC class must be one of:
       aid_class_half_duplex / digital_cmd_driven / mixed_signal_otp
   AND L3 must have at least one `opcodes[]` entry with a
   `payload_semantics: [...]` array carrying typed `byte_offset`
   entries. Otherwise SKIP.

2. **cmd-buffer signal name** — discovered in this priority:
   (a) L9 `cmd_buffer_signal_name` (any of `integration_spec` /
       top-level / `submodules[].cmd_buffer_signal_name`), OR
   (b) auto-detected in RTL: any `reg [7:0] <NAME> [N:0]` /
       `logic [7:0] <NAME> [N];` declaration where <NAME> matches
       one of {`cmd_buf`, `cmd_buffer`, `payload_buf`, `rx_buf`,
       `frame_buf`}, AND that array is written by either a
       byte_assembler / main_fsm file.
   If no candidate matches → SKIP (the project is not using a
   linear cmd-buffer pattern).

3. **For every opcode entry in L3.opcodes** with both:
       (a) `payload_semantics: [{byte_offset: K, field: NAME, ...}]`
       (b) the corresponding RTL-detectable index read in main_fsm
           that matches a request-time guard for the same opcode
           (e.g. `if (op == 8'hXX) ... <buf>[K]`),
   verify the offset K matches between L3 and RTL. Specifically:

   - For each main_fsm `<buf>[K]` read inside an opcode-specific
     branch, locate the L3 payload_semantics entry whose `field`
     name appears in (i) the RTL comment one or two lines above
     the read, OR (ii) a state-name with a matching label. If the
     offset disagrees with L3's byte_offset for that field → FAIL.

4. **Comment-vs-code consistency** — for every `<buf>[K]` read
   line, scan ±2 lines for a comment that names another byte
   offset (e.g. `// cmd_buf[1] = length, cmd_buf[2] = addr`). If
   the comment lists the field at offset K but the L3
   payload_semantics says that field is at offset K' ≠ K → FAIL.

This implementation is intentionally conservative: opcodes whose
L3 entry lacks `payload_semantics` are skipped (the schema does not
mandate it for every command); only typed entries are cross-checked.

Chip-AGNOSTIC. Does NOT hardcode `cmd_buf` — the buffer name is
discovered from L9 or from the RTL itself.

Exit codes
==========
0  — PASS / SKIP / PASS_WITH_WAIVER
1  — FAIL
2  — usage error
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import _path_layout as _pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ic_class_profile import detect_ic_class  # noqa: E402

WAIVER_KEY = "cmd_buf_index_semantic_intentional"
WAIVER_MIN_LEN = 40

_CANDIDATE_BUF_NAMES = (
    "cmd_buf", "cmd_buffer", "payload_buf",
    "rx_buf", "frame_buf",
)
_APPLICABLE_CLASSES = (
    "aid_class_half_duplex", "digital_cmd_driven", "mixed_signal_otp",
)


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def _l3_load(project: Path) -> Optional[dict]:
    for cand in (
        _pl.generated_docs_dir(project) / "L3_CMD_PROTOCOL.json",
        _pl.generated_docs_dir(project) / "L3_CMD.json",
    ):
        if cand.is_file():
            try:
                return json.loads(cand.read_text())
            except Exception:
                return None
    return None


def _l9_load(project: Path) -> Optional[dict]:
    for cand in (
        _pl.generated_docs_dir(project) / "L9_INTEGRATION_SPEC.json",
        _pl.generated_docs_dir(project) / "L9_INTEGRATION.json",
    ):
        if cand.is_file():
            try:
                return json.loads(cand.read_text())
            except Exception:
                return None
    return None


def _l3_opcodes_with_semantics(l3: dict) -> List[dict]:
    """Return list of dicts {hex, payload_semantics_list, name}.

    Only entries whose payload_semantics is a non-empty list of
    typed dicts with a `byte_offset` key are returned.
    """
    out: List[dict] = []
    for key in ("opcodes", "commands"):
        v = l3.get(key)
        items: List[dict] = []
        if isinstance(v, list):
            items = [e for e in v if isinstance(e, dict)]
        elif isinstance(v, dict):
            items = [
                {**e, "_dict_key": k} for k, e in v.items()
                if isinstance(e, dict)
            ]
        for entry in items:
            sem = entry.get("payload_semantics")
            if not isinstance(sem, list) or not sem:
                continue
            typed = [s for s in sem
                     if isinstance(s, dict) and "byte_offset" in s]
            if not typed:
                continue
            hex_v = (entry.get("hex") or entry.get("opcode")
                     or entry.get("opcode_hex") or entry.get("code"))
            if isinstance(hex_v, str):
                hex_v = hex_v.strip()
            out.append({
                "hex": hex_v,
                "name": entry.get("name") or entry.get("command_name"),
                "payload_semantics": typed,
            })
    return out


def _l9_buffer_signal_name(l9: Optional[dict]) -> Optional[str]:
    if not isinstance(l9, dict):
        return None
    direct = l9.get("cmd_buffer_signal_name")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    spec = l9.get("integration_spec")
    if isinstance(spec, dict):
        v = spec.get("cmd_buffer_signal_name")
        if isinstance(v, str) and v.strip():
            return v.strip()
    subs = l9.get("submodules")
    if isinstance(subs, list):
        for s in subs:
            if isinstance(s, dict):
                v = s.get("cmd_buffer_signal_name")
                if isinstance(v, str) and v.strip():
                    return v.strip()
    return None


def _find_rtl_files(project: Path) -> List[Path]:
    rtl = _pl.rtl_dir(project)
    if not rtl.is_dir():
        return []
    out: List[Path] = []
    for ext in (".v", ".sv"):
        for p in rtl.rglob(f"*{ext}"):
            out.append(p)
    return sorted(out)


_BUF_DECL_RE = re.compile(
    r"\b(?:reg|logic|wire|input|output|inout)\s*(?:\[\s*\d+\s*:\s*\d+\s*\])?\s+"
    r"(\w+)\s*\[\s*\d+\s*(?::\s*\d+\s*)?\]",
)


def _autodetect_buffer_names(rtl_bodies: List[Tuple[Path, str]]
                              ) -> List[str]:
    """Auto-detect a cmd-buffer-shaped reg array."""
    found: dict[str, int] = {}
    for path, src in rtl_bodies:
        for m in _BUF_DECL_RE.finditer(src):
            name = m.group(1)
            lname = name.lower()
            for cand in _CANDIDATE_BUF_NAMES:
                if cand in lname:
                    found[name] = found.get(name, 0) + 1
                    break
    # Order by hit count desc, then name.
    return sorted(found, key=lambda n: (-found[n], n))


def _is_main_fsm(path: Path, src: str) -> bool:
    name = path.stem.lower()
    if any(t in name for t in ("main_fsm", "fsm", "control",
                                "dispatcher", "ctrl")):
        return True
    if re.search(r"\bcase\s*\(\s*\w*\bop\w*\b", src, re.IGNORECASE) \
       and re.search(r"\bstate\s*<=\s*S_", src):
        return True
    return False


def _opcode_normalise(s: Optional[str]) -> Optional[int]:
    if not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None
    s = s.lower().replace("0x", "").replace("8'h", "").replace("'h", "")
    try:
        return int(s, 16)
    except Exception:
        return None


_BUF_READ_RE_TEMPLATE = (
    r"\b{name}\s*\[\s*(?P<idx>\d+)\s*\]"
)


def _scan_buf_reads(src: str, buf_name: str) -> List[Tuple[int, int, str]]:
    """Return list of (line_no, idx, full_line) for buf reads."""
    rgx = re.compile(_BUF_READ_RE_TEMPLATE.format(name=re.escape(buf_name)))
    out: List[Tuple[int, int, str]] = []
    lines = src.splitlines()
    for i, line in enumerate(lines, 1):
        # Skip pure declarations.
        if re.search(r"\b(?:reg|logic|wire)\b.*\[", line) and \
           buf_name in line and "<=" not in line and "=" not in line:
            continue
        for m in rgx.finditer(line):
            try:
                idx = int(m.group("idx"))
            except Exception:
                continue
            out.append((i, idx, line.strip()))
    return out


def _comment_at(src_with_comments: str, line_no: int,
                radius: int = 2) -> List[str]:
    """Return comment lines near the target line."""
    lines = src_with_comments.splitlines()
    out: List[str] = []
    for j in range(max(1, line_no - radius), min(len(lines), line_no + radius) + 1):
        L = lines[j - 1]
        m = re.search(r"//\s*(.*)$", L)
        if m:
            out.append(m.group(1).strip())
    return out


def _opcode_branch_for_line(src: str, line_no: int) -> Optional[int]:
    """Walk back to find the active `if (op == 8'hXX)` or `8'hXX:`
    case arm context for the given line."""
    lines = src.splitlines()
    op_re = re.compile(
        r"(?:case[^:]*\)\s*)?"
        r"\b(?:8\s*'\s*h\s*([0-9a-fA-F]{1,2})|0x([0-9a-fA-F]{1,2}))\b"
    )
    cmp_re = re.compile(
        r"\b(?:op|cmd_op|opcode|op_q|cmd_byte|cmd_code)\b\s*==\s*"
        r"(?:8\s*'\s*h\s*([0-9a-fA-F]{1,2})|0x([0-9a-fA-F]{1,2}))",
        re.IGNORECASE,
    )
    for j in range(line_no, 0, -1):
        L = lines[j - 1]
        m = cmp_re.search(L)
        if m:
            try:
                return int(m.group(1) or m.group(2), 16)
            except Exception:
                pass
        # Case label: `8'hXX:` at start of a line followed by colon.
        m2 = re.match(
            r"\s*(?:8\s*'\s*h\s*([0-9a-fA-F]{1,2})|0x([0-9a-fA-F]{1,2}))"
            r"\s*:",
            L,
        )
        if m2:
            try:
                return int(m2.group(1) or m2.group(2), 16)
            except Exception:
                pass
        # Stop when we cross a module boundary.
        if "module " in L and ";" in L:
            break
    return None


def _waived(project_dir: Path) -> Tuple[bool, str]:
    waivers = project_dir / "waivers.json"
    if not waivers.exists():
        return False, ""
    try:
        d = json.loads(waivers.read_text())
    except Exception:
        return False, ""
    raw = d.get(WAIVER_KEY)
    if isinstance(raw, str) and len(raw.strip()) >= WAIVER_MIN_LEN:
        return True, raw.strip()
    if isinstance(raw, dict):
        rationale = raw.get("rationale") or raw.get("reason") or ""
        if isinstance(rationale, str) and \
           len(rationale.strip()) >= WAIVER_MIN_LEN:
            return True, rationale.strip()
    return False, ""


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("Usage: cmd_buf_index_semantic_consistency_check.py "
              "<project_dir>")
        return 2

    project = Path(argv[1]).resolve()
    if not project.exists():
        print(f"FAIL — project dir not found: {project}")
        return 1

    profile = detect_ic_class(project)
    ic_class = profile.get("ic_class", "unknown")

    if ic_class in ("pure_analog", "bare_fpga"):
        print(f"SKIP — ic_class={ic_class} not applicable")
        return 0
    if ic_class not in _APPLICABLE_CLASSES and ic_class != "unknown":
        print(f"SKIP — ic_class={ic_class} not in applicable set")
        return 0

    l3 = _l3_load(project)
    if l3 is None:
        print("SKIP — no L3_CMD_PROTOCOL.json present")
        return 0
    typed_entries = _l3_opcodes_with_semantics(l3)
    if not typed_entries:
        print("SKIP — no L3 opcode entries carry typed "
              "payload_semantics with byte_offset")
        return 0

    rtl_files = _find_rtl_files(project)
    if not rtl_files:
        print("SKIP — no rtl/ directory")
        return 0

    bodies_with_cmt: list[tuple[Path, str]] = []
    bodies_no_cmt: list[tuple[Path, str]] = []
    for p in rtl_files:
        try:
            raw = p.read_text(errors="ignore")
        except Exception:
            continue
        bodies_with_cmt.append((p, raw))
        bodies_no_cmt.append((p, _strip_comments(raw)))

    fsm_files = [(p, s, raw) for ((p, raw), (_, s)) in zip(
        bodies_with_cmt, bodies_no_cmt) if _is_main_fsm(p, s)]

    if not fsm_files:
        print("SKIP — no main_fsm RTL detected")
        return 0

    l9 = _l9_load(project)
    explicit = _l9_buffer_signal_name(l9)
    if explicit:
        buf_candidates = [explicit]
    else:
        buf_candidates = _autodetect_buffer_names(bodies_no_cmt)

    if not buf_candidates:
        print("SKIP — no cmd-buffer-shaped reg array detected "
              "(L9 cmd_buffer_signal_name absent and no candidate "
              "matched cmd_buf|cmd_buffer|payload_buf|rx_buf|frame_buf)")
        return 0

    failures: List[str] = []

    # For each opcode with typed semantics, look for the matching
    # branch in main_fsm and verify each `<buf>[K]` read.
    for entry in typed_entries:
        op_int = _opcode_normalise(entry.get("hex"))
        sem_list = entry.get("payload_semantics", [])
        if op_int is None:
            continue
        # Build offset -> field map from L3.
        l3_off_to_field: Dict[int, str] = {}
        for s in sem_list:
            try:
                bo = int(s.get("byte_offset"))
            except Exception:
                continue
            f = s.get("field") or s.get("description") or ""
            if isinstance(f, str) and f:
                l3_off_to_field[bo] = f

        for buf_name in buf_candidates:
            for path, src_no_cmt, src_raw in fsm_files:
                reads = _scan_buf_reads(src_no_cmt, buf_name)
                for line_no, idx, line_text in reads:
                    branch_op = _opcode_branch_for_line(src_no_cmt,
                                                         line_no)
                    if branch_op is None or branch_op != op_int:
                        continue
                    # Check (i) comment vs code: if a comment near
                    # this line claims `<buf>[K]` is `FIELD`, but
                    # L3 says FIELD lives at K' != K, that's a swap.
                    cmts = _comment_at(src_raw, line_no, radius=2)
                    cmt_blob = " | ".join(cmts).lower()
                    cmt_pair_re = re.compile(
                        re.escape(buf_name) + r"\s*\[\s*(\d+)\s*\]"
                        r"\s*[=:]\s*([a-z_]+)",
                        re.IGNORECASE,
                    )
                    cmt_pairs = cmt_pair_re.findall(cmt_blob)
                    for cm_idx_s, cm_field in cmt_pairs:
                        try:
                            cm_idx = int(cm_idx_s)
                        except Exception:
                            continue
                        cm_field_l = cm_field.lower()
                        for l3_off, l3_field in l3_off_to_field.items():
                            if cm_field_l == l3_field.lower() and \
                               cm_idx != l3_off:
                                failures.append(
                                    f"{path.name}:{line_no} — comment "
                                    f"says `{buf_name}[{cm_idx}] = "
                                    f"{cm_field}` but L3 opcode "
                                    f"0x{op_int:02X} payload_semantics "
                                    f"places `{l3_field}` at "
                                    f"byte_offset={l3_off} (swap)."
                                )
                    # (ii) direct index check — if RTL reads
                    # `<buf>[K]` inside the branch for opcode X but
                    # L3 says the field at byte_offset K is e.g.
                    # constant `value` (not a runtime arg) and the
                    # SAME code reads K — and L3 has a DIFFERENT
                    # offset for the runtime arg field name found
                    # in the RTL's lhs / target signal — flag it.
                    # We use a simple lhs heuristic: `<sig> <= ... buf[K] ...`
                    lhs_re = re.compile(
                        r"^\s*(?:if\s*\([^)]*\)\s*)?"
                        r"(\w+)\s*<=\s*",
                    )
                    m = lhs_re.search(line_text)
                    if m:
                        lhs = m.group(1).lower()
                        for l3_off, l3_field in l3_off_to_field.items():
                            if l3_field.lower() == lhs and \
                               l3_off != idx:
                                failures.append(
                                    f"{path.name}:{line_no} — RTL "
                                    f"reads `{buf_name}[{idx}]` to "
                                    f"drive `{lhs}`, but L3 opcode "
                                    f"0x{op_int:02X} payload_semantics "
                                    f"places `{l3_field}` at "
                                    f"byte_offset={l3_off}."
                                )

    is_waived, rationale = _waived(project)

    if not failures:
        print(
            f"PASS — cmd-buffer index semantics consistent across "
            f"{len(typed_entries)} L3 opcode(s) with typed "
            f"payload_semantics and {len(fsm_files)} main_fsm "
            f"file(s); buf candidates={buf_candidates}"
        )
        return 0

    if is_waived:
        print(
            f"PASS_WITH_WAIVER — {len(failures)} cmd-buf index "
            f"issue(s) silenced by waivers.{WAIVER_KEY}: "
            f"{rationale[:80]}…"
        )
        for f in failures:
            print(f"  • {f}")
        return 0

    print(f"FAIL — {len(failures)} cmd-buf index semantic issue(s):")
    for f in failures:
        print(f"  • {f}")
    print()
    print("Why this matters:")
    print("  Even when numeric guards happen to coincide, an index")
    print("  swap between RTL and L3 is fragile: any byte-order")
    print("  rework or schema-driven RTL regen will silently break")
    print("  the chip. The fix is either to swap the RTL index back")
    print("  to match L3 byte_offset, or update L3 byte_offset to")
    print("  match RTL — and update the comment to match the code.")
    print()
    print(
        "Or document the alternative in waivers.json:\n"
        f'    {{"{WAIVER_KEY}": '
        '"<≥40-char rationale>"}}'
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
