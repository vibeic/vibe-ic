# FINDINGS — vibe-ic#1952 (A2 `w_res=0.35` below the PDK poly-resistor layout minimum)

Work dir `/home/reyerchu/_gk1952`, worktree branch `i1952cand`, based on
`origin/main` `6b7136f4c` (plugin v1.14.61).

## 1. Reproduced on the base, before any edit

```
$ python3 programs/analog_a2_topology_emit.py <repro> --pdk ihp-sg13g2
constants: {'l_unit': 20.0, 'w_res': 0.35}
res devices: [('r_bias', 0.35), ('r1', 0.35), ('r2', 0.35)]
```

`analog_a2_topology_emit.LIBRARY["ldo"]` carries `constants.w_res = 0.35` and
`w: 0.35` on all three `res` devices, as a **static library constant**. The
selector never consults any layout rule, on any PDK.

`delta_sigma` is in `LIBRARY_GAPS` on this base (the issue's campaign tree,
v1.14.47, is older/different) — so only the `ldo` entry is reachable from the
library today. The fix is written over *roles*, not over the `ldo` entry, so a
future `delta_sigma`/`bandgap` entry inherits it with no code change.

## 2. The value the drawn device is actually held to — measured, not recalled

Read out of each PDK's OWN rule record inside `ghcr.io/vibeic/vibeic-eda:0.2.24`:

| PDK family | rule | device | min drawn width |
|---|---|---|---|
| `ihp-sg13g2` | `Rppd.a` "Min. GatPoly width = 0.50" | `rppd` | **0.50 µm** |
| `gf180mcuD` | `PRES.1` "ppolyres minimum width" | `rpp` / `ppolyres` | **0.80 µm** |
| `sky130A` | `poly.3` "mrp1 resistor width" | `mrp1` / `res_generic_po` | **0.33 µm** |

Sources (verbatim lines):

```
/foss/pdks/ihp-sg13g2/libs.tech/klayout/tech/drc/rule_decks/sg13g2_tech_default.json:166
    "Rppd_a": 0.5,
/foss/pdks/ihp-sg13g2/libs.tech/klayout/tech/drc/rule_decks/sg13g2_maximal.drc:2603-2604
    Rppd_all.ext_width(0.5.um)
    end.().output("Rppd.a", "Min. GatPoly width = 0.50")

/foss/pdks/gf180mcuD/libs.tech/magic/gf180mcuD.tech:3124
    width rpp 800 "ppolyres minimum width < %d (PRES.1)"

/foss/pdks/sky130A/libs.tech/magic/sky130A.tech:673
    width mrp1 330 "mrp1 resistor width < %d (poly.3)"
```

Two consequences:

* The defect is **not** SG13G2-only. `gf180mcuD` reproduces it worse
  (0.35 vs 0.80 → 56.3 % property delta). Two of the three shipped analog PDKs
  are affected by one static constant.
* `sky130A` at 0.33 is a genuine **control**: its minimum is BELOW the library
  value, so a correct fix must leave 0.35 alone there. That is what makes this
  a floor and not a retune.

## 3. Where the fix has to sit

`analog_a3_netlist_emit` renders `w=` straight out of the A2 IR
(`programs/analog_a3_netlist_emit.py:746-751`, `d.get("w")` with
`device_param_exprs` overrides), and `constants` feed the expression env
(`:620`). So flooring the IR — both `constants` and each device's `w` — is what
reaches the netlist that netgen later compares against the drawn layout.

`pdk_registry.json` had no layout-minimum record of any kind: `analog_device_params`
carries only `vth_n_v` / `vth_p_v` / `nominal_supply_v`. The registry pattern to
copy is `metal_density_windows`, which already records rule constants with a
`_measured_from` citation.

## 4. Shape landed

* `programs/pdk_analog_layout_minima.py` — new, generic reader. Given ANY
  selector it returns that family's `analog_device_layout_minima.roles` from the
  registry. No family name appears in it.
* `pdk_registry.json` — new `analog_device_layout_minima` block on the three
  analog-populated families, each with `_measured_from` quoting the rule file,
  line, rule id and rule text above.
* `analog_a2_topology_emit` — `constant_roles` on the library entry declares
  which constants are drawn widths of which role; `build_ir` floors those
  constants and every device `w` to the resolved role minimum and records every
  clamp in `_provenance.layout_minima` + `fields_clamped`; `topology.md` states
  it.

## 5. Adjacent, measured, deliberately NOT fixed here

The same defect exists in the LENGTH dimension and is not hypothetical:

| PDK | transistor length rule | min |
|---|---|---|
| `sky130A` | `poly.1a` (`sky130A.tech:4333` `width allpoly,polyfill 150`) | 0.15 µm |
| `gf180mcuD` | `PL.2` (`gf180mcuD.tech:3092` `extend nfet,ncap *ndiff 280`) | 0.28 µm |

`LIBRARY["oscillator"]` draws `l: 0.15` on all six devices — exactly sky130's minimum, and
below gf180's. Left out of this patch on purpose: it needs the length rules measured across
the families, and a length floor interacts with W/L in a way a width floor does not.
`analog_device_layout_minima.roles` accommodates it as pure data when someone measures it.

Residual, deliberately NOT in scope here and stated in LAND.md: the A2 GATE
(`analog_a2_topology_select_check`) still measures vocabulary only, so a
topology.json hand-authored by the `analog-topology-select` skill (the path the
issue's `delta_sigma` block took) is not floored by anything.
