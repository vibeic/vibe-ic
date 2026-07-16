# vibeic-eda

**Forked + bug-fixed open-source EDA toolchain, shipped as one Docker image.**

`vibeic-eda` is the [hpretl/iic-osic-tools](https://github.com/iic-jku/iic-osic-tools)
base (all the open-source EDA tools + the sky130 / gf180mcu / ihp PDKs) with our
**patched `vibeic/*` tool forks** layered in to close the capability gaps where stock
open-source EDA falls short of commercial tools. Every fix ships with a reproducible
**FAIL → PASS proof** (see [`FIX_STATUS.md`](./FIX_STATUS.md)).

You do **not** need to fork or build the individual tools yourself — pull one image and
you have the whole fixed toolchain. The image is published to the **GitHub Container
Registry (GHCR)** and is public (no login required):

```bash
docker pull ghcr.io/vibeic/vibeic-eda:0.2.18
```

> The image lives on GHCR (`ghcr.io/vibeic/...`), **not** Docker Hub — always use the
> full `ghcr.io/` prefix. A bare `docker pull vibeic/vibeic-eda` resolves to Docker Hub,
> which does not host this image and returns "repository does not exist / access denied".
> The newest released tag is `ghcr.io/vibeic/vibeic-eda:latest`.

---

## Why forked, not just wrapped

Most "AI EDA" stacks *call* open-source tools and inherit their bugs. We instead **fork
the tools and fix them** where they silently produce wrong results or crash — then prove
each fix reproducibly against the stock binary. A few of the load-bearing ones:

| Tool | What stock does wrong | vibeic fix (proven) |
|---|---|---|
| **OpenROAD** | post-detailed-route `repair_design` **segfaults** on real parasitics (Signal-11) | routes buffering through the Steiner builder → runs to completion, max-slew violators **289 → 0**, exit 0 |
| **netgen** | a transistor property mismatch is reported as `Circuits match uniquely` — a **silent LVS false-pass** | `Final result:` reflects property errors → correctly `do NOT match uniquely` |
| **yosys** | tri-state fanin dropped in `synth`; gate-level ripple adders never lifted to parallel-prefix | `tribuf` preserved (`$_TBUF_`); `lift_adder` restructures ripple → Kogge-Stone, depth 128 → 73, CEC-proven |
| **ngspice** | a failed `.measure` in `-b` batch exits **rc = 0** — CI reads it as a pass | per-`.measure` PASS/FAIL marker + nonzero rc on failure |
| **magic** | `def read` silently drops an unmapped-layer route (metal open) | retains geometry on unknown layers + warns |
| **klayout** | sign-off DRC on a foundry Calibre/SVRF `.rule` deck needs a **commercial license** | native `svrfdrc` C++ buddy runs the deck directly on KLayout's DRC engine — byte-identical to the reference on a real 87k-line foundry deck, license-free |

Full scoreboard (8 forks, gatekeeper-verified proofs): [`FIX_STATUS.md`](./FIX_STATUS.md).

---

## Quick start

**Headless / batch (CI, scripted flows):**
```bash
docker rm -f vibeic-eda 2>/dev/null || true   # "name already in use"? drop the old container first
docker run -d --name vibeic-eda ghcr.io/vibeic/vibeic-eda:0.2.18 --skip sleep infinity
docker exec vibeic-eda yosys --version
docker exec vibeic-eda openroad -version
```

**Using it with the Vibe-IC plugin (identity bind-mount required).** Flows that write
into the container from the host — the plugin's phase-3 place-&-route step does an in-container
`cd <host_project_path>` — need the project tree mounted at the **same path** inside the
container, or you get `cd: No such file or directory`. Start it with an identity mount:
```bash
docker run -d --name vibeic-eda \
  -v "$PWD:$PWD" -w "$PWD" \
  ghcr.io/vibeic/vibeic-eda:0.2.18 --skip sleep infinity
# then point the MCP at it:  EDA_CONTAINER=vibeic-eda
```

**Interactive desktop (VNC / noVNC in the browser):**
```bash
docker run -d --name vibeic-eda \
  -p 5901:5901 -p 8080:80 \
  ghcr.io/vibeic/vibeic-eda:0.2.18
# noVNC:  http://localhost:8080     VNC: localhost:5901   (default password: abc123)
```

**Mount your design directory:**
```bash
docker run -it --rm -v "$PWD:/foss/designs/work" -w /foss/designs/work \
  ghcr.io/vibeic/vibeic-eda:0.2.18 bash
```

Tools live at the same paths as the iic-osic-tools base (`/foss/tools/bin/...`), so any
flow written for iic-osic-tools runs unchanged — it just gets the fixed binaries.

**Upgrade a running container to a new image version:** a container is pinned to the
image ID its tag resolved to at creation, so pulling a newer image does NOT update it —
the container must be recreated. [`restart-eda.sh`](./restart-eda.sh) does that safely:
it clones the existing container's mounts / cmd / user / workdir onto the new image,
refuses to interrupt an in-flight EDA job (override with `FORCE=1`), and verifies the
image ID after the swap. Run it as your normal user (not root/sudo).
```bash
./restart-eda.sh              # recreate on the PINNED version from ./VERSION
./restart-eda.sh 0.2.11       # or any explicit tag / full image ref
```
The no-argument default is deliberately the pinned `VERSION`, never a floating
`latest` — a stale local `latest` would silently hand you an outdated toolchain.

---

## What's inside

**Forked + patched (8 tools)** — each pinned to a commit SHA in the [Dockerfile](./Dockerfile):

| Tool | Fork branch | Focus |
|---|---|---|
| OpenROAD | `vibeic/post-route-detailed-routing-repair` | post-route repair on real parasitics + incremental reroute |
| yosys + abc | `vibeic/synth-fixes` | tri-state preserve, slang SV frontend, D-latch mapping, prefix-adder lift |
| ngspice | `vibeic/batch-honesty` | batch rc honesty, `.param` expansion, native Monte-Carlo (LHS), DC homotopy |
| magic | `vibeic/lvs-fidelity` | `ext2spice` label→port, unknown-layer/via retain, SPECIALNET power names |
| netgen | `vibeic/lvs-fidelity` | property-error verdict, portless guard, `-auto-global`, `-nopower`, black-box match |
| iverilog | `vibeic/sv-tb-coverage` | nonblocking-event codegen segfault fix, package ordering |
| klayout | `vibeic/svrf-native-drc` | streamout MANUFACTURINGGRID snap + merge-abutting + foundry layer-map, **AND** native in-KLayout SVRF/Calibre DRC (`db::SVRFDeck`/`db::SVRFEngine` + the `svrfdrc` C++ buddy — no Python interpreter) |
| verilator | `vibeic/` (base tree) | forked; no custom patch warranted on the shipped version |

**Inherited from the iic-osic-tools base** — OpenSTA, xschem, Xyce, cocotb, SymbiYosys,
Fault, GHDL, and the PDKs: `sky130A`, `gf180mcuD`, `ihp-sg13g2`, `ihp-sg13cmos5l`, `ciel`.

---

## Build from source (reproducible)

The image is built entirely from source, with every fork pinned to a commit SHA, so a
rebuild is byte-for-byte reproducible:

```bash
git clone https://github.com/vibeic/vibeic-eda.git
cd vibeic-eda
docker build -t vibeic-eda:local .
```

Each tool is compiled in a native ubuntu24.04 builder so the binary matches the
iic-osic-tools runtime (python3.12 / glibc2.39). Override any fork ref with
`--build-arg YOSYS_REF=<sha>` etc. **Note:** a full from-source build produces a ~26 GB
image and takes 1–2 h — use a machine with adequate disk (≥ 60 GB free) and cores.

---

## Versioning

Semantic versions track the fix-program milestones in `FIX_STATUS.md`:

- `ghcr.io/vibeic/vibeic-eda:X.Y.Z` — immutable, reproducible from the pinned SHAs at that tag.
- `ghcr.io/vibeic/vibeic-eda:latest` — the newest released `X.Y.Z`.

Current: **0.2.18** — makes every EDA tool resolve on a **non-login `docker exec` PATH**
(a global `ENV PATH` bakes `/foss/tools/bin` into the image), so the bare
`docker exec vibeic-eda yosys --version` shown above works with no login shell and no
per-command `export PATH`. Builds on **0.2.11**, which added **native in-KLayout
SVRF/Calibre DRC-deck execution** — the klayout fork's `svrfdrc` C++ buddy parses and runs a
foundry Calibre/SVRF `.rule` deck directly on KLayout's DRC engine, no scripting interpreter
and no commercial license — atop the 0.2.5 fix set (yosys `lift_adder` / prefix-adder,
OpenROAD incremental reroute DRT-0073/0155/0218, ngspice native MC-LHS, magic/netgen
LVS-fidelity). Every fork in the [Dockerfile](./Dockerfile) is pinned to a commit SHA, so
`docker build .` reproduces this tag.

---

## License

The build recipe, scripts, and docs in this repository are licensed under
[Apache-2.0](./LICENSE).

The image **aggregates** upstream open-source EDA tools, each under its own license
(OpenROAD BSD-3, yosys ISC, ngspice BSD, magic/netgen public-domain-style, klayout GPL-3,
iverilog GPL-2, verilator LGPL-3/Apache-2.0, and the iic-osic-tools base + PDKs). Our
modifications live in the public `vibeic/<tool>` forks under each tool's own license. See
[`THIRD_PARTY_LICENSES.md`](./THIRD_PARTY_LICENSES.md) for the full attribution and links
to each fork's source.

---

## Links

- Fix scoreboard + proofs: [`FIX_STATUS.md`](./FIX_STATUS.md)
- The AI-native IC-design platform this powers: [vibeic.ai](https://vibeic.ai)
- Upstream base: [iic-osic-tools](https://github.com/iic-jku/iic-osic-tools) (TU Wien / JKU)
