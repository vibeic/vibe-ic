# LAND.md — the topology library sized its resistors from a constant, and the process was never asked

**Issue:** vibe-ic#1952 — "A2 topology library `w_res=0.35` sits below SG13G2 rppd layout
wmin=0.50 — every rppd chip carries a built-in 35.3% LVS property error"
**Branch:** `i1952cand`, based on `origin/main` `6b7136f4c` (plugin v1.14.61)
**This file:** `A_a2_wres/LAND.md`. Measurement log: `A_a2_wres/FINDINGS.md`.
**VERSION-LESS** — no version bump, no baseline write, no PR, no push. The owner lands.

---

## 1. What the defect actually is

`analog_a2_topology_emit.LIBRARY["ldo"]` carried `constants.w_res = 0.35` and `w: 0.35` on
its three `res` devices, as a **static library constant**. Nothing in A2 consulted any
layout rule, on any PDK. Reproduced on the base before any edit:

```
$ python3 programs/analog_a2_topology_emit.py <repro> --pdk ihp-sg13g2
constants: {'l_unit': 20.0, 'w_res': 0.35}
res devices: [('r_bias', 0.35), ('r1', 0.35), ('r2', 0.35)]
```

Per the issue's own measurement (campaign tree, v1.14.47 — that A5 generator is not on this
base and I did not re-verify it here), the A5 layout generator does the right thing and
clamps the DRAWN device up to the process minimum, recording the clamp. The netlist keeps
the constant. So the two disagree **by construction, on every block**, and the disagreement
is only discovered at A6 when netgen compares them:

```
w circuit1: 5e-07   circuit2: 3.5e-07   (delta=35.3%, cutoff=0%)
Final result: Circuits do NOT match uniquely (property errors present)
```

## 2. The premise held, and it is worse than the issue reports

The issue is titled as an SG13G2 problem. It is not. Reading each shipped analog PDK's
**own** rule record (inside `ghcr.io/vibeic/vibeic-eda:0.2.24`):

| PDK family | rule | min drawn width | vs the library's 0.35 |
|---|---|---|---|
| `ihp-sg13g2` | `Rppd.a` "Min. GatPoly width = 0.50" | 0.50 µm | **illegal**, 35.3 % delta |
| `gf180mcuD` | `PRES.1` "Minimum width of Poly2 resistor is 0.8µm" | 0.80 µm | **illegal**, 56.3 % delta |
| `sky130A` | `poly.3` "mrp1 resistor width" | 0.33 µm | legal — 0.35 is above it |

Verbatim sources, all three cited in the registry entries themselves:

```
/foss/pdks/ihp-sg13g2/libs.tech/klayout/tech/drc/rule_decks/sg13g2_tech_default.json:166
    "Rppd_a": 0.5,
/foss/pdks/ihp-sg13g2/.../sg13g2_maximal.drc:2603,2604
    Rppd_all.ext_width(0.5.um)  ->  output("Rppd.a", "Min. GatPoly width = 0.50")
/foss/pdks/gf180mcuD/libs.tech/magic/gf180mcuD.tech:3124
    width rpp 800 "ppolyres minimum width < %d (PRES.1)"
  corroborated by .../klayout/tech/drc/rule_decks/pres.rb:32,35
/foss/pdks/sky130A/libs.tech/magic/sky130A.tech:4831
    width mrp1 330 "mrp1 resistor width < %d (poly.3)"
```

Two of the three analog-populated PDKs are affected by one constant, and the third is the
**control**: its minimum sits *below* the library nominal, so a correct fix must leave it
alone. That is what makes the fix a floor rather than a retune — and it is why simply
editing `0.35` to `0.5`, which is how the campaign closed the two blocks by hand, is not a
fix: it would be wrong on `gf180mcuD` (too small) and gratuitous on `sky130A`.

## 3. The change

### `programs/pdk_analog_layout_minima.py` — new, and the whole general core

One generic reader. Given ANY selector it returns that family's
`analog_device_layout_minima.roles` from `pdk_registry.json`, keyed on the same generic
device ROLE tokens the analog IR already uses (`res`/`nmos`/`pmos`/`cap`), plus
`floor_width(value, minimum) -> (value, raised_from)`.

**No PDK family, foundry, vendor or device name appears anywhere in it.** It supplies no
default and no fallback constant: a family with no record floors nothing, and the caller is
told so. It behaves identically for a family it has never seen — proven against a synthetic
registry carrying an invented family and an invented rule.

It also becomes the **one** selector→family matcher: `analog_a2_topology_emit.pdk_device_params`
now resolves through it instead of keeping a second copy of the same match ladder, so the
electrical constants and the layout minima can no longer be read off two different families.

### `programs/pdk_registry.json` — the rule records

New `analog_device_layout_minima` block on the three analog-populated families. Each carries
`_measured_from` naming the file, line, rule id and rule text it was read from — the same
honesty pattern `metal_density_windows` already uses — and `gf180mcuD` additionally carries
`_corroborated_by` for the second deck that states the same number.

`roles` is deliberately **partial**: `res` only. That is the rule this issue is about and
the only one measured. An absent role means NOT MEASURED and floors nothing; it never reads
as "no minimum exists". Adding `nmos`/`pmos`/`cap` later is a data edit with no code change.

### `programs/analog_a2_topology_emit.py` — the floor

* New library key `constant_roles` declares which `constants` entries are the drawn WIDTH of
  which role. `{"w_res": "res"}` on the ldo entry. `l_unit` is a length in the same units and
  is deliberately not listed — inferring "is this a width?" from the name would corrupt it,
  and there is a test that fails if it does.
* New `floor_geometry_to_pdk()` raises every declared width constant **and** every device's
  `w` to the resolved role minimum, on a COPY, returning one record per clamp that fired.
  Both have to be floored because they reach the netlist by different routes:
  `analog_a3_netlist_emit` renders each device's own `w` (`:746-751`) and separately seeds
  `device_param_exprs` from `constants` (`:620`), so a constant left un-floored would
  re-introduce the illegal width through any expression reading it.
* Every clamp is recorded — `_provenance.layout_minima.clamps` (target, role, library value,
  PDK minimum, rule id, rule text), `_provenance.fields_clamped`, the run report record, and
  a `topology.md` section. A silent clamp is the same defect one step later.
* `minima_available` distinguishes "checked, nothing was below the floor" from "this family
  declares no minimum, so nothing was floored". A reader who cannot tell those apart reads
  the second as the first.

### Measured after the change, same command, four families

```
ihp-sg13g2   w_res=0.5   res_w=[0.5,0.5,0.5]     minima=True   clamped=[w_res, r1.w, r2.w, r_bias.w]
gf180mcuD    w_res=0.8   res_w=[0.8,0.8,0.8]     minima=True   clamped=[w_res, r1.w, r2.w, r_bias.w]
sky130A      w_res=0.35  res_w=[0.35,0.35,0.35]  minima=True   clamped=[]      <- control, unchanged
asap7        w_res=0.35  res_w=[0.35,0.35,0.35]  minima=False  clamped=[]      <- no record, says so
```

and the floored width reaches the netlist netgen actually compares — A3 on the same project:

```
xr_bias vdd nbias vss rhigh w=0.5 l=60
xr1     vout vfb   vss rhigh w=0.5 l=20
xr2     vfb  vss   vss rhigh w=0.5 l=20
```

No runner wiring was needed: `analog_one_shot_runner` invokes A2 without `--pdk`, so A2
falls through to `_declared_pdk_target()` — the project's own L19 `pdk_target` — which is the
right source and is already the same field A3 reads. A real run on a project that declares
`ihp-sg13g2` therefore floors without anyone passing a flag. (Verified by reading
`analog_one_shot_runner.py:444-471,905-925`: the only `--pdk` it passes is A4's.)

(A3 resolves the `res` role to `rhigh` rather than `rppd` on this PDK. The floor is right
either way: this PDK states 0.50 for every resistor flavour it ships — `Rsil_a`, `Rpnd_a`,
`Rppd_a`, `Rhi_a`, `sg13g2_tech_default.json:155,161,166,171 — so the number does not depend
on which flavour a design picks. Recorded in the registry entry's `_note`.)

## 4. Tests — `programs/tests/test_issue1952_a2_res_width_floors_at_pdk_layout_minimum.py`

Every number asserted against a shipped family is **read out of the registry at test time**,
never retyped, so the tests cannot drift from the data and cannot become the place a wrong
constant survives.

**Bidirectional control, run for real.** A scratch worktree at `origin/main` `6b7136f4c` was
given the new test file, the new reader and the new registry data — i.e. everything except
the A2 emitter change — so the RED arm measures the defect and not an ImportError:

| | pre-fix (`origin/main` emitter) | post-fix |
|---|---|---|
| total | **11 failed, 4 passed** | **15 passed** |

The 4 that pass on BOTH sides are the ones that must:

* `test_a_pdk_whose_minimum_is_below_the_library_value_is_left_untouched` — **the control the
  issue needs.** `sky130A`'s 0.33 is below the library's 0.35, so the emitted geometry must be
  byte-identical before and after. It carries no assertion about the new provenance fields,
  deliberately: mixing those in would make it another RED arm and it would stop proving the
  fix left this family alone. The disclosure half is a separate test, and that one IS red pre-fix.
* `test_a_length_constant_is_not_floored_by_a_width_rule` — `l_unit` survives the largest floor.
* `test_the_reader_floors_against_a_pdk_it_has_never_seen` — synthetic family, reader level.
* `test_every_registry_minimum_cites_the_rule_it_was_read_from` — every declared record names
  its rule and its `_measured_from`, including families added after this was written.

Red pre-fix / green post-fix: the two shipped-family defect arms (`ihp-sg13g2`, `gf180mcuD`)
× {below-minimum, exactly-the-rule-not-a-margin, clamp-is-recorded}, the no-record family
degrading loudly, the producer-level synthetic family, the two-blocks-in-one-run
contamination guard (the LIBRARY is a module-level dict shared across blocks), and the
source guard asserting no shipped family name appears in the reader or in any of the four
emitter functions that implement the floor — scoped to the live function objects via
`inspect.getsource`, so renaming one cannot quietly drop it from the scan.

## 5. What was run

| check | result |
|---|---|
| new suite, fixed tree | 15 passed |
| new suite, pre-fix emitter | 11 failed, 4 passed (the intended 4) |
| `test_analog_a2_topology_emit` + `_select_check` + `test_analog_a3_netlist_emit` | 29 passed |
| analog + registry + pdk regression sweep (~110 files) | see §6 |
| `source_chip_agnostic_check.py` | PASS, 1661 files |
| `plugin_full_audit.py` D1 | PASS (1327 programs) |
| `plugin_full_audit.py` D2 | FAIL — **pre-existing**, byte-identical on the pre-fix tree (`flow_condition_reachability_check`, step DT2, known-open vibe-ic#235 baseline) |

## 6. What this does NOT fix — stated, not buried

* **The A2 GATE still measures vocabulary only.** `analog_a2_topology_select_check` reads
  `topology.md` for circuit words and never opens `topology.json`. So a topology.json
  **hand-authored by the `analog-topology-select` skill** — the path the issue's
  `delta_sigma` block took, since `delta_sigma` is in `LIBRARY_GAPS` on this base — is
  floored by nothing. Closing that means the gate growing a structural check with a PDK
  selector, which is a new BLOCKING gate and owes the full `flow-change-acceptance`
  standard. It is a separate change and should be a separate issue.
* **Only the `res` role is populated**, and only `min_width_um`. Channel LENGTH minima are
  a live adjacent risk this patch does not touch, and it is not hypothetical: the library's
  `oscillator` entry draws `l=0.15`, which is exactly sky130's poly minimum
  (`sky130A.tech:4333`, `width allpoly,polyfill 150 (poly.1a)`) but is **below gf180mcuD's
  0.28** (`gf180mcuD.tech:3092`, `extend nfet,ncap *ndiff 280 (PL.2)`). Same defect, different
  dimension. It is left out because closing it means measuring the length rules across the
  families and because a length floor interacts with W/L in a way a width floor does not —
  and recording an unmeasured number is precisely the defect this patch removes. The
  reader's shape already accommodates it as pure data.
* **A floor makes geometry drawable, not correct.** It is not a sizing solution. Whether a
  floored width still meets spec is an A4 corner-sweep question — the artefacts say so, in
  both `limits` and `topology.md`. On the campaign's own blocks it did (ldo PASS
  vout=1.19151/1.2), but that is a fact about those blocks, not about the floor.

## 7. Landing constraints honoured

No version bump. No `--write-baseline`. No PR. No push. Nothing outside
`programs/{analog_a2_topology_emit.py, pdk_analog_layout_minima.py, pdk_registry.json,
tests/test_issue1952_*.py}` plus this `A_a2_wres/` pack. NDA clean — every PDK named is an
open PDK already present throughout the plugin, every constant is from a public open-source
rule deck, and `source_chip_agnostic_check.py` passes.
