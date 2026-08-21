#!/usr/bin/env python3
"""l9_rtl_pin_consistency_check.py — Wave 79 cross-layer integrity gate.

Verifies that the L9 integration spec's `top_level_ports[]` and the
RTL top-module port list agree on:

  - Pin-set membership (every L9 pin appears in RTL top, and vice versa).
  - Direction (`input` / `output` / `inout`) matches per pin.

Why this gate exists
====================
Wave 47-49 fresh-agent runs repeatedly produced an L9 declaring N
top-level pins, then generated RTL whose top module either dropped a
pin (e.g., `bor_trip` declared in L9 but missing from the top module)
or had its direction mismatched (e.g., `id_bus_tx_en` declared `output`
in L9 but `inout` in RTL because the agent chose to merge tristate).

Mid-flow consequences:
  - QSF/SDC generators (`qsf_gen` / `sdc_gen`) read
    L9 and emit pin assignments for pins that don't exist in synth →
    Quartus warns, agent ignores, hardware silently floats.
  - Reverse case: an RTL port not in L9 means no pin assignment → the
    pin gets defaulted to a random FPGA pin → demonstrably random
    bench failures.

This gate runs ONLY when both L9 + RTL are present. It SKIPs cleanly
when either is missing — that's a different gate's job (e.g. L9
presence is checked by L9_INTEGRATION_SPEC presence gates; RTL
existence is checked by Phase 2 structural gates).

Open-drain handling
===================
When L9 marks a pin `open_drain: true`, this gate does NOT inspect
the QSF/SDC; that contract is owned by `aid_class_qsf_gen.py`. We
only verify the L9 schema field is well-formed (boolean) so the
downstream generator has the data it needs.

Detection (chip-AGNOSTIC)
=========================
1. Find L9_*.json under <project>/generated_docs/. SKIP when none.
2. Extract top_level_ports[] (also accept legacy keys
   `top_module_pins`, `dtop_top_level.ports`).
3. Find the RTL top module file under phase2/stage1/rtl/. Heuristics
   (in order, first match wins):
     - L9.top_module / L9.top / L9.dtop  (schema v2 canonical)
     - L9.dtop_top_level.module_name (schema v1)
     - L9.dtop_module_name (schema v1)
     - <ic_name>_dtop.sv / <ic_name>.sv (best-effort name guess)
     - content scan: any rtl/*.sv|.v containing `module <top>`
   SKIP when no rtl file matches.
4. Parse the RTL top module's port list (via the same regex
   `extract_top_ports` style as `fpga_top_pin_completeness_check.py`,
   but capturing direction tokens too).
5. Cross-check membership both ways + direction agreement.

Honors waiver `l9_rtl_pin_consistency_intentional` (≥40 chars).

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
from typing import Optional
import _path_layout as _pl

WAIVER_KEY = "l9_rtl_pin_consistency_intentional"
WAIVER_MIN_LEN = 40

_DIR_NORMALIZE = {
    "input": "input",
    "in": "input",
    "i": "input",
    "output": "output",
    "out": "output",
    "o": "output",
    "inout": "inout",
    "io": "inout",
    "bidir": "inout",
}


# Wave 82 Fix G — debug / scan / testbench-only port allowlist.
# When a port name matches one of these patterns, the port is treated
# as RTL-only (it is a debug or test hook that legitimately should NOT
# appear in the L9 production pin contract). Any port NOT matching one
# of these patterns must still appear in L9, otherwise it is a real
# pin-set discrepancy.
_DEBUG_PORT_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in [
        r"^debug_",
        r"_debug$",
        r"_dbg_",
        r"_dbg$",
        r"^dbg_",
        r"^scan_",
        r"_scan$",
        r"^tb_",
        r"_tb$",
        r"^test_",
        r"^observation_",
        r"^probe_",
    ]
)


def _is_debug_port(name: str) -> bool:
    """Return True when the port name matches a debug/scan/tb-only
    naming pattern and may legitimately be omitted from L9."""
    return any(p.search(name) for p in _DEBUG_PORT_PATTERNS)


# v1.6.85 (#17 Bug B) — implicit pins that every chip carries by
# convention but L9 frequently doesn't enumerate (because they're
# obvious / always-required infrastructure ports). Whitelisting them
# from BOTH sides of the diff prevents false-FAIL when L9 omits clk
# / reset_n while RTL declares them, or vice-versa. Chip-AGNOSTIC.
#
# ORGANIC-20260606 #491 (b) — widened from an EXACT-name set to a
# NAME-PATTERN set. The exact set `{"clk", "reset_n"}` only stripped
# those two literal spellings, so when L9 carries `i_clk`/`rst_n` but
# the RTL emitter (or the AID-class canonical-pin augment) declares the
# OTHER conventional spelling (`clk`/`reset`), the asymmetric pair
# survived the strip and produced a false "RTL has ports not in L9" /
# "L9 declares pins missing from RTL" FAIL. The pattern set now covers
# the common infra-port spellings on BOTH the clock and reset families:
#
#   clock:  clk, i_clk, o_clk, clk_i, clock, sys_clk, core_clk, …
#           (a `clk`/`clock` segment, with an optional i_/o_ direction
#            prefix, an optional `_i`/`_o` suffix, and optional descriptive
#            qualifier segments — `sys_clk`, `core_clk`, `clk_i`)
#   reset:  rst, i_rst, rst_n, reset, reset_n, i_reset_n, por_rst_n, …
#           (a `rst`/`reset`/`por` segment, optional i_/o_ prefix,
#            optional active-low `_n`/`n` suffix, optional qualifiers)
#
# GPIO is DELIBERATELY NOT whitelisted here — per the issue, GPIO must
# come from the L3 pin table (the promoter already extracts every
# direction-bearing table row, verified end-to-end), not from a gate-side
# convenience whitelist that would mask a genuinely-dropped GPIO pin.
# Chip-AGNOSTIC: pure naming-convention SHAPE; no chip/vendor literal.
_IMPLICIT_PIN_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in [
        # clock family: optional i_/o_ prefix, a clk/clock segment
        # (optionally qualified, e.g. sys_clk / core_clk), optional
        # _i/_o direction suffix, optional trailing digits.
        r"^(?:[io]_)?(?:[a-z][a-z0-9]*_)*"
        r"(?:clk|clock)(?:_[io])?\d*$",
        # reset family: optional i_/o_ prefix, a rst/reset/por segment
        # (optionally qualified, e.g. por_rst / soft_reset), optional
        # active-low _n / n suffix, optional _i/_o direction suffix.
        # ORGANIC #659 round-2 — the direction suffix's leading underscore
        # is OPTIONAL so a GLUED active-low+direction spelling matches
        # (`rst_ni` = `_n` + `i`, `rst_no` = `_n` + `o`) — the near-universal
        # OpenTitan / comportable reset name that otherwise survived the
        # strip as an RTL-only false-FAIL. Still stem-gated on rst/reset/por,
        # so a non-reset port never matches (no leak).
        r"^(?:[io]_)?(?:[a-z][a-z0-9]*_)*"
        r"(?:rst|reset|por)(?:_?n)?(?:_?[io])?\d*$",
    ]
)


def _is_implicit_pin(name: str) -> bool:
    """ORGANIC #491 (b) — True iff `name` matches a conventional
    implicit infra-port (clock / reset) spelling that L9 frequently
    does not enumerate. Pattern-on-SHAPE, chip-AGNOSTIC."""
    if not isinstance(name, str) or not name:
        return False
    return any(p.match(name) for p in _IMPLICIT_PIN_PATTERNS)


# ─── ORGANIC #659 — reused-IP struct-flatten reconciliation ────────
# A catalog-glue / reused-IP wrapper (phase2/stage1/rtl/SOURCE_MANIFEST.json
# with reused_ip=true) legitimately diverges from the L9 production pin
# contract in TWO chip-AGNOSTIC ways:
#
#   (a) Struct-bus prefix-expansion. L9 declares a struct-typed bus port
#       by its ROOT name `X` (e.g. a packed interface), but the chip_top
#       flattens it into prefix-expanded scalar pads `X_a_*` / `X_d_*` /
#       `X_*`. The L9 root then reads as "missing from RTL" and every
#       expanded pad reads as "RTL has a port not in L9" — neither is a
#       real mismatch.
#   (b) Documented tie-offs. The manifest documents struct interfaces it
#       drives to a constant internally (no pad). L9 still lists the
#       interface root, but the chip_top has no matching pad — an
#       INTENTIONAL omission, not a dropped pin.
#
# Reconciliation is chip-AGNOSTIC: it keys ONLY on the SOURCE_MANIFEST
# structure (reused_ip flag + tie-off declarations) and the name-prefix
# SHAPE of the expanded pads — never on a bus/vendor literal. A non-
# reused-IP design (no manifest / reused_ip != true) gets NO relaxation,
# so a genuine pin mismatch there still FAILs. A reused-IP design whose
# L9-only pin is neither tied-off nor prefix-covered ALSO still FAILs.

# The manifest may document its intentionally-omitted (tied-off /
# internally-driven) struct interfaces under any of these list/dict keys.
# All are deduped into one name set. Chip-AGNOSTIC: structure-only.
_MANIFEST_TIEOFF_KEYS = (
    "tie_offs",
    "tied_interfaces",
    "tied_off",
    "tie_off",
)
# The manifest may ALSO explicitly declare which L9 roots are flattened
# into prefix-expanded pads. When present this is authoritative; when
# absent we fall back to pure name-prefix-shape coverage detection.
_MANIFEST_FLATTEN_KEYS = (
    "flattened_buses",
    "flattened_interfaces",
    "flattened",
)
# ORGANIC #712 — a reused-IP wrapper may authoritatively expose struct-flattened
# IP OUTPUTS that L9 lacks ENTIRELY (no L9 root to prefix-expand from, e.g.
# alert_fatal_o / alert_recov_o assigned from an alert_tx struct). The manifest
# declares the exact RTL output names under any of these keys.
_MANIFEST_EXPOSED_OUTPUT_KEYS = (
    "wrapper_exposed_outputs",
    "flattened_outputs",
    "exposed_outputs",
)
# ORGANIC #711 — a catalog-pulled top may declare spec-permitted RENAMED
# interface sub-ports whose L9 'typical/illustrative' names differ from the RTL
# split names (a rename is NOT a prefix, so prefix-expansion cannot reconcile).
# The manifest pairs them under one of these keys, each entry a dict with
# `l9`/`rtl` (or `from`/`to`, `typical`/`actual`) NAME LISTS.
_MANIFEST_RENAME_KEYS = (
    "renamed_interfaces",
    "renamed_buses",
    "interface_renames",
)


def _manifest_renamed_groups(manifest: dict) -> list:
    """ORGANIC #711 — list of (l9_name_set, rtl_name_set) declared in the
    manifest's renamed-interface key(s). Each entry pairs an L9 illustrative
    interface group with its renamed RTL group. Chip-AGNOSTIC: structure-only,
    no chip/vendor literal."""
    out: list = []
    if not isinstance(manifest, dict):
        return out
    for key in _MANIFEST_RENAME_KEYS:
        v = manifest.get(key)
        if not isinstance(v, list):
            continue
        for entry in v:
            if not isinstance(entry, dict):
                continue
            l9v = (entry.get("l9") or entry.get("from")
                   or entry.get("typical") or entry.get("illustrative"))
            rtlv = (entry.get("rtl") or entry.get("to")
                    or entry.get("actual") or entry.get("renamed"))
            l9_set = {s.strip() for s in l9v
                      if isinstance(s, str) and s.strip()} \
                if isinstance(l9v, list) else set()
            rtl_set = {s.strip() for s in rtlv
                       if isinstance(s, str) and s.strip()} \
                if isinstance(rtlv, list) else set()
            if l9_set or rtl_set:
                out.append((l9_set, rtl_set))
    return out


def _manifest_name_set(manifest: dict, keys: tuple[str, ...]) -> set:
    """Collect interface/port names from any of `keys` in the manifest.

    Tolerates each value being a list of strings, a list of dicts (each
    carrying a `name`/`port`/`interface`/`root` field), or a dict whose
    KEYS are the interface names. Chip-AGNOSTIC: structure-only, no
    literal. Returns a set of stripped names.

    ORGANIC #775 (+ Step-2.7 r2) — ALSO accepts the documented `{l9, rtl}` dict
    schema (the same shape `flattened_buses` / `flattened_outputs` carry in
    `catalog-glue-author/SKILL.md`, parsed for `renamed_interfaces` by
    `_manifest_renamed_groups`). A manifest authored EXACTLY per the docs
    previously yielded an empty set here (silent no-op) → false chip_top pin
    hard-FAIL. The {l9,rtl} expansion is CONSUMER-AWARE — the two consumers key
    on DIFFERENT name families, so folding both into one set is a §4.05 leak
    (an L9-root name colliding with an RTL pad, or vice-versa, would wave a
    genuine mismatch through):
      - `_MANIFEST_FLATTEN_KEYS` (`dict_family='l9'`) keys on the L9 ROOT
        (`root in declared_flatten`) → take ONLY the `l9` name(s).
      - `_MANIFEST_EXPOSED_OUTPUT_KEYS` (`dict_family='rtl'`) keys on the RTL
        PAD (`p in exposed`) → take ONLY the `rtl` wire name(s).
    Each of `l9`/`rtl` may be a bare string or a list of strings.
    Chip-AGNOSTIC: structure-only ({l9,rtl} grammar), no chip/vendor literal."""
    # which family of a {l9,rtl} entry this consumer wants (None ⇒ neither).
    dict_family = None
    if keys is _MANIFEST_FLATTEN_KEYS:
        dict_family = "l9"
    elif keys is _MANIFEST_EXPOSED_OUTPUT_KEYS:
        dict_family = "rtl"

    def _add_str_or_list(val) -> None:
        if isinstance(val, str) and val.strip():
            out.add(val.strip())
        elif isinstance(val, list):
            for s in val:
                if isinstance(s, str) and s.strip():
                    out.add(s.strip())

    out: set = set()
    if not isinstance(manifest, dict):
        return out
    for key in keys:
        v = manifest.get(key)
        if isinstance(v, dict):
            for name in v.keys():
                if isinstance(name, str) and name.strip():
                    out.add(name.strip())
        elif isinstance(v, list):
            for entry in v:
                if isinstance(entry, str) and entry.strip():
                    out.add(entry.strip())
                elif isinstance(entry, dict):
                    nm = (entry.get("name") or entry.get("port")
                          or entry.get("interface") or entry.get("root"))
                    if isinstance(nm, str) and nm.strip():
                        out.add(nm.strip())
                    # ORGANIC #775 r2 — documented {l9, rtl} dict schema,
                    # CONSUMER-AWARE: take ONLY this consumer's name family so an
                    # L9 root and an RTL pad never cross-contaminate.
                    if dict_family is not None:
                        _add_str_or_list(entry.get(dict_family))
    return out


def load_source_manifest(project: Path) -> Optional[dict]:
    """ORGANIC #659 — return phase2/stage1/rtl/SOURCE_MANIFEST.json's
    parsed dict ONLY when it exists AND declares reused_ip truthily.

    Returns None when the manifest is absent, unparseable, or does not
    assert reused_ip=true — in EVERY such case the gate keeps its exact-
    name comparison with NO reused-IP relaxation (no-leak). Chip-AGNOSTIC:
    pure file read + boolean flag, no chip/vendor literal."""
    mf = _pl.rtl_dir(project) / "SOURCE_MANIFEST.json"
    if not mf.is_file():
        return None
    try:
        data = json.loads(mf.read_text())
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if data.get("reused_ip") is not True:
        return None
    return data


# ORGANIC #659 round-2 — structural tie-off detection. The manifest tie_offs
# dict is NOT guaranteed exhaustive: a catalog-glue wrapper may wire an L9
# interface to a constant / another port / an unused net INTERNALLY (e.g.
# `.clk_edn_i(clk_i)`, `.edn_o(edn_req_unused)`) without listing it in the
# manifest. Such an interface is a legitimate internal-drive, not a dropped
# pin — but it has no chip_top PAD, so it reads as an L9-only mismatch. The
# proof that it is intentional is STRUCTURAL: the chip_top instantiation BINDS
# the interface (or its IP-split direction children `<root>_i`/`<root>_o`/
# `<root>_*`) to something. chip-AGNOSTIC: matches the SystemVerilog named-
# port-connection grammar `.<ident>(...)`, no chip/vendor literal.
_RE_PORT_BINDING = re.compile(r"\.\s*([A-Za-z_]\w*)\s*\(")


def _chip_top_bound_ports(rtl_top: Path) -> set:
    """ORGANIC #659 round-2 — the set of port names the chip_top file BINDS in
    a module instantiation (`.<name>(<net>)`). A residual L9-only root that
    appears here (directly, or via a `<root>_`-prefixed IP-split child) is
    driven/tied internally by the glue — an intentional internal-drive, not a
    dropped pad. Returns an empty set on any read error (→ no relaxation)."""
    try:
        text = rtl_top.read_text(errors="ignore")
    except Exception:
        return set()
    return set(_RE_PORT_BINDING.findall(text))


def _is_structurally_bound(root: str, bound_ports: set) -> bool:
    """True iff `root` (or an IP-split child `root_*`) is bound in the chip_top
    instantiation — structural proof the interface is internally driven."""
    if not bound_ports:
        return False
    if root in bound_ports:
        return True
    pre = root + "_"
    return any(b.startswith(pre) for b in bound_ports)


# ── ORGANIC #781 — reused-IP CONFIG-VARIANT surface reconciliation ──────────
# A catalog-glue / reused-IP wrapper faithfully instantiates a SPECIFIC
# configured vendor module (e.g. `ibex_core` for the 'small' Ibex config,
# `aes_wrap` for the flat-scalar AES integration) and passes that module's
# REAL ports through to chip_top 1:1. The L9 integration spec, however, is
# extracted from the input datasheet/docs and frequently describes a DIFFERENT
# (fuller / more-secure / struct-typed) variant of the same IP — `ibex_top`
# (SecureIbex lockstep + shadow buses + memory-integrity + crash-dump), or the
# full comportable `aes` (TL-UL + EDN + keymgr + lifecycle struct interfaces).
#
# The resulting diff is NOT a wrapper defect and NOT a dropped pin:
#   (a) L9 pins absent from chip_top because the chosen configuration
#       parameterises them away (they are not ports of the instantiated module
#       at all) — config-gated / doc-over-declaration, advisory.
#   (b) chip_top ports absent from L9 because they ARE real ports of the
#       instantiated module that the L9 doc named differently (or did not
#       enumerate) — legitimate IP passthrough, advisory.
#
# The GROUND TRUTH is the actual synthesizable IP surface: the DECLARED port
# list of the reused-IP module(s) the wrapper instantiates. Reconciliation is
# chip-AGNOSTIC and NO-LEAK — it keys ONLY on the manifest ip_list + the
# instantiation grammar + the instantiated module's own declared ports:
#   - an L9-only pin that IS a declared port of the instantiated IP but is
#     missing from chip_top → the wrapper genuinely DROPPED a real IP port →
#     STILL a residual FAIL.
#   - a chip_top RTL-only port that is NOT a declared port of any instantiated
#     IP → the wrapper INVENTED a port not sourced from the IP → STILL FAIL.
# A non-reused-IP design (no manifest) never reaches this path.
_RE_IP_INSTANTIATION_TMPL = (
    r"\b{name}\s+(?:#\s*\([^;]*?\)\s*)?[A-Za-z_]\w*\s*\("
)


def _reused_ip_instantiated_surface(project: Path, rtl_top: Path,
                                    manifest: dict,
                                    defines: Optional[set] = None) -> set:
    """ORGANIC #781 — the union of DECLARED port names of every reused-IP
    module (manifest ip_list) that the wrapper's glue files instantiate.

    A "glue file" is any staged rtl file whose stem is NOT itself an ip_list
    module (chip_top.sv and any local wrapper) — scanning ONLY glue files for
    ip_list instantiations yields the TOP-of-IP module(s) the wrapper wraps,
    never the internal IP hierarchy (which would over-broaden the surface and
    leak). Returns the empty set when the manifest carries no ip_list or no
    instantiated IP module resolves — in which case the caller applies NO
    relaxation (no-leak). chip-AGNOSTIC: manifest structure + SV instantiation
    grammar + the instantiated module's own declared ports; no chip/vendor
    literal."""
    ip_list = manifest.get("ip_list") if isinstance(manifest, dict) else None
    if not isinstance(ip_list, list):
        return set()
    ip_set = {m.strip() for m in ip_list
              if isinstance(m, str) and m.strip()}
    if not ip_set:
        return set()
    rtl = _pl.rtl_dir(project)
    if not rtl.is_dir():
        return set()
    # Glue files: staged rtl sources whose stem is not an ip_list module.
    glue_files = [p for p in (sorted(rtl.glob("*.sv")) + sorted(rtl.glob("*.v")))
                  if p.stem not in ip_set]
    # Always include the resolved rtl_top even if (unusually) named after an IP.
    if rtl_top not in glue_files and rtl_top.is_file():
        glue_files.append(rtl_top)
    instantiated: set = set()
    compiled = {m: re.compile(_RE_IP_INSTANTIATION_TMPL.format(name=re.escape(m)))
                for m in ip_set}
    for gf in glue_files:
        try:
            text = _strip_comments(gf.read_text(errors="ignore"))
        except OSError:
            continue
        for m, rx in compiled.items():
            if m in instantiated:
                continue
            if rx.search(text):
                instantiated.add(m)
    surface: set = set()
    for m in instantiated:
        mfile = None
        for ext in (".sv", ".v"):
            cand = rtl / f"{m}{ext}"
            if cand.is_file():
                mfile = cand
                break
        if mfile is None:
            continue
        for p in parse_rtl_top_ports(mfile, m, defines):
            nm = p.get("name")
            if nm:
                surface.add(nm)
    return surface


# ── ORGANIC #778 — L3 doc-level explicit PIN-ALIAS reconciliation ──────────
# Independent of reused-IP/manifest status (manifest may be None — this is
# NOT gated on SOURCE_MANIFEST.json or a declared ip_list): the L3 external-
# interface doc sometimes documents a port under TWO accepted spellings via
# the backtick-quoted parenthetical grammar:
#     `<name_a>` (or `<name_b>`)
# meaning name_a and name_b are two authoritative labels for the SAME
# physical signal (a doc-author convenience, e.g. a generic bus-role name
# alongside a design-specific name). The Phase-1 L9 extractor promotes only
# ONE spelling into top_level_ports[]; when the generated RTL top wrapper
# "honours the extracted contract" by exposing BOTH spellings as literal
# ports (tied together internally — e.g. an OR-merge on a read bus, or a
# duplicated wire on a write bus) the un-promoted spelling surfaces as a
# spurious RTL-only (or, symmetrically, L9-only) residual — not a genuinely
# dropped or invented pin.
#
# Reconciliation is chip-AGNOSTIC and NO-LEAK: it keys ONLY on the L3 doc's
# own backtick + "(or ...)" grammar, and only credits a residual pin when
# the OTHER member of its documented alias group is an ANCHOR — a name
# already present with AGREEING direction on both L9 and RTL — and the
# residual pin's own RTL/L9 direction agrees with that anchor's direction.
# A residual pin whose alias partner is not itself a matched anchor, or
# whose own direction disagrees with the anchor, is NOT reconciled — it
# still FAILs (a real direction/pin defect can never hide behind an
# unrelated doc alias).
_RE_L3_ALIAS_PAIR = re.compile(
    r"`([A-Za-z_]\w*)`"                 # first name, in backticks
    r"\s*\(\s*or\s+"                     # `(or ` separator
    r"`([A-Za-z_]\w*)`"                 # second name, in backticks
    r"\s*\)",                            # closing paren
    re.IGNORECASE,
)


def _l3_doc_alias_groups(project: Path) -> list:
    """ORGANIC #778 — scan L3 input/generated docs for the explicit
    backtick `` `a` (or `b`) `` alias grammar and return the list of
    2-name equivalence groups found (each a frozenset of the two
    spellings). Order-independent — handles either authoring order
    (primary-first or alias-first) because the group is unordered.
    Empty when no L3 doc exists or no such pattern is present.
    Chip-AGNOSTIC: pure regex on the doc's own grammar; no chip /
    vendor / bus literal."""
    groups: list = []
    seen: set = set()
    roots = [project / "input" / "docs", _pl.generated_docs_dir(project)]
    for root in roots:
        if not root.is_dir():
            continue
        for p in sorted(root.glob("L3*")) + sorted(root.glob("*interface*")):
            try:
                txt = p.read_text(errors="ignore")
            except OSError:
                continue
            for m in _RE_L3_ALIAS_PAIR.finditer(txt):
                a, b = m.group(1).strip(), m.group(2).strip()
                if a and b and a != b:
                    key = frozenset((a, b))
                    if key not in seen:
                        seen.add(key)
                        groups.append(key)
    return groups


def _reconcile_l3_doc_aliases(only_l9: list, only_rtl: list,
                              alias_groups: list,
                              l9_names: set, rtl_names: set,
                              l9_dir_map: dict, rtl_dir_map: dict):
    """ORGANIC #778 — drop a residual pin from only_l9/only_rtl when its
    documented alias-group partner is a genuinely MATCHED anchor pin (the
    same name present in both L9 and RTL with agreeing direction) and the
    residual pin's own direction agrees with that anchor's direction.

    Returns (only_l9', only_rtl', advisory_list). `advisory_list` entries
    are human-readable "<residual> (side, doc-aliased to `<anchor>`)"
    strings for the PASS-path advisory print. Never removes a pin whose
    alias partner is not itself a matched anchor, or whose direction
    disagrees — no-leak."""
    if not alias_groups:
        return only_l9, only_rtl, []
    advisory: list = []
    kept_l9 = list(only_l9)
    kept_rtl = list(only_rtl)
    for group in alias_groups:
        names = sorted(group)
        anchor = None
        anchor_dir = None
        for n in names:
            if n in l9_names and n in rtl_names:
                ld, rd = l9_dir_map.get(n), rtl_dir_map.get(n)
                if ld and rd and ld == rd:
                    anchor = n
                    anchor_dir = rd
                    break
        if anchor is None:
            continue
        for n in names:
            if n == anchor:
                continue
            if n in kept_rtl:
                rd = rtl_dir_map.get(n)
                if rd == anchor_dir:
                    kept_rtl.remove(n)
                    advisory.append(
                        f"{n} (RTL-only, doc-aliased to `{anchor}`)")
                    continue
            if n in kept_l9:
                ld = l9_dir_map.get(n)
                if ld == anchor_dir:
                    kept_l9.remove(n)
                    advisory.append(
                        f"{n} (L9-only, doc-aliased to `{anchor}`)")
    return sorted(kept_l9), sorted(kept_rtl), advisory


# ── ORGANIC #711 round-2 — AUTO-DERIVE the renamed-interface pairing ────────
# Round-1 added a `renamed_interfaces` reconcile path but NOTHING populated it,
# so on a real catalog-glue SoC the gate still FAILed (or needed a per-run hand-
# authored manifest block — equivalent to the per-run waiver it was meant to
# remove). Round-2 AUTO-DERIVES the pairing in the gate (which has BOTH the L9
# and the RTL surface) from two authoritative, design-supplied signals:
#   (1) `declaration.json` declares a RECOGNISED interface protocol via a
#       `<iface>_interface_protocol` key (e.g. sram_interface_protocol), and
#   (2) the L3 input doc marks that interface's sub-ports TYPICAL / ILLUSTRATIVE
#       (the `<name>` (or `<alt>`) / "(typical)" / "illustrative" notation).
# Under BOTH, the residual L9-only and RTL-only ports that belong to that
# interface (share the `<iface>` token) are reconciled as one renamed group.
# §4.05: fires ONLY for an interface that is BOTH protocol-declared AND
# L3-illustrative; a genuinely missing/extra functional port outside such an
# interface (or any port when no protocol/illustrative signal exists) STILL
# FAILs. chip-AGNOSTIC: keyed on the `_interface_protocol` declaration grammar +
# the doc's own illustrative tag + a shared interface-name token — no chip /
# vendor / SKU literal.
_RE_IFACE_PROTOCOL_KEY = re.compile(r"^([a-z][a-z0-9]*)_interface_protocol$")
_RE_ILLUSTRATIVE_TAG = re.compile(r"\(\s*(?:or\b|typical\b)|illustrative",
                                  re.IGNORECASE)


def _declared_interface_protocols(project: Path) -> set:
    """ORGANIC #711 r2 — interface TOKENS declared via a
    `<iface>_interface_protocol` key with a truthy value in
    plugin_output/declaration.json (e.g. {'sram'}). Empty on absence."""
    decl = project / "plugin_output" / "declaration.json"
    if not decl.is_file():
        return set()
    try:
        data = json.loads(decl.read_text())
    except Exception:
        return set()
    if not isinstance(data, dict):
        return set()
    out: set = set()
    for k, v in data.items():
        m = _RE_IFACE_PROTOCOL_KEY.match(str(k))
        if m and v:
            out.add(m.group(1))
    return out


def _l3_iface_illustrative(project: Path, iface: str) -> bool:
    """ORGANIC #711 r2 — True iff an L3 input/generated doc marks the `<iface>`
    interface sub-ports as TYPICAL/ILLUSTRATIVE (the `<name>` (or `<alt>`) /
    '(typical)' / 'illustrative' notation on a line naming an `<iface>` port).
    This is the design's OWN authoritative 'these names are illustrative'
    signal — without it the interface must match exactly (no auto-reconcile)."""
    roots = [project / "input" / "docs", _pl.generated_docs_dir(project)]
    tok = re.compile(rf"(?:^|_){re.escape(iface)}(?:_|\b)", re.IGNORECASE)
    for root in roots:
        if not root.is_dir():
            continue
        for p in sorted(root.glob("L3*")) + sorted(root.glob("*interface*")):
            try:
                txt = p.read_text(errors="ignore")
            except OSError:
                continue
            for line in txt.splitlines():
                if tok.search(line) and _RE_ILLUSTRATIVE_TAG.search(line):
                    return True
    return False


def _auto_derive_renamed_interfaces(project: Path, only_l9: list,
                                    only_rtl: list) -> list:
    """ORGANIC #711 r2 — derive `renamed_interfaces` groups WITHOUT a hand-
    authored manifest block. For each interface that is BOTH protocol-declared
    (declaration.json) AND L3-illustrative, pair the residual L9-only and
    RTL-only ports that carry the `<iface>` token into one {l9, rtl} group.
    Returns [] when no interface satisfies both gates (→ no relaxation)."""
    ifaces = _declared_interface_protocols(project)
    if not ifaces:
        return []
    out: list = []
    for iface in sorted(ifaces):
        if not _l3_iface_illustrative(project, iface):
            continue
        tok = re.compile(rf"(?:^|_){re.escape(iface)}(?:_|\b)", re.IGNORECASE)
        l9_grp = sorted(p for p in only_l9 if tok.search(p))
        rtl_grp = sorted(p for p in only_rtl if tok.search(p))
        if l9_grp and rtl_grp:
            out.append({"l9": l9_grp, "rtl": rtl_grp})
    return out


def reconcile_reused_ip(only_l9: list, only_rtl: list,
                        manifest: dict,
                        bound_ports: Optional[set] = None
                        ) -> tuple[list, list, list, list]:
    """ORGANIC #659 — structurally reconcile a reused-IP wrapper's L9-only
    and RTL-only pin diffs against SOURCE_MANIFEST + name-prefix shape.

    Returns (residual_l9_only, residual_rtl_only, tied_off, prefix_matched):
      - residual_l9_only   : L9 roots that are NEITHER tied-off NOR
                             prefix-covered — still a genuine mismatch.
      - residual_rtl_only  : RTL pads not consumed by any prefix-expansion
                             match — still a genuine extra port.
      - tied_off           : L9 roots dropped as documented intentional
                             tie-offs (advisory WARN, not FAIL).
      - prefix_matched     : [(root, [pads…]), …] reconciled bus roots.

    Order: tie-offs are resolved FIRST (a manifest-documented tied root is
    dropped even if no pads exist), then remaining L9 roots attempt prefix-
    expansion against the RTL-only pool. A root claims pads named `root_*`
    (with the underscore boundary, so `tl` claims `tl_a_*`/`tl_d_*` but
    never `tlx`). A root is prefix-matched ONLY when it claims ≥1 pad.

    Chip-AGNOSTIC: matches on manifest structure + the `root_` name-prefix
    SHAPE only; never a bus/vendor literal."""
    tie_set = _manifest_name_set(manifest, _MANIFEST_TIEOFF_KEYS)
    declared_flatten = _manifest_name_set(manifest, _MANIFEST_FLATTEN_KEYS)

    tied_off: list = []
    remaining_l9: list = []
    # (1) Drop manifest-documented tie-offs from the L9-only diff first.
    for p in only_l9:
        if p in tie_set:
            tied_off.append(p)
        else:
            remaining_l9.append(p)

    # (2) Prefix-expansion: each remaining L9 root claims `root_`-prefixed
    #     scalar pads out of the RTL-only pool. Longer roots match first so
    #     a more-specific root (`tl_a`) claims its pads before a shorter
    #     sibling (`tl`) could greedily absorb them.
    rtl_pool = list(only_rtl)
    prefix_matched: list = []
    residual_l9: list = []
    for root in sorted(remaining_l9, key=lambda r: (-len(r), r)):
        prefix = root + "_"
        claimed = [pad for pad in rtl_pool if pad.startswith(prefix)]
        # When the manifest explicitly declares this root as flattened we
        # honour it even though the structural prefix check is the same;
        # the declaration is documentation, the SHAPE check is the proof.
        if claimed:
            for pad in claimed:
                rtl_pool.remove(pad)
            prefix_matched.append((root, sorted(claimed)))
        elif root in declared_flatten:
            # Declared flattened but no pads survived in the RTL-only pool
            # (e.g. all pads were also implicit-stripped) — treat as
            # reconciled documentation, not a residual mismatch.
            prefix_matched.append((root, []))
        else:
            residual_l9.append(root)

    # (3) ORGANIC #659 round-2 — STRUCTURAL tie-off: a residual L9 root that
    #     is NEITHER manifest-tied NOR prefix-covered, but whose interface the
    #     chip_top instantiation actually BINDS internally (`.root(net)` or an
    #     IP-split child `.root_i(net)`/`.root_o(net)`), is a legitimate
    #     internal-drive — drop it to the advisory tie-off list, not a FAIL.
    #     This closes the manifest-not-exhaustive gap (clk_edn_i/edn_o/edn)
    #     WITHOUT requiring every internally-driven interface to be enumerated.
    #     No-leak: a root bound NOWHERE in chip_top stays a residual FAIL.
    if bound_ports:
        still_residual: list = []
        for root in residual_l9:
            if _is_structurally_bound(root, bound_ports):
                tied_off.append(root)
            else:
                still_residual.append(root)
        residual_l9 = still_residual

    # (4) ORGANIC #712 — manifest-declared wrapper-exposed OUTPUTS. A reused-IP
    #     wrapper authoritatively exposes struct-flattened IP outputs that L9
    #     lacks ENTIRELY (no L9 root, so step (2) prefix-expansion never claims
    #     them). Drop EXACTLY the declared RTL names from the residual RTL-only
    #     pool (advisory). No-leak: only the names the manifest lists fire; an
    #     undeclared extra RTL port still surfaces as a residual FAIL.
    exposed = _manifest_name_set(manifest, _MANIFEST_EXPOSED_OUTPUT_KEYS)
    if exposed:
        claimed_out = [p for p in rtl_pool if p in exposed]
        for p in claimed_out:
            rtl_pool.remove(p)
        if claimed_out:
            prefix_matched.append(
                ("(wrapper-exposed-output)", sorted(claimed_out)))

    # (5) ORGANIC #711 — manifest-declared RENAMED interface groups. The L9
    #     'typical/illustrative' sub-port names differ from the RTL split names
    #     (a rename is not a prefix). The manifest authoritatively pairs them, so
    #     drop the declared L9 names from residual_l9 (advisory tie_off) and the
    #     declared RTL names from residual_rtl (advisory). No-leak: ONLY the
    #     explicitly-paired names reconcile; an undeclared rename still FAILs.
    for l9_set, rtl_set in _manifest_renamed_groups(manifest):
        kept_l9: list = []
        for nm in residual_l9:
            if nm in l9_set:
                tied_off.append(nm)
            else:
                kept_l9.append(nm)
        residual_l9 = kept_l9
        claimed_r = [p for p in rtl_pool if p in rtl_set]
        for p in claimed_r:
            rtl_pool.remove(p)
        if claimed_r:
            prefix_matched.append(("(renamed-interface)", sorted(claimed_r)))

    return sorted(residual_l9), sorted(rtl_pool), sorted(tied_off), \
        prefix_matched


# ─── L9 ingestion ─────────────────────────────────────────────────
def find_l9(project: Path) -> Optional[Path]:
    gd = _pl.generated_docs_dir(project)
    if not gd.is_dir():
        return None
    for p in sorted(gd.glob("L9_*.json")):
        return p
    return None


def _normalise_dir(raw: str) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    return _DIR_NORMALIZE.get(raw.lower().strip())


# ORGANIC-20260606 #490 — L9 port-key fragmentation. The L9 schema has
# accreted THREE port-list keys over its history:
#   - `top_ports`        — the CANONICAL key the promoter writes (also
#                          read by the RTL emitter, the SDC/QSF/clock
#                          generators, and most post-emit hooks);
#   - `ports`            — the alias gen_l9 emits alongside `top_ports`;
#   - `top_level_ports`  — the original Wave-79 schema-v1 key this gate
#                          was first written against;
#   - `top_module_pins`  — the legacy compat name;
#   - `dtop_top_level.ports` — schema-v1 nested form.
# `full_stack_tb_gen` + the L9 promoter populate `top_ports`, but this
# gate historically read ONLY `top_level_ports` / `top_module_pins` /
# `dtop_top_level.ports`. A correct RTL top therefore got NO verification
# (silent SKIP) when the promoted port set landed in `top_ports`/`ports`
# — and a field run had to write the same pins into BOTH keys to clear
# the gate. Fix: read the UNION of every known key (deduped by name, so
# the dual-write that field runs used is harmless and the order-of-
# precedence between aliases no longer matters). The promoter side
# (gen_l9_integration_spec) writes the canonical `top_ports` AND mirrors
# into whatever legacy keys it finds populated, so no consumer is
# orphaned regardless of which key it reads.
_L9_PORT_KEYS = (
    "top_ports",          # canonical (promoter + TB-gen + emitters)
    "ports",              # promoter alias
    "top_level_ports",    # original Wave-79 schema-v1 key
    "top_module_pins",    # legacy compat alias
)


def extract_l9_ports_with_audit(l9: dict) -> tuple[list[dict], list[dict]]:
    """ORGANIC #591 — like extract_l9_ports but also returns the SKIP
    audit: [{entry_repr, reason}] for every raw entry that did not
    become (or merge into) a port record. Reasons: `duplicate` (same
    name seen again — merged, counts as skipped raw entry),
    `unparseable` (no name field / not a dict). The PASS evidence line
    uses this so its count can never silently disagree with the L9
    contract it certifies."""
    raw_lists: list[list] = []
    for key in _L9_PORT_KEYS:
        v = l9.get(key)
        if isinstance(v, list):
            raw_lists.append(v)
    dtop = l9.get("dtop_top_level", {})
    if isinstance(dtop, dict) and isinstance(dtop.get("ports"), list):
        raw_lists.append(dtop["ports"])
    out: list[dict] = []
    skipped: list[dict] = []
    by_name: dict[str, dict] = {}
    for lst in raw_lists:
        for entry in lst:
            if not isinstance(entry, dict):
                skipped.append({"entry": repr(entry)[:80],
                                "reason": "unparseable (not a dict)"})
                continue
            name = entry.get("name") or entry.get("port") or entry.get("pin")
            direction = (
                entry.get("direction")
                or entry.get("dir")
                or entry.get("io")
            )
            if not name:
                skipped.append({"entry": repr(entry)[:80],
                                "reason": "unparseable (no name field)"})
                continue
            # #591 — strip whitespace variants ('data_o ' vs 'data_o'):
            # they are the SAME pin; un-stripped they mis-compare as a
            # phantom L9-only + RTL-only pair.
            name = str(name).strip()
            if not name:
                skipped.append({"entry": repr(entry)[:80],
                                "reason": "unparseable (blank name)"})
                continue
            if name in by_name:
                skipped.append({"entry": name,
                                "reason": f"duplicate '{name}'"})
            d = _normalise_dir(direction) if direction else None
            prev = by_name.get(name)
            if prev is None:
                rec = {
                    "name": name,
                    "direction": d,
                    "open_drain": bool(entry.get("open_drain", False)),
                    # v0.3.4 — ORGANIC #491 R4. Doc-declared optionality
                    # (`(optional)` name annotation / optionality width
                    # cell, modelled by the phase1 promoter) reaches the
                    # gate so an optional pin absent from the RTL top is
                    # advisory, not FAIL.
                    "optional": bool(entry.get("optional", False)),
                }
                by_name[name] = rec
                out.append(rec)
            else:
                # Same pin under another key: backfill a missing
                # direction / open_drain so a dual-write where only one
                # copy carries the direction still yields it.
                if prev.get("direction") is None and d is not None:
                    prev["direction"] = d
                if entry.get("open_drain"):
                    prev["open_drain"] = True
                if entry.get("optional"):
                    prev["optional"] = True
    return out, skipped


def extract_l9_ports(l9: dict) -> list[dict]:
    """Return [{name, direction, open_drain}] from the UNION of every
    accepted L9 schema port-key variant (#490).

    The union is deduped by name (first occurrence wins, but a later
    occurrence that carries a direction backfills a missing one) so a
    dual-written L9 (the same pins under both `top_ports` and
    `top_module_pins`) yields the same single port set as a singly-keyed
    L9. This is what makes the gate read ports that landed in ANY one
    key without requiring producers to mirror into every key.
    #591: thin wrapper over extract_l9_ports_with_audit (one parser)."""
    ports, _skipped = extract_l9_ports_with_audit(l9)
    return ports


# ─── RTL top extraction ────────────────────────────────────────────
def l9_top_module_name(l9: dict) -> Optional[str]:
    """ORGANIC-20260614 — return the L9-declared top-module NAME (not the
    file). This is the same name `find_rtl_top` greps with when it does
    its content-scan fallback; threading it into the port parser lets the
    parser anchor on the correct module header even when the resolved top
    is NOT the first `module` declared in a multi-module bundle file.

    Mirrors `find_rtl_top`'s precedence for the name-bearing fields
    (schema-v2 canonical first, then legacy dtop_* keys). Returns None
    when L9 carries no explicit top-module name — in that case the parser
    falls back to the historical first-module behaviour, which is correct
    for the single-module-per-file / name-guess cases. Chip-AGNOSTIC:
    pure schema-key read, no chip/vendor literal."""
    top_v2 = l9.get("top_module") or l9.get("top") or l9.get("dtop")
    if isinstance(top_v2, str) and top_v2.strip():
        return top_v2.strip()
    dtop = l9.get("dtop_top_level", {})
    if isinstance(dtop, dict):
        m = dtop.get("module_name")
        if isinstance(m, str) and m.strip():
            return m.strip()
    m = l9.get("dtop_module_name")
    if isinstance(m, str) and m.strip():
        return m.strip()
    return None


def find_rtl_top(project: Path, l9: dict) -> Optional[Path]:
    rtl = _pl.rtl_dir(project)
    if not rtl.is_dir():
        return None
    candidates: list[str] = []
    # Schema v2 canonical field — added v1.6.19. Honoured before legacy
    # dtop_* keys so v2 projects (which carry top_module="chip_top" but
    # no dtop_module_name) stop being silently SKIPped by this gate.
    top_v2 = l9.get("top_module") or l9.get("top") or l9.get("dtop")
    if isinstance(top_v2, str) and top_v2:
        candidates.extend([f"{top_v2}.sv", f"{top_v2}.v"])
    dtop = l9.get("dtop_top_level", {})
    if isinstance(dtop, dict):
        m = dtop.get("module_name")
        if isinstance(m, str) and m:
            candidates.extend([f"{m}.sv", f"{m}.v"])
    m = l9.get("dtop_module_name")
    if isinstance(m, str) and m:
        candidates.extend([f"{m}.sv", f"{m}.v"])
    ic = l9.get("ic_name")
    if isinstance(ic, str) and ic:
        ic_l = ic.lower()
        candidates.extend(
            [f"{ic_l}_dtop.sv", f"{ic_l}_dtop.v",
             f"{ic_l}.sv", f"{ic_l}.v"]
        )
    # v1.6.84 (#16 Bug B): fallback to AID-class canonical 'chip_top'
    # when L9.top_module is null/empty. Without this, a project with a
    # null L9.top_module silently SKIPs even though the deterministic
    # generator emitted rtl/chip_top.sv — a silent quality loss.
    candidates.extend(["chip_top.sv", "chip_top.v"])

    for c in candidates:
        p = rtl / c
        if p.is_file():
            return p
    # Content-scan (v1.6.19+): when schema v2 declares
    # top_module="X" but the file isn't named "X.sv", grep every
    # rtl/*.sv|.v for `module X` and return the first match. Catches
    # projects where the top is bundled inside a multi-module file.
    if isinstance(top_v2, str) and top_v2:
        pat = re.compile(rf"\bmodule\s+{re.escape(top_v2)}\b")
        for p in sorted(rtl.glob("*.sv")) + sorted(rtl.glob("*.v")):
            try:
                if pat.search(p.read_text(encoding="utf-8", errors="replace")):
                    return p
            except OSError:
                continue
    return None


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def _strip_param_block(src: str) -> str:
    """Remove the optional `#( ... )` parameter port list that follows a
    `module <name>` header, using a balanced-paren depth counter so a
    parameter default containing a function call (e.g.
    `parameter aw = $clog2(memsize)`) — or arbitrarily nested calls —
    does NOT terminate the strip at an INNER `)`.

    Without this, the old `#\\s*\\([^)]*\\)` regex closed the parameter
    block at the first inner `)` of `$clog2(memsize)`, leaving the real
    port list unmatched and parse_rtl_top_ports returning zero ports
    (GitHub #474). The scanner walks every `module <name>` occurrence and
    splices out only the matched `#(...)` span, preserving the rest of
    the text (including the port-list parens) verbatim.
    """
    out: list[str] = []
    pos = 0
    # Iterate header-by-header: `module <name>` then optional whitespace.
    for hm in re.finditer(r"\bmodule\s+\w+\s*", src):
        # Emit everything up to and including the header we just matched.
        out.append(src[pos:hm.end()])
        pos = hm.end()
        # ORGANIC #637 — consume any `import pkg::*;` clauses that sit between
        # `module <name>` and the `#(...)` parameter block (the standard SV
        # ordering `module X import a_pkg::*; import b_pkg::*; #(params)
        # (ports);`). Without this the anchored `#(` test below misses the
        # param block — an import clause intervenes — so the block survives the
        # strip and the downstream port-list regex never matches → zero ports.
        # Emit the import clauses verbatim (preserved) and advance past them.
        im = re.match(r"(?:import\s+[\w:\*\s,]+;\s*)+", src[pos:])
        if im:
            out.append(src[pos:pos + im.end()])
            pos += im.end()
        # A parameter block must begin with `#` then `(` (whitespace ok).
        pm = re.match(r"#\s*\(", src[pos:])
        if not pm:
            continue
        # Walk from the opening paren with a depth counter.
        i = pos + pm.end() - 1   # index of the `(` itself
        depth = 0
        end = None
        while i < len(src):
            ch = src[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
            i += 1
        if end is None:
            # Unbalanced — bail out without stripping; leave text as-is so
            # the downstream regex can still try (and fail loudly).
            continue
        # Skip the entire `#(...)` span (replace with a single space so
        # tokens on either side don't accidentally merge).
        out.append(" ")
        pos = end
    out.append(src[pos:])
    return "".join(out)


# ─── #704 — preprocessor-aware compile define-set resolution ───────
# The RTL-top port parser must be told the SAME compile define-set the
# in-runner sv2v / iverilog DUT conversion uses, so that ports inside a
# NOT-TAKEN `ifdef arm (optional formal / RVFI / ECC / debug interfaces)
# are EXCLUDED before extraction. Without it, the parser harvests
# conditionally-compiled ports the DUT never exposes AND leaks the
# last-seen direction token across a stripped conditional boundary into
# the next real port. Mirrors design_one_shot_runner._v671_tb_compile_defines
# exactly (base SIMULATION, flipped to SYNTHESIS only when the simulation
# arm leaves an include-closure hole the synthesis arm resolves). A
# formal/debug/coverage define (e.g. RISCV_FORMAL) is in NEITHER set, so
# its `ifdef arm is dropped under whichever arm wins — matching the real
# DUT surface. chip-AGNOSTIC: pure SIMULATION/SYNTHESIS grammar; no
# chip/vendor/macro literal.
def _resolve_compile_defines(project: Path) -> set:
    """#704 — return the compile-time -D macro set the runner's DUT
    conversion compiles under (e.g. {"SIMULATION"} or {"SYNTHESIS"}), so
    the RTL-top port parser blanks not-taken `ifdef arms the SAME way the
    runner's full-stack TB does. Defaults to {"SIMULATION"} on any read /
    import error so the gate stays preprocessor-aware even when the
    closure resolver is unavailable. chip-AGNOSTIC."""
    rtl_dir = _pl.rtl_dir(project)
    if not rtl_dir.is_dir():
        return {"SIMULATION"}
    files_text: dict[str, str] = {}
    for ext in (".v", ".sv", ".svh", ".vh"):
        for f in sorted(rtl_dir.rglob(f"*{ext}")):
            try:
                files_text[str(f)] = f.read_text(errors="replace")
            except OSError:
                continue
    try:
        import synth_frontend as _sf
        define, _reason = _sf.decide_sv2v_tb_define(files_text)
    except Exception:  # pragma: no cover — defensive
        define = "SIMULATION"
    return {define}


def _rtl_power_pin_face(rtl_path: Path,
                        top_name: Optional[str] = None) -> set:
    """ORGANIC-20260722 #784 — return the set of port names declared inside the
    RTL top module's ```ifdef USE_POWER_PINS`` arm (empty when the top has no
    such arm, or on ANY parse/import error so the gate degrades to its
    historical exact-name diff).

    Reuses the SAME comment-mask / port-block / power-gate helpers the
    auto-emitted chip_top wrapper uses (`design_one_shot_runner._chip_top_*`),
    so the emitter and this gate can never disagree about which pins are the
    power face. chip-AGNOSTIC: keyed on the universal ``USE_POWER_PINS`` macro
    name only."""
    try:
        import design_one_shot_runner as _d
        text = _d._chip_top_mask_comments(
            rtl_path.read_text(errors="ignore"))
        anchor = None
        if isinstance(top_name, str) and top_name.strip():
            anchor = re.search(
                r"\bmodule\s+%s\s*[(#]" % re.escape(top_name.strip()), text)
        if anchor is None:
            anchor = re.search(r"\bmodule\s+\w+\s*[(#]", text)
        if anchor is None:
            return set()
        _params, port_block = _d._chip_top_extract_param_and_ports(
            text, anchor.end() - 1)
        if not port_block:
            return set()
        # `_chip_top_power_pin_gated_names` yields every IDENTIFIER inside the
        # guarded arm — including the `inout`/`wire` declaration keywords, which
        # is harmless where it is used as a membership filter over an
        # already-extracted name list, but would put non-ports into a set we
        # SUBTRACT from both sides here. Intersect with the block's real port
        # names so the face is exactly "ports declared in the power arm".
        return (_d._chip_top_power_pin_gated_names(port_block)
                & _d._chip_top_port_names(port_block))
    except Exception:  # pragma: no cover — defensive
        return set()


def parse_rtl_top_ports(rtl_path: Path,
                        top_name: Optional[str] = None,
                        defines: Optional[set] = None) -> list[dict]:
    """Parse `module <name>(...);` and emit [{name, direction}].

    Supports the SystemVerilog `module foo import pkg::*;
    (input wire clk, output id_tx_en, inout id_bus, ...)` shape.

    ORGANIC-20260614 — when `top_name` is supplied (the L9-declared top
    that `find_rtl_top` already resolved the FILE by), the port list is
    extracted from that specific module header so a multi-module bundle
    file whose top is NOT declared first is parsed at the CORRECT module.
    When `top_name` is None / absent, the parser falls back to the first
    module declared in the file (preserving behaviour for single-module
    files and name-mismatch edge cases). Chip-AGNOSTIC: the anchor is the
    resolved-top string itself, never a chip/vendor literal.

    #704 — migrated OFF the former local comment/param-strip-only regex
    ONTO the SHARED preprocessor-aware parser
    `reset_clock_variant_alias.parse_module_ports(text, module, defines)`
    (the #671 parser already consumed by l9_submodule_conformance_check /
    leaf_typo_alias_emit / design_one_shot_runner). The shared parser
    handles comment + balanced-paren `#(...)` parameter stripping + SV
    `import pkg::*;` clauses AND — when `defines` is supplied — BLANKS the
    bodies of NOT-TAKEN `ifdef/`ifndef/`elsif/`else arms BEFORE the port
    list is read. This (1) excludes conditionally-compiled optional
    interfaces (formal/RVFI/ECC/debug) the DUT never exposes, and (2)
    prevents the last-seen direction token from carrying across a stripped
    conditional boundary into the next real port.

    §4.05 NO-LEAK: `defines=None` preserves take-EVERY-arm behaviour — a
    NON-ifdef top is unaffected and every existing passing case still
    passes; a port genuinely declared in the COMPILED arm is still
    returned; the direction of a real compiled port is read correctly (no
    carry-forward). chip-AGNOSTIC: pure `ifdef grammar + abstract compile
    define-set; no chip/vendor literal.
    """
    try:
        import reset_clock_variant_alias as _rcv
    except Exception:  # pragma: no cover — defensive import guard
        return []
    text = rtl_path.read_text(errors="ignore")
    module = top_name.strip() if isinstance(top_name, str) and top_name.strip() \
        else None
    ports: list[tuple] = []
    if module is not None:
        # Anchor on the resolved top module header (the shared parser greps
        # for `\bmodule <module>\b`, so `mytop` never matches `mytop_wrapper`).
        ports = _rcv.parse_module_ports(text, module, defines)
    if not ports:
        # Fallback: first module declared in the file (historical behaviour,
        # correct for single-module files and when the named top is absent /
        # mis-spelled). Resolve the first module NAME the same way the shared
        # parser would, then parse it (with the same define-set).
        stripped = _rcv._strip_comments(text)
        fm = re.search(r"\bmodule\s+(\w+)", stripped)
        if fm:
            ports = _rcv.parse_module_ports(text, fm.group(1), defines)
    out: list[dict] = []
    # NB: reset_clock_variant_alias.parse_module_ports yields
    # (direction, width, name) tuples — the WIDTH `[msb:lsb]` cell is the
    # MIDDLE element, the port NAME is LAST (matching the #671 parser's
    # own `for _d, _w, n in ports` unpack contract).
    for direction, _width, name in ports:
        if not name:
            continue
        # The shared parser only yields ANSI ports carrying a direction
        # keyword; normalise it through the same in/out/io table so the
        # downstream direction-mismatch check compares apples to apples.
        cur_dir = _normalise_dir(direction) if direction else None
        out.append({"name": name, "direction": cur_dir})
    return out


# ─── waiver ────────────────────────────────────────────────────────
def waived(project: Path) -> tuple[bool, str]:
    waivers = project / "waivers.json"
    if not waivers.is_file():
        return False, ""
    try:
        d = json.loads(waivers.read_text())
    except Exception:
        return False, ""
    raw = d.get(WAIVER_KEY)
    if not isinstance(raw, dict):
        return False, ""
    rationale = raw.get("rationale") or raw.get("reason") or ""
    if isinstance(rationale, str) and \
       len(rationale.strip()) >= WAIVER_MIN_LEN:
        return True, rationale.strip()
    return False, ""


# ─── main ─────────────────────────────────────────────────────────
def _exclusion_advisories(only_l9_optional, reused_prefix_matched,
                          reused_tied_off, reused_config_gated,
                          reused_ip_passthrough, l3_alias_reconciled):
    """The WARN lines that explain which pins were EXCLUDED from the mismatch
    set, and on what grounds.

    #345 salvage 1. These were emitted inline under `if not findings:` — the
    PASS path only. Every one of them is a statement about what was taken OUT
    of the comparison, so on a FAIL the reader saw N findings with no record
    of the exclusions that shaped them. If an exclusion rule is wrong the
    finding list is wrong, and the evidence was being suppressed precisely
    then. Built once here so all three verdict paths print the same set.
    """
    out = []
    if only_l9_optional:
        # v0.3.4 — #491 R4: doc-optional pins the RTL top legitimately omits.
        out.append(f"  WARN (advisory) — L9 doc-OPTIONAL pin(s) not in "
                   f"RTL top: {only_l9_optional}")
    if reused_prefix_matched:
        # ORGANIC #659: reused-IP struct-bus roots reconciled with their
        # prefix-expanded scalar pads.
        _pm = ", ".join(f"{root}\u2192{pads}"
                        for root, pads in reused_prefix_matched)
        out.append(f"  WARN (advisory) — reused-IP struct-bus flatten "
                   f"reconciled (root \u2194 prefix-expanded pads): {_pm}")
    if reused_tied_off:
        # ORGANIC #659: SOURCE_MANIFEST-documented intentional tie-offs
        # dropped from the L9-only diff.
        out.append(f"  WARN (advisory) — reused-IP SOURCE_MANIFEST tie-off(s) "
                   f"omitted from RTL top (intentional, internally driven): "
                   f"{reused_tied_off}")
    if reused_config_gated:
        # ORGANIC #781: L9 pins the chosen reused-IP configuration
        # parameterises away — doc described a fuller variant than was
        # instantiated, not a dropped pin.
        out.append(f"  WARN (advisory) — reused-IP CONFIG-GATED L9 pin(s) not "
                   f"exposed by the instantiated IP variant "
                   f"(doc-over-declaration, not a dropped pin): "
                   f"{reused_config_gated}")
    if reused_ip_passthrough:
        # ORGANIC #781: chip_top ports that ARE real declared ports of the
        # instantiated reused-IP module (faithful passthrough) which the L9
        # doc named differently / did not list.
        out.append(f"  WARN (advisory) — reused-IP passthrough port(s) present "
                   f"in chip_top and in the instantiated IP but not enumerated "
                   f"in L9 (legitimate IP surface): {reused_ip_passthrough}")
    if l3_alias_reconciled:
        # ORGANIC #778: residual pin(s) reconciled against the L3 doc's own
        # alias grammar — a documented duplicate spelling, not a dropped or
        # invented pin.
        out.append(f"  WARN (advisory) — L3 doc-declared pin alias(es) "
                   f"reconciled (not a mismatch): {l3_alias_reconciled}")
    return out


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: l9_rtl_pin_consistency_check.py <project_dir>")
        return 2
    project = Path(argv[1]).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}")
        return 1

    l9_path = find_l9(project)
    if l9_path is None:
        print("SKIP — no L9 doc")
        return 0
    try:
        l9 = json.loads(l9_path.read_text())
    except Exception as e:
        print(f"FAIL — cannot parse L9 ({l9_path.name}): {e}")
        return 1

    l9_ports, l9_skipped = extract_l9_ports_with_audit(l9)
    if not l9_ports:
        print(
            "SKIP — L9 declares no top_level_ports[] / top_module_pins[]"
        )
        return 0

    rtl_top = find_rtl_top(project, l9)
    if rtl_top is None:
        print(
            "SKIP — no RTL top file (gate active only when both L9 and "
            "RTL exist)"
        )
        return 0

    # ORGANIC-20260614 — thread the L9-declared top-module name into the
    # parser so the port-list regex anchors on the CORRECT module header
    # even when the resolved top is not the first `module` in a multi-
    # module bundle file. Precedence: the explicit L9 name field; else the
    # resolved file's stem (the candidate-filename / chip_top / <ic_name>
    # resolution paths name the file after the module, so the stem is the
    # module name there). The parser falls back to the first module if the
    # named module turns out to be absent. Chip-AGNOSTIC: the anchor is the
    # resolved-top string, never a chip/vendor literal.
    top_name = l9_top_module_name(l9) or rtl_top.stem
    # #704 — resolve the SAME compile define-set the in-runner DUT
    # conversion uses (base SIMULATION, synth/TB flip) so the shared
    # preprocessor-aware parser blanks NOT-TAKEN `ifdef arms before
    # extracting ports — excluding conditionally-compiled optional
    # interfaces (formal/RVFI/ECC/debug) AND preventing a stripped
    # conditional boundary from carrying the last-seen direction token
    # into the next real port. A non-`ifdef top is unaffected (every arm
    # is present regardless of the define-set). chip-AGNOSTIC.
    rtl_defines = _resolve_compile_defines(project)
    rtl_ports = parse_rtl_top_ports(rtl_top, top_name, rtl_defines)
    if not rtl_ports:
        print(
            f"FAIL — RTL top {rtl_top.name} parsed zero ports — "
            f"either the module declaration is malformed or the regex "
            f"failed; investigate."
        )
        return 1

    l9_names = {p["name"] for p in l9_ports}
    rtl_names = {p["name"] for p in rtl_ports}

    # v1.6.85 (#17 Bug B) — strip implicit pins (clk / reset family) from
    # BOTH sides of the diff before comparing. They're always required
    # but L9 sometimes doesn't enumerate them (relying on the
    # canonical-fallback in aid_class_rtl_gen). Without this, every
    # such project hits a false-FAIL "L9 declares pins missing from
    # RTL".
    # ORGANIC-20260606 #491 (b) — the strip now matches a NAME-PATTERN
    # (clk/i_clk/clock/clk_i + rst/rst_n/reset/reset_n/por…) so an
    # asymmetric spelling pair (L9=`i_clk`, RTL=`clk`) no longer survives
    # the strip and false-FAILs.
    l9_names = {n for n in l9_names if not _is_implicit_pin(n)}
    rtl_names = {n for n in rtl_names if not _is_implicit_pin(n)}

    # ORGANIC-20260722 #784 — strip the RTL top's OWN `ifdef USE_POWER_PINS
    # face from BOTH sides. #704 made the parser preprocessor-aware and blanks
    # not-taken arms; USE_POWER_PINS is in NEITHER the SIMULATION nor the
    # SYNTHESIS define-set, so a supply pin declared behind that guard vanished
    # from `rtl_names` while L9 still declares it (every PDK datasheet lists the
    # supplies) → a permanent false "L9 declares pins missing from RTL top:
    # ['vccd1','vssd1']" on any design using the universal USE_POWER_PINS
    # convention. Simply TAKING the arm is not the fix either: the hardened
    # face legitimately carries supplies the functional pin table never lists
    # (unused-domain rails), which would flip the false-missing into an equally
    # false "RTL has ports not in L9".
    #
    # Supply pins are owned by the power-intent / PDN layer (L21), not by this
    # gate — whose stated purpose is QSF/SDC pin ASSIGNMENT correctness, and a
    # supply rail is never pin-assigned. The exemption is therefore SYMMETRIC
    # and derived from the DUT's own source: only names literally declared
    # inside that module's USE_POWER_PINS arm are exempt, so a dropped
    # FUNCTIONAL pin can never hide behind it. A top with no USE_POWER_PINS arm
    # yields an empty set → byte-identical behaviour. chip-AGNOSTIC: the
    # USE_POWER_PINS macro name only; no chip/vendor/rail literal.
    power_face = _rtl_power_pin_face(rtl_top, top_name)
    if power_face:
        l9_names = l9_names - power_face
        rtl_names = rtl_names - power_face

    only_l9_all = sorted(l9_names - rtl_names)
    only_rtl_all = sorted(rtl_names - l9_names)

    # Direction maps built once, up-front — reused by both the #778 doc-
    # alias reconciliation below AND the final dir_mismatch pass further
    # down (single source, no drift between the two uses).
    l9_dir_map = {p["name"]: p["direction"] for p in l9_ports}
    rtl_dir_map = {p["name"]: p["direction"] for p in rtl_ports}

    # ORGANIC #659 — reused-IP struct-flatten reconciliation. BEFORE the
    # optional/debug splits, if phase2/stage1/rtl/SOURCE_MANIFEST.json
    # declares reused_ip=true, reconcile the raw diffs: drop documented
    # tie-offs (advisory) and collapse struct-bus prefix-expansion
    # (`root` ↔ `root_*` pads) so only genuinely-unmatched pins survive.
    # Non-reused-IP designs get manifest=None → NO relaxation → exact-name
    # diff preserved (no-leak). Chip-AGNOSTIC: manifest structure + name-
    # prefix shape only.
    reused_tied_off: list = []
    reused_prefix_matched: list = []
    reused_config_gated: list = []
    reused_ip_passthrough: list = []
    manifest = load_source_manifest(project)
    if manifest is not None:
        # ORGANIC #711 round-2 — AUTO-DERIVE the renamed-interface pairing from
        # the design's own protocol declaration + L3 illustrative tag, so a real
        # catalog-glue SoC reconciles a spec-permitted interface RENAME with NO
        # hand-authored manifest block (round-1 only honoured a manually-written
        # `renamed_interfaces`, which nothing populated). Merge the auto-derived
        # groups into the manifest before reconcile; §4.05 gating lives inside
        # _auto_derive_renamed_interfaces (protocol + illustrative + iface-token).
        _auto_renames = _auto_derive_renamed_interfaces(
            project, only_l9_all, only_rtl_all)
        if _auto_renames:
            manifest = dict(manifest)
            manifest["renamed_interfaces"] = (
                list(manifest.get("renamed_interfaces") or []) + _auto_renames)
        # ORGANIC #659 round-2 — also pass the chip_top instantiation's bound
        # port set so a glue-driven interface absent from the manifest tie_offs
        # dict (clk_edn_i / edn_o / IP-split edn) is recognised structurally.
        reused_bound_ports = _chip_top_bound_ports(rtl_top)
        (only_l9_all, only_rtl_all,
         reused_tied_off, reused_prefix_matched) = reconcile_reused_ip(
            only_l9_all, only_rtl_all, manifest,
            bound_ports=reused_bound_ports)

        # ORGANIC #781 — reused-IP CONFIG-VARIANT surface reconciliation.
        # After the struct-flatten / tie-off / rename passes, any residual
        # diff is measured against the ACTUAL declared port surface of the
        # reused-IP module(s) the wrapper instantiates (the ground truth of
        # the synthesizable interface). An L9-only pin the instantiated IP
        # does not expose is config-gated (the chosen variant parameterises
        # it away); a chip_top port that IS a real IP port is a legitimate
        # passthrough the L9 doc named differently. Both are advisory. A
        # residual L9-only pin the IP DOES expose (dropped by the wrapper) or
        # a chip_top port sourced from NO IP (invented) still FAILs — no-leak.
        ip_surface = _reused_ip_instantiated_surface(
            project, rtl_top, manifest, rtl_defines)
        if ip_surface:
            _kept_l9: list = []
            for p in only_l9_all:
                if p in ip_surface:
                    _kept_l9.append(p)   # real IP port dropped by wrapper → FAIL
                else:
                    reused_config_gated.append(p)  # not instantiated → advisory
            only_l9_all = _kept_l9
            _kept_rtl: list = []
            for p in only_rtl_all:
                if p in ip_surface:
                    reused_ip_passthrough.append(p)  # legit IP passthrough → adv
                else:
                    _kept_rtl.append(p)   # invented, not from IP → FAIL
            only_rtl_all = _kept_rtl
            reused_config_gated = sorted(reused_config_gated)
            reused_ip_passthrough = sorted(reused_ip_passthrough)

    # ORGANIC #778 — L3 doc-level explicit pin-alias reconciliation (see
    # _reconcile_l3_doc_aliases doc above). Runs UNCONDITIONALLY (never
    # gated on manifest/reused-IP status) — the alias grammar is a property
    # of the L3 INPUT DOC, not of reused-IP provenance, so it also covers a
    # freshly-authored (non-catalog-glue) top that faithfully exposes both
    # doc-documented spellings as literal ports.
    l3_alias_groups = _l3_doc_alias_groups(project)
    l3_alias_reconciled: list = []
    if l3_alias_groups:
        only_l9_all, only_rtl_all, l3_alias_reconciled = (
            _reconcile_l3_doc_aliases(
                only_l9_all, only_rtl_all, l3_alias_groups,
                l9_names, rtl_names, l9_dir_map, rtl_dir_map))

    # v0.3.4 — ORGANIC #491 R4. Split L9-only pins into doc-declared
    # OPTIONAL vs required. A doc says "(optional) pin" → the RTL top
    # legitimately may omit it; absence is advisory, not FAIL (mirror
    # of the debug/scan/tb split on the RTL side below).
    l9_optional_names = {p["name"] for p in l9_ports if p.get("optional")}
    only_l9_optional = [n for n in only_l9_all if n in l9_optional_names]
    only_l9 = [n for n in only_l9_all if n not in l9_optional_names]

    # Wave 82 Fix G — split RTL-only ports into debug-allowed vs real.
    # debug_*/scan_*/tb_*/_dbg* / probe_* / etc. are test hooks that
    # legitimately do NOT belong in the L9 production pin contract.
    only_rtl_debug = [n for n in only_rtl_all if _is_debug_port(n)]
    only_rtl = [n for n in only_rtl_all if not _is_debug_port(n)]

    # Direction-mismatch list (only for pins in BOTH). rtl_dir_map was built
    # up-front (see #778 comment above) — reused here, single source.
    dir_mismatch: list[str] = []
    for p in l9_ports:
        if p["name"] not in rtl_names:
            continue
        l9d = p["direction"]
        rtld = rtl_dir_map.get(p["name"])
        if l9d and rtld and l9d != rtld:
            dir_mismatch.append(
                f"{p['name']}: L9={l9d} vs RTL={rtld}"
            )

    findings: list[str] = []
    if only_l9:
        findings.append(
            f"L9 declares pins missing from RTL top "
            f"({rtl_top.name}): {only_l9}"
        )
    if only_rtl:
        findings.append(
            f"RTL top ({rtl_top.name}) has ports not in L9: {only_rtl}"
        )
    if dir_mismatch:
        findings.append(
            f"direction mismatches: {dir_mismatch}"
        )

    if not findings:
        # ORGANIC #591 — honest evidence line: total raw L9 entries,
        # entries compared, entries skipped WITH reasons. The old line
        # printed only the deduped count, so on a 47-entry contract it
        # read "agree on 46 pins" with the dedupe invisible — and a
        # silent per-entry skip is exactly how a real one-pin mismatch
        # could hide inside a PASS at larger drift.
        _total_raw = len(l9_ports) + len(l9_skipped)
        msg = (
            f"PASS — L9 ↔ RTL top ({rtl_top.name}) pin set + "
            f"direction agree on {len(l9_names)}/{_total_raw} pins"
        )
        if l9_skipped:
            _reasons = "; ".join(s["reason"] for s in l9_skipped[:6])
            msg += (f" ({len(l9_skipped)} L9 entr"
                    f"{'y' if len(l9_skipped) == 1 else 'ies'} skipped: "
                    f"{_reasons})")
        if only_rtl_debug:
            msg += (
                f" (RTL has {len(only_rtl_all)} extra port(s); "
                f"{len(only_rtl_debug)} are debug/scan/tb-only and "
                f"ignored: {only_rtl_debug})"
            )
        print(msg)
        # Any skip that is neither a duplicate nor a parse-shape issue
        # would be an unknown-reason skip — surface as WARN. (The two
        # known classes are tagged at the parser; anything else is a
        # parser bug worth seeing.)
        _unknown = [s for s in l9_skipped
                    if not (s["reason"].startswith("duplicate")
                            or s["reason"].startswith("unparseable"))]
        if _unknown:
            print(f"  WARN — {len(_unknown)} L9 entr"
                  f"{'y' if len(_unknown) == 1 else 'ies'} skipped for "
                  f"unknown reason: {_unknown}")
        for _a in _exclusion_advisories(
                only_l9_optional, reused_prefix_matched, reused_tied_off,
                reused_config_gated, reused_ip_passthrough,
                l3_alias_reconciled):
            print(_a)
        return 0

    # #345 salvage 1. EVERY advisory above says WHY a pin was EXCLUDED from
    # the mismatch set — config-gated, passthrough, tie-off, alias-reconciled.
    # They used to print only under `if not findings:`, i.e. only on PASS. So
    # on a FAIL a reader saw N findings and no record of what had been taken
    # OUT of that comparison, which is the one moment the exclusions matter:
    # if an exclusion rule is wrong, the finding list is wrong, and the
    # evidence that would show it was suppressed exactly then. Printed on all
    # three paths now.
    _advisories = _exclusion_advisories(
        only_l9_optional, reused_prefix_matched, reused_tied_off,
        reused_config_gated, reused_ip_passthrough, l3_alias_reconciled)

    is_waived, rationale = waived(project)
    if is_waived:
        print(
            f"PASS_WITH_WAIVER — {len(findings)} finding(s) waived: "
            f"{rationale[:80]}"
        )
        for f in findings:
            print(f"  · {f}")
        for _a in _advisories:
            print(_a)
        return 0

    print(
        f"FAIL — L9 ↔ RTL top pin/direction mismatch "
        f"({rtl_top.name}): {len(findings)} finding(s)"
    )
    for f in findings:
        print(f"  · {f}")
    for _a in _advisories:
        print(_a)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
