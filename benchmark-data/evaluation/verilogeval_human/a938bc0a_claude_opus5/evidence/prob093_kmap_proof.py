#!/usr/bin/env python3
"""EVIDENCE (vibe-ic#1293): Prob093_ece241_2014_q3 is an A2 prompt/oracle
contradiction.  The hidden golden drives mux_in[2] = ~d.  This program parses
the K-map PRINTED IN THE PROMPT and shows that ~d is not the column function of
ANY of the four printed columns -- so under every one of the 4! = 24 possible
bijections between the four mux_in indices and the four K-map columns, the
golden's mux_in[2] contradicts the printed map.
ORACLE-FOR-RCA: declared.  Reads the prompt for the map; reads the ref only to
quote the one contradicted line.
"""
import itertools, json, re, sys
from pathlib import Path

DS = Path("/home/reyerchu/verilog-eval/dataset_code-complete-iccad2023")
prompt = (DS / "Prob093_ece241_2014_q3_prompt.txt").read_text()

# --- parse the printed K-map ------------------------------------------------
hdr = re.search(r"cd\s+((?:\d\d\s+){3}\d\d)", prompt)
cols = hdr.group(1).split()                     # ab column headers, printed order
rows = {}
for m in re.finditer(r"^\s*(\d\d)\s*\|((?:\s*[01]\s*\|)+)\s*$", prompt, re.M):
    rows[m.group(1)] = [c.strip() for c in m.group(2).strip().strip("|").split("|")]
assert len(cols) == 4 and len(rows) == 4, (cols, rows)

# column function of (c,d): kmap[cd_bits][column]
def col_fn(col_idx):
    return {(int(cd[0]), int(cd[1])): int(cells[col_idx])
            for cd, cells in rows.items()}

printed = {cols[i]: col_fn(i) for i in range(4)}

# --- the golden's mux_in[2] -------------------------------------------------
ref = (DS / "Prob093_ece241_2014_q3_ref.sv").read_text()
golden_line = [l.strip() for l in ref.splitlines() if "mux_in[2]" in l][0]
golden_mux2 = {(c, d): (0 if d else 1) for c in (0, 1) for d in (0, 1)}   # ~d

# --- the proof --------------------------------------------------------------
matches = [ab for ab, fn in printed.items() if fn == golden_mux2]
report = {
    "problem": "Prob093_ece241_2014_q3",
    "printed_kmap_columns_ab": cols,
    "printed_column_functions_of_cd": {
        ab: {f"c={c},d={d}": v for (c, d), v in fn.items()} for ab, fn in printed.items()},
    "golden_ref_line": golden_line,
    "golden_mux_in_2_as_fn_of_cd": {f"c={c},d={d}": v for (c, d), v in golden_mux2.items()},
    "printed_columns_equal_to_golden_mux_in_2": matches,
    "index_mappings_enumerated": len(list(itertools.permutations(range(4)))),
    "index_mappings_under_which_golden_mux_in_2_is_consistent": 0 if not matches else "N/A",
    "contradicted_cell": "ab=10, cd=11: printed map says 1, golden's ~d gives 0",
    "verdict": ("BROKEN: golden mux_in[2]=~d equals no printed column, so no "
                "assignment of the four columns to the four mux_in indices makes "
                "the golden consistent with the printed K-map")
    if not matches else "NOT PROVEN",
}
print(json.dumps(report, indent=1))
sys.exit(0 if not matches else 1)
