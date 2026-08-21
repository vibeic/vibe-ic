#!/usr/bin/env python3
"""phase1_quality_parity_check.py — v0.50 gate

Enforces quantitative spec-floor minimums from the IC class template, so that
three pseudo-users (common / medium / high) end up with *similar quality*
L*.json documents rather than three different ICs.

Motivation (v0.49 3-persona <benchmark> benchmark, memory
project_v049_3persona_benchmark): when IC Expert Agent's common-persona input
was vague, the L*.json output ended up degenerate (4 opcodes / 32-byte OTP /
placeholder CRC) — it passed presence + schema checks but wasn't hardware-
ready. v0.50 introduces a `spec_floor` block in each class template; this
program verifies every L*.json meets that floor.

Usage:
    python3 phase1_quality_parity_check.py <generated_docs_dir>
        [--class-path <protocol-ic/cable-side-id-ic>]
        [--class-kb <path-to-class_kb-dir>]
        [--json <output-json>]
        [--strict]

Exit codes:
    0  — all floor metrics met
    1  — one or more floor metrics below minimum
    2  — input error (missing files, bad class path)
"""

from __future__ import annotations
import argparse, json, sys
from pathlib import Path

import _spec_floor_keys as _sfk   # noqa: E402  (re #495 Stage 0)
import _class_template_resolve as _ctr   # noqa: E402  (re #495 Stage 3)
from _class_template_resolve import resolve as resolve_class_template  # noqa: E402

try:
    import yaml
except ImportError:
    yaml = None


def load_yaml(path: Path):
    if yaml is None:
        # Minimal inline YAML parser sufficient for our class templates
        # (flat key: value + nested dicts/lists only). Fallback only.
        raise RuntimeError("PyYAML required; install with: pip install pyyaml")
    with path.open() as f:
        return yaml.safe_load(f)


def find_class_template(class_path: str, class_kb_dir: Path) -> tuple[dict, bool]:
    """Load class template yaml by name, searching class_kb/templates/.

    Returns ``(template, fallback_applied)``. ``fallback_applied`` is True when
    the requested ``class_path`` had no template of its own and a NEUTRAL
    generic floor was substituted.

    Fallback discipline (the fix for the unknown-class mis-scoring defect): an
    unknown class MUST NOT inherit a protocol-specific floor. The previous
    chain defaulted to ``cable-side-id-ic`` first, so any leaf not in the KB
    (an accelerator, a DSP block, a bridge …) was scored against SERIAL-ID-IC
    floors (opcode-count >= 8 / CRC-8 whitelist / 64-byte OTP) that do not
    apply to it. The chain falls back to ``generic-ic`` — a small
    CLASS-AGNOSTIC floor — and finally to the vacuous ``any-ic`` only if that
    neutral template is somehow absent. chip-AGNOSTIC.

    re #495 Stage 3 — that neutral fallback was ALSO catching the 20 class-tree
    nodes that have no template of their own, which is a different case with a
    real answer: in an inheritance tree, "no template" means "adds nothing
    beyond my parent". `generic-ic` is not any node's ancestor (it is not a node
    at all), so substituting it was applying a sibling's floor, silently, and
    not even consistently in one direction — LOOSER than the taxonomy for
    `hash-function` / `spi-peripheral` / `i2c-peripheral` / `protocol-bridge`
    (2 floor keys instead of 7-10) and STRICTER for `dsp-block` /
    `analog-mixed-ic` / `debug-block` and the other digital-ic children (whose
    ancestors carry NO floor at all). Resolution now goes own -> nearest
    templated ANCESTOR -> neutral, matching what
    `gap_detect._spec_floor_from_chain` has always done, and `fallback_applied`
    keeps meaning only the genuine unknown-class case."""
    templates_dir = class_kb_dir / "templates"
    if not templates_dir.exists():
        raise FileNotFoundError(f"class_kb/templates not found at {templates_dir}")
    r = resolve_class_template(class_path, class_kb_dir)
    if r["template"] is None:
        raise FileNotFoundError(f"no class template found for {class_path}")
    # `fallback_applied` keeps its original meaning — "an unknown class was
    # given a NEUTRAL floor" — and therefore stays False for the inheritance
    # case added in #495 Stage 3, which is not a fallback but the tree's own
    # answer. `check()` reports the inheritance separately.
    return r["template"], r["how"] == _ctr.NEUTRAL


def load_layer(docs_dir: Path, layer: str) -> dict | None:
    # L1_DATASHEET.json etc.  accept any filename starting with the layer code
    for f in docs_dir.glob(f"{layer}*.json"):
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    return None


def count_opcodes(l3: dict) -> int:
    """Count distinct opcodes in L3_CMD_PROTOCOL."""
    if not l3:
        return 0
    # common shapes: {"commands": [{"opcode": ...}]}, {"opcodes": [...]}, {"accepted_commands": [...]}
    for key in ("commands", "opcodes", "accepted_commands", "cmd_table"):
        v = l3.get(key)
        if isinstance(v, list):
            return len(v)
        if isinstance(v, dict):
            return len(v)
    return 0


def extract_crc_poly(l3: dict) -> str | None:
    """Find the CRC polynomial string.

    re #495 Stage 0 — the incumbent read was ``{crc,crc8,crc_config}.{poly,
    polynomial}``, none of which any producer writes: the doc-extraction
    producers emit ``crc.poly_hex`` and ``crc_parameters.polynomial_hex``.
    The incumbent container/field order is preserved and the producer
    spellings appended, so a doc that does carry ``crc.poly`` still resolves
    to exactly the same value."""
    if not l3:
        return None
    for key in _sfk.L3_CRC_CONTAINER_KEYS:
        p = _sfk.first_crc_poly(l3.get(key))
        if p:
            # normalise — accept "0x31", "0x07", "0x8c" mirror-of-0x31
            return p
    # Also check nested under frame_format etc.
    ff = l3.get("frame_format")
    if isinstance(ff, dict):
        return _sfk.first_crc_poly(ff.get("crc"))
    return None


def count_otp_bytes(l4: dict) -> int:
    """Count OTP bytes from L4_REGMAP."""
    if not l4:
        return 0
    for key in ("otp_map_128x8", "otp_map", "otp", "otp_layout"):
        v = l4.get(key)
        if isinstance(v, list):
            return len(v)
        if isinstance(v, dict):
            # e.g. {size_bytes: 128} or {bytes: 128}
            for sk in ("size_bytes", "bytes", "byte_count"):
                if sk in v and isinstance(v[sk], int):
                    return v[sk]
            return len(v)
    return 0


def count_regmap_regs(l4: dict) -> int:
    if not l4:
        return 0
    for key in ("registers", "regmap", "register_map", "runtime_registers"):
        v = l4.get(key)
        if isinstance(v, list):
            return len(v)
        if isinstance(v, dict):
            return len(v)
    return 0


def count_submodules(l6: dict, l9: dict) -> (int, set):
    """Prefer L9 submodule list; fall back to L6 keys."""
    names = set()
    if l9 and isinstance(l9.get("submodules"), (list, dict)):
        subs = l9["submodules"]
        if isinstance(subs, list):
            for s in subs:
                if isinstance(s, str):
                    names.add(s.lower())
                elif isinstance(s, dict):
                    for k in ("name", "module", "instance"):
                        if k in s:
                            names.add(str(s[k]).lower())
                            break
        elif isinstance(subs, dict):
            names.update(k.lower() for k in subs)
    if not names and l6 and isinstance(l6.get("submodule_control_logic"), dict):
        names.update(k.lower() for k in l6["submodule_control_logic"])
    return len(names), names


def count_l9_ports(l9: dict) -> int:
    """Return the number of top-level (chip-boundary) ports declared in L9.

    The orchestrator schema (phase1-orchestrate/SKILL.md) puts ports under
    `dtop_top_level.ports`, but earlier handwritten L9 docs used
    `top_level_ports` / `ports` / `dtop_ports` at the JSON root. v0.56
    descends into the orchestrator-mandated nested location too, so the
    floor check actually fires (regression caught by B1 multi-IC run —
    prior version always returned 0 for orchestrator-shaped L9 docs).

    re #495 Stage 0: the root-key list read only the LEGACY mirror ``ports``
    and missed ``top_ports`` — the CANONICAL spelling per #490, which the L9
    emitter writes alongside ``ports`` / ``top_module_pins`` and which every
    other port consumer in the tree reads first. Selection is now
    first-NON-EMPTY rather than first-PRESENT, so an empty ``ports: []`` can
    no longer shadow a populated ``top_ports``."""
    if not l9:
        return 0
    # Nested orchestrator locations (preferred — current schema)
    for parent_key in _sfk.L9_TOP_PORT_NESTED_PARENT_KEYS:
        parent = l9.get(parent_key)
        _sub, v = _sfk.first_nonempty(parent, _sfk.L9_TOP_PORT_NESTED_SUB_KEYS)
        if isinstance(v, (list, dict)):
            return len(v)
    # Root-level keys (legacy spellings first, canonical + mirrors appended)
    _key, v = _sfk.first_nonempty(l9, _sfk.L9_TOP_PORT_ROOT_KEYS)
    if isinstance(v, (list, dict)):
        return len(v)
    return 0


def count_l9_wires(l9: dict) -> int:
    if not l9:
        return 0
    for key in ("internal_wires", "wires", "nets"):
        v = l9.get(key)
        if isinstance(v, list):
            return len(v)
        if isinstance(v, dict):
            return len(v)
    return 0


def check(docs_dir: Path, class_kb: Path, class_path: str) -> dict:
    # One resolution, reused: `how` drives the disclosures below, and
    # `fallback_applied` keeps its original narrow meaning (unknown class ->
    # NEUTRAL floor) so the incumbent `unknown_class_generic_floor` warning is
    # unchanged. re #495 Stage 3.
    _res = resolve_class_template(class_path, class_kb)
    if _res["template"] is None:
        raise FileNotFoundError(f"no class template found for {class_path}")
    tpl = _res["template"]
    fallback_applied = _res["how"] == _ctr.NEUTRAL
    floor = (tpl or {}).get("spec_floor") or {}

    l3 = load_layer(docs_dir, "L3")
    l4 = load_layer(docs_dir, "L4")
    l6 = load_layer(docs_dir, "L6")
    l9 = load_layer(docs_dir, "L9")

    findings = []
    measured = {}

    # v0.56: L3 no-protocol sentinel (added to support memory-access /
    # register-pointer / analog-front-end ICs whose L3 is not a command
    # protocol). When `protocol_present: false`, every L3-floor check
    # is skipped — opcode-count and CRC-poly are meaningless concepts
    # for these IC classes. Records the sentinel in `measured` so the
    # report shows the skip was intentional.
    l3_no_protocol = bool(l3 and l3.get("protocol_present") is False)
    if l3_no_protocol:
        measured["L3_protocol_present"] = False
        measured["L3_no_protocol_reason"] = l3.get("reason", "")

    # ---- L3 opcode count ----
    min_op = floor.get("L3_opcode_count_min")
    if min_op is not None and not l3_no_protocol:
        n = count_opcodes(l3)
        measured["L3_opcode_count"] = n
        if n < min_op:
            findings.append({
                "severity": "FAIL",
                "rule": "L3_opcode_count_min",
                "floor": min_op, "actual": n,
                "message": f"L3 opcode count {n} below class floor {min_op}"
            })

    # ---- L3 CRC poly allowed ----
    allowed = floor.get("L3_crc_poly_allowed")
    if allowed and not l3_no_protocol:
        p = extract_crc_poly(l3)
        measured["L3_crc_poly"] = p
        if p and p not in [str(x).lower() for x in allowed]:
            findings.append({
                "severity": "FAIL",
                "rule": "L3_crc_poly_allowed",
                "floor": allowed, "actual": p,
                "message": f"L3 CRC poly {p} not in class-allowed set {allowed}"
            })
        elif not p:
            findings.append({
                "severity": "FAIL",
                "rule": "L3_crc_poly_allowed",
                "floor": allowed, "actual": None,
                "message": "L3 CRC poly not found"
            })

    # ---- L4 OTP bytes ----
    min_otp = floor.get("L4_otp_bytes_min")
    if min_otp is not None:
        n = count_otp_bytes(l4)
        measured["L4_otp_bytes"] = n
        if n < min_otp:
            findings.append({
                "severity": "FAIL",
                "rule": "L4_otp_bytes_min",
                "floor": min_otp, "actual": n,
                "message": f"L4 OTP bytes {n} below class floor {min_otp}"
            })

    # ---- L4 regmap ----
    min_reg = floor.get("L4_regmap_reg_count_min")
    if min_reg is not None:
        n = count_regmap_regs(l4)
        measured["L4_regmap_reg_count"] = n
        if n < min_reg:
            findings.append({
                "severity": "FAIL",
                "rule": "L4_regmap_reg_count_min",
                "floor": min_reg, "actual": n,
                "message": f"L4 register count {n} below class floor {min_reg}"
            })

    # ---- L6 submodules ----
    min_sub = floor.get("L6_submodule_count_min")
    req_sub = floor.get("L6_required_submodules") or []
    sub_count, sub_names = count_submodules(l6, l9)
    measured["L6_submodule_count"] = sub_count
    if min_sub is not None and sub_count < min_sub:
        findings.append({
            "severity": "FAIL",
            "rule": "L6_submodule_count_min",
            "floor": min_sub, "actual": sub_count,
            "message": f"L6 submodule count {sub_count} below class floor {min_sub}"
        })
    if req_sub:
        # Fuzzy match — instance names like `u_pad_ctrl` should match class
        # name `pad_ctrl`. Strip leading "u_" / "i_" / "inst_" and compare.
        def _canon(n):
            n = n.lower()
            for p in ("u_", "i_", "inst_", "m_"):
                if n.startswith(p):
                    n = n[len(p):]
                    break
            return n
        canon = {_canon(x) for x in sub_names}
        canon |= {x.lower() for x in sub_names}   # also keep raw
        missing = [r for r in req_sub if r.lower() not in canon]
        measured["L6_missing_required"] = missing
        if missing:
            findings.append({
                "severity": "FAIL",
                "rule": "L6_required_submodules",
                "floor": req_sub, "actual": sorted(sub_names),
                "message": f"L6 missing required submodules: {missing}"
            })

    # ---- L9 ports / wires ----
    min_ports = floor.get("L9_top_level_port_count_min")
    if min_ports is not None:
        n = count_l9_ports(l9)
        measured["L9_top_level_port_count"] = n
        if n < min_ports:
            findings.append({
                "severity": "FAIL",
                "rule": "L9_top_level_port_count_min",
                "floor": min_ports, "actual": n,
                "message": f"L9 top-level port count {n} below floor {min_ports}"
            })

    min_wires = floor.get("L9_internal_wire_count_min")
    if min_wires is not None:
        n = count_l9_wires(l9)
        measured["L9_internal_wire_count"] = n
        if n < min_wires:
            findings.append({
                "severity": "FAIL",
                "rule": "L9_internal_wire_count_min",
                "floor": min_wires, "actual": n,
                "message": f"L9 internal wire count {n} below floor {min_wires}"
            })

    # v0.56: WARN when the chosen class template has no spec_floor at all,
    # so a vacuous PASS doesn't masquerade as real validation. The four
    # silent templates flagged by B1 (memory-controller / protocol-ic /
    # apb-peripheral / uart-peripheral) are filled in v0.56 A2; this
    # warning catches any future template that ships without a floor.
    warnings = []
    # Unknown class → a NEUTRAL generic floor was substituted. Surface this so
    # a human sees the score is class-agnostic (not a protocol/memory/crypto
    # floor mis-applied to an unrelated design).
    if fallback_applied:
        warnings.append({
            "severity": "WARN",
            "rule": "unknown_class_generic_floor",
            "class_path": class_path,
            "template_used": str(tpl.get("class") if tpl else "any-ic"),
            "message": (f"class `{class_path}` has no template in the class KB; "
                        f"a NEUTRAL generic floor "
                        f"(`{tpl.get('class') if tpl else 'any-ic'}`) was applied "
                        "instead of a protocol-specific one. Add a dedicated "
                        "class template if this IC needs tighter floors."),
        })
    # re #495 Stage 3 — when the floor came from an ANCESTOR rather than the
    # class's own template, say so. This is the case that used to be silently
    # served a sibling orphan's floor; naming it is what stops a template-less
    # node from "reading as success". Disclosure only — no finding is added.
    if _res["how"] == _ctr.INHERITED:
        warnings.append({
            "severity": "WARN",
            "rule": "class_floor_inherited_from_ancestor",
            "class_path": class_path,
            "template_used": _res["used"],
            "message": (
                f"class `{class_path}` is a class-tree node with no template of "
                f"its own, so the floor was INHERITED from its nearest "
                f"templated ancestor `{_res['used']}` — the same walk "
                f"gap_detect._spec_floor_from_chain performs. Before #495 "
                f"Stage 3 this case was served the `generic-ic` floor instead, "
                f"which is not an ancestor of any node. Give "
                f"`{class_path}` its own template if it needs a tighter "
                f"floor than `{_res['used']}`."),
        })
    # re #495 Stage 2 — a class_path written in the REGISTRY taxonomy cannot be
    # resolved by the class-tree taxonomy: the two share no names. Until now
    # that mismatch was silent — the class simply fell through to the neutral
    # floor above and nothing said why. Each registry entry now declares which
    # tree node it belongs to and what that declaration is worth, so say it.
    # This is DISCLOSURE ONLY: `findings` is untouched, so no verdict moves.
    # The mapping is deliberately NOT applied here — measured over the corpus,
    # applying it adds 21 findings of which 0 are defects (11 sit on floors no
    # doc-set can satisfy, 10 on fields the document explicitly declares absent
    # from its source). Applying it is gated on the floors first learning to
    # read the honest-absence sentinels the producers already emit.
    if fallback_applied:
        try:
            from ic_class_profile import class_tree_node_for as _ctn
            m = _ctn(class_path)
        except Exception:
            m = None
        if m and m.get("registry_matched"):
            warnings.append({
                "severity": "WARN",
                "rule": "registry_class_not_in_class_tree",
                "class_path": class_path,
                "class_tree_node": m.get("node"),
                "class_tree_node_status": m.get("status"),
                "message": (
                    f"`{class_path}` is a name from programs/"
                    f"ic_class_registry.json, which shares no names with "
                    f"agents/class_kb/class-tree.yaml, so the class tree could "
                    f"not resolve it and the neutral floor above was used "
                    f"instead. The registry declares its tree node as "
                    f"{m.get('node')!r} (status "
                    f"{m.get('status')!r}); that declaration is recorded, not "
                    f"applied. Basis: {m.get('basis')}"),
            })
    if tpl is not None and not floor:
        warnings.append({
            "severity": "WARN",
            "rule": "vacuous_pass_no_spec_floor",
            "class_path": class_path,
            "message": (f"class template `{class_path}` has no `spec_floor:` "
                        "block; this run is a vacuous PASS (no floors "
                        "to check). Either pick a more specific class "
                        "or add a spec_floor block to the template."),
        })

    return {
        "class_path": class_path,
        "template_used": str(tpl.get("class") if tpl else class_path),
        "spec_floor_present": bool(floor),
        "measured": measured,
        "findings": findings,
        "warnings": warnings,
        "pass": len(findings) == 0,
    }


def _resolve_class_path_from_l1(docs_dir: Path) -> str | None:
    """Mirror layer_extension_presence_check.main() — reads
    L1_DATASHEET.json's `class_path` field, returns the leaf segment
    of a `parent > child > leaf` chain, lower-cased. Returns None if
    L1 is missing / unparseable / has no class_path field. Lenient
    JSON loading (tolerates 0xNN literals)."""
    l1 = docs_dir / "L1_DATASHEET.json"
    if not l1.exists():
        return None
    try:
        text = l1.read_text()
        import re as _re
        text_fixed = _re.sub(
            r'(?P<p>[:\[\,\s])0x([0-9a-fA-F]+)',
            lambda m: m.group("p") + str(int(m.group(2), 16)),
            text,
        )
        l1_data = json.loads(text_fixed)
    except Exception:
        return None
    cp = l1_data.get("class_path", "")
    if not (isinstance(cp, str) and cp.strip()):
        return None
    return cp.split(">")[-1].strip().lower()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("docs_dir")
    # v0.56: --class-path is now an explicit OVERRIDE; default behaviour
    # is to auto-resolve from L1_DATASHEET.json's class_path field
    # (mirroring layer_extension_presence_check). Final fallback to
    # 'any-ic'. Earlier behaviour ("default cable-side-id-ic") was the
    # single biggest <chip-class>-overfit bug per the v0.55 multi-IC validation.
    ap.add_argument("--class-path", default=None,
                    help="Override class. When omitted, auto-resolves from "
                         "L1_DATASHEET.json's class_path field; final "
                         "fallback to 'any-ic'.")
    ap.add_argument("--class-kb", default=None,
                    help="path to plugins/vibe-ic/agents/class_kb (autodetected if omitted)")
    ap.add_argument("--json", default=None, help="output JSON report path")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on any floor miss (default behaviour)")
    args = ap.parse_args()

    docs_dir = Path(args.docs_dir)
    if not docs_dir.exists():
        print(f"ERROR: docs_dir {docs_dir} does not exist", file=sys.stderr)
        return 2

    if args.class_kb:
        class_kb = Path(args.class_kb)
    else:
        # Wave 82: the former second plugin merged into vibe-ic.
        # Probe in order: vibe-ic/agents/class_kb (current),
        # then legacy vibe-ic/agents/class_kb.
        here = Path(__file__).resolve().parent
        candidates = [
            here.parent / "agents" / "class_kb",                       # vibe-ic
            here.parent.parent / "vibe-ic" / "agents" / "class_kb",  # legacy
        ]
        class_kb = next(
            (c for c in candidates if c.exists()), candidates[0]
        )
    if not class_kb.exists():
        print(f"ERROR: class_kb {class_kb} does not exist", file=sys.stderr)
        return 2

    # Resolve class_path
    class_path = args.class_path
    if not class_path:
        class_path = _resolve_class_path_from_l1(docs_dir) or "any-ic"

    result = check(docs_dir, class_kb, class_path)

    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))

    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
