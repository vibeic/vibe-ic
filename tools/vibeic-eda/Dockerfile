# vibeic-eda — forked + enhanced OSS EDA toolchain (vibeic)
# = hpretl/iic-osic-tools runtime + vibeic/* patched EDA-tool forks.
#
# Each tool is built from its vibeic fork branch in a ubuntu24.04-family builder so
# the binary matches the iic-osic-tools runtime (python3.12 / glibc2.39). An
# ubuntu22.04 build fails in the runtime (wants libpython3.10).
#
# Every PATCHED fork branch below (Stages 1-7) has a gatekeeper-verified FAIL->PASS
# proof recorded in FIX_STATUS.md. Version-jump note: yosys is a deliberate uplift
# (0.4x -> 0.66+slang, the roadmap's prescribed "make slang the default SV path");
# magic/netgen/ngspice track the same rolling releases the base ships. The Stage-8
# verification toolchain (cocotb/cocotb-coverage/pyuvm/sby) is baked as
# ENHANCEMENT-READY forks (editable install, no FAIL->PASS patch yet) so the
# professional TB generator runs on tools we own and can patch. A full plugin-flow
# validation pass gates promotion of 0.2.0 over 0.1.0 (see FIX_STATUS.md).

# ---------------------------------------------------------------------------
# Stage 1 — vibeic/OpenROAD (post-detailed-route repair on real parasitics; Signal-11 fix)
# ---------------------------------------------------------------------------
FROM openroad/ubuntu24.04-dev:latest AS openroad-builder
# Pinned to the F-A2 commit (tapcell -bound_to_placement) shipped in vibeic-eda:0.2.7,
# a fast-forward over the F-A1 repair_antennas -reroute commit (0.2.6).
# HEAD of branch vibeic/post-route-detailed-routing-repair as of 2026-07-09.
ARG OPENROAD_REF=3efb695851045c200b95d9bf243884e3810656a6
RUN git clone https://github.com/vibeic/OpenROAD.git /src \
 && cd /src && git checkout ${OPENROAD_REF} \
 && git submodule update --init --recursive --depth 1 \
 && ./etc/Build.sh -threads=$(nproc) -cmake="-DCMAKE_BUILD_TYPE=Release"

# ---------------------------------------------------------------------------
# Stage 2 — vibeic/yosys (tri-state fanin preservation + modern slang SV frontend)
# ---------------------------------------------------------------------------
FROM ubuntu:24.04 AS yosys-builder
ARG YOSYS_REF=1042b3f554592b4f49ea5380ad6af912abc270cd  # pinned; branch vibeic/synth-fixes-v0.67 (v0.67 + 4 vibeic patches + stat-0cells #124, 2026-07-14)
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential cmake git bison flex gawk pkg-config \
      libreadline-dev tcl-dev libffi-dev zlib1g-dev python3 \
      libboost-system-dev libboost-python-dev libboost-filesystem-dev ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/vibeic/yosys.git /yosys \
 && cd /yosys && git checkout ${YOSYS_REF} && git submodule update --init --recursive \
 && cmake -S /yosys -B /yosys/build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/foss/tools/yosys \
 && cmake --build /yosys/build -j"$(nproc)" \
 && cmake --install /yosys/build

# ---------------------------------------------------------------------------
# Stage 3 — vibeic/ngspice (batch-honesty rc + $& scalar + control-mode .param + native MC)
# ---------------------------------------------------------------------------
FROM ubuntu:24.04 AS ngspice-builder
ARG NGSPICE_REF=cdb4fae2db9716de251cb55df9ebad0bc2c5172b  # pinned; branch vibeic/batch-honesty
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential git autoconf automake libtool bison flex \
      libx11-dev libxaw7-dev libreadline-dev libncurses-dev ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/vibeic/ngspice.git /ngspice \
 && cd /ngspice && git checkout ${NGSPICE_REF} \
 && ./autogen.sh \
 && ./configure --prefix=/foss/tools/ngspice --with-ngshared=no --enable-xspice --disable-debug \
 && make -j"$(nproc)" && make install

# ---------------------------------------------------------------------------
# Stage 4 — vibeic/magic + vibeic/netgen (LVS-fidelity pair)
#   magic:  ext2spice label->port promotion (feeds netgen portless guard)
#   netgen: property-error verdict, portless guard, -auto-global, -nopower, black-box match
# ---------------------------------------------------------------------------
FROM ubuntu:24.04 AS lvs-builder
ARG MAGIC_REF=9f91cd2487d61bbc7120b4c1371a3612986d6ddd  # pinned; branch vibeic/lvs-fidelity-8.3.675 (rebased onto 8.3.675 clean, 2026-07-13)
ARG NETGEN_REF=b7d4138b6407d86107868efd5896644b4f81e535  # pinned; branch vibeic/lvs-fidelity
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential git m4 tcl-dev tk-dev libx11-dev libcairo2-dev libncurses-dev ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/vibeic/magic.git /magic \
 && cd /magic && git checkout ${MAGIC_REF} \
 && ./configure --prefix=/foss/tools/magic && make -j"$(nproc)" && make install
RUN git clone https://github.com/vibeic/netgen.git /netgen \
 && cd /netgen && git checkout ${NETGEN_REF} \
 && ./configure --prefix=/foss/tools/netgen && make -j"$(nproc)" && make install

# ---------------------------------------------------------------------------
# Stage 5 — vibeic/iverilog (->> nonblocking-event codegen segfault fix + package ordering)
# ---------------------------------------------------------------------------
FROM ubuntu:24.04 AS iverilog-builder
ARG IVERILOG_REF=110cadd57c3a96ca81e84bdb0a78463e81575088  # pinned; branch vibeic/sv-tb-coverage
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential git autoconf gperf flex bison ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/vibeic/iverilog.git /iverilog \
 && git config --global --add safe.directory /iverilog \
 && cd /iverilog && git checkout ${IVERILOG_REF} \
 && sh autoconf.sh && ./configure --prefix=/foss/tools/iverilog \
 && make -j"$(nproc)" && make install

# ---------------------------------------------------------------------------
# Stage 6 — vibeic/klayout (streamout MANUFACTURINGGRID snap + merge-abutting + foundry
#   layer-map, AND the native SVRF/Calibre DRC engine + `svrfdrc` buddy). Qt-less db-lib
#   + pymod + buddies; shipped parallel as klayout-vibeic so the base 0.30.6 GUI/DRC stays
#   intact. Phase-3 streamout AND commercial sign-off DRC both point here.
#   The svrf-native-drc branch = streamout-fixes + db::SVRFDeck/db::SVRFEngine + the
#   `svrfdrc <deck> <layout> <report>` buddy (native C++, NO Python interpreter). Byte-
#   parity vs the old run_svrf_drc.py proven on a real commercial foundry deck.
# ---------------------------------------------------------------------------
FROM ubuntu:24.04 AS klayout-builder
ARG KLAYOUT_REF=e3d26a3342ecaf3468d422e50f806ebff48cbbb0  # pinned; branch vibeic/svrf-native-drc
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential git python3-dev zlib1g-dev libexpat1-dev libcurl4-openssl-dev libpng-dev \
      qtbase5-dev qttools5-dev-tools ca-certificates \
 && rm -rf /var/lib/apt/lists/*
# build.sh needs qmake in PATH to drive the build system even with -without-qt.
RUN git clone https://github.com/vibeic/klayout.git /klayout \
 && cd /klayout && git checkout ${KLAYOUT_REF} \
 && ./build.sh -without-qt -noruby -nolibgit2 -j"$(nproc)" -bin /foss/tools/klayout-vibeic -build /klayout/bld
# verilator: forked, no honest fix warranted on v5.051 (see FIX_STATUS.md) — nothing to layer.

# ---------------------------------------------------------------------------
# Stage 7 — RETIRED. The SVRF/Calibre DRC deck is now executed by the NATIVE C++
#   `svrfdrc` buddy compiled in Stage 6 (part of the svrf-native-drc branch), NOT by
#   the old pure-Python `run_svrf_drc.py` interpreter. No separate source stage: the
#   buddy ships inside /klayout/bld and is surfaced on PATH in the runtime stage.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Stage 8 — vibeic verification toolchain (cocotb / cocotb-coverage / pyuvm / sby)
#   The professional testbench generator (plugin `professional_tb_gen`, MCP
#   `eda_professional_tb`) emits cocotb TBs + cocotb-coverage covergroups + an SVA
#   bind that RUN on this toolchain — so we OWN it (Bucket-T: fork every OSS EDA tool
#   so we can enhance it, never a "the tool can't do it" excuse). Pure-source fetch
#   here; editable-installed in the runtime so an in-image Python patch is live.
#   sby (SymbiYosys) drives our vibeic/yosys for the SVA-bind / formal path.
#   Cloned from the vibeic org forks (github.com/vibeic/{cocotb,cocotb-coverage,
#   pyuvm,sby}); the pinned SHAs live in those forks (shared upstream history) so
#   a vibeic patch is a branch/commit on top. Keep COCOTB_REF on the stable 2.0.x
#   line the base ships until a real vibeic patch lands.
# ---------------------------------------------------------------------------
FROM alpine/git AS tb-src
ARG COCOTB_REF=606fb1f5e552fd12e20780dfb3826cfa150a3a85
ARG COCOTB_COVERAGE_REF=201c6e19761528eb9c03f876666c485027abb7fb
ARG PYUVM_REF=dfcd1ffb6b7141c6c654e970a0447e36615d5ae9
ARG SBY_REF=8f8833c6176be263907dea5b50da7759632aaff6
RUN git clone https://github.com/vibeic/cocotb.git           /tb/cocotb          && git -C /tb/cocotb          checkout ${COCOTB_REF} \
 && git clone https://github.com/vibeic/cocotb-coverage.git  /tb/cocotb-coverage && git -C /tb/cocotb-coverage checkout ${COCOTB_COVERAGE_REF} \
 && git clone https://github.com/vibeic/pyuvm.git            /tb/pyuvm           && git -C /tb/pyuvm           checkout ${PYUVM_REF} \
 && git clone https://github.com/vibeic/sby.git              /tb/sby             && git -C /tb/sby             checkout ${SBY_REF}

# ===========================================================================
# Runtime: layer the patched tools onto the iic-osic-tools base.
# ===========================================================================
FROM hpretl/iic-osic-tools:latest
LABEL org.opencontainers.image.title="vibeic-eda"
LABEL org.opencontainers.image.description="Forked+enhanced OSS EDA toolchain (vibeic): iic-osic-tools base + vibeic/* patched EDA-tool forks with gatekeeper-verified FAIL->PASS proofs (see FIX_STATUS.md)."
LABEL org.opencontainers.image.source="https://github.com/vibeic"

# /foss/tools is root-owned and the base runs as user 1000 — become root to mutate it.
USER root
# --- vibeic/OpenROAD (native 24.04 build → RUNPATH /opt/or-tools, no lib bundling) ---
COPY --from=openroad-builder /opt/or-tools /opt/or-tools
COPY --from=openroad-builder /src/build/bin/openroad /foss/tools/openroad/bin/openroad
# Clean-replace the base tool dirs FIRST so no stale base files survive the COPY merge —
# e.g. the base's ghdl.so yosys plugin is built against the old ABI and would crash yosys 0.66.
RUN rm -rf /foss/tools/yosys /foss/tools/ngspice /foss/tools/magic /foss/tools/netgen /foss/tools/iverilog
# --- vibeic/yosys (replaces base yosys install; bin symlinked into /foss/tools/bin) ---
COPY --from=yosys-builder /foss/tools/yosys /foss/tools/yosys
# --- vibeic/ngspice ---
COPY --from=ngspice-builder /foss/tools/ngspice /foss/tools/ngspice
# --- vibeic/magic + vibeic/netgen ---
COPY --from=lvs-builder /foss/tools/magic /foss/tools/magic
COPY --from=lvs-builder /foss/tools/netgen /foss/tools/netgen
# --- vibeic/iverilog ---
COPY --from=iverilog-builder /foss/tools/iverilog /foss/tools/iverilog
# --- vibeic/klayout (parallel streamout install; base klayout untouched) ---
# build.sh emits the Qt-less db-lib + pymod + db_plugins/liblefdef.so into its -build dir.
COPY --from=klayout-builder /klayout/bld /foss/tools/klayout-vibeic
# Re-point the /foss/tools/bin symlinks the base created to our installs.
RUN for t in yosys yosys-abc; do ln -sf /foss/tools/yosys/bin/$t /foss/tools/bin/$t 2>/dev/null || true; done \
 && ln -sf /foss/tools/ngspice/bin/ngspice /foss/tools/bin/ngspice 2>/dev/null || true \
 && ln -sf /foss/tools/magic/bin/magic /foss/tools/bin/magic 2>/dev/null || true \
 && ln -sf /foss/tools/netgen/bin/netgen /foss/tools/bin/netgen 2>/dev/null || true \
 && for t in iverilog vvp iverilog-vpi vvp; do ln -sf /foss/tools/iverilog/bin/$t /foss/tools/bin/$t 2>/dev/null || true; done
# fault (AUCOHL DFT toolchain) ships from the iic-osic-tools base at
# /usr/local/bin/fault (already on PATH). Surface it under /foss/tools/bin too so
# its path is consistent with every other EDA tool — eda_dft invokes bare `fault`
# (PATH) and eda_doctor probes bare `fault`, so both work with or without this
# symlink; it's a path-consistency convenience, not a functional requirement.
RUN command -v fault >/dev/null 2>&1 && ln -sf "$(command -v fault)" /foss/tools/bin/fault 2>/dev/null || true
# --- vibeic/klayout svrfdrc (NATIVE C++ SVRF/Calibre DRC buddy) ---
# The `svrfdrc <deck> <layout> <report> [--cell=TOP]` binary was compiled in Stage 6
# (svrf-native-drc branch) and shipped inside /klayout/bld -> already copied to
# /foss/tools/klayout-vibeic above. The `svrfdrc()` entry + the whole native SVRF
# engine (dbSVRFDeck/dbSVRFEngine) are baked into the FORK's libklayout_bd.so there.
# NO Python interpreter, NO `-r` script, NO GUI macro — byte-parity with the retired
# run_svrf_drc.py proven on a real commercial foundry deck.
#
# WRAPPER (not a bare symlink): the buddy's ELF carries DT_RUNPATH=/foss/tools/klayout-vibeic,
# but the runtime env sets LD_LIBRARY_PATH=/foss/tools/klayout:... and DT_RUNPATH is
# searched AFTER LD_LIBRARY_PATH. A bare symlink therefore loads the STOCK
# /foss/tools/klayout/libklayout_bd.so (which lacks the svrfdrc symbol + engine) →
# `undefined symbol: svrfdrc(int, char**)`. The wrapper prepends the fork lib dir to
# LD_LIBRARY_PATH so ALL klayout libs resolve consistently from the fork build.
RUN printf '#!/bin/sh\nexec env LD_LIBRARY_PATH=/foss/tools/klayout-vibeic:${LD_LIBRARY_PATH} /foss/tools/klayout-vibeic/svrfdrc "$@"\n' > /foss/tools/bin/svrfdrc \
 && chmod +x /foss/tools/bin/svrfdrc \
 && LD_LIBRARY_PATH=/foss/tools/klayout /foss/tools/bin/svrfdrc --help >/dev/null 2>&1 \
      && echo "svrfdrc buddy OK" || echo "WARN: svrfdrc buddy self-test failed"
# --- vibeic verification toolchain (cocotb / cocotb-coverage / pyuvm / sby) ---
# Editable-installed from the vibeic forks so an in-image Python patch is live; this
# overrides the base's stock cocotb with our fork. sby installs its driver + libs into
# /usr/local (it drives vibeic/yosys for the SVA-bind / formal path). Build isolation
# stays ON so cocotb's C-extension build pulls its own build deps.
# cocotb 2.x's `cocotb/simulator` extension #include's <Python.h>; the base ships the
# python3.12 runtime but NOT the dev headers, so install python3-dev first (g++/gcc/make
# are already in the base). Otherwise the editable build dies with
# "fatal error: Python.h: No such file or directory".
COPY --from=tb-src /tb /opt/vibeic-forks
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      python3-dev \
 && rm -rf /var/lib/apt/lists/* \
 && python3 -m pip install --break-system-packages \
      -e /opt/vibeic-forks/cocotb \
      -e /opt/vibeic-forks/cocotb-coverage \
      -e /opt/vibeic-forks/pyuvm \
 && make -C /opt/vibeic-forks/sby install PREFIX=/usr/local \
 && chmod -R a+rX /opt/vibeic-forks
# restore the base's non-root runtime user
USER 1000

# --- bare `docker exec` PATH (vibeic enhancement over stock iic-osic-tools) ---
# The stock base only puts /foss/tools/* on PATH via /etc/profile.d/iic-osic-tools-setup.sh,
# which runs for LOGIN shells only. A non-login `docker exec <c> <tool>` (and
# `docker exec <c> bash -c '<tool>'`, the idiom the Vibe-IC MCP uses) therefore could not
# resolve yosys/openroad/sta/... ("executable file not found in $PATH") — including the bare
# `docker exec vibeic-eda yosys --version` in this repo's README Quick Start. Bake the tool
# dirs into a global ENV PATH so tools resolve WITHOUT a login shell or a per-command export.
# Additive only (login shells still re-prepend via profile.d — harmless duplicate).
ENV PATH=/headless/.local/bin:/foss/tools/bin:/foss/tools/sak:/foss/tools/kactus2:/foss/tools/klayout:/foss/tools/osic-multitool:${PATH}
