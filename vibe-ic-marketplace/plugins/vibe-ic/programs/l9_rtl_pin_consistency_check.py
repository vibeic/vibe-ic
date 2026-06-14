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
  - QSF/SDC generators (`aid_class_qsf_gen` / `aid_class_sdc_gen`) read
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


def _manifest_name_set(manifest: dict, keys: tuple[str, ...]) -> set:
    """Collect interface/port names from any of `keys` in the manifest.

    Tolerates each value being a list of strings, a list of dicts (each
    carrying a `name`/`port`/`interface`/`root` field), or a dict whose
    KEYS are the interface names. Chip-AGNOSTIC: structure-only, no
    literal. Returns a set of stripped names."""
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


def parse_rtl_top_ports(rtl_path: Path,
                        top_name: Optional[str] = None) -> list[dict]:
    """Parse `module <name>(...);` and emit [{name, direction}].

    Supports the SystemVerilog `module foo import pkg::*;
    (input wire clk, output id_tx_en, inout id_bus, ...)` shape.

    ORGANIC-20260614 — when `top_name` is supplied (the L9-declared top
    that `find_rtl_top` already resolved the FILE by), the port-list regex
    is ANCHORED to that specific module header
    (`module <re.escape(top_name)>\\b ... ( ... );`) so a multi-module
    bundle file whose top is NOT declared first is parsed at the CORRECT
    module — not the first `module` in the file. When `top_name` is None,
    or the named module is absent from the file, the parser falls back to
    the historical first-module match (preserving behaviour for
    single-module files and name-mismatch edge cases). Chip-AGNOSTIC: the
    anchor is the resolved-top string itself, never a chip/vendor literal.
    """
    text = _strip_comments(rtl_path.read_text(errors="ignore"))
    # Strip the optional `#( ... )` parameter block with a balanced-paren
    # scanner BEFORE the port-list regex runs, so function-call defaults
    # like `$clog2(memsize)` (and nested calls) can't truncate the match
    # at an inner `)` and yield zero ports (#474).
    text = _strip_param_block(text)
    m = None
    if isinstance(top_name, str) and top_name.strip():
        # Anchor on the resolved top module header. `\b` after the escaped
        # name prevents `mytop` from matching `mytop_wrapper`. The optional
        # SV import clause(s) between the header and the port-list paren are
        # tolerated exactly as in the generic pattern below.
        m = re.search(
            r"module\s+" + re.escape(top_name.strip()) + r"\b\s*"
            r"(?:import\s+[\w:\*\s,]+;\s*)*"  # SV imports
            r"\(([^;]+?)\)\s*;",
            text,
            flags=re.DOTALL,
        )
    if m is None:
        # Fallback: first `module <name>(...)` in the file (historical
        # behaviour, correct for single-module files and when the named
        # top is absent / mis-spelled).
        m = re.search(
            r"module\s+\w+\s*"
            r"(?:import\s+[\w:\*\s,]+;\s*)*"  # SV imports
            r"\(([^;]+?)\)\s*;",
            text,
            flags=re.DOTALL,
        )
    if not m:
        return []
    body = m.group(1)
    out: list[dict] = []
    cur_dir: Optional[str] = None
    for line in body.split(","):
        toks = line.split()
        if not toks:
            continue
        # Detect direction token; carry forward when omitted (Verilog
        # `input a, b, c` shape).
        if toks[0].lower() in _DIR_NORMALIZE:
            cur_dir = _DIR_NORMALIZE[toks[0].lower()]
            toks = toks[1:]
        # Drop type / width tokens; the LAST token is the port name.
        if not toks:
            continue
        name = toks[-1].strip("[]()")
        # Skip pure type-only tokens (rare).
        if not re.match(r"^[A-Za-z_]\w*$", name):
            continue
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
    rtl_ports = parse_rtl_top_ports(rtl_top, top_name)
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

    only_l9_all = sorted(l9_names - rtl_names)
    only_rtl_all = sorted(rtl_names - l9_names)

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
    manifest = load_source_manifest(project)
    if manifest is not None:
        # ORGANIC #659 round-2 — also pass the chip_top instantiation's bound
        # port set so a glue-driven interface absent from the manifest tie_offs
        # dict (clk_edn_i / edn_o / IP-split edn) is recognised structurally.
        reused_bound_ports = _chip_top_bound_ports(rtl_top)
        (only_l9_all, only_rtl_all,
         reused_tied_off, reused_prefix_matched) = reconcile_reused_ip(
            only_l9_all, only_rtl_all, manifest,
            bound_ports=reused_bound_ports)

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

    # Direction-mismatch list (only for pins in BOTH).
    dir_mismatch: list[str] = []
    rtl_dir_map = {p["name"]: p["direction"] for p in rtl_ports}
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
        if only_l9_optional:
            # v0.3.4 — #491 R4 advisory (non-gating): doc-optional
            # pins the RTL top legitimately omits.
            print(
                f"  WARN (advisory) — L9 doc-OPTIONAL pin(s) not in "
                f"RTL top: {only_l9_optional}"
            )
        if reused_prefix_matched:
            # ORGANIC #659 advisory (non-gating): reused-IP struct-bus
            # roots reconciled with their prefix-expanded scalar pads.
            _pm = ", ".join(
                f"{root}→{pads}" for root, pads in reused_prefix_matched)
            print(
                f"  WARN (advisory) — reused-IP struct-bus flatten "
                f"reconciled (root ↔ prefix-expanded pads): {_pm}"
            )
        if reused_tied_off:
            # ORGANIC #659 advisory (non-gating): SOURCE_MANIFEST-
            # documented intentional tie-offs dropped from the L9-only diff.
            print(
                f"  WARN (advisory) — reused-IP SOURCE_MANIFEST tie-off(s) "
                f"omitted from RTL top (intentional, internally driven): "
                f"{reused_tied_off}"
            )
        return 0

    is_waived, rationale = waived(project)
    if is_waived:
        print(
            f"PASS_WITH_WAIVER — {len(findings)} finding(s) waived: "
            f"{rationale[:80]}"
        )
        for f in findings:
            print(f"  · {f}")
        return 0

    print(
        f"FAIL — L9 ↔ RTL top pin/direction mismatch "
        f"({rtl_top.name}): {len(findings)} finding(s)"
    )
    for f in findings:
        print(f"  · {f}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
