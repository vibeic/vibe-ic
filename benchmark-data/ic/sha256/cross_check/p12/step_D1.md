# Step D1 — L-docs field diff (OURS vs REF)

**Verdict: DIFFERENT-BUT-OK** (semantic facts agree; OUR L9 port table is empty — extractor gap, but RTL is correct)

## What ran
Field-by-field diff of `phase1/generated_docs/L1..L13.json`: OURS
`/home/reyerchu/vibe-ic/benchmark_clean/sha256/phase1/generated_docs/`
vs REF `/home/reyerchu/AI_IC_design/4th_benchmark/sha256_v2_e2e/phase1/generated_docs/`.

## Facts compared

| Field | OURS | REF | Verdict |
|-------|------|-----|---------|
| Modes SHA-256 / SHA-224 | L1 has 13×"SHA-256", 7×"SHA-224" | identical counts | MATCH |
| 512-bit block | L1 "512" ×4 | "512" ×4 | MATCH |
| 66-cycle latency | L1/L8 "66" ×39 | ×39 | MATCH |
| Clock / period | clk 38.6 MHz, period 25.906736 ns | same | MATCH |
| Reset | reset_n, active-LOW | active-LOW | MATCH |
| PDK sky130 | present (L1 sky130×6) | present (sky130×11) | MATCH (REF richer) |
| Register map 0x00..0x27 | RTL implements full map | REF L9 ports + RTL | MATCH (RTL) |
| **L9 top_ports table** | **EMPTY** (`top_module_extraction_strategy=l1_ic_name_fallback`, `ports:[]`) | **FULL 6-port table** (clk,reset_n,address[7:0],write_data[31:0],read_data[31:0],error) | **DIFFERENT** |
| L9 top_module | `sha256` | `chip_top` (wraps aid-class harness) | DIFFERENT (REF adds chip-top+CDC wrapper) |
| L8 timing_constants | empty | 11 entries (t_setup 0.5, t_co 1.2, t_block_latency 66, input/output_delay 2.0) | REF richer |

## Finding (HONEST)
The semantic spec facts that matter for RTL (modes, 512-bit block, register
map, 66-cycle latency, 25.9 ns clock, active-LOW reset, PDK) **all agree**.
However OUR Phase-1 extractor produced an **empty L9 port table** (it fell back
to `l1_ic_name_fallback` and did not populate `ports`/`top_module_pins`),
whereas REF's L9 carries the full 6-port interface table. This is a Phase-1
*ingester* gap, not an RTL gap: OUR generated RTL (`sha256.v`) nevertheless
implements the exact same 8-port contract (clk, reset_n, cs, we, address[7:0],
write_data[31:0], read_data[31:0], error) and the identical 0x00–0x27 register
map — confirmed by reading the RTL and by the co-sim (step 1/4) passing the
same interface as REF. REF also wraps a `chip_top` + 3-FF CDC synchroniser for
the generic benchmark harness; OURS keeps `sha256` as top (no async crossing).

## Evidence
- OUR L9: `ports: []`, `top_ports: []`, `top_module: "sha256"`.
- REF L9: 6 populated ports with widths/msb/lsb/descriptions; `top_module: "chip_top"`.
- Both L8/L9 clock_domains: `period_ns: 25.906736`, `freq_mhz: 38.6`.
