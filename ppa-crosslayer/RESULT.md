# The cross-layer search — synthesis + RTL + micro-architecture, against a PnR-only winner

Tree under test: `origin/main` @ `8a9c5ad9e` (**v1.11.51**), **unmodified**.
Design: `spm` (serial-parallel modulo-2^size multiplier) on **`sky130A`**.
Prior art this is measured against: [`ppa-e2e/`](../ppa-e2e/) on `main` — a
60-point **place-and-route-only** search on the same design.

---

## The short version

Every open flow searches place-and-route knobs. Nothing searches RTL, because a
tuner cannot rewrite a design. This lane searched **RTL, micro-architecture and
synthesis strategy**, held the place-and-route knobs where the PnR-only search
put them, and asked whether an agent that has read the specification can beat a
tuner that has not.

It can, and the margin is small, attributable, and paid for in a currency the
report names.

| | objective `area.design_report.um2` @ `post_route` | post-route power | ECO spares |
|---|---:|---:|---|
| shipped default run | 6594 µm² | 0.000573 W | 10 |
| **PnR-only winner** (published `t028`, re-run here as `p04`) | **6136 µm²** (−6.95 %) | 0.000559 W | **0 — all ten deleted** |
| **cross-layer, objective winner** (`u01`) | **5941 µm²** (−9.90 %) | 0.000747 W (**+30 %**) | 0 |
| **cross-layer, Pareto winner** (`z21`) | **6011 µm²** (−8.84 %) | 0.000545 W (−4.89 %) | 0 |
| **cross-layer, ECO-preserving winner** (`z23`) | **6106 µm²** (−7.40 %) | 0.000541 W (−5.58 %) | **10 — all kept** |

Read across the middle three rows, because that is where the claim lives:

* **`u01` beats the PnR-only winner by −3.18 % on the declared objective and it
  is a TRADE, not an improvement** — it buys that area with **+33.6 % more
  post-route power** than `p04`. The shipped head-to-head gate says so itself:
  `pareto INCOMPARABLE`. It is the winner on the objective this search declared,
  and it is published as a trade because that is what it is.
* **`z21` beats the PnR-only winner on BOTH axes** — 6011 vs 6136 µm² (−2.04 %)
  *and* 0.000545 vs 0.000559 W (−2.5 %). That is a Pareto improvement over the
  tuner's best, and it is the honest headline.
* **`z23` beats the PnR-only winner on both axes WHILE KEEPING ALL TEN SPARE ECO
  CELLS** — 6106 vs 6136 µm² and 0.000541 vs 0.000559 W. The published report
  says two thirds of its own winner was placement and one third was **deleting
  every spare ECO cell**. This arm gives that third back and is still ahead.

**Every RTL that produced any of those numbers is PROVEN equivalent to the
baseline RTL**, cycle for cycle, at every port, by the shipped
`crosslayer_rewrite_equivalence` gate: 165 of 165 compared points proven, zero
unproven, zero counterexamples.

**And the arm that would have won biggest is published as NOT ADMITTED.** A
non-redundant accumulator removes **31 of the design's 65 flip-flops** and is
**−21.3 % to −27.3 % at synthesis** — three to four times the best admitted RTL
win. It appears
nowhere in the headline, because the equivalence gate could not prove it and
`unproven is not proven`. Twelve candidates are published as failures for that
reason and for one other, and §7 is about them.

---

## 1. The search space, and the authority for every lever

`programs/crosslayer_search_space.py`, run against the design's own input
documents, with nothing widened and nothing added:

```
$ python3 programs/crosslayer_search_space.py <project> --json reports/space.json
[crosslayer_search_space] admitted 5 lever(s): arithmetic_architecture,
    module_hierarchy, pipelining, state_encoding, synthesis_strategy
[crosslayer_search_space]   POLARITY phase1/input_doc/L2_architecture.txt:53 —
    '不' denies the free marker, so this sentence asserts nothing
[crosslayer_search_space]   POLARITY phase1/input_doc/L7_verification_plan.txt:106 —
    '非' denies the bound marker, so this sentence asserts nothing
[crosslayer_search_space]   POLARITY phase1/input_doc/L8_submodule_integration.txt:53 —
    '無' denies the pin marker, so this sentence asserts nothing
rc=0
```

Five of five admitted, none refused, `self_audit_problems: []`. The full space
with every citation is [`search/space.json`](search/space.json).

| lever | status | the sentence that authorises it |
|---|---|---|
| `arithmetic_architecture` | `FREE` | `L2_architecture:11` — *r3_multiple_correct: "PASS — 演算法/結構由 Plugin 自選,只要功能等價、時序滿足"* |
| `module_hierarchy` | `FREE` | `L2_architecture:61` — *「❌ 不指定 module hierarchy 或子模組命名」*, and five more |
| `pipelining` | `FREE` | `L2_architecture:65` — *「❌ 不指定 latency cycle 數」*; `:46`; `L3_external_interface:51` |
| `state_encoding` | `FREE` | `L2_architecture:63` — *「❌ 不指定 FSM state 數量或編碼」* |
| `synthesis_strategy` | `NO_DESIGN_CHANGE` | none needed — it re-maps the same RTL and none is claimed |

**Three levers were admitted and three were not searched anyway, and that is the
part worth reading.** §6 says which and why. A search that turns every knob it
is handed is not being careful; it is being obedient.

---

## 2. The problem is the published one, by hash and by number

The published run's source project no longer exists on this host. It was
recovered by hash: the three artefacts the published baseline declares in its
`problem` identity were searched for by digest, and one tree on this host
carries all three byte-identically.

| role | published `records/baseline/contract.json` | this lane's source |
|---|---|---|
| `rtl_top` | `sha256:e7feff2cbbad384a…` (5442 B) | **identical** |
| `sdc` | `sha256:74b39a3339ede80a…` (1049 B) | **identical** |
| `l19_spec` | `sha256:717f38a3d0cfc171…` (1070 B) | **identical** |

The design's own input documents are byte-identical too (`.txt` in
`phase1/input_doc/`, `.md` in `input/docs/`; same content hash for all nine).

**And the numbers reproduce.** The published search's `die_um=auto` slice is
fifteen cells; this lane re-ran all fifteen on v1.11.51:

| density \ spare | 0.00 | 0.02 | 0.05 |
|---|---|---|---|
| 0.20 | 6709 · 6709 | 6823 · 6823 | 6994 · 6994 |
| 0.30 | 6454 · 6454 | **6594 · 6594** | 6775 · 6775 |
| 0.40 | 6267 · 6267 | 6394 · 6394 | 6578 · 6578 |
| 0.50 | 6160 · 6160 | 6306 · 6306 | 6492 · 6492 |
| 0.60 | **6136 · 6136** | 6291 · 6291 | 6462 · 6462 |

*(published · this lane, µm²)* — **15 of 15 identical to the digit**, on a tree
19 versions newer, with the same pinned image
`ghcr.io/vibeic/vibeic-eda@sha256:24b5074b…` and the same OpenROAD build
`26Q3-1535-g543c33894f`. The published winner `t028` = this lane's `p04` = 6136.
The published default = `b000` = 6594.

So the PnR-only winner is not quoted from a document. It was re-measured here,
and every cross-layer arm is measured against a number produced by the same
tree on the same day.

**Determinism was checked rather than assumed.** Four configurations were run
twice, independently, in separate containers:

| configuration | first run | repeat | Δ |
|---|---:|---:|---|
| `base` / 0.60 / 0.00 | `p04` 6136 | `v01` 6136 | 0 |
| `csa_mux` / 0.60 / 0.00 | `z11` 5961 | `v02` 5961 | 0 |
| `csa_alt_maj` + `ks` / 0.60 / 0.00 | `z21` 6011 | `v03` 6011 | 0 |
| `csa_mux` + `ks` / 0.60 / 0.00 | `w02` 5942 | `v04` 5942 | 0 |

The ranking is not noise.

---

## 3. What was searched, and what turned each lever

The objective is declared here and in every head-to-head record, because the
design declares none (`L19_CONSTRAINTS_PDK.json` carries
`die_area_budget_um: null`, `power_budget_uw: null`):

> **minimise `area.design_report.um2` at `scope.stage = post_route`**
> (OpenROAD `report_design_area`, status `MEASURED`), subject to the hard
> feasibility gate. Power and timing are published alongside and never
> collapsed into it.

**The place-and-route knobs were NOT searched by the cross-layer arm.**
`crosslayer_search_space` excludes them on purpose — *"a cross-layer arm that
also moved them would not be measuring the cross-layer contribution"* — so the
cross-layer contribution is measured at ONE place-and-route configuration at a
time, against the PnR-only arm at that same configuration. Where a table below
shows density 0.60 / spare 0.00, the PnR-only arm is at density 0.60 /
spare 0.00 too.

### The RTL and micro-architecture levers, as candidate files

Thirteen candidate RTLs, all in [`rtl/`](rtl/), each carrying its lever and its
citation in its own header:

| variant | lever moved | what changed |
|---|---|---|
| `base` | — | the design's own RTL, unmodified |
| `csa_alt_maj` | `arithmetic_architecture` | majority factored through the shared `m^s` term |
| `csa_mux` | `arithmetic_architecture` | majority as a bitwise mux: `maj(m,s,c) = (m^s) ? c : m` |
| `csa_aoi` | `arithmetic_architecture` | majority as `(m&s) \| (c&(m\|s))` — the AOI shape |
| `csa_add1` | `arithmetic_architecture` | per-bit `{co,so} = m+s+c`, mapper picks the adder cell |
| `hier_split` | `module_hierarchy` | the cell array extracted into a submodule |
| `csa_alt_hier` | both | shared-XOR form **and** split hierarchy |
| `csa_mux_hier` | both | mux form **and** split hierarchy |
| `nr_rca`, `nr_rca_hier`, `nr_csel16`, `nr_csel8` | `arithmetic_architecture` | **non-redundant** accumulator: 32 fewer flops, a carry chain added |
| `pipe1` | `pipelining` | +1 output pipeline stage (`latency_offset = 1`) |

### The synthesis-strategy lever, and the actuator it had to borrow

`synthesis_strategy` is admitted with `justification_kind = no_design_change`,
so it needs no specification permission. It needs an ACTUATOR, and
**`phase3_one_shot_runner.py` exposes none**: its CLI has `--die-um`, `--util`
and `--spare-density` and no synthesis flag at all. The only synthesis-recipe
input the runner reads is `input/reference_flow/*.mk`, which it treats as *the
design's own* declared ORFS configuration.

So this lane wrote the knob there, and says so plainly rather than letting the
runner's audit line (`REFERENCE-FLOW PnR QoR-KNOB INGEST (input/reference_flow)`)
imply the design declared it. Every file is in
[`reference_flow/`](reference_flow/) and every one carries that disclosure in
its own comment header. What is checkable rather than asserted:

* the RTL, SDC and L19 digests are **unchanged** by staging a reference flow —
  they are published per arm in `records/trials/*/contract.json`;
* `ppa_problem_integrity_check --require-implementation-differs` returns **rc=0**
  for every such arm against the default baseline;
* the only thing that changes is the yosys command line.

**This is REQUEST 1 to the lander**: give the runner a first-class
`--synth-strategy`, so a lever that changes no design does not have to be
actuated by writing into the design's input tree.

| strategy | what the runner does with it |
|---|---|
| `none` | shipped recipe |
| `rab` | `REMOVE_ABC_BUFFERS=1` → post-`abc` `opt_clean -purge` |
| `swap` | `SWAP_ARITH_OPERATORS=1` → `alumacc` |
| `rab_swap` | both |
| `ks` / `sk` / `hc` | `alumacc` + `ADDER_MAP_FILE` = yosys's **own** shipped `choices/kogge-stone.v` / `sklansky.v` / `han-carlson.v`, copied out of the pinned image unmodified, + `REMOVE_ABC_BUFFERS` |

---

## 4. All 70 candidates, published

Not the winner. All of them, including the twelve that produced no number.

| trial | arm | rtl_variant | synth strategy | density | spare | objective µm² | Δ vs default | synth area µm² | post-route power W | rewrite-equivalence |
|---|---|---|---|---|---|---:|---:|---:|---:|---|
| `u01` | cross-layer | `csa_mux` | `hc` | 0.60 | 0.00 | **5941** | -9.90% | 2417.3 | 0.000747 | PASS (165/165) |
| `v04` | cross-layer | `csa_mux` | `ks` | 0.60 | 0.00 | **5942** | -9.89% | 2417.3 | — | PASS (165/165) |
| `w02` | cross-layer | `csa_mux` | `ks` | 0.60 | 0.00 | **5942** | -9.89% | 2417.3 | 0.000747 | PASS (165/165) |
| `w07` | cross-layer | `csa_mux` | `sk` | 0.60 | 0.00 | **5942** | -9.89% | 2417.3 | — | PASS (165/165) |
| `u02` | cross-layer | `csa_mux_hier` | `ks` | 0.60 | 0.00 | **5959** | -9.63% | 2416.1 | 0.000756 | PASS (165/165) |
| `v02` | cross-layer | `csa_mux` | `none` | 0.60 | 0.00 | **5961** | -9.60% | 2427.3 | — | PASS (165/165) |
| `z11` | cross-layer | `csa_mux` | `none` | 0.60 | 0.00 | **5961** | -9.60% | 2427.3 | 0.000698 | PASS (165/165) |
| `w05` | cross-layer | `csa_mux_hier` | `none` | 0.60 | 0.00 | **5966** | -9.52% | 2521.2 | 0.000596 | PASS (165/165) |
| `w03` | cross-layer | `csa_mux` | `none` | 0.50 | 0.00 | **5983** | -9.27% | 2427.3 | 0.000675 | PASS (165/165) |
| `v03` | cross-layer | `csa_alt_maj` | `ks` | 0.60 | 0.00 | **6011** | -8.84% | 2533.7 | — | PASS (165/165) |
| `v05` | cross-layer | `csa_alt_maj` | `sk` | 0.60 | 0.00 | **6011** | -8.84% | 2533.7 | — | PASS (165/165) |
| `z21` | cross-layer | `csa_alt_maj` | `ks` | 0.60 | 0.00 | **6011** | -8.84% | 2533.7 | 0.000545 | PASS (165/165) |
| `w08` | cross-layer | `csa_mux` | `none` | 0.40 | 0.00 | **6037** | -8.45% | 2427.3 | — | PASS (165/165) |
| `z14` | cross-layer | `csa_alt_hier` | `none` | 0.60 | 0.00 | **6037** | -8.45% | 2532.4 | 0.000592 | PASS (165/165) |
| `c02` | cross-layer | `csa_alt_maj` | `none` | 0.60 | 0.00 | **6040** | -8.40% | 2532.4 | 0.000540 | PASS (165/165) |
| `u05` | cross-layer | `csa_alt_hier` | `ks` | 0.60 | 0.00 | **6041** | -8.39% | 2532.4 | 0.000550 | PASS (165/165) |
| `c03` | cross-layer | `nr_csel16` | `none` | 0.60 | 0.00 | **6043** | -8.36% | 2047.0 | — | NOT_PROVEN_EQUIVALENT (36/37) |
| `u04` | cross-layer | `csa_mux` | `ks` | 0.60 | 0.02 | **6050** | -8.25% | 2417.3 | 0.000747 | PASS (165/165) |
| `u03` | cross-layer | `csa_alt_maj` | `ks` | 0.50 | 0.00 | **6052** | -8.22% | 2533.7 | — | PASS (165/165) |
| `c04` | cross-layer | `hier_split` | `none` | 0.60 | 0.00 | **6072** | -7.92% | 2602.5 | — | PASS (165/165) |
| `w01` | cross-layer | `csa_mux` | `none` | 0.60 | 0.02 | **6075** | -7.87% | 2427.3 | 0.000700 | PASS (165/165) |
| `z12` | cross-layer | `csa_add1` | `none` | 0.60 | 0.00 | **6095** | -7.57% | 2533.7 | — | PASS (165/165) |
| `z23` | cross-layer | `csa_alt_maj` | `ks` | 0.60 | 0.02 | **6106** | -7.40% | 2533.7 | 0.000541 | PASS (165/165) |
| `v06` | cross-layer | `csa_mux_hier` | `none` | 0.60 | 0.02 | **6126** | -7.10% | 2521.2 | — | PASS (165/165) |
| `p04` | PnR-only | `base` | `none` | 0.60 | 0.00 | **6136** | -6.95% | 2601.2 | 0.000559 | n/a (baseline RTL) |
| `v01` | PnR-only | `base` | `none` | 0.60 | 0.00 | **6136** | -6.95% | 2601.2 | — | n/a (baseline RTL) |
| `c05` | cross-layer | `csa_alt_maj` | `none` | 0.60 | 0.02 | **6148** | -6.76% | 2532.4 | 0.000541 | PASS (165/165) |
| `p03` | PnR-only | `base` | `none` | 0.50 | 0.00 | **6160** | -6.58% | 2601.2 | — | n/a (baseline RTL) |
| `u06` | cross-layer | `csa_add1` | `ks` | 0.60 | 0.00 | **6182** | -6.25% | 2533.7 | — | PASS (165/165) |
| `y02` | cross-layer | `nr_csel16` | `sk` | 0.30 | 0.02 | **6198** | -6.01% | 1923.1 | — | NOT_PROVEN_EQUIVALENT (36/37) |
| `z13` | cross-layer | `csa_aoi` | `none` | 0.60 | 0.00 | **6205** | -5.90% | 2681.3 | — | PASS (165/165) |
| `c06` | cross-layer | `nr_csel16` | `none` | 0.60 | 0.02 | **6259** | -5.08% | 2047.0 | — | NOT_PROVEN_EQUIVALENT (36/37) |
| `p02` | PnR-only | `base` | `none` | 0.40 | 0.00 | **6267** | -4.96% | 2601.2 | — | n/a (baseline RTL) |
| `p08` | PnR-only | `base` | `none` | 0.60 | 0.02 | **6291** | -4.60% | 2601.2 | 0.000562 | n/a (baseline RTL) |
| `p07` | PnR-only | `base` | `none` | 0.50 | 0.02 | **6306** | -4.37% | 2601.2 | — | n/a (baseline RTL) |
| `w04` | cross-layer | `csa_mux` | `rab` | 0.30 | 0.02 | **6312** | -4.28% | 2427.3 | — | PASS (165/165) |
| `z01` | cross-layer | `csa_mux` | `none` | 0.30 | 0.02 | **6312** | -4.28% | 2427.3 | 0.000682 | PASS (165/165) |
| `x05` | cross-layer | `nr_csel16` | `none` | 0.30 | 0.02 | **6379** | -3.26% | 2047.0 | — | NOT_PROVEN_EQUIVALENT (36/37) |
| `x15` | cross-layer | `nr_csel16` | `rab` | 0.30 | 0.02 | **6379** | -3.26% | 2047.0 | — | NOT_PROVEN_EQUIVALENT (36/37) |
| `p06` | PnR-only | `base` | `none` | 0.40 | 0.02 | **6394** | -3.03% | 2601.2 | — | n/a (baseline RTL) |
| `p01` | PnR-only | `base` | `none` | 0.30 | 0.00 | **6454** | -2.12% | 2601.2 | — | n/a (baseline RTL) |
| `z22` | cross-layer | `csa_alt_maj` | `ks` | 0.30 | 0.02 | **6460** | -2.03% | 2533.7 | 0.000564 | PASS (165/165) |
| `p13` | PnR-only | `base` | `none` | 0.60 | 0.05 | **6462** | -2.00% | 2601.2 | — | n/a (baseline RTL) |
| `z02` | cross-layer | `csa_add1` | `none` | 0.30 | 0.02 | **6464** | -1.97% | 2533.7 | — | PASS (165/165) |
| `p12` | PnR-only | `base` | `none` | 0.50 | 0.05 | **6492** | -1.55% | 2601.2 | — | n/a (baseline RTL) |
| `x01` | cross-layer | `csa_alt_maj` | `none` | 0.30 | 0.02 | **6509** | -1.29% | 2532.4 | 0.000563 | PASS (165/165) |
| `x14` | cross-layer | `csa_alt_maj` | `rab` | 0.30 | 0.02 | **6509** | -1.29% | 2532.4 | — | PASS (165/165) |
| `y07` | cross-layer | `csa_alt_maj` | `rab_swap` | 0.30 | 0.02 | **6509** | -1.29% | 2532.4 | — | PASS (165/165) |
| `z04` | cross-layer | `csa_alt_hier` | `none` | 0.30 | 0.02 | **6510** | -1.27% | 2532.4 | — | PASS (165/165) |
| `x02` | cross-layer | `hier_split` | `none` | 0.30 | 0.02 | **6519** | -1.14% | 2602.5 | — | PASS (165/165) |
| `w06` | cross-layer | `csa_mux_hier` | `none` | 0.30 | 0.02 | **6524** | -1.06% | 2521.2 | — | PASS (165/165) |
| `x06` | cross-layer | `nr_csel8` | `none` | 0.30 | 0.02 | **6535** | -0.89% | 2097.0 | — | NOT_PROVEN_EQUIVALENT (36/37) |
| `y06` | cross-layer | `base` | `ks` | 0.30 | 0.02 | **6558** | -0.55% | 2611.3 | — | n/a (baseline RTL) |
| `p11` | PnR-only | `base` | `none` | 0.40 | 0.05 | **6578** | -0.24% | 2601.2 | — | n/a (baseline RTL) |
| `b000` | PnR-only | `base` | `none` | 0.30 | 0.02 | **6594** | +0.00% | 2601.2 | 0.000573 | n/a (baseline RTL) |
| `x08` | cross-layer | `base` | `rab` | 0.30 | 0.02 | **6594** | +0.00% | 2601.2 | — | n/a (baseline RTL) |
| `x09` | cross-layer | `base` | `swap` | 0.30 | 0.02 | **6594** | +0.00% | 2601.2 | — | n/a (baseline RTL) |
| `x10` | cross-layer | `base` | `rab_swap` | 0.30 | 0.02 | **6594** | +0.00% | 2601.2 | — | n/a (baseline RTL) |
| `x07` | cross-layer | `pipe1` | `none` | 0.30 | 0.02 | **6600** | +0.09% | 2627.5 | — | NOT_PROVEN_EQUIVALENT (201/202) |
| `z03` | cross-layer | `csa_aoi` | `none` | 0.30 | 0.02 | **6618** | +0.36% | 2681.3 | — | PASS (165/165) |
| `p00` | PnR-only | `base` | `none` | 0.20 | 0.00 | **6709** | +1.74% | 2601.2 | — | n/a (baseline RTL) |
| `p10` | PnR-only | `base` | `none` | 0.30 | 0.05 | **6775** | +2.74% | 2601.2 | — | n/a (baseline RTL) |
| `p05` | PnR-only | `base` | `none` | 0.20 | 0.02 | **6823** | +3.47% | 2601.2 | — | n/a (baseline RTL) |
| `p09` | PnR-only | `base` | `none` | 0.20 | 0.05 | **6994** | +6.07% | 2601.2 | — | n/a (baseline RTL) |
| `x03` | cross-layer | `nr_rca` | `none` | 0.30 | 0.02 | NOT_MEASURED | — | 1891.8 | — | NOT_PROVEN_EQUIVALENT (36/37) |
| `x04` | cross-layer | `nr_rca_hier` | `none` | 0.30 | 0.02 | NOT_MEASURED | — | 1891.8 | — | NOT_PROVEN_EQUIVALENT (36/37) |
| `x11` | cross-layer | `nr_rca` | `rab` | 0.30 | 0.02 | NOT_MEASURED | — | 1891.8 | — | NOT_PROVEN_EQUIVALENT (36/37) |
| `x12` | cross-layer | `nr_rca` | `swap` | 0.30 | 0.02 | NOT_MEASURED | — | 1850.5 | — | NOT_PROVEN_EQUIVALENT (36/37) |
| `x13` | cross-layer | `nr_rca` | `rab_swap` | 0.30 | 0.02 | NOT_MEASURED | — | 1850.5 | — | NOT_PROVEN_EQUIVALENT (36/37) |
| `y01` | cross-layer | `nr_csel16` | `ks` | 0.30 | 0.02 | NOT_MEASURED | — | 1975.6 | — | NOT_PROVEN_EQUIVALENT (36/37) |
| `y03` | cross-layer | `nr_csel16` | `hc` | 0.30 | 0.02 | NOT_MEASURED | — | 1904.3 | — | NOT_PROVEN_EQUIVALENT (36/37) |
| `y04` | cross-layer | `nr_rca` | `ks` | 0.30 | 0.02 | NOT_MEASURED | — | 2078.2 | — | NOT_PROVEN_EQUIVALENT (36/37) |
| `y05` | cross-layer | `nr_rca` | `sk` | 0.30 | 0.02 | NOT_MEASURED | — | 1930.6 | — | NOT_PROVEN_EQUIVALENT (36/37) |
| `y08` | cross-layer | `nr_rca` | `none` | 0.60 | 0.00 | NOT_MEASURED | — | 1891.8 | — | NOT_PROVEN_EQUIVALENT (36/37) |
| `z24` | cross-layer | `nr_csel16` | `sk` | 0.60 | 0.00 | NOT_MEASURED | — | 1923.1 | — | NOT_PROVEN_EQUIVALENT (36/37) |
| `z25` | cross-layer | `nr_csel16` | `sk` | 0.60 | 0.02 | NOT_MEASURED | — | 1923.1 | — | NOT_PROVEN_EQUIVALENT (36/37) |

64 of 76 candidates produced a MEASURED objective; 12 did not and every one is in the table with its reason.

The objective took **50 distinct values over 76 candidates**, from **5941** to
**6994 µm² — a 17.7 % spread**. Cost: **8.21 h wall / 10.107 CPU-hours**, median
300 s wall and 371 CPU-s per trial, median peak RSS 619 MB. Every CPU and RSS
figure is that trial's own container cgroup.

Machine-readable: [`records/summary.json`](records/summary.json) carries every
figure this document quotes; [`records/trials/`](records/trials/) carries each
arm's full canonical record set, contract, feasibility adjudication and
post-route power diagnostic.

---

## 5. The winners, and the attribution of each

### 5.1 The objective winner is a TRADE and the gate says so

`u01` — mux-form majority RTL + Han-Carlson `$lcu` techmap, at density 0.60 /
spare 0.00 — is **5941 µm², −9.90 % against the default and −3.18 % against the
PnR-only winner.** Its post-route power is **0.000747 W against the default's
0.000573 W: +30.4 %**, and against the PnR-only winner's 0.000559 W: **+33.6 %**.

`ppa_head_to_head_check` returns rc=0 and reports `pareto INCOMPARABLE`. It is
better on the declared objective and worse on an axis published beside it. That
is a trade, and calling it an improvement would be the exact failure this
report is supposed not to commit.

The whole `csa_mux` family behaves this way. Sixteen of its arms produced a
number; nine of those carry a post-route power measurement, and **every one of
the nine is above the shipped default's 0.000573 W** — 0.000596, 0.000675,
0.000682, 0.000698, 0.000700, 0.000747 ×3, 0.000756. It is a property of the
mux-form majority and not one lucky placement. The three
prefix-adder maps land on the same number to within 1 µm² (`hc` 5941, `ks` 5942,
`sk` 5942) and the mux form without any of them is 5961, so the RTL lever
carries this result and the synthesis lever trims it.

### 5.2 The Pareto winner beats the tuner on both axes

`z21` — shared-XOR majority RTL + Kogge-Stone techmap, density 0.60 /
spare 0.00 — is **6011 µm² and 0.000545 W**, against the PnR-only winner's
**6136 µm² and 0.000559 W**. Smaller *and* cooler. Against the shipped default
the gate reports:

```
### h2h_I   (b000 -> z21, power=diagnostic)
[PASS] ppa_head_to_head_check
  area_um2      subject=6011.0  baseline=6594.0  delta=-583   -8.84%  -> SUBJECT_BETTER
  power_mw      subject=0.545   baseline=0.573   delta=-0.028  -4.89%  -> SUBJECT_BETTER
  timing_wns_ns subject=0.0     baseline=0.0     delta=+0             -> TIE
  pareto        SUBJECT_DOMINATES
rc=0
```

### 5.3 The ECO-preserving winner, which is the one to read

The published PnR-only report is explicit that one third of its own win came
from **deleting all ten spare ECO cells** — metal-only ECO readiness traded for
area — and that a design wanting to keep it should read `t020` at 6291 µm²
instead of `t028` at 6136.

`z23` is the shared-XOR RTL + Kogge-Stone techmap at density 0.60 with the
**shipped spare density 0.02 kept**: **6106 µm², 0.000541 W, and ten spare ECO
cells actually in the routed database.** Not asserted — the flow's own
`phase3/stage3/pnr/spare_cells.json` reads `{"count": 10, "density": 0.02}` for
`z23` and `{"count": 0, "density": 0.0}` for `p04`, and the cell-category
decomposition of the two routed netlists finds their ten tie-offs
(`tie 37.5 µm² (10)`) present in one and absent in the other.

| | area | power | spare ECO cells |
|---|---:|---:|---:|
| PnR-only winner `p04` | 6136 | 0.000559 | **0** |
| PnR-only, spares kept `p08` | 6291 | 0.000562 | 10 |
| **cross-layer, spares kept `z23`** | **6106** | **0.000541** | **10** |

`z23` is smaller and cooler than the PnR-only arm that **deleted** its spares,
and −2.94 % / −3.7 % against the PnR-only arm that kept them. **The cross-layer
lever buys back the thing the PnR-only winner sold.** Two further arms do the
same: `v06` (`csa_mux_hier`, spares kept) at 6126 and `c05` at 6148.

### 5.4 Where the win comes from — cell by cell

`area.design_report.um2` is *logic cells + tap cells*; fill and decap are
excluded. That was established, not assumed: summing the PDK liberty's own
areas over the routed netlist reproduces the tool's figure to 0.2 µm² on every
arm checked.

`p04` → `c02` (same PnR knobs, RTL is the only difference), −96 µm²:

| category | `p04` 6136 µm² | `c02` 6040 µm² | Δ | share of the win |
|---|---:|---:|---:|---:|
| combinational | 2921.6 (355) | 2851.5 (355) | **−70.1** | 73 % |
| buffer / inverter | 142.6 (34) | 126.4 (32) | −16.2 | 17 % |
| flop | 2168.3 (99) | 2155.8 (99) | −12.5 | 13 % |
| antenna diode | 5.0 (2) | 2.5 (1) | −2.5 | 3 % |
| clock tree | 683.2 (122) | 688.2 (123) | +5.0 | −5 % |
| tap | 215.2 (172) | 215.2 (172) | 0.0 | 0 % |

Three quarters of it is the combinational cells, at an **identical cell count**:
the mapper picked a cheaper structure. The cell-level diff shows exactly that —
22 `xor2_1`, 22 `a22oi_1`, 38 `nor2_1`, 14 `nand2_1` and 12 `xnor2_1` disappear;
51 `nand3_1`, 31 `a21o_1` and 35 more `a21oi_1` appear.

**Nothing was given up, and every row of that table was checked for it.** The
flop count is identical (99 / 99), so no state was dropped. The spare-cell count
is whatever `--spare-density` put there and both arms sit at 0.00, so this
comparison is not the ECO trade (§5.3 is). The one row that could look like
something removed is the antenna diode, 2 → 1: the router inserts diodes to fix
antenna violations, so a diode fewer means one fewer violation to fix, and the
`antenna` feasibility axis is **SATISFIED with 0 violations on both arms**. The
clock tree got 5.0 µm² *bigger*, which is the win paying a small cost rather
than hiding one.

### 5.5 The synthesis win is not the post-route win, and the gap is the finding

| variant | synthesis area | Δ | post-route objective (0.30/0.02) | Δ |
|---|---:|---:|---:|---:|
| `base` | 2601.2 | — | 6594 | — |
| `csa_alt_maj` | 2532.4 | −2.6 % | 6509 | −1.3 % |
| `csa_mux` | 2427.3 | −6.7 % | 6312 | −4.3 % |
| `nr_csel16` | 2047.0 | **−21.3 %** | 6379 | −3.3 % |
| `nr_rca` | 1891.8 | **−27.3 %** | *no number* | *tool crash, §7.3* |

**A −21.3 % synthesis win becomes a −3.3 % post-route win.** The decomposition
of `b000` → `x05` says where it goes: the 31 flops removed are worth −628 µm²
and the clock tree that served them another −135, but the carry chain those
flops were avoiding costs **+580 µm² of buffers and inverters** (32 cells → 150).
The redundant carry-save representation is not wasteful; it is buying away a
carry chain, and the place-and-route flow charges for that chain at a rate
synthesis does not show.

This is the single most useful thing an agent gets from being cross-layer and a
tuner cannot: it can see that a pre-PnR area model would have ranked these arms
in a different order, and it can measure which order is right.

---

## 6. What was NOT searched, and why — including things nobody stopped

**The place-and-route knobs.** `crosslayer_search_space` lists them under
`pnr_levers_excluded_on_purpose` and this lane obeyed it. Where a cross-layer
arm sits at density 0.60 / spare 0.00, it is being compared against a PnR-only
arm at density 0.60 / spare 0.00, so the delta is the cross-layer contribution
and nothing else.

**`state_encoding` was admitted and is VACUOUS on this design.** The
specification frees it (`「❌ 不指定 FSM state 數量或編碼」`) and there is no
FSM to re-encode: `spm` is a pure datapath — one accumulator, one serial-operand
register bank, one output register, no control state. The lever is admitted,
its applicable-site count is zero, and no candidate was authored for it.
Authoring one would have meant inventing a state machine the design does not
have in order to have something to search.

**The serial-operand replication factor was NOT searched, and nobody stopped
me.** The baseline holds `y` in a `(* keep *)`-marked bank of `NREP = 4`
replicated flops, sized by `FANOUT_GROUP = 8`, for a stated physical-design
reason. Changing it to 16 would delete two flip-flops. **No admitted lever names
operand-broadcast replication** — it is not arithmetic architecture, not module
hierarchy, not state encoding, not pipelining — and the rule is that silence is
not permission. It is not searched. It is written down here because a reader
should be able to see the thing that was left on the table.

**`pipelining` was searched and lost, twice over.** `pipe1` adds one output
stage: +1 flop, 6600 µm² — *worse* than the baseline, which is what an extra
register should be for an area objective. And it is **NOT ADMITTED** anyway
(§7). Both halves are published because a lever that was tried and lost is a
measurement, and a lever that was quietly dropped is not.

**Nothing was hand-edited.** No GDS was touched, no violating geometry deleted,
no pin moved, no rule deck relaxed. `phase3/stage3/pnr/constraint.sdc` declares
`set_max_fanout 8`; it was read, not written. No `--write-baseline` was run. No
file under `vibe-ic-marketplace/plugins/vibe-ic/` was modified — everything this
lane wrote is under [`ppa-crosslayer/`](.) and calls the shipped programs.

---

## 7. The failures — five not admitted, twelve with no number, and the arm that would have won

### 7.1 Five candidates are NOT ADMITTED by the equivalence gate

`crosslayer_rewrite_equivalence.py`, default settings, every candidate against
the baseline RTL:

| candidate | verdict | proven / compared | elapsed |
|---|---|---:|---:|
| `csa_alt_maj`, `csa_mux`, `csa_aoi`, `csa_add1`, `hier_split`, `csa_alt_hier`, `csa_mux_hier` | **PASS** | 165 / 165 | 0.7–0.8 s |
| `nr_rca`, `nr_rca_hier`, `nr_csel16`, `nr_csel8` | `NOT_PROVEN_EQUIVALENT` | 36 / 37 | 1795 s (budget) |
| `pipe1` (`latency_offset = 1`) | `NOT_PROVEN_EQUIVALENT` | 201 / 202 | 3.8 s |

**The split is not random and it is not a bug.** The seven that pass preserve
the accumulator's STATE ENCODING and change only the combinational function that
feeds it, so `equiv_struct` matches the state and `equiv_simple` discharges the
rest in under a second. The four `nr_*` candidates replace the redundant
carry-save pair `(s, c)` with one non-redundant register `a`, and the invariant
that makes them equivalent — `a == s + c` — is not an inductive invariant of the
miter. `equiv_induct` has to unroll until the two state spaces are forced
together; the transcript shows it reaching **induction step 19 of an estimated
~33 when the 1800 s budget expired**, with clause counts growing ~8 000 per step.

`pipe1` is separate: the latency-offset mode was authorised correctly (the
evidence `L2_architecture.txt:65` resolved and the literal matched), the offset
wrapper was built, and **201 of 202 points proved**. One point did not, in 3.8 s
— so it is not a budget problem, it is the alignment chain leaving one point the
engine neither proved nor refuted.

**The budget was raised rather than the gate lowered.** A re-run of `nr_csel16`
through the same gate, same relation, same engine, with `--timeout 21600` was
launched and is still running at the time this document is written; whatever it
returns, the candidate stays out of the headline. The gate's own words are the
policy: *"Unproven is not proven; this candidate is NOT admitted, and this is
NOT a report that it is wrong."*

For the record, and NOT as a defence: the gate's bounded-refutation pass
(`sat -seq 12 -prove-asserts -set-init-zero`) reported **no counterexample** for
`nr_rca` — 12 cycles from reset with no mismatch. That is a bounded search, not
a proof, and it is reported here for exactly the reason the gate reports it: so
the difference between *refuted* and *unproven* stays visible.

### 7.2 What that costs, stated plainly

The `nr_*` family is where the real area was. `nr_rca` is **−27.3 % at
synthesis** and `nr_csel16` **−21.3 %**, against the −6.7 % of the best admitted
RTL. `nr_csel16` at the PnR-only winner's knobs (`c03`) measured **6043 µm²** —
which would have been a headline. It is not in the headline. **A rewritten RTL
the gate cannot prove is a different design and its number is not comparable**,
so it is published as infeasible on the equivalence axis and nowhere else.

### 7.3 Twelve candidates produced no number at all, and all twelve are the same family

| cause | n | which |
|---|---:|---|
| OpenROAD **SIGSEGV in `postroute_drv_repair`** after routing completed | 10 | `x03 x04 x11 x12 x13 y03 y04 y08 z24 z25` |
| trial exceeded the declared 3600 s per-trial budget | 2 | `y01 y05` |

**All twelve are `nr_*` candidates — twelve of the eighteen arms that carry a
non-redundant accumulator. Not one of the 52 state-encoding-preserving
candidates failed.** The runner classified the crash correctly and said so:

```
[pnr] PNR_TOOL_FATAL_SIGNAL: routing SUCCEEDED — the router printed its own
completion line (DRT-0198 Complete detail routing) — and OpenROAD was then
killed by SIGSEGV (signal 11) in postroute_drv_repair. This is a TOOL CRASH
after a completed route, not a routing failure (rc=139 = 128+11).
[pnr] RESUME: reading routed_preantenna.def and re-running the post-route tail
with postroute_drv_repair omitted
```

The resume path exists and fires; on `y01` and `y05` it consumed the rest of the
hour budget. **Nothing was done to make these arms pass** — no repair step was
disabled, no timeout raised for them, no DEF hand-patched. Ten of ten
reproductions of the same crash on the same design family is a defect worth a
bug report, and it is **REQUEST 8**.

---

## 8. The head-to-head, and the four conditions

`_ppa/benchmark.py` requires four things of a valid comparison, plus a fifth
about who tuned what. All of them were checked and none was worked around.

### 8.0 Condition 0 — same problem. PASSES, and it needed one declaration change

```
$ python3 programs/ppa_problem_integrity_check.py --baseline <b000> \
      --candidate <z21> --require-implementation-differs
[PASS] problem, analysis and toolchain identities MATCH and the implementation
       identity differs — these two runs are comparable.      rc=0
```

**This required moving `rtl_top` out of the `problem` identity and into
`implementation`, and that is the one methodological change a cross-layer search
forces.** The published PnR-only lane declared the RTL in `problem`, and for a
PnR-only search that is right: no knob touches it, so "same problem" is checkable
by hash. A cross-layer search REWRITES it. Left in `problem`, every cross-layer
arm would differ there and the check would refuse the comparison — not because
the runs solve different problems, but because the declaration had confused the
SPECIFICATION with one implementation of it.

So this lane declares the **specification** as the problem — the nine input
documents, the SDC, the L19 PDK spec — and the RTL as part of the
implementation. **The licence for that move is not an argument, it is the
equivalence proof**: an arm whose RTL differs and whose
`crosslayer_rewrite_equivalence` verdict is not PASS is published as NOT
ADMITTED, never as a win. Without that gate this re-declaration would be exactly
the cheat this lane exists not to be. It is **REQUEST 2** that
`docs/PPA_INTERFACES.md` state the rule.

### 8.1 The four conditions, and the three refusals it took to satisfy them

Each record below differs from the one above it in exactly one respect, and each
was produced before its successor rather than assembled backwards.

| record | as produced, it declared | verdict when produced | condition that failed |
|---|---|---|---|
| `h2h_A` | shipped numbers, setup at the governing `ss` corner | rc=2 `SCOPE_SENTINEL` | *same corner* — **producer defect**, §8.2 |
| `h2h_B` | setup at `tt`, shipped power | rc=2 `SCOPE_INCOMPLETE` | *same activity basis* — **producer defect**, §8.3 |
| `h2h_C` … `h2h_O` | setup at `tt`, power from the labelled post-route diagnostic | **rc=0 PASS** | none |

**`h2h_A` AND `h2h_B` NO LONGER DECLARE WHAT THAT TABLE SAYS THEY DECLARE, and
the column headings are past tense for that reason.** Both have been RE-FILED,
and this section is kept rather than deleted because the progression it records
is how the four conditions were satisfied and that history is still true.

WHAT WAS WRONG WITH THEM, which is not what §8.2 and §8.3 say. Each carried its
`power_mw` at `scope.stage = "synth"` while the arm around it declared
`measurement_basis: "post_route_sta"` — a number that states where it came from
and states it falsely. `ppa_head_to_head_check` could not say so while
`check_scope_parity` ran first: an rc 2 was reported and the rc 1 behind it was
never printed, which is why the verdict column above reads `SCOPE_SENTINEL` and
`SCOPE_INCOMPLETE` rather than `STAGE_CONTRADICTS_BASIS`. With the checks
reordered the refusal surfaced, on these two records and on `ppa-e2e`'s
`head_to_head.json`.

WHAT WAS DONE. The power axis of all three was re-filed from the labelled
post-route diagnostic — the same one `h2h_C` uses, for the same trial, from the
artefact whose `sha256` the record already recorded and which is committed in
this tree (`records/trials/b000/diag/power_postroute.rpt`,
`records/trials/c02/diag/power_postroute.rpt`). Nothing was relabelled: the
synth number was not restamped as post-route, it was REPLACED by the post-route
number that had been measured and not used. The alternative remedy — filing the
arm `NOT_MEASURED` with the producer's `--power withheld` reason — was not
needed here, because the measurement exists.

WHERE THAT LEAVES THEM. Both are now **rc=2 `FEASIBILITY_NOT_CHECKED`**, on
`feasibility.checks.drv.status`: the `drv` axis is undecided on both arms
because, as §8.4 records, nothing in `programs/` produces it. That is a STATED
GAP over a named field, not a claim, and it is the same axis that was already
the last one standing in §8.4. `h2h_C` … `h2h_O` are unchanged and still PASS.

Full machine reports: `records/h2h_*_report.json`; the records themselves are
`records/h2h_*.json`. The reports for the three re-filed records were
regenerated from the shipped checker over the re-filed record, so a report
beside a record is that record's verdict and not its predecessor's.

### 8.2 `SCOPE_SENTINEL` — `_ppa/timing.py` writes `null` into a scope

> arm's `timing_wns_ns` scope declares `['rc_corner']` with no value. `null` and
> `""` are not unknown-corner markers: two of them compare EQUAL, so two numbers
> measured under conditions nobody recorded would pass as measured under the
> SAME conditions.

`_ppa/timing.py` emits `"rc_corner": null, "clock": null` for every `ss` and
`ff` row. `docs/PPA_INTERFACES.md` §2 forbids this in bold — *"A `scope` key
that is present and null is worse than one that is absent"* — and the consumer
catches it. The `tt` rows do carry `rc_corner: "max"`, so the setup axis is
taken at `tt`, declared as such, in both arms. **The governing sign-off corner
is `ss` and it could not be used.** That is **REQUEST 3**.

### 8.3 `SCOPE_INCOMPLETE`, and the power number that is still 1.87× low

> arm's `power_mw` scope does not declare `['mode']`.

`_ppa/power.py` fills `process`, `voltage_v` and `temperature_c` and not `mode`.
Behind it sits the bigger one, which **v1.11.51 has not fixed**: the flow's only
power session reads

```
read_verilog .../phase2/stage2/synth/spm_synth.v
link_design spm
```

— the **pre-place-and-route** netlist, with no SPEF — while `reports/phase3/power.rpt`
says in its own header *"values reflect the post-PnR netlist"*. The consequences
reproduce exactly: total 0.000306 W with the **Clock group at 0.0 %**, and a
controlled re-measurement on the routed netlist with extracted parasitics —
same tool, same liberty, same SDC, same declared vectorless basis — gives
**0.000573 W, 1.873×**, with the clock group at 33.7 %.

Both reproduce the published figures to the digit
(`0.000573` default, `0.000559` winner). That diagnostic is what every passing
head-to-head uses for the power axis, it is labelled `scenario: "diagnostic"` in
every record, and its script is `tools/diag_power.sh`. It is **REQUEST 4**.

### 8.4 Both arms feasible — six of nine axes came free, and the ninth took a producer

With **only shipped programs**, no caller-side bridge:

| axis | verdict | producer |
|---|---|---|
| `setup`, `hold` | **SATISFIED** | `_ppa/timing.py` — *newly decidable*: the runner now stamps `STA_BASIS: POST_ROUTE_SPEF` |
| `drc`, `lvs`, `antenna`, `ir` | **SATISFIED** | `ppa_signoff_records.py` — *newly shipped* at v1.11.51 |
| `drv` | UNDETERMINED | **nothing in `programs/` produces it** |
| `em` | UNDETERMINED | the current-density screen states verdict `"MEASURED"`, which is neither PASS, FAIL nor SKIPPED, and no `worst_utilization` |
| `equivalence` | UNDETERMINED | post-layout LEC verdict `RUN_ERROR`, and the proven pair names the *synthesis* netlist, not the routed one |

The published lane, with a caller-side bridge, got four axes; without it, zero.
This lane gets six with nothing but shipped code. **That is real progress by the
lander and it is worth saying so.**

The head-to-head's floor is `drc lvs antenna setup hold drv`, so it came down to
**one axis: `drv`**, and its refusal was precise:

> feasibility is not established: `['drv']` on both arms.

`tools/drv_records.py` is the missing producer, written caller-side in the same
shape as the sign-off bridge the previous lane published and this tree has since
shipped. **The whole difficulty is one line of semantics**: the flow drives
`report_check_types … -violators`, which prints ONLY violating entries, so a
clean design and a command that never ran produce a byte-identical empty region.
The discriminator is the flow's own marker — `SIGNOFF_CHECK_TYPES_REPORTED`
(ran) vs `SIGNOFF_CHECK_TYPES_FAILED` (raised) vs neither (never reached) — and
only the first admits a count. The report's own
`SIGNOFF_MAX_FANOUT_SEMANTICS` warning is honoured too: each count is admitted
only when the SDC **the sign-off session actually read** declares the matching
limit, and that SDC is read out of the session's own `read_sdc` line rather than
assumed.

It ships with the four fixtures `PPA_INTERFACES.md` §7 requires, runnable:

```
$ python3 tools/drv_records.py --selftest
  positive     -> 0 (want 0) OK          clean run, marker present
  negative     -> 2 (want 2) OK          two violators, counted
  vacuous      -> None (want None) OK    no marker: NOT_MEASURED, not zero
  tool-failed  -> None (want None) OK    FAILED marker: NOT_MEASURED
[drv_records] selftest: 4/4 fixtures behave                       rc=0
```

On this design it reports `0 / 0 / 0` over two reported invocations with all
three limits declared, and `drv` becomes SATISFIED. It is **REQUEST 5**.

`em` and `equivalence` stay UNDETERMINED. They are not in the head-to-head's
floor, so they do not block it, and the nine-axis gate correctly reports every
arm as `UNDETERMINED` overall. **Both facts are published; neither is rounded
into the other.**

### 8.5 The fifth condition refuses the comparison the search most wants to make

The one comparison a search naturally wants — *our cross-layer winner against
our PnR-only winner* — is **REFUSED**, and correctly:

```
### h2h_F   (p04 -> c02)
[FAIL] ppa_head_to_head_check: BASELINE_TUNED_BY_US
  baseline does not declare `tuned_by_this_project: false`. A baseline we tune
  is an oracle we wrote, and a favourable number measured against it says
  nothing about silicon.                                             rc=1
```

**The gate is right and the refusal is published rather than routed around.** A
search-internal ranking is not a product claim. So every passing head-to-head in
this document is measured against the **untuned shipped default**, and the
cross-layer-vs-PnR-only figures in §0 and §5 are presented as *attribution
within one search* — which is what they are — and not as gate-blessed claims.

### 8.6 The head-to-heads that PASS

All against `b000`, the untuned shipped default. Power from the labelled
post-route diagnostic; setup at `tt`; identical scope on every axis in every arm.

| record | subject | area µm² | Δ | power W | Δ | pareto | rc |
|---|---|---:|---:|---:|---:|---|---|
| `h2h_D` | PnR-only winner `p04` | 6136 | −6.95 % | 0.000559 | −2.44 % | SUBJECT_DOMINATES | 0 |
| `h2h_G` | cross-layer only, PnR untouched `x01` | 6509 | −1.29 % | 0.000563 | −1.75 % | SUBJECT_DOMINATES | 0 |
| `h2h_J` | cross-layer only, PnR untouched `z01` | 6312 | −4.28 % | 0.000682 | +19.02 % | INCOMPARABLE | 0 |
| `h2h_M` | cross-layer only, PnR untouched `z22` | 6460 | −2.03 % | 0.000564 | −1.57 % | SUBJECT_DOMINATES | 0 |
| `h2h_C` | cross-layer `c02` | 6040 | −8.40 % | 0.000540 | −5.76 % | SUBJECT_DOMINATES | 0 |
| `h2h_I` | **cross-layer Pareto winner `z21`** | **6011** | **−8.84 %** | **0.000545** | **−4.89 %** | **SUBJECT_DOMINATES** | 0 |
| `h2h_L` | **cross-layer, ECO-preserving `z23`** | **6106** | **−7.40 %** | **0.000541** | **−5.58 %** | **SUBJECT_DOMINATES** | 0 |
| `h2h_N` | cross-layer objective winner `u01` | 5941 | −9.90 % | 0.000747 | +30.37 % | **INCOMPARABLE** | 0 |
| `h2h_K` | cross-layer objective winner `w02` | 5942 | −9.89 % | 0.000747 | +30.37 % | **INCOMPARABLE** | 0 |
| `h2h_O` | cross-layer, ECO-preserving objective `u04` | 6050 | −8.25 % | 0.000747 | +30.37 % | **INCOMPARABLE** | 0 |
| `h2h_E` | cross-layer, ECO-preserving `c05` | 6148 | −6.76 % | 0.000541 | −5.58 % | SUBJECT_DOMINATES | 0 |
| `h2h_H` | cross-layer `z11` | 5961 | −9.60 % | 0.000698 | +21.82 % | **INCOMPARABLE** | 0 |

`h2h_D` reproduces the published PnR-only result exactly (−6.95 % area,
−2.44 % power), which is the control that makes the rest of the column mean
something.

Every one of these carries the gate's own closing line, and it belongs in this
document too:

> **NOT SILICON**: every arm here is a simulated triple. This is a better number
> than a pass rate and it is not a wafer measurement.

---

## 9. Did the cross-layer search beat the PnR-only winner? Yes, three ways, and one of them is not a win

* **On the declared objective**: `u01` 5941 vs `p04` 6136 — **−3.18 %**. But
  +33.6 % power. **A trade.** The gate calls it `INCOMPARABLE` and so does this
  report. The same trade is available with the ECO spares kept: `u04` at
  6050 µm² (−1.40 % against `p04`) with all ten present.
* **On the Pareto front**: `z21` 6011 / 0.000545 W vs `p04` 6136 / 0.000559 W —
  **−2.04 % area and −2.5 % power at once.** An improvement, not a trade.
* **On the Pareto front with ECO readiness intact**: `z23` 6106 / 0.000541 W
  with **all ten spare cells present**, vs a PnR-only winner that deleted all
  ten. **−0.49 % area and −3.2 % power against an arm that was already spending
  its ECO budget**, and −2.94 % / −3.7 % against the PnR-only arm that kept it.

And the honest ceiling. **At the shipped place-and-route defaults, with no PnR
knob touched at all**, the best ADMITTED cross-layer candidate is `z01` at
**6312 µm² (−4.28 %)** and it is a power trade (+19.0 %); the best Pareto-clean
one is `z22` at **6460 µm² (−2.03 %) with −1.57 % power** (`h2h_M`, rc=0,
`SUBJECT_DOMINATES`). **Neither beats the PnR-only winner's 6136 on its own.**
The layers compose; on this design the RTL layer alone does not out-earn the
placement layer. That is a smaller claim than "cross-layer wins" and it is the
one the measurements support.

It is also the reason the three results above are stated at the PnR winner's
knobs rather than at the defaults: the cross-layer contribution is what the RTL
adds **on top of** the best the tuner could do, measured at the tuner's own
configuration, and −2.04 % area with −2.5 % power is what it adds.

---

## 10. Reproducing

```bash
# the space
python3 programs/crosslayer_search_space.py <project> --json reports/space.json

# one candidate  (rtl variant, die, density, spare, synthesis strategy)
bash tools/run_trial.sh z21 csa_alt_maj auto 0.60 0.00 ks

# a wave
bash tools/drive.sh search/trials3.txt        # concurrency 8, one container each

# equivalence, per candidate
bash tools/run_equiv.sh csa_alt_maj           # default budget
bash tools/run_equiv_long.sh nr_csel16 21600  # same gate, longer budget

# per-arm records, feasibility, contract
python3 tools/build_arm.py z21
python3 tools/gen_declaration.py z21
bash    tools/diag_power.sh <run> <out>       # the labelled post-route power

# the comparison
python3 tools/head_to_head.py h2h_I --baseline b000 --subject z21 \
        --power diagnostic --timing-corner tt --baseline-source ... --subject-source ...
python3 tools/drv_records.py --selftest
python3 tools/summarize.py
```

Environment: EDA image `ghcr.io/vibeic/vibeic-eda@sha256:24b5074b6863…`
(tag `0.3.13`), OpenROAD `26Q3-1535-g543c33894f`, OpenSTA `2.7.0`,
Yosys `0.68+ 0048145dd`, KLayout + netgen from the same image. Host 32 cores /
125 GB. Concurrency 8, `VIBEIC_OPENROAD_THREADS=3`, one container per trial,
created and destroyed around it.

`ppa_contract_check.py` is run **inside the pinned image**, because it needs
`jsonschema >= 4` and this host carries 3.2.0 — where it correctly returns rc=2
`[CANNOT CHECK]` rather than a false pass. Nothing about the check is relaxed;
it is given the dependency it says it needs. That is **REQUEST 6**.

---

## REQUESTS TO THE LANDER

Ordered by how much they unblock. Every one names the file and the reason.

**1 — `programs/phase3_one_shot_runner.py`: add a first-class synthesis-strategy
flag.** The `synthesis_strategy` lever is admitted by
`crosslayer_search_space` as `no_design_change`, and the runner exposes no
actuator for it. The only one it reads is `input/reference_flow/*.mk`, which its
own audit line reports as *the design's* declaration. A search that must write
into the design's input tree to turn a knob that changes no design is one
mislabel away from looking like a cheat. `--synth-strategy {none,area,delay,…}`
or `--adder-map <file>` would let the lever be turned where it belongs.

**2 — `docs/PPA_INTERFACES.md`: state where the RTL sits when the search is
cross-layer.** §4 and the contract lane are written for a search whose RTL is
fixed. A cross-layer search must declare the SPECIFICATION as `problem` and the
RTL as `implementation`, licensed by a `crosslayer_rewrite_equivalence` PASS.
That rule is currently implicit, and the obvious reading makes
`ppa_problem_integrity_check` refuse every legitimate cross-layer comparison.
Proposed wording: *"An artefact the search is permitted to rewrite may not sit
in the `problem` identity. Where a lever rewrites the design, the design's own
input documents are the problem and the rewrite gate is what makes the two
implementations comparable."*

**3 — `_ppa/timing.py`: omit the scope keys it cannot establish.** Every `ss`
and `ff` row is emitted with `"rc_corner": null, "clock": null`.
`PPA_INTERFACES.md` §2 forbids exactly this, `ppa_head_to_head_check` refuses on
`SCOPE_SENTINEL`, and the corner that cannot be used is `ss` — the governing
setup corner. The `tt` rows already carry `rc_corner: "max"`, so the parser
knows how; it just writes `null` where the report did not say.

**4 — `programs/phase3_one_shot_runner.py`: fix the Phase-3 power session, or
stop the report claiming post-PnR.** `reports/phase3/power_spm.tcl` links
`phase2/stage2/synth/spm_synth.v` and reads no SPEF, while `power.rpt`'s own
Substance section says the values reflect the post-PnR netlist. Measured here:
1.873× low, clock tree at exactly 0.0 %. Unchanged since the previous lane
reported it. Either fix is honest; shipping both statements is not.
Related and smaller: `_ppa/power.py` fills `process`/`voltage_v`/`temperature_c`
and not `mode`, which is `SCOPE_INCOMPLETE` at the head-to-head.

**5 — a `drv` producer.** Nothing in `programs/` emits any of the five metric
names `_ppa/feasibility.DEFAULT_AXES` proves `drv` from, so `drv` is
UNDETERMINED on every run and "both arms feasible" can never hold.
[`tools/drv_records.py`](tools/drv_records.py) is a working reference
implementation with its four fixtures; the parts that matter are the
ran-vs-never-ran discriminator (`SIGNOFF_CHECK_TYPES_REPORTED` /
`_FAILED` / neither) and honouring the report's own
`SIGNOFF_MAX_FANOUT_SEMANTICS` warning by reading the SDC the sign-off session
actually loaded.

**6 — declare `jsonschema >= 4` as a dependency, or bundle it.** `PPA-C-010` is
worded correctly and returns rc=2, but it means `ppa_contract_check.py` cannot
run on a stock host. The pinned EDA image carries 4.26.0; the plugin should say
so.

**7 — `crosslayer_rewrite_equivalence.py`: report HOW FAR the induction got, and
consider `--induct-depth`.** A `NOT_PROVEN_EQUIVALENT` that exhausted its budget
at induction step 19 of an estimated 33 is a different finding from one that
converged and left a point open — `pipe1` is the second kind in 3.8 s, `nr_rca`
the first in 1795 s, and the JSON reports both as `unproven_points: 1`. Adding
`induction_depth_reached` and `budget_exhausted: true|false` would let a search
tell "give it more time" from "this needs a different relation". The deeper
point: a candidate that changes a state ENCODING is the most valuable rewrite an
agent can make and the one this relation is least able to prove; a
`--state-relation <file>` hook for a caller-supplied invariant (here
`a == s + c`) would open the whole `nr_*` family, which was **−27 % at
synthesis**.

**8 — OpenROAD SIGSEGV in `postroute_drv_repair`, 10 reproductions.** Every
non-redundant-accumulator arm crashes the same way after
`DRT-0198 Complete detail routing`; no state-encoding-preserving arm ever did
(0 of 52). The runner's classification and resume path are both correct and both
worked — this is a bug report for the tool, with ten reproducible cases in
`records/trials/{x03,x04,x11,x12,x13,y03,y04,y08,z24,z25}/`. On two of them
(`y01`, `y05`) the resume consumed the whole 3600 s trial budget.

**9 — `_ppa/backends/openroad.py`: name the taps in the area taxonomy.**
`area.design_report.um2` is *logic + tap*, excluding fill and decap. Establishing
that took summing the PDK liberty over the routed netlist and matching the
tool's figure to 0.2 µm². It is the objective of this search and of the
published one, and nothing in the record says what it includes. A
`scope` key — `"includes": "logic+tap"` — would make it readable.

**10 — smaller ones.** `ppa_contract_build.py` refuses a tag-form image
reference (`PPA-C-002`) with a good reason and no hint; printing "use
`docker inspect --format '{{index .RepoDigests 0}}'`" would save the next lane a
cycle. And `_ppa/feasibility.py`'s per-axis view semantics deserve one worked
example in `PPA_INTERFACES.md` §2.1: declaring `[ss, tt, ff]` for BOTH setup and
hold leaves setup@ff and hold@ss permanently `NO_RECORD` — because the flow signs
setup off at `{ss, tt}` and hold at `{tt, ff}`, which is correct practice — so
the axis can never be adjudicated. The strictest declaration a flow can satisfy
is not the broadest one that can be written down.

---

## Where everything is

```
ppa-crosslayer/
  RESULT.md
  search/     space.json  trials.txt trials2..6.txt
  rtl/        base/ csa_alt_maj/ csa_mux/ csa_aoi/ csa_add1/ hier_split/
              csa_alt_hier/ csa_mux_hier/ nr_rca/ nr_rca_hier/ nr_csel16/
              nr_csel8/ pipe1/            one spm.v each, header = lever + citation
  reference_flow/  none rab swap rab_swap ks sk hc     the synthesis strategies
  equivalence/     one crosslayer_rewrite_equivalence verdict per candidate RTL
  records/    trials/<id>/  run.json objective.json records.json records_flat.json
                            signoff_records.json timing_records.json
                            drv_records.json candidates.json feasibility_report.json
                            declaration.json contract.json contract_check.json
                            assembly.json diag/power_postroute*
              h2h_*.json  h2h_*_report.json   every head-to-head record, refusals included
              problem_integrity_*.json        condition 0, per pair
              summary.json                    every figure this document quotes
  tools/      run_trial.sh drive.sh run_equiv.sh run_equiv_long.sh
              extract_area.py build_arm.py gen_declaration.py head_to_head.py
              drv_records.py diag_power.sh decompose.py cell_areas.py
              summarize.py gen_tables.py
```

Nothing under `vibe-ic-marketplace/plugins/vibe-ic/` is touched by this branch.
