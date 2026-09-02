# A falsifiable ROUTING criterion for the OpenROAD `NS Metal` fix

Measured 2026-09-02/03 on 8HD-4. Every number below came from running the tool
named beside it; nothing here is recalled. Subject: `subservient` × `gf180mcuD`,
plugin tree `030b86c544`, argv `--top-name subservient --ic-name subservient
--die-um auto --util 0.45 --pdk gf180mcuD`, routed netlist
`post_dft_netlist.v` sha256 `c52197a4…` byte-identical in every arm, die
416×416 µm at util 0.18 in every arm.

Images are named by **digest** (for reproduction) and by their **OCI label**
(for humans). No version string from the image is recorded as an identity.

| arm | image | `openroad -version` | contains `#12`+`#13` |
|---|---|---|---|
| A | `ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2e057…` (label `org.opencontainers.image.version` = `2026.06`) | `26Q3-1472-g42cadea9df` | no |
| C | local `sha256:190b37be3407…` — arm A's image with ONLY `/foss/tools/openroad/bin/openroad` replaced | `07c9614452…` | **yes** |
| R | local `sha256:c6de76d5e73e…` — same build recipe as C, from `42cadea9df` with the two cherry-picks REMOVED | `42cadea9df…` | no |

`klayout`, `sta` (OpenSTA), `magic`, `yosys` and the `gf180mcuD` tree are
byte-identical across A, C and R (sha256 `fab07da4aa887c34`, `2a61a5aeb0103d28`,
`17f68edb3134f5f5`, `174d8d71dfd77e29`, `8342c17bea662e29`). The only thing that
varies is the `openroad` binary.

The two commits, in `vibeic/OpenROAD`, an adjacent pair (`#12` is `#13`'s direct
parent), both confined to `src/drt`:

* `0dfe7d129` — *a same-net edge abutment is not insufficient metal* (#12)
* `7ec616c6c` — *repair the NS Metal junctions post-route verification finds* (#13)

---

## The criterion

> **On a design whose only post-route residual is `NS Metal` at a fixed
> cell-local offset, a router that carries `#12`+`#13` converges — 0 violations,
> a streamed GDS and an LVS match — and the same router with those two commits
> removed does not, leaving that residual and failing `pnr`.**

It is falsified by either of: a router carrying both commits that still leaves an
`NS Metal` residual on this design, or a router without them that converges on it.

### Forward — add the commits
Arm **C** (and its independent repeat **C2**):

```
[INFO DRT-0703] Post-route non-sufficient-metal repair: widened 2 same-net
                junction(s) to MINWIDTH, 0 left unresolved.
[INFO DRT-0702] Post-route verification: 0 violation(s).
ROUTE_LOOSEN_DECLINED reason=route_still_converging kind=not_engaged
                die=416x416um rung=0 residual_series=[0]
```
`pnr` PASS · `gds` PASS 9 056 396 B · `lvs` PASS "Circuits match uniquely" ·
`drc` 2 user violations, `M2.4`=1 `M3.4`=1 (die-wide dummy-fill coverage rules).

### Reverse — remove them, same build recipe
Arm **R**:

```
[WARNING DRT-0701] Post-route verification found 2 violation(s) ...
[INFO DRT-0702] Post-route verification: 2 violation(s).
DRT-0703 occurrences: 0
ROUTE_LOOSEN_DECLINED reason=residual_not_congestion_shaped kind=evidence
                die=416x416um rung=0 residual_series=[2]
FAIL pnr ROUTE_NOT_CONVERGED: detailed route completed with 2 violations remaining
```
`routed_router.drc.rpt`, verbatim:
```
violation type: NS Metal  net:__uuf__._0434_  (229.7500,177.3900)-(229.7900,177.4450) Metal1
violation type: NS Metal  net:__uuf__._0055_  (317.1100,292.9550)-(317.1500,293.0100) Metal1
```
**Identical to arm A's residual — same two nets, same bounding boxes.** So the
non-convergence follows from the two commits' absence and not from how the
pinned image happened to be built: R is our own build of the same source,
differing from C by exactly those two commits.

### What this criterion does NOT claim
* **Not** that timing is better. It says nothing about SS setup. Arm A never
  reaches post-route sign-off at all (its `pnr` FAILs, so no GDS), so there is
  no pinned-arm timing number to compare and none is offered.
* **Not** that the DRC result improves. `M2.4`/`M3.4` are die-wide fill-coverage
  rules; they appear the moment a GDS exists and arm A's value for them is
  NOT MEASURED, not clean.
* **Not** that this generalises to other designs. It is a statement about a
  residual class (`NS Metal` at a fixed cell-local offset) on one design.
* **Not** a decision to move the repository's pinned image. It is the routing
  evidence such a decision would rest on.

---

## Two runs of the same inputs produce the same DEF

Arms **C** and **C2** are independent full phase-3 runs — same image digest,
same plugin tree, same argv, same seed project:

| | C | C2 |
|---|---|---|
| 1st-PnR `segments_analysed` | 29137 | 29137 |
| 1st-PnR `max_segment_current_A` | 0.006082 | 0.006082 |
| derived Metal4 floor | 20.18 µm | 20.18 µm |
| **final `subservient.def` sha256** | `64d46d83adaf0f30…` | `64d46d83adaf0f30…` |
| GDS bytes | 9 056 396 | 9 056 396 |
| `drc` user violations | `M2.4`=1 `M3.4`=1 | `M2.4`=1 `M3.4`=1 |
| `lvs` | PASS | PASS |
| SS setup / TNS | −2.030 ns / −16.17 | −2.030 ns / −16.17 |
| EM re-run wall-clock | 3178 s | 4164 s |

**The routed DEF is byte-identical.** Only wall-clock differs, and that is host
load. This closes the last open item from the `pdn_em_resize` work: the stage is
deterministic given the DEF, and the DEF itself is reproducible, so the
10.68 µm / 20.18 µm spread seen earlier was the router difference and nothing
else.

---

## One verifiable statement about the pinned image's provenance

Recorded, not fixed. In `ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2e057…`:

* `/foss/tools/openroad/SOURCES` reads `openroad 4c26918f5a77392910939b51b9c2490b7e7e3201`
* the binary beside it reports `26Q3-1472-g42cadea9df`
* `gh api repos/vibeic/OpenROAD/compare/4c26918f5a...42cadea9df` → `ahead_by 1782`

So the `SOURCES` file names a commit **1782 commits behind** the binary it sits
next to. The binary's own `git describe` string is the one that reproduces.
