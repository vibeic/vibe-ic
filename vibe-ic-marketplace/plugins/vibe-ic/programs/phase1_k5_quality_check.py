#!/usr/bin/env python3
"""
phase1_k5_quality_check.py — catch the 6 K5 issues found by real Phase-2 synth.

Detects Phase-1 document patterns that produce weak / inconsistent RTL:

  K5-A  Templated L6 FSMs:   >=3 submodules share identical states list
  K5-B  Register overlap:    L4 register_map entries with overlapping ranges
  K5-C  Generic port map:    L9.submodules[*].ports_mapped uses boilerplate
  K5-D  Duplicate port keys: L9 ports have both "dir" and "direction"
  K5-E  Reset polarity split: L8 rst_i vs L9 rst_n
  K5-F  Missing crypto params: crypto-engine IC lacks key schedule

All WARN, not ERROR. Usage:
  python3 phase1_k5_quality_check.py <generated_docs/>
  python3 phase1_k5_quality_check.py --all
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

# Override via VIBE_IC_BENCHMARK_ROOT to point at the local benchmark tree.
# Default to cwd so the --all sweep simply finds nothing if the env var is
# unset, instead of pointing at a developer-specific worktree path.
WORKTREE = Path(os.environ.get("VIBE_IC_BENCHMARK_ROOT", "."))


def lenient_load(p):
    t = p.read_text()
    try: return json.loads(t)
    except json.JSONDecodeError:
        return json.loads(re.sub(
            r'(?P<pfx>[:\[\,\s])0x([0-9a-fA-F]+)',
            lambda m: m.group("pfx") + str(int(m.group(2), 16)), t))


def check_templated_fsms(l6):
    subs = l6.get("submodule_control_logic") if isinstance(l6, dict) else None
    if not isinstance(subs, dict) or len(subs) < 3: return []
    state_groups = Counter()
    for _, cfg in subs.items():
        if isinstance(cfg, dict):
            states = cfg.get("states")
            if isinstance(states, list) and states:
                state_groups[tuple(sorted(str(s).upper() for s in states))] += 1
    out = []
    for key, n in state_groups.items():
        if n >= 3:
            out.append({"id":"K5-A","severity":"warn",
                "msg":f"{n} submodules share identical states {list(key)} — templated default"})
    return out


def parse_addr_range(s):
    if not isinstance(s, str): return None
    m = re.match(r'^\s*(0x[0-9a-fA-F]+|\d+)\s*(?:-\s*(0x[0-9a-fA-F]+|\d+))?\s*$', s.strip())
    if not m: return None
    def _int(x): return int(x,16) if x and x.lower().startswith('0x') else int(x)
    a = _int(m.group(1))
    b = _int(m.group(2)) if m.group(2) else a
    return (a, b)


def check_register_overlap(l4):
    out = []
    regmap = None
    for k in ("register_map", "otp_map_128x8", "control_registers_logical"):
        v = l4.get(k) if isinstance(l4, dict) else None
        if isinstance(v, list) and v: regmap = v; break
    if not regmap: return []
    ranges = []
    for entry in regmap:
        if not isinstance(entry, dict): continue
        name = entry.get("name") or "unnamed"
        addr = entry.get("addr") or entry.get("offset") or entry.get("address")
        r = parse_addr_range(addr) if addr else None
        # Bank-select key: when an entry declares bank_select_reg + bank_select_value,
        # registers on different banks legitimately share an offset (e.g. SJA1000
        # PeliCAN RMC vs CDR at 0x1F, muxed by MOD.RM). Strategy-(c) per K5-B fix spec.
        bank_reg = entry.get("bank_select_reg")
        bank_val = entry.get("bank_select_value")
        bank_key = (bank_reg, str(bank_val)) if bank_reg is not None else None
        if r: ranges.append((name, r[0], r[1], bank_key))
    for i, (n1, s1, e1, b1) in enumerate(ranges):
        for n2, s2, e2, b2 in ranges[i+1:]:
            if s1 > e2 or s2 > e1 or n1 == n2: continue
            # Skip if both declare bank-select on the same reg with different values.
            if b1 is not None and b2 is not None and b1[0] == b2[0] and b1[1] != b2[1]:
                continue
            out.append({"id":"K5-B","severity":"warn",
                "msg":f"Register overlap: {n1}[0x{s1:X}-0x{e1:X}] vs {n2}[0x{s2:X}-0x{e2:X}]"})
    return out


def check_generic_port_map(l9):
    if not isinstance(l9, dict): return []
    subs = l9.get("submodules")
    if not isinstance(subs, dict): return []
    generic = {"clk","rst_n","in_bus","out_bus"}
    generic_count = total = 0
    for _, sbody in subs.items():
        if not isinstance(sbody, dict): continue
        pm = sbody.get("ports_mapped")
        if isinstance(pm, dict):
            total += 1
            keys = {str(k).lower().strip() for k in pm.keys()}
            if keys == generic: generic_count += 1
    if total >= 3 and generic_count == total:
        return [{"id":"K5-C","severity":"warn",
            "msg":f"All {total} submodules use generic {{clk,rst_n,in_bus,out_bus}} — no real handshake names"}]
    if total > 0 and generic_count >= total * 0.7:
        return [{"id":"K5-C","severity":"warn",
            "msg":f"{generic_count}/{total} submodules use generic ports_mapped"}]
    return []


def check_duplicate_port_keys(l9):
    if not isinstance(l9, dict): return []
    dtop = l9.get("dtop_top_level")
    if not isinstance(dtop, dict): return []
    ports = dtop.get("ports")
    if isinstance(ports, dict):
        flat = []
        for v in ports.values():
            if isinstance(v, list): flat.extend(v)
            elif isinstance(v, dict): flat.append(v)
        ports = flat
    if not isinstance(ports, list): return []
    bad = [p for p in ports if isinstance(p, dict) and "dir" in p and "direction" in p]
    if bad:
        return [{"id":"K5-D","severity":"warn",
            "msg":f"{len(bad)} dtop ports have BOTH 'dir' and 'direction'"}]
    return []


def check_reset_polarity_split(docs):
    def find_rst(node):
        found = set()
        def walk(x):
            if isinstance(x, dict):
                for k, v in x.items():
                    if isinstance(k, str) and k.lower() in ("rst_n","rst_i","reset"):
                        found.add(k.lower())
                    walk(v)
            elif isinstance(x, list):
                for v in x: walk(v)
            elif isinstance(x, str) and x.lower() in ("rst_n","rst_i"):
                found.add(x.lower())
        walk(node)
        return found
    l8_r = find_rst(docs.get("L8", {}))
    l9_r = find_rst(docs.get("L9", {}))
    if "rst_i" in l8_r and "rst_n" in l9_r and "rst_i" not in l9_r:
        return [{"id":"K5-E","severity":"warn",
            "msg":"Reset polarity split: L8 rst_i vs L9 rst_n"}]
    return []


def check_fifo_bitfield_missing(docs):
    """K5-G: packet/FIFO register exposed without bit-field schema."""
    l4 = docs.get("L4", {})
    if not isinstance(l4, dict): return []
    out = []
    for key in ("register_map", "control_registers_logical"):
        regs = l4.get(key)
        if not isinstance(regs, list): continue
        for r in regs:
            if not isinstance(r, dict): continue
            name = str(r.get("name", "")).upper()
            if any(tag in name for tag in ("FIFO", "PACKET", "CMD", "DATA_PKT")):
                if not r.get("bitfields") and not r.get("fields") and not r.get("bit_fields"):
                    out.append({"id": "K5-G", "severity": "warn",
                        "msg": f"Packet/FIFO register '{r.get('name')}' lacks bitfield schema"})
    return out


def check_mmio_vs_native_bus_conflict(docs):
    """K5-I: L4 describes MMIO view while L9 ports show native bus."""
    l4 = docs.get("L4", {})
    l9 = docs.get("L9", {})
    if not isinstance(l4, dict) or not isinstance(l9, dict): return []
    # Explicit override: L4 can declare that the register_map is a backdoor
    # view of the native handshake bus (no MMIO wrapper exists).
    if isinstance(l4, dict) and l4.get("native_bus_only"):
        return []
    # Likewise, L9 can declare an MMIO bus_interface block as authoritative.
    dtop_check = l9.get("dtop_top_level", {}) if isinstance(l9, dict) else {}
    if isinstance(dtop_check, dict) and dtop_check.get("bus_interface"):
        return []
    has_mmio_reg = bool(l4.get("register_map") or l4.get("control_registers_logical"))
    # Check L9 port names for native-bus signals (not MMIO's PADDR/PWDATA/etc.)
    dtop = l9.get("dtop_top_level", {})
    ports = dtop.get("ports", []) if isinstance(dtop, dict) else []
    if isinstance(ports, dict):
        flat = []
        for v in ports.values():
            if isinstance(v, list): flat.extend(v)
            elif isinstance(v, dict): flat.append(v)
        ports = flat
    port_names = {str(p.get("name", "")).lower() for p in ports if isinstance(p, dict)}
    mmio_hint = {"paddr","pwdata","prdata","psel","penable","pwrite","pready"}
    native_hint = {"cs","we","re","wr_data","rd_data","addr","valid","ready"}
    has_mmio_ports = any(p in port_names for p in mmio_hint)
    has_native_ports = any(p in port_names for p in native_hint)
    if has_mmio_reg and has_native_ports and not has_mmio_ports:
        return [{"id": "K5-I", "severity": "warn",
            "msg": "L4 describes MMIO register_map but L9 ports expose native/handshake bus only — "
                   "RTL writer can't tell which interface the registers appear on"}]
    return []


def check_scope_class_mismatch(docs):
    """K5-H/J: L1 class_path says simple/minimal but L6/L9 show a full SoC."""
    l1 = docs.get("L1", {})
    l6 = docs.get("L6", {})
    l9 = docs.get("L9", {})
    if not isinstance(l1, dict): return []
    cls = str(l1.get("class_path", "")).lower()
    if not cls: return []
    simple_markers = ("simple-cpu", "simple-peripheral", "minimal", "tiny")
    if not any(m in cls for m in simple_markers): return []
    subs = l6.get("submodule_control_logic") if isinstance(l6, dict) else None
    sub_count = len(subs) if isinstance(subs, dict) else 0
    if sub_count >= 6:
        return [{"id": "K5-H", "severity": "warn",
            "msg": f"L1 class_path suggests simple/minimal IC, but L6 has {sub_count} "
                   f"submodules (JTAG/DM/IPIC-style SoC scope). Scope-class mismatch"}]
    return []


def _flatten_ports(ports):
    """Normalize L9 dtop ports into a flat list of dicts."""
    if isinstance(ports, dict):
        flat = []
        for v in ports.values():
            if isinstance(v, list): flat.extend(v)
            elif isinstance(v, dict): flat.append(v)
        return flat
    if isinstance(ports, list): return ports
    return []


def check_bus_summary_not_expanded(docs):
    """K5-J: DTOP ports_summary mentions AXI/bus group but ports[] never expands it."""
    l9 = docs.get("L9", {})
    if not isinstance(l9, dict): return []
    dtop = l9.get("dtop_top_level")
    if not isinstance(dtop, dict): return []
    summary = dtop.get("ports_summary")
    if not isinstance(summary, str) or not summary.strip(): return []
    s = summary.lower()
    bus_protocols = {
        "axi":   ("awvalid","awready","arvalid","arready","wvalid","rvalid"),
        "ahb":   ("haddr","hwrite","hready","hsel","htrans"),
        "apb":   ("paddr","psel","penable","pwrite","pready"),
        "wishbone": ("wb_adr","wb_dat","wb_cyc","wb_stb","wb_ack"),
        "tilelink": ("tl_a_valid","tl_a_ready","tl_d_valid","tl_d_ready"),
    }
    mentioned = [b for b in bus_protocols if b in s]
    if not mentioned: return []
    ports = _flatten_ports(dtop.get("ports", []))
    port_names = {str(p.get("name","")).lower() for p in ports if isinstance(p, dict)}
    out = []
    for bus in mentioned:
        hits = sum(1 for sig in bus_protocols[bus] if any(sig in pn for pn in port_names))
        if hits == 0:
            out.append({"id":"K5-J","severity":"warn",
                "msg":f"DTOP ports_summary mentions {bus.upper()} but ports[] has no {bus.upper()} signals"})
    return out


def check_soc_harness_no_grouping(docs):
    """K5-K: SoC-harness mixes power/io/mgmt in one flat ports list."""
    l1 = docs.get("L1", {})
    l9 = docs.get("L9", {})
    if not isinstance(l1, dict) or not isinstance(l9, dict): return []
    cls = str(l1.get("class_path","")).lower()
    if "soc-harness" not in cls: return []
    dtop = l9.get("dtop_top_level")
    if not isinstance(dtop, dict): return []
    raw_ports = dtop.get("ports")
    # Grouped form: dict with named groups like power_group/io_group/mgmt_group
    if isinstance(raw_ports, dict):
        keys = {str(k).lower() for k in raw_ports.keys()}
        group_markers = {"power_group","io_group","mgmt_group",
                         "power","io","mgmt","management"}
        if keys & group_markers:
            return []
    flat = _flatten_ports(raw_ports)
    if len(flat) >= 15:
        return [{"id":"K5-K","severity":"warn",
            "msg":f"SoC-harness DTOP has {len(flat)} ports in one flat list (no power/io/mgmt grouping)"}]
    return []


def check_pad_count_drift(docs):
    """K5-L: User brief vs Phase-1 pad-count drift (>=5 pads)."""
    l1 = docs.get("L1", {})
    l9 = docs.get("L9", {})
    if not isinstance(l1, dict) or not isinstance(l9, dict): return []
    text = json.dumps(l1, default=str)
    m = re.search(r'MPRJ_IO_PADS\s*[=:]\s*(\d+)', text)
    declared = None
    if m:
        declared = int(m.group(1))
    else:
        # fallback: look for "pads": N or "pad_count": N in L1
        for key in ("pads","pad_count","io_pads","mprj_io_pads"):
            v = l1.get(key)
            if isinstance(v, int): declared = v; break
    if declared is None: return []
    dtop = l9.get("dtop_top_level", {})
    if not isinstance(dtop, dict): return []
    flat = _flatten_ports(dtop.get("ports", []))
    pad_count = 0
    for p in flat:
        if not isinstance(p, dict): continue
        name = str(p.get("name","")).lower()
        if "pad" in name or "mprj_io" in name or "io[" in name:
            w = p.get("width")
            if isinstance(w, int) and w > 1: pad_count += w
            else: pad_count += 1
    if pad_count == 0: return []
    delta = abs(pad_count - declared)
    if delta >= 5:
        return [{"id":"K5-L","severity":"warn",
            "msg":f"Pad-count drift: L1 declares {declared}, L9 dtop has {pad_count} (delta {delta})"}]
    return []


def check_axi_not_threaded(docs):
    """K5-M: AXI channels expand at DTOP but not into submodules."""
    l9 = docs.get("L9", {})
    if not isinstance(l9, dict): return []
    dtop = l9.get("dtop_top_level")
    if not isinstance(dtop, dict): return []
    flat = _flatten_ports(dtop.get("ports", []))
    port_names = {str(p.get("name","")).lower() for p in flat if isinstance(p, dict)}
    axi_markers = ("awvalid","awready","arvalid","arready","wvalid","rvalid","bvalid")
    if not any(any(m in pn for pn in port_names) for m in axi_markers): return []
    subs = l9.get("submodules")
    if not isinstance(subs, dict) or not subs: return []
    hs_pat = re.compile(r'(valid|ready|addr|data)', re.I)
    hit = False
    for _, sbody in subs.items():
        if not isinstance(sbody, dict): continue
        pm = sbody.get("ports_mapped")
        if isinstance(pm, dict):
            for k, v in pm.items():
                if hs_pat.search(str(k)) or hs_pat.search(str(v)):
                    hit = True; break
        if hit: break
    if not hit:
        return [{"id":"K5-M","severity":"warn",
            "msg":"DTOP exposes AXI bundle but submodules ports_mapped never references *valid/*ready/*addr/*data"}]
    return []


def check_memory_macro_placeholder(docs):
    """K5-N: Memory-macro class silent in K5 despite placeholder submodule ports."""
    l1 = docs.get("L1", {})
    l6 = docs.get("L6", {})
    if not isinstance(l1, dict) or not isinstance(l6, dict): return []
    cls = str(l1.get("class_path","")).lower()
    if "memory-macro" not in cls: return []
    subs = l6.get("submodule_control_logic")
    if not isinstance(subs, dict) or not subs: return []
    l9 = docs.get("L9", {})
    l9_subs = l9.get("submodules") if isinstance(l9, dict) else None
    placeholder_cnt = 0; total = 0
    generic_set = {"clk","rst_n","in_bus","out_bus"}
    for name in subs.keys():
        total += 1
        if isinstance(l9_subs, dict):
            sbody = l9_subs.get(name)
            if isinstance(sbody, dict):
                pm = sbody.get("ports_mapped")
                if isinstance(pm, dict):
                    keys = {str(k).lower().strip() for k in pm.keys()}
                    # Treat zero-item or fully generic as placeholder
                    if len(pm) == 0 or keys == generic_set:
                        placeholder_cnt += 1
                    continue
        # Missing ports_mapped also counts as placeholder
        placeholder_cnt += 1
    if total > 0 and placeholder_cnt >= 1:
        return [{"id":"K5-N","severity":"warn",
            "msg":f"memory-macro IC: {placeholder_cnt}/{total} submodules have placeholder/empty ports_mapped (K5-C skipped)"}]
    return []


def check_tristate_not_hoisted(docs):
    """K5-O: DTOP tristate_rule OK but submodule pad-split never hoisted to _i/_o/_oe triplet."""
    l9 = docs.get("L9", {})
    if not isinstance(l9, dict): return []
    dtop = l9.get("dtop_top_level")
    if not isinstance(dtop, dict): return []
    if "tristate_rule" not in dtop: return []
    subs = l9.get("submodules")
    if not isinstance(subs, dict) or not subs: return []
    # Look for _i/_o/_oe triplets inside any submodule's ports list
    triplet_re_i  = re.compile(r'^(.+)_i$',  re.I)
    triplet_re_o  = re.compile(r'^(.+)_o$',  re.I)
    triplet_re_oe = re.compile(r'^(.+)_oe$', re.I)
    found_triplet = False
    for _, sbody in subs.items():
        if not isinstance(sbody, dict): continue
        sports = sbody.get("ports")
        if sports is None: sports = sbody.get("ports_mapped")
        names = []
        if isinstance(sports, dict): names = [str(k) for k in sports.keys()]
        elif isinstance(sports, list):
            for p in sports:
                if isinstance(p, dict) and p.get("name"):
                    names.append(str(p.get("name")))
                elif isinstance(p, str):
                    names.append(p)
        bases_i  = {triplet_re_i.match(n).group(1).lower()  for n in names if triplet_re_i.match(n)}
        bases_o  = {triplet_re_o.match(n).group(1).lower()  for n in names if triplet_re_o.match(n)}
        bases_oe = {triplet_re_oe.match(n).group(1).lower() for n in names if triplet_re_oe.match(n)}
        if bases_i & bases_o & bases_oe:
            found_triplet = True; break
    if not found_triplet:
        return [{"id":"K5-O","severity":"warn",
            "msg":"DTOP declares tristate_rule but no submodule splits pads into _i/_o/_oe triplets"}]
    return []


def check_l1_class_path_missing(docs):
    """K5-P: L1.class_path is null/empty — silently disables class-keyed checkers."""
    l1 = docs.get("L1", {})
    if not isinstance(l1, dict): return []
    if "class_path" not in l1:
        return [{"id":"K5-P","severity":"warn",
            "msg":"L1 has no class_path field — disables K5-F/H/K/N class-keyed checkers"}]
    v = l1.get("class_path")
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return [{"id":"K5-P","severity":"warn",
            "msg":"L1.class_path is null/empty — disables K5-F/H/K/N class-keyed checkers"}]
    return []


def check_l6_states_schema_drift(docs):
    """K5-Q: L6.submodule_control_logic has states as list-of-dicts instead of list-of-strings."""
    l6 = docs.get("L6", {})
    if not isinstance(l6, dict): return []
    subs = l6.get("submodule_control_logic")
    if not isinstance(subs, dict): return []
    drift = []
    for name, cfg in subs.items():
        if not isinstance(cfg, dict): continue
        states = cfg.get("states")
        if isinstance(states, list) and states:
            if any(isinstance(s, dict) for s in states):
                drift.append(name)
    if drift:
        return [{"id":"K5-Q","severity":"warn",
            "msg":f"L6 states schema drift: {len(drift)} submodule(s) have list-of-dicts states "
                  f"({', '.join(drift[:3])}{'...' if len(drift)>3 else ''}) — "
                  f"check_templated_fsms str-coerces and mis-classifies"}]
    return []


def check_ports_summary_signature_placeholder(docs):
    """K5-R: ports_summary carries real signature but ports[] is a placeholder stub."""
    l9 = docs.get("L9", {})
    if not isinstance(l9, dict): return []
    dtop = l9.get("dtop_top_level")
    if not isinstance(dtop, dict): return []
    summary = dtop.get("ports_summary")
    if not isinstance(summary, str): return []
    if len(summary) <= 50: return []
    s_low = summary.lower()
    sig_keywords = ("axi","wishbone","apb","tilelink","obi","handshake")
    if not any(kw in s_low for kw in sig_keywords): return []
    ports = _flatten_ports(dtop.get("ports", []))
    if len(ports) > 6: return []
    generic_names = {"clk","rst_n","valid","ready","data_in","data_out"}
    port_names = {str(p.get("name","")).lower() for p in ports if isinstance(p, dict)}
    # Count how many of the ports use generic names
    generic_hits = len(port_names & generic_names)
    # If >=50% of ports are generic placeholders AND total <=6, flag it
    if len(port_names) > 0 and generic_hits >= max(1, len(port_names) // 2):
        return [{"id":"K5-R","severity":"warn",
            "msg":f"ports_summary carries real signature ({[k for k in sig_keywords if k in s_low]}) "
                  f"but ports[] has only {len(ports)} placeholder ports "
                  f"({generic_hits} generic: clk/rst_n/valid/ready/data_in/data_out)"}]
    return []


def check_soc_harness_no_interconnect(docs):
    """K5-S: soc-harness class with >=15 submodules but no interconnect topology declared."""
    l1 = docs.get("L1", {})
    l6 = docs.get("L6", {})
    l9 = docs.get("L9", {})
    if not isinstance(l1, dict) or not isinstance(l9, dict): return []
    cls = str(l1.get("class_path","")).lower()
    if "soc-harness" not in cls: return []
    l6_subs = l6.get("submodule_control_logic") if isinstance(l6, dict) else None
    l9_subs = l9.get("submodules") if isinstance(l9, dict) else None
    l6_n = len(l6_subs) if isinstance(l6_subs, dict) else 0
    l9_n = len(l9_subs) if isinstance(l9_subs, dict) else 0
    if l6_n < 15 and l9_n < 15: return []
    # Look for interconnect topology fields anywhere in L9
    topo_keys = ("interconnect_topology","xbar_map","address_decode","bus_hierarchy")
    l9_text = json.dumps(l9, default=str).lower()
    if any(k in l9_text for k in topo_keys): return []
    return [{"id":"K5-S","severity":"warn",
        "msg":f"soc-harness class with {max(l6_n,l9_n)} submodules but L9 has no "
              f"interconnect_topology/xbar_map/address_decode/bus_hierarchy field"}]


def check_crypto_params(docs):
    l1 = docs.get("L1", {})
    if not isinstance(l1, dict): return []
    cls_path = str(l1.get("class_path", "")).lower()
    if "crypto" not in cls_path: return []
    fam = str(l1.get("crypto_family", "")).lower()
    if fam not in ("block-cipher","hash-function","stream-cipher"): return []
    keywords = ("key_schedule","round_constants","key_expansion",
                "round_keys","iv_init","h_init","h0","k_constants",
                "initial_hash","round_function")
    text = json.dumps(docs, default=str).lower()
    if not any(kw in text for kw in keywords):
        return [{"id":"K5-F","severity":"warn",
            "msg":f"Crypto IC ({fam}) missing key schedule / round constants"}]
    return []


# ---------------------------------------------------------------------------
# v0.74 Task-C Stage-C3: consume fact-UUID markers emitted by Phase-2 RTL
#
# Convention (docs/design/PHASE1_FACT_UUID_PROPOSAL.md §3.1-3.3):
#
#     // phase1-fact: <uuid> path=<L.path> source=<provenance_source>
#     localparam BIT_PERIOD_CYCLES = 200;
#
# This check scans Verilog/SystemVerilog sources for the marker regex and
# cross-references each hit against fact_index.json + facts.yaml emitted
# by Phase-1 render. Three classifications:
#
#   K5-T  missing_fact_uuid     — UUID in RTL not present in fact_index
#                                (fact renamed/deleted since render)
#   K5-U  fact_value_mismatch   — RTL literal disagrees with current fact
#                                value (stale RTL, needs re-render)
#   K5-V  multi_fact_conflict   — multiple markers on same construct point
#                                at facts whose values are inconsistent
# ---------------------------------------------------------------------------
FACT_MARKER_RE = re.compile(
    r"//\s*phase1-fact:\s*(?P<uuid>[0-9a-fA-F-]{8,})\s+"
    r"path=(?P<path>[^\s]+)\s+"
    r"source=(?P<source>\w+)"
)


def _extract_rtl_literal(line: str):
    """Given the RTL line immediately after a marker, try to extract a
    literal value following `=`. Returns the raw string token or None.
    Handles `localparam NAME = 200;`, `assign x = 32'h1234;`, etc. —
    best-effort regex, not a real Verilog parser."""
    m = re.search(r"=\s*([^\s;,]+)", line)
    return m.group(1) if m else None


def _parse_rtl_for_markers(rtl_path):
    """Walk a dir (or single file) of .v / .sv, yield
    (file, line_no, marker_dict, following_line_or_None)."""
    out = []
    paths = []
    p = Path(rtl_path)
    if p.is_dir():
        paths += sorted(p.rglob("*.v")) + sorted(p.rglob("*.sv"))
    elif p.is_file():
        paths = [p]
    for f in paths:
        try:
            lines = f.read_text().splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        # Group consecutive markers so multi-marker constructs are detected.
        i = 0
        while i < len(lines):
            m = FACT_MARKER_RE.search(lines[i])
            if not m:
                i += 1
                continue
            group = [{"line": i + 1, **m.groupdict()}]
            j = i + 1
            while j < len(lines):
                m2 = FACT_MARKER_RE.search(lines[j])
                if not m2:
                    break
                group.append({"line": j + 1, **m2.groupdict()})
                j += 1
            next_non_marker = lines[j] if j < len(lines) else ""
            for marker in group:
                marker["group_size"] = len(group)
            out.append({
                "file": str(f),
                "markers": group,
                "next_line": next_non_marker,
            })
            i = j + 1
    return out


def _coerce_value_for_compare(rtl_lit, fact_value):
    """Best-effort normalization so '200' and 200 compare equal, and
    Verilog hex like "8'h31" matches fact value "0x31". Returns
    (rtl_norm, fact_norm) for equality check."""
    if rtl_lit is None:
        return None, None
    rl = str(rtl_lit).strip().rstrip(";")
    fv = fact_value
    # Strip Verilog sized-hex prefix  '  ->  '
    m = re.match(r"^\d+'([bBhHoOdD])(.+)$", rl)
    if m:
        kind = m.group(1).lower()
        digits = m.group(2).replace("_", "")
        try:
            val = int(digits, {"b": 2, "o": 8, "d": 10, "h": 16}[kind])
            rl_num = val
        except ValueError:
            rl_num = None
    else:
        try: rl_num = int(rl)
        except ValueError:
            try: rl_num = int(rl, 0)   # 0x / 0b / 0o prefixes
            except (ValueError, TypeError): rl_num = None
    fv_num = None
    if isinstance(fv, (int, bool)) and not isinstance(fv, bool):
        fv_num = int(fv)
    elif isinstance(fv, str):
        try: fv_num = int(fv, 0)
        except (ValueError, TypeError): fv_num = None
    if rl_num is not None and fv_num is not None:
        return rl_num, fv_num
    return rl, str(fv) if fv is not None else None


def check_fact_uuid_markers(rtl_dir, fact_index_path, facts_yaml_path=None):
    """Scan RTL under rtl_dir for phase1-fact markers and classify each.

    fact_index_path : JSON file { path: uuid } emitted by render.
    facts_yaml_path : optional — used for value-mismatch detection.
                      Without it, only missing_fact_uuid is reported.
    Returns list of issue dicts.
    """
    if not Path(fact_index_path).exists():
        return [{"id": "K5-T", "severity": "warn",
                 "msg": f"fact_index.json not found at {fact_index_path} — "
                        "skipping marker check"}]
    index = json.loads(Path(fact_index_path).read_text())
    # Invert: uuid -> path
    uuid_to_path = {u: p for p, u in index.items()}

    facts_by_path = {}
    if facts_yaml_path and Path(facts_yaml_path).exists():
        # Lazy-import yaml; tools/phase1_engine/schema loads the whole graph.
        try:
            import yaml
            fg = yaml.safe_load(Path(facts_yaml_path).read_text())
            for fact in (fg or {}).get("facts", []) or []:
                facts_by_path[fact.get("path")] = fact.get("value")
        except Exception:
            pass

    issues = []
    entries = _parse_rtl_for_markers(rtl_dir)
    for entry in entries:
        f = entry["file"]
        markers = entry["markers"]
        next_line = entry["next_line"]
        rtl_lit = _extract_rtl_literal(next_line)

        # K5-T: unknown UUIDs
        for m in markers:
            if m["uuid"] not in uuid_to_path:
                issues.append({
                    "id": "K5-T", "severity": "warn",
                    "msg": f"{f}:{m['line']} marker points at unknown "
                           f"fact UUID {m['uuid']} (path was {m['path']}) — "
                           "fact may have been renamed or deleted since render",
                })

        # K5-U: value mismatch (only if we have facts.yaml and RTL literal)
        if facts_by_path and rtl_lit is not None:
            for m in markers:
                fact_path = m["path"]
                if fact_path not in facts_by_path:
                    continue
                fv = facts_by_path[fact_path]
                if fv is None:
                    continue
                rl_n, fv_n = _coerce_value_for_compare(rtl_lit, fv)
                if rl_n is not None and fv_n is not None and rl_n != fv_n:
                    issues.append({
                        "id": "K5-U", "severity": "warn",
                        "msg": f"{f}:{m['line']} RTL has {rtl_lit!r} but "
                               f"fact {fact_path} now = {fv!r} — "
                               "RTL is stale vs current facts.yaml",
                    })

        # K5-V: multi-marker group with inconsistent values
        if len(markers) >= 2 and facts_by_path:
            vals = {}
            for m in markers:
                if m["path"] in facts_by_path:
                    vals[m["path"]] = facts_by_path[m["path"]]
            distinct = set()
            for v in vals.values():
                try: distinct.add(json.dumps(v, sort_keys=True))
                except TypeError: distinct.add(repr(v))
            if len(distinct) > 1:
                issues.append({
                    "id": "K5-V", "severity": "warn",
                    "msg": f"{f}:{markers[0]['line']} {len(markers)} markers on "
                           f"same construct but facts disagree: {vals}",
                })
    return issues


def run_on(gen_dir):
    docs = {}
    for L, fn in [("L1","L1_DATASHEET.json"),("L4","L4_REGMAP.json"),
                  ("L6","L6_CONTROL_LOGIC.json"),("L8","L8_TIMING_WAVEFORM.json"),
                  ("L9","L9_INTEGRATION_SPEC.json")]:
        p = gen_dir / fn
        if p.exists():
            try: docs[L] = lenient_load(p)
            except Exception: pass
    out = []
    out += check_templated_fsms(docs.get("L6", {}))
    out += check_register_overlap(docs.get("L4", {}))
    out += check_generic_port_map(docs.get("L9", {}))
    out += check_duplicate_port_keys(docs.get("L9", {}))
    out += check_reset_polarity_split(docs)
    out += check_crypto_params(docs)
    out += check_fifo_bitfield_missing(docs)
    out += check_mmio_vs_native_bus_conflict(docs)
    out += check_scope_class_mismatch(docs)
    out += check_bus_summary_not_expanded(docs)
    out += check_soc_harness_no_grouping(docs)
    out += check_pad_count_drift(docs)
    out += check_axi_not_threaded(docs)
    out += check_memory_macro_placeholder(docs)
    out += check_tristate_not_hoisted(docs)
    out += check_l1_class_path_missing(docs)
    out += check_l6_states_schema_drift(docs)
    out += check_ports_summary_signature_placeholder(docs)
    out += check_soc_harness_no_interconnect(docs)
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--json", action="store_true")
    # v0.74 Task-C Stage-C3: optional fact-UUID marker scan over Phase-2 RTL
    ap.add_argument("--rtl",
                    help="directory (or single file) of Phase-2 RTL to scan "
                         "for phase1-fact: markers")
    ap.add_argument("--fact-index",
                    help="path to fact_index.json (emitted by phase1 render)")
    ap.add_argument("--facts",
                    help="optional path to facts.yaml — enables K5-U / K5-V "
                         "value-mismatch + multi-fact-conflict checks")
    args = ap.parse_args(argv)

    if args.all:
        targets = sorted((WORKTREE / "benchmark/phase1_v046").rglob("generated_docs"))
        total = 0; issues = Counter(); per_ic = {}
        for t in targets:
            if not t.is_dir(): continue
            total += 1
            fs = run_on(t)
            if fs:
                per_ic[t.parent.name] = fs
                for f in fs: issues[f["id"]] += 1
        print(f"Scanned {total} ICs")
        print(f"ICs with >=1 K5 issue: {len(per_ic)}")
        print(f"\nIssue totals:")
        for cat, n in sorted(issues.items()): print(f"  {cat}: {n}")
        print(f"\nTop 15 ICs:")
        for ic, fs in sorted(per_ic.items(), key=lambda x: -len(x[1]))[:15]:
            cats = ",".join(f['id'] for f in fs)
            print(f"  {len(fs):2}  {ic:<25} [{cats}]")
        return 0

    if args.rtl and args.fact_index and not args.target:
        # Stand-alone Stage-C3 mode: scan RTL only, no L*.json doc checks.
        fs = check_fact_uuid_markers(
            rtl_dir=args.rtl,
            fact_index_path=args.fact_index,
            facts_yaml_path=args.facts,
        )
    else:
        if not args.target: ap.error("--all or <dir> (or --rtl + --fact-index)")
        fs = run_on(Path(args.target))
        if args.rtl and args.fact_index:
            fs += check_fact_uuid_markers(
                rtl_dir=args.rtl,
                fact_index_path=args.fact_index,
                facts_yaml_path=args.facts,
            )
    if args.json:
        print(json.dumps(fs, indent=2, ensure_ascii=False))
    else:
        if not fs: print("No K5 quality issues detected.")
        else:
            for f in fs: print(f"  [{f['severity']}] {f['id']}: {f['msg']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
