#!/usr/bin/env python3
"""Remove SENT-protocol contamination from the io_link claude_extracted gold.

The io_link gold was cross-polluted during the Tier-G parallel-agent batch
(io_link shared a wave with sent + uart). A faithful IO-Link / SDCI
(IEC 61131-9) extraction contains NO nibble/tick/SPC/CRC-4 facts — IO-Link uses
a checksum, COM1-3 baud rates, M-sequences and ISDU. The program-generated docs
are correct (0 SENT keys). This removes the SENT contamination precisely:

  (1) any key whose NAME carries a distinctive SENT token (delete its subtree —
      a SENT-named key is wholly SENT), recursion-preserving so legit IO-Link
      siblings survive;
  (2) a *table leaf* (dict with rows/header_columns, or a string) whose VALUE
      carries SENT markers — this catches generically-named SENT tables
      (timing_table / crc_table) without nuking structural containers;
  (3) the SENT device-role subkeys under `device_classification`.

It deliberately does NOT touch prose that merely mentions a neighbouring
protocol, and never deletes a structural container (e.g. `fields`).
"""
import json, re
from pathlib import Path

GOLD = Path(__file__).parent / "io_link" / "phase1" / "claude_extracted"

SENT_NAME = re.compile(
    r"nibble|tick|spc|sent|calibration|crc|slow_serial|slow_channel|"
    r"slow_message|frame_format|frame_transmit|frame_receive|frame_order|"
    r"resync|data_nibble|edge_of_interest|single_wire|unidirectional", re.I)
# Value markers — actual SENT *facts* (NOT the bare word "SENT", which appears
# in legit IO-Link warnings like "...is not SENT"). Applied only to leaf
# records / table leaves / strings (IO-Link genuinely has none of these).
SENT_VALUE = re.compile(r"nibble|calibration pulse|CRC-4|J2716|\bticks?\b", re.I)
DEVICE_ROLE_KEYS = {"receiver", "transmitter", "spc_master"}

def is_table_leaf(v):
    return isinstance(v, dict) and ("rows" in v or "header_columns" in v)

def _scalar_or_scalar_list(x):
    if isinstance(x, dict):
        return False
    if isinstance(x, list):
        return all(not isinstance(e, (dict, list)) for e in x)
    return True

def is_terminal_record(v):
    # A leaf record whose values are only scalars or lists-of-scalars
    # (e.g. frame_waveform={order:[str,...], pause:str}). A container that
    # holds lists-of-dicts (e.g. `fields` with backward_compat_traps:[{...}])
    # is NOT terminal — recurse into it so legit sibling entries survive.
    return (isinstance(v, dict) and bool(v)
            and all(_scalar_or_scalar_list(x) for x in v.values()))

def clean(obj, parent_key=""):
    removed = 0
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            v = obj[k]
            drop = bool(SENT_NAME.search(k))
            if parent_key == "device_classification" and k in DEVICE_ROLE_KEYS:
                drop = True
            if not drop and (is_table_leaf(v) or is_terminal_record(v) or isinstance(v, str)):
                if SENT_VALUE.search(json.dumps(v) if not isinstance(v, str) else v):
                    drop = True
            if drop:
                del obj[k]; removed += 1
            else:
                removed += clean(v, k)
    elif isinstance(obj, list):
        for v in obj:
            removed += clean(v, parent_key)
    return removed

total = 0
for p in sorted(GOLD.glob("L*.json")):
    d = json.loads(p.read_text())
    n = clean(d)
    if n:
        p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        print(f"{p.stem}: removed {n} SENT keys")
        total += n
print(f"TOTAL removed: {total}")
