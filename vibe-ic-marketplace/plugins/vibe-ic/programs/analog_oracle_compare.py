"""analog_oracle_compare.py — deterministic analog-benchmark comparator.

Given a Plugin project directory (with `analog/<block>/spec.json`,
`topology.md`, `<block>.sp`, `corner_results.json`, etc.) and an
`oracle_specs.json` file produced by the Oracle Auditor persona,
emit a per-block + overall PASS / PASS_WITH_NOTES / FAIL verdict
on numeric tolerance bands. Re-running on the same artefacts MUST
produce the same verdict — no randomness, no clock, no environment
sensitivity. This is the determinism guarantee the user asked for.

Usage:
    python3 analog_oracle_compare.py <project_dir> \\
        [--oracle <path-to-oracle_specs.json>] \\
        [--tolerance-config <path>] \\
        [--out-json <path>] \\
        [--out-md <path>]

When `--oracle` is omitted the runner looks for
`<project_dir>/analog/oracle_specs.json`.

Output (under `<project_dir>/reports/` by default):
    analog_oracle_compare.json   — machine-readable verdict tree
    analog_oracle_compare.md     — human-readable summary

Chip-AGNOSTIC. No chip-class literals. Pure numeric / set-membership
comparisons against a per-PDK declarative tolerance config.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)


# ---------------------------------------------------------------------------
# Default tolerance config — chip-AGNOSTIC, per-metric-class. Override via
# --tolerance-config <path> pointing at a JSON file with the same shape.
# ---------------------------------------------------------------------------
_DEFAULT_TOLERANCE = {
    # vout / vref targets: tight band — analog DC operating point
    "vout_target":      {"rel_pct": 5.0,   "abs_floor": 0.05},
    "vref":             {"rel_pct": 5.0,   "abs_floor": 0.05},

    # Bandgap-class targets — slightly looser because topology can vary
    "vbgr_target":      {"rel_pct": 10.0,  "abs_floor": 0.05},

    # PSRR / dropout / Iq / TC / PM / GBW — wider because metrics are
    # topology-dependent (a different LDO topology with the same spec
    # can legitimately come in at 0.5x or 2x on these without being
    # "wrong"). User can tighten via --tolerance-config.
    "psrr":             {"rel_pct": 30.0,  "abs_floor": 5.0},   # dB
    "dropout":          {"rel_pct": 50.0,  "abs_floor": 50.0},  # mV
    "iq":               {"rel_pct": 50.0,  "abs_floor": 10.0},  # µA
    "tc":               {"rel_pct": 50.0,  "abs_floor": 10.0},  # ppm/°C
    "pm":               {"rel_pct": 30.0,  "abs_floor": 5.0},   # deg
    "gbw":              {"rel_pct": 50.0,  "abs_floor": 1e3},   # Hz
    "line_regulation":  {"rel_pct": 50.0,  "abs_floor": 0.1},
    "load_regulation":  {"rel_pct": 50.0,  "abs_floor": 0.1},
    "iload_max":        {"rel_pct": 30.0,  "abs_floor": 5e-3},  # A
    "vin_min":          {"rel_pct": 10.0,  "abs_floor": 0.05},
    "vin_max":          {"rel_pct": 10.0,  "abs_floor": 0.05},

    # Topology — Jaccard similarity on the SET of device classes used.
    # Counts are checked separately under netlist.
    "topology_jaccard_min": 0.5,

    # Netlist — device-count match per class. Bands are wide because
    # different topology choices legitimately differ on count.
    "netlist_per_class_pct":   60.0,   # allow 60% mismatch per class
    "netlist_per_class_floor": 2,      # but at least 2 devices off OK
    "netlist_total_pct":       50.0,   # total device count band

    # GDS — file-existence + size sanity only (we do not deep-parse
    # GDS in the deterministic gate; that requires klayout).
    "gds_min_bytes": 1024,
}


@dataclass
class FieldCmp:
    field: str
    plugin: Any
    oracle: Any
    verdict: str          # PASS / FAIL / SKIP_MISSING_ORACLE / SKIP_MISSING_PLUGIN
    tolerance: Optional[Dict[str, float]] = None
    delta_abs: Optional[float] = None
    delta_pct: Optional[float] = None
    note: str = ""


@dataclass
class BlockCmp:
    name: str
    verdict: str          # PASS / PASS_WITH_NOTES / FAIL / SKIP
    spec_match:     Dict[str, Any] = field(default_factory=dict)
    topology_match: Dict[str, Any] = field(default_factory=dict)
    netlist_match:  Dict[str, Any] = field(default_factory=dict)
    a4_match:       Dict[str, Any] = field(default_factory=dict)
    gds_match:      Dict[str, Any] = field(default_factory=dict)
    notes:          List[str]      = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers — numeric tolerance comparison
# ---------------------------------------------------------------------------
def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _cmp_numeric(field_name: str, plugin: Any, oracle: Any,
                 tol: Dict[str, float]) -> FieldCmp:
    if oracle is None:
        return FieldCmp(field=field_name, plugin=plugin, oracle=oracle,
                        verdict="SKIP_MISSING_ORACLE",
                        note="Oracle did not publish this metric.")
    if plugin is None:
        return FieldCmp(field=field_name, plugin=plugin, oracle=oracle,
                        verdict="SKIP_MISSING_PLUGIN",
                        note="Plugin spec.json does not declare this metric.")
    if not (_is_num(plugin) and _is_num(oracle)):
        # String / categorical fields fall back to exact match
        verdict = "PASS" if str(plugin) == str(oracle) else "FAIL"
        return FieldCmp(field=field_name, plugin=plugin, oracle=oracle,
                        verdict=verdict,
                        note="categorical-exact-match")
    delta = float(plugin) - float(oracle)
    abs_d = abs(delta)
    denom = abs(float(oracle)) if float(oracle) != 0.0 else 1.0
    pct_d = (abs_d / denom) * 100.0
    rel = tol.get("rel_pct", 5.0)
    floor = tol.get("abs_floor", 0.0)
    ok = (pct_d <= rel) or (abs_d <= floor)
    return FieldCmp(field=field_name, plugin=plugin, oracle=oracle,
                    verdict="PASS" if ok else "FAIL",
                    tolerance=tol, delta_abs=abs_d, delta_pct=pct_d)


# ---------------------------------------------------------------------------
# Helpers — read project + oracle artefacts
# ---------------------------------------------------------------------------
def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _read_text(path: Path) -> str:
    try:
        return path.read_text(errors="ignore")
    except Exception:
        return ""


# v1.6.604 — netlist device-class extraction. Counts SPICE primitives
# by leading-letter convention + sky130-style subckt-call names. Chip-
# AGNOSTIC: pure SPICE syntax — no PDK-specific token in the regex.
_SPICE_DEVICE_RE = re.compile(
    r"(?m)^\s*([XMQDRCLIVE])\w+\s+[^\n]*",
    re.IGNORECASE,
)
_SPICE_SUBCKT_CALL_RE = re.compile(
    r"(?m)^\s*X\w+\s+[\w\s]*?\s+(sky130_fd_pr__\w+|\w+__\w+)\s*[\(\s]",
    re.IGNORECASE,
)


def _classify_model_token(model: str) -> Optional[str]:
    """Map a SPICE model name (e.g. `sky130_fd_pr__nfet_g5v0d10v5`,
    `pfet`, `cap_mim_m3_1`, `res_high_po`) to a canonical analog
    device class. Returns None when no token recognised. Chip-
    AGNOSTIC: vocabulary is generic (nfet/pfet/cap/res/diode/bjt)."""
    if not model:
        return None
    m = model.lower()
    if "nfet" in m or m.endswith("_n") or m == "nmos":
        return "nfet"
    if "pfet" in m or m.endswith("_p") or m == "pmos":
        return "pfet"
    # v1.6.605 — unify cap_mim and cap into one canonical class so
    # oracle (using sky130 specific cap_mim_m3_1) and plugin (using
    # generic "cap" vocabulary in topology.md) compare equal.
    if "cap" in m:
        return "cap"
    if "res" in m:
        return "res"
    if "diode" in m:
        return "diode"
    if ("bjt" in m or "pnp" in m or "npn" in m
            or m.startswith("q")):
        return "bjt"
    # sky130 hvl standard-cell buffers / inverters / schmitts —
    # POR-class block uses these as digital level-shifter / shaping
    # primitives. Map to canonical labels so the comparator can
    # see them as expected building blocks.
    if "schmitt" in m:
        return "schmitt"
    # Match both sky130_fd_sc_hvl__buf_8 and std_cell_hvl_buf_8 shapes
    if ("buf_8" in m or "__buf_" in m or "_buf_" in m
            or m.endswith("_buf")):
        return "buf"
    if ("inv_8" in m or "__inv_" in m or "_inv_" in m
            or m.endswith("_inv")):
        return "inv"
    return None


_SPICE_MULTIPLICITY_RE = re.compile(
    r"(?:^|\s)m\s*=\s*([1-9]\d*)", re.IGNORECASE)


def _extract_multiplicity(line: str) -> int:
    """v1.6.605 — extract SPICE `m=N` parameter from a device line.
    Defaults to 1. Oracle device counts (extracted by grepping X-
    lines from a flat testbench) treat `m=N` placements as N
    separate devices; this helper aligns plugin-side counting with
    that convention. Chip-AGNOSTIC: pure SPICE syntax."""
    m = _SPICE_MULTIPLICITY_RE.search(line)
    if not m:
        return 1
    try:
        return int(m.group(1))
    except (ValueError, TypeError):
        return 1


def _count_spice_devices(text: str) -> Dict[str, int]:
    """Return a dict like {'nfet': 12, 'pfet': 8, 'cap_mim': 2,
    'res': 4, ...} by inspecting SPICE primitive prefixes and
    sky130-style subckt names. v1.6.605 — counts `m=N`
    multiplicities so a single SPICE X-line with `m=8` registers as
    8 devices (aligns with oracle device-count convention). Chip-
    AGNOSTIC."""
    classes: Dict[str, int] = {}
    for m in _SPICE_DEVICE_RE.finditer(text):
        line = m.group(0)
        letter = m.group(1).upper()
        # Refine M-prefix MOS lines by peeking at the model token
        # (6th word: `Mname drain gate source bulk MODEL ...`).
        if letter == "M":
            toks = line.split()
            model_tok = toks[5] if len(toks) >= 6 else ""
            cls = _classify_model_token(model_tok) or "mos"
        # X-prefix subckt calls: scan all tokens for a recognised
        # model name (sky130_fd_pr__nfet, sky130_fd_pr__cap_mim, ...).
        elif letter == "X":
            cls = None
            for tok in line.split():
                hit = _classify_model_token(tok)
                if hit:
                    cls = hit
                    break
            if cls is None:
                cls = "subckt"
        else:
            cls = {
                "Q": "bjt",
                "D": "diode",
                "R": "res",
                "C": "cap",
                "L": "ind",
                "V": "vsrc",
                "I": "isrc",
                "E": "vcvs",
            }.get(letter)
            if cls is None:
                continue
        mult = _extract_multiplicity(line)
        classes[cls] = classes.get(cls, 0) + mult
    # Drop zero/negative
    classes = {k: v for k, v in classes.items() if v > 0}
    return classes


def _extract_subckt_name(text: str) -> Optional[str]:
    m = re.search(r"(?im)^\s*\.subckt\s+(\w+)", text)
    return m.group(1) if m else None


def _topology_classes_from_md(text: str) -> set:
    """Extract device-class words from a topology.md prose. Looks for
    common analog vocabulary (pmos, nmos, pfet, nfet, cap, res, bjt,
    diode, opamp, mirror, diff_pair). Chip-AGNOSTIC."""
    vocab = {"pmos", "nmos", "pfet", "nfet", "cap", "res", "bjt",
             "diode", "opamp", "mirror", "current_mirror",
             "differential_pair", "diff_pair", "cascode", "schmitt",
             "comparator", "amplifier", "bandgap", "ldo",
             "pass_device", "error_amp", "feedback_divider",
             "compensation"}
    seen: set = set()
    lc = text.lower()
    for w in vocab:
        if w in lc:
            # Normalise pmos/pfet, nmos/nfet (treat as equivalent)
            if w in ("pmos", "pfet"):
                seen.add("pfet")
            elif w in ("nmos", "nfet"):
                seen.add("nfet")
            elif w in ("current_mirror", "mirror"):
                seen.add("mirror")
            elif w in ("differential_pair", "diff_pair"):
                seen.add("diff_pair")
            else:
                seen.add(w)
    return seen


# ---------------------------------------------------------------------------
# Per-section compare
# ---------------------------------------------------------------------------
_SPEC_FIELDS = (
    "vout_target", "vref", "vbgr_target",
    "psrr", "dropout", "iq", "tc", "pm", "gbw",
    "line_regulation", "load_regulation",
    "iload_max", "vin_min", "vin_max",
)


# Canonical alias map for spec field names. Oracle and Plugin can write
# the spec.json with unit suffixes (sky130 / mabrains convention) OR
# unit-less canonical names; comparator normalises both into the
# canonical key + canonical unit before comparing. Chip-AGNOSTIC.
#
# unit convention (canonical):
#   vout_target / vref / vbgr_target / vin_*  → V
#   iq                                        → µA
#   iload_max                                 → mA
#   psrr / pm                                 → dB / deg
#   tc                                        → ppm/°C
#   dropout                                   → mV
#   gbw                                       → Hz
#   line_regulation / load_regulation         → mV / unit
_SPEC_ALIAS = {
    # vout / vref / vbg
    "vout_target_v":      "vout_target",
    "vout_target_V":      "vout_target",
    "vout":               "vout_target",
    "vref_v":             "vref",
    "vref_V":             "vref",
    "vbgr_target_v":      "vbgr_target",
    "vbg_target_v":       "vbgr_target",
    "vbg_target_V":       "vbgr_target",
    "vbgr_target_V":      "vbgr_target",
    "vbg":                "vbgr_target",
    # input rail
    "vin_min_v":          "vin_min",
    "vin_min_V":          "vin_min",
    "vin_max_v":          "vin_max",
    "vin_max_V":          "vin_max",
    "vin_nominal_v":      "vin_nominal",
    "vin_nominal_V":      "vin_nominal",
    # current
    "iq_ua":              "iq",
    "Iq_uA":              "iq",
    "iq_uA":              "iq",
    "Iquiescent_uA":      "iq",
    "iload_max_ma":       "iload_max",
    "Iload_max_mA":       "iload_max",
    "iload_max_mA":       "iload_max",
    # supply-rejection / phase margin
    "psrr_db":            "psrr",
    "PSRR_dB":            "psrr",
    "psrr_dB":            "psrr",
    "PSRR_dB_100Hz":      "psrr",   # canonical: 100Hz value
    "psrr_db_100hz":      "psrr",
    "pm_deg":             "pm",
    "PM_deg":             "pm",
    "pm_degrees":         "pm",
    # temperature coefficient
    "tc_ppm_per_c":       "tc",
    "TC_ppm_per_C":       "tc",
    "tc_ppm_per_C":       "tc",
    # dropout
    "dropout_mv":         "dropout",
    "dropout_mV":         "dropout",
    "dropout_mV_at_0p1mA": "dropout",  # mabrains convention
    "dropout_mV_at_100mA": "dropout_full_load",
    # bandwidth
    "gbw_hz":             "gbw",
    "GBW_Hz":             "gbw",
    "bandwidth_hz":       "gbw",
    # regulation
    "line_regulation_mv_per_v":  "line_regulation",
    "load_regulation_mv_per_a":  "load_regulation",
}


def _normalize_spec(spec: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """v1.6.604 — normalise spec field names from unit-suffixed
    (oracle / sky130 convention) into the canonical _SPEC_FIELDS
    set. Identity-passes through any field already in canonical
    form. Chip-AGNOSTIC. When two aliases would collapse to the
    same canonical key, the FIRST (oracle-published) value wins
    (oracle is the ground truth)."""
    if not spec:
        return {}
    out: Dict[str, Any] = {}
    for k, v in spec.items():
        # Try exact alias first, then lower-cased alias
        canonical = _SPEC_ALIAS.get(k) or _SPEC_ALIAS.get(k.lower()) or k
        if canonical not in out:
            out[canonical] = v
    return out


def _compare_spec(plugin_spec: Optional[Dict[str, Any]],
                  oracle_spec:  Optional[Dict[str, Any]],
                  tol_cfg: Dict[str, Any]) -> Dict[str, Any]:
    plugin_spec = _normalize_spec(plugin_spec)
    oracle_spec = _normalize_spec(oracle_spec)
    if not oracle_spec:
        return {"verdict": "SKIP_MISSING_ORACLE", "per_field": {}}
    plugin_spec = plugin_spec or {}
    per_field: Dict[str, Any] = {}
    n_pass = n_fail = n_skip = 0
    for fld in _SPEC_FIELDS:
        tol = tol_cfg.get(fld, {"rel_pct": 10.0, "abs_floor": 0.0})
        cmp = _cmp_numeric(fld, plugin_spec.get(fld),
                           oracle_spec.get(fld), tol)
        per_field[fld] = {
            "plugin": cmp.plugin, "oracle": cmp.oracle,
            "verdict": cmp.verdict,
            "delta_abs": cmp.delta_abs, "delta_pct": cmp.delta_pct,
            "tolerance": cmp.tolerance, "note": cmp.note,
        }
        if cmp.verdict == "PASS":
            n_pass += 1
        elif cmp.verdict == "FAIL":
            n_fail += 1
        else:
            n_skip += 1
    if n_fail > 0:
        verdict = "FAIL"
    elif n_pass == 0:
        # Everything skipped — no comparison happened
        verdict = "SKIP"
    elif n_skip > 0:
        verdict = "PASS_WITH_NOTES"
    else:
        verdict = "PASS"
    return {"verdict": verdict, "per_field": per_field,
            "summary": {"pass": n_pass, "fail": n_fail, "skip": n_skip}}


def _normalize_oracle_device_set(devs: Optional[List[str]]) -> set:
    """v1.6.604 — normalise a list of device-class tokens (which may
    use sky130 full model names like `sky130_fd_pr__nfet_g5v0d10v5`,
    `cap_mim_m3_1`, `res_xhigh_po_0p69`, or generic tokens like
    `pfet`, `nfet`, `cap`) into the canonical comparator vocabulary.
    Chip-AGNOSTIC."""
    out: set = set()
    for d in devs or []:
        hit = _classify_model_token(d) if d else None
        if hit:
            out.add(hit)
        elif d:
            # Already-canonical token (pfet / nfet / mirror / amp / etc.)
            out.add(d.lower())
    return out


def _compare_topology(plugin_md: str,
                      oracle_topo: Optional[Dict[str, Any]],
                      tol_cfg: Dict[str, Any]) -> Dict[str, Any]:
    if not oracle_topo:
        return {"verdict": "SKIP_MISSING_ORACLE"}
    if not plugin_md.strip():
        return {"verdict": "SKIP_MISSING_PLUGIN"}
    plugin_set = _topology_classes_from_md(plugin_md)
    # Accept both 'device_classes' (canonical) and 'device_classes_used'
    # (oracle-auditor convention) keys.
    raw_oracle_devs = (oracle_topo.get("device_classes")
                        or oracle_topo.get("device_classes_used"))
    oracle_set = _normalize_oracle_device_set(raw_oracle_devs)
    if not oracle_set:
        return {"verdict": "SKIP_MISSING_ORACLE",
                "note": "oracle_topo has no device_classes list"}
    inter = plugin_set & oracle_set
    union = plugin_set | oracle_set
    jaccard = len(inter) / len(union) if union else 0.0
    # v1.6.605 — Oracle-coverage ratio is the primary topology
    # metric: "does plugin topology cover what oracle says is in the
    # design?" Less harsh than Jaccard on asymmetric sets where the
    # plugin's topology.md naturally enumerates more architectural
    # vocabulary (error_amp, mirror, diff_pair, ...) than the oracle's
    # compact device-class list.
    oracle_coverage = (len(inter) / len(oracle_set)
                       if oracle_set else 0.0)
    thr_cov = float(tol_cfg.get("topology_oracle_coverage_min", 0.7))
    thr_jac = float(tol_cfg.get("topology_jaccard_min", 0.5))
    # Verdict precedence: PASS if oracle_coverage meets threshold
    # (plugin captures the device classes oracle declares). Falls
    # back to Jaccard for legacy callers / pathological cases. FAIL
    # only when neither metric is met.
    if oracle_coverage >= thr_cov:
        verdict = "PASS"
    elif jaccard >= thr_jac:
        verdict = "PASS_WITH_NOTES"
    else:
        verdict = "FAIL"
    return {"verdict": verdict,
            "jaccard": jaccard, "threshold": thr_jac,
            "oracle_coverage": oracle_coverage,
            "oracle_coverage_threshold": thr_cov,
            "plugin_classes": sorted(plugin_set),
            "oracle_classes": sorted(oracle_set),
            "intersection": sorted(inter),
            "plugin_only": sorted(plugin_set - oracle_set),
            "oracle_only": sorted(oracle_set - plugin_set)}


def _compare_netlist(plugin_sp_text: str,
                     oracle_netlist: Optional[Dict[str, Any]],
                     tol_cfg: Dict[str, Any]) -> Dict[str, Any]:
    if not oracle_netlist:
        return {"verdict": "SKIP_MISSING_ORACLE"}
    if not plugin_sp_text.strip():
        return {"verdict": "SKIP_MISSING_PLUGIN"}
    # v1.6.605 — when oracle netlist has both total_devices=None AND
    # by_class=None (auditor skipped flat-testbench / no LVS subckt
    # available), there is nothing to compare against — SKIP rather
    # than FAIL.
    if (oracle_netlist.get("total_devices") in (None, 0)
            and not oracle_netlist.get("by_class")):
        return {"verdict": "SKIP_MISSING_ORACLE",
                "note": ("oracle netlist not characterised "
                         "(flat testbench or no LVS subckt)")}
    plugin_counts = _count_spice_devices(plugin_sp_text)
    plugin_total = sum(plugin_counts.values())
    plugin_subckt = _extract_subckt_name(plugin_sp_text)
    # v1.6.604 — normalise oracle by_class keys (sky130 full model
    # names → canonical class). Each oracle key is mapped via
    # _classify_model_token; unmapped keys keep their original name
    # so e.g. a custom 'bjt_pnp' lane survives.
    #
    # v1.6.606 — symmetric m=N unrolling: when the oracle audit
    # publishes `by_class_m_unrolled` + `total_devices_m_unrolled`
    # (auditor v2 convention), prefer those keys so both sides count
    # multiplicity the same way. Falls back to `by_class` +
    # `total_devices` when the auditor only published raw counts.
    raw_oracle_counts = (oracle_netlist.get("by_class_m_unrolled")
                         or oracle_netlist.get("by_class")
                         or {})
    raw_oracle_counts = dict(raw_oracle_counts)
    # v1.6.606 — defensive: auditors sometimes interleave free-form
    # metadata (`total`, `source`, `note`) into otherwise-numeric
    # by_class dicts. Skip keys that are NOT a device class and skip
    # non-numeric values.
    _METADATA_KEYS = {"total", "source", "note", "convention",
                       "method", "count_method", "comment",
                       "notes", "description"}
    oracle_counts: Dict[str, int] = {}
    for k, v in raw_oracle_counts.items():
        if k.lower() in _METADATA_KEYS:
            continue
        try:
            count_val = int(v or 0)
        except (TypeError, ValueError):
            continue
        canon = _classify_model_token(k) or k.lower()
        oracle_counts[canon] = oracle_counts.get(canon, 0) + count_val
    oracle_total_raw = (oracle_netlist.get("total_devices_m_unrolled")
                        or oracle_netlist.get("total_devices_raw")
                        or oracle_netlist.get("total_devices")
                        or sum(oracle_counts.values()))
    oracle_total = int(oracle_total_raw or 0)
    oracle_subckt = oracle_netlist.get("top_module_name")
    # Per-class tolerance
    per_class: Dict[str, Any] = {}
    n_pass = n_fail = 0
    pct = float(tol_cfg.get("netlist_per_class_pct", 60.0))
    floor = int(tol_cfg.get("netlist_per_class_floor", 2))
    for cls in sorted(set(plugin_counts) | set(oracle_counts)):
        p_n = plugin_counts.get(cls, 0)
        o_n = oracle_counts.get(cls, 0)
        delta = abs(p_n - o_n)
        denom = max(o_n, 1)
        delta_pct = (delta / denom) * 100.0
        ok = (delta <= floor) or (delta_pct <= pct)
        per_class[cls] = {"plugin": p_n, "oracle": o_n,
                          "delta": delta, "delta_pct": delta_pct,
                          "verdict": "PASS" if ok else "FAIL"}
        if ok:
            n_pass += 1
        else:
            n_fail += 1
    # Total
    delta_tot = abs(plugin_total - oracle_total)
    denom_tot = max(oracle_total, 1)
    delta_pct_tot = (delta_tot / denom_tot) * 100.0
    tot_pct = float(tol_cfg.get("netlist_total_pct", 50.0))
    tot_ok = (delta_pct_tot <= tot_pct) or (delta_tot <= floor)
    # Subckt
    subckt_match = (plugin_subckt and oracle_subckt and
                    plugin_subckt == oracle_subckt)
    if n_fail > 0 or not tot_ok:
        verdict = "FAIL"
    else:
        verdict = "PASS" if subckt_match else "PASS_WITH_NOTES"
    return {"verdict": verdict,
            "plugin_total": plugin_total, "oracle_total": oracle_total,
            "total_delta_pct": delta_pct_tot,
            "plugin_subckt": plugin_subckt,
            "oracle_subckt": oracle_subckt,
            "subckt_match": bool(subckt_match),
            "per_class": per_class,
            "summary": {"pass_classes": n_pass, "fail_classes": n_fail}}


def _compare_a4(corner_results: Optional[Dict[str, Any]],
                oracle_spec: Optional[Dict[str, Any]],
                tol_cfg: Dict[str, Any]) -> Dict[str, Any]:
    if not corner_results:
        return {"verdict": "SKIP_MISSING_PLUGIN"}
    if not oracle_spec:
        return {"verdict": "SKIP_MISSING_ORACLE"}
    # Normalise oracle keys (handles vout_target_V etc.)
    oracle_spec = _normalize_spec(oracle_spec)
    target = (oracle_spec.get("vout_target") or
              oracle_spec.get("vref") or
              oracle_spec.get("vbgr_target"))
    if target is None:
        return {"verdict": "SKIP_MISSING_ORACLE",
                "note": "oracle has no vout-class target"}
    # Plugin corner_results.json shape: {"corners": [{"vout": ...}, ...]}
    # OR a flat {"vout": x, "verdict": ...} when single corner.
    vouts: List[float] = []
    if isinstance(corner_results.get("corners"), list):
        for c in corner_results["corners"]:
            v = c.get("vout")
            if _is_num(v):
                vouts.append(float(v))
    if not vouts and _is_num(corner_results.get("vout")):
        vouts.append(float(corner_results["vout"]))
    if not vouts:
        return {"verdict": "SKIP_MISSING_PLUGIN",
                "note": "corner_results has no numeric vout entries"}
    tol = tol_cfg.get("vout_target", {"rel_pct": 5.0, "abs_floor": 0.05})
    rel = float(tol["rel_pct"])
    floor = float(tol.get("abs_floor", 0.0))
    pass_count = fail_count = 0
    detail: List[Dict[str, Any]] = []
    for v in vouts:
        d = abs(v - float(target))
        denom = abs(float(target)) if float(target) != 0.0 else 1.0
        pct = (d / denom) * 100.0
        ok = (pct <= rel) or (d <= floor)
        detail.append({"vout": v, "delta_abs": d,
                       "delta_pct": pct, "ok": ok})
        if ok:
            pass_count += 1
        else:
            fail_count += 1
    if fail_count == 0:
        verdict = "PASS"
    elif pass_count == 0:
        verdict = "FAIL"
    else:
        verdict = "PASS_WITH_NOTES"
    return {"verdict": verdict, "target": target,
            "pass_corners": pass_count, "fail_corners": fail_count,
            "corners": detail}


def _compare_gds(plugin_gds: Optional[Path],
                 oracle_gds: Optional[Dict[str, Any]],
                 tol_cfg: Dict[str, Any]) -> Dict[str, Any]:
    if not oracle_gds:
        return {"verdict": "SKIP_MISSING_ORACLE"}
    if plugin_gds is None or not plugin_gds.is_file():
        return {"verdict": "SKIP_MISSING_PLUGIN"}
    size = plugin_gds.stat().st_size
    min_bytes = int(tol_cfg.get("gds_min_bytes", 1024))
    ok = size >= min_bytes
    return {"verdict": "PASS" if ok else "FAIL",
            "plugin_path": str(plugin_gds), "plugin_size": size,
            "oracle_size": oracle_gds.get("file_size"),
            "min_bytes": min_bytes}


# ---------------------------------------------------------------------------
# Block-level + overall verdict roll-up
# ---------------------------------------------------------------------------
def _roll_up(section_verdicts: List[str]) -> str:
    """Roll up a list of section verdicts into a single block verdict.

    Rules (chip-AGNOSTIC):
    - any FAIL  → FAIL
    - all SKIP* → SKIP
    - any PASS_WITH_NOTES or any SKIP*  → PASS_WITH_NOTES
    - all PASS → PASS
    """
    s = [v.upper() for v in section_verdicts]
    if any(v == "FAIL" for v in s):
        return "FAIL"
    skip_kinds = {"SKIP", "SKIP_MISSING_ORACLE", "SKIP_MISSING_PLUGIN"}
    if all(v in skip_kinds for v in s):
        return "SKIP"
    if any(v == "PASS_WITH_NOTES" or v in skip_kinds for v in s):
        return "PASS_WITH_NOTES"
    return "PASS"


def _compare_block(project: Path, block_name: str,
                   oracle_block: Dict[str, Any],
                   tol_cfg: Dict[str, Any]) -> BlockCmp:
    bdir = project / "phase3" / "analog" / block_name
    plugin_spec = _read_json(bdir / "spec.json")
    plugin_topo = _read_text(bdir / "topology.md")
    # SPICE netlist file may be named after the block or be just .sp
    sp_candidates = list(bdir.glob("*.sp")) + list(bdir.glob("*.spice"))
    plugin_sp_text = ""
    if sp_candidates:
        plugin_sp_text = _read_text(sp_candidates[0])
    plugin_corner = _read_json(bdir / "corner_results.json")
    gds_candidates = (list(bdir.glob("*.gds")) +
                      list((project / "phase3" / "analog" / "hardmacro" /
                            block_name).glob("*.gds")))
    plugin_gds = gds_candidates[0] if gds_candidates else None

    spec_m  = _compare_spec(plugin_spec, oracle_block.get("spec"),  tol_cfg)
    topo_m  = _compare_topology(plugin_topo, oracle_block.get("topology"),
                                tol_cfg)
    net_m   = _compare_netlist(plugin_sp_text, oracle_block.get("netlist"),
                               tol_cfg)
    a4_m    = _compare_a4(plugin_corner, oracle_block.get("spec"), tol_cfg)
    gds_m   = _compare_gds(plugin_gds, oracle_block.get("gds"), tol_cfg)

    verdict = _roll_up([spec_m.get("verdict", "SKIP"),
                        topo_m.get("verdict", "SKIP"),
                        net_m.get("verdict",  "SKIP"),
                        a4_m.get("verdict",   "SKIP"),
                        gds_m.get("verdict",  "SKIP")])
    return BlockCmp(name=block_name, verdict=verdict,
                    spec_match=spec_m, topology_match=topo_m,
                    netlist_match=net_m, a4_match=a4_m, gds_match=gds_m)


# ---------------------------------------------------------------------------
# Markdown emitter
# ---------------------------------------------------------------------------
def _format_md(result: Dict[str, Any]) -> str:
    out: List[str] = []
    out.append("# Analog Oracle Compare Report")
    out.append("")
    meta = result.get("_meta", {})
    out.append(f"**Project**: `{meta.get('project_dir')}`")
    out.append(f"**Oracle**: `{meta.get('oracle_path')}`")
    out.append(f"**Overall verdict**: **{result.get('overall_verdict')}**")
    out.append("")
    out.append("## Per-block verdict")
    out.append("")
    out.append("| Block | Verdict | Spec | Topology | Netlist | A4 | GDS |")
    out.append("|-------|---------|------|----------|---------|----|-----|")
    for name, b in (result.get("blocks") or {}).items():
        out.append(
            f"| {name} | **{b['verdict']}** | "
            f"{b['spec_match'].get('verdict','-')} | "
            f"{b['topology_match'].get('verdict','-')} | "
            f"{b['netlist_match'].get('verdict','-')} | "
            f"{b['a4_match'].get('verdict','-')} | "
            f"{b['gds_match'].get('verdict','-')} |")
    out.append("")
    for name, b in (result.get("blocks") or {}).items():
        out.append(f"## Block `{name}` — {b['verdict']}")
        s = b["spec_match"]
        if s.get("per_field"):
            out.append("### Spec")
            out.append("")
            out.append("| Field | Plugin | Oracle | Δ% | Verdict |")
            out.append("|-------|--------|--------|----|---------|")
            for fld, pf in s["per_field"].items():
                d = pf.get("delta_pct")
                dstr = f"{d:.1f}%" if isinstance(d, (int, float)) else "-"
                out.append(
                    f"| {fld} | {pf.get('plugin')} | "
                    f"{pf.get('oracle')} | {dstr} | "
                    f"{pf.get('verdict')} |")
            out.append("")
        t = b["topology_match"]
        if t.get("jaccard") is not None:
            out.append("### Topology")
            out.append("")
            out.append(f"- Jaccard: **{t['jaccard']:.2f}** "
                       f"(threshold {t['threshold']})")
            out.append(f"- Intersection: {t.get('intersection')}")
            out.append(f"- Plugin-only: {t.get('plugin_only')}")
            out.append(f"- Oracle-only: {t.get('oracle_only')}")
            out.append("")
        n = b["netlist_match"]
        if n.get("plugin_total") is not None:
            out.append("### Netlist")
            out.append("")
            out.append(
                f"- Total devices: plugin={n['plugin_total']}, "
                f"oracle={n['oracle_total']} "
                f"(Δ {n['total_delta_pct']:.1f}%)")
            out.append(f"- Subckt match: {n.get('subckt_match')} "
                       f"(plugin={n.get('plugin_subckt')}, "
                       f"oracle={n.get('oracle_subckt')})")
            if n.get("per_class"):
                out.append("")
                out.append("| Class | Plugin | Oracle | Δ | Verdict |")
                out.append("|-------|--------|--------|---|---------|")
                for cls, pc in n["per_class"].items():
                    out.append(
                        f"| {cls} | {pc['plugin']} | {pc['oracle']} | "
                        f"{pc['delta']} | {pc['verdict']} |")
            out.append("")
        a = b["a4_match"]
        if a.get("corners"):
            out.append("### A4 corner sweep")
            out.append("")
            out.append(f"- target = {a.get('target')}")
            out.append(f"- corners: {a['pass_corners']} PASS / "
                       f"{a['fail_corners']} FAIL")
            out.append("")
        g = b["gds_match"]
        if g.get("plugin_path"):
            out.append("### GDS")
            out.append("")
            out.append(f"- plugin={g['plugin_path']} ({g['plugin_size']}B) "
                       f"oracle_size={g.get('oracle_size')}")
            out.append("")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def run(project_dir: Path,
        oracle_path: Optional[Path] = None,
        tolerance_config: Optional[Path] = None,
        out_json: Optional[Path] = None,
        out_md: Optional[Path] = None) -> Dict[str, Any]:
    if oracle_path is None:
        oracle_path = project_dir / "phase3" / "analog" / "oracle_specs.json"
    oracle = _read_json(oracle_path) or {}
    tol_cfg = dict(_DEFAULT_TOLERANCE)
    if tolerance_config and tolerance_config.is_file():
        override = _read_json(tolerance_config) or {}
        # Shallow-merge: per-metric dicts override, scalars override
        for k, v in override.items():
            tol_cfg[k] = v

    blocks_out: Dict[str, Any] = {}
    for name, oracle_block in (oracle.get("blocks") or {}).items():
        bcmp = _compare_block(project_dir, name, oracle_block, tol_cfg)
        blocks_out[name] = {
            "verdict": bcmp.verdict,
            "spec_match": bcmp.spec_match,
            "topology_match": bcmp.topology_match,
            "netlist_match": bcmp.netlist_match,
            "a4_match": bcmp.a4_match,
            "gds_match": bcmp.gds_match,
        }

    overall = _roll_up([b["verdict"] for b in blocks_out.values()]) \
        if blocks_out else "SKIP"

    result = {
        "_meta": {
            "comparator_version": _pmd.emitted_by(
                "analog_oracle_compare"),
            "project_dir": str(project_dir),
            "oracle_path": str(oracle_path),
            "tolerance_config": str(tolerance_config) if tolerance_config else None,
        },
        "overall_verdict": overall,
        "blocks": blocks_out,
    }

    # Emit
    out_json = out_json or (project_dir / "reports" /
                            "analog_oracle_compare.json")
    out_md = out_md or (project_dir / "reports" /
                        "analog_oracle_compare.md")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, indent=2))
    out_md.write_text(_format_md(result))
    return result


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Deterministic analog-benchmark comparator")
    ap.add_argument("project", type=Path,
                    help="Plugin project directory")
    ap.add_argument("--oracle", type=Path,
                    help="Path to oracle_specs.json "
                         "(default: <project>/analog/oracle_specs.json)")
    ap.add_argument("--tolerance-config", type=Path,
                    help="JSON file overriding _DEFAULT_TOLERANCE")
    ap.add_argument("--out-json", type=Path)
    ap.add_argument("--out-md",   type=Path)
    args = ap.parse_args(argv)
    result = run(args.project, args.oracle,
                 args.tolerance_config, args.out_json, args.out_md)
    print(f"Overall verdict: {result['overall_verdict']}")
    for name, b in (result["blocks"] or {}).items():
        print(f"  {name:>10s}: {b['verdict']}")
    # Exit non-zero only on FAIL (PASS_WITH_NOTES is acceptable signal)
    return 0 if result["overall_verdict"] != "FAIL" else 2


if __name__ == "__main__":
    sys.exit(main())
