# vibeic-eda — forked + enhanced OSS EDA toolchain (vibeic)
# = hpretl/iic-osic-tools runtime + vibeic/* patched EDA-tool forks.
#
# Each tool is built from its vibeic fork branch in a ubuntu24.04-family builder so
# the binary matches the iic-osic-tools runtime (python3.12 / glibc2.39). An
# ubuntu22.04 build fails in the runtime (wants libpython3.10).
#
# Every fork branch below has a gatekeeper-verified FAIL->PASS proof recorded in
# FIX_STATUS.md. Version-jump note: yosys is a deliberate uplift (0.4x -> 0.66+slang,
# the roadmap's prescribed "make slang the default SV path"); magic/netgen/ngspice
# track the same rolling releases the base ships. A full plugin-flow validation pass
# gates promotion of 0.2.0 over 0.1.0 (see FIX_STATUS.md).

# ---------------------------------------------------------------------------
# Stage 1 — vibeic/OpenROAD (post-detailed-route repair on real parasitics; Signal-11 fix)
# ---------------------------------------------------------------------------
FROM openroad/ubuntu24.04-dev:latest AS openroad-builder
ARG OPENROAD_REF=vibeic/post-route-detailed-routing-repair
RUN git clone https://github.com/vibeic/OpenROAD.git /src \
 && cd /src && git checkout ${OPENROAD_REF} \
 && git submodule update --init --recursive --depth 1 \
 && ./etc/Build.sh -threads=$(nproc) -cmake="-DCMAKE_BUILD_TYPE=Release"

# ---------------------------------------------------------------------------
# Stage 2 — vibeic/yosys (tri-state fanin preservation + modern slang SV frontend)
# ---------------------------------------------------------------------------
FROM ubuntu:24.04 AS yosys-builder
ARG YOSYS_REF=vibeic/synth-fixes
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
ARG NGSPICE_REF=vibeic/batch-honesty
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
ARG MAGIC_REF=vibeic/lvs-fidelity
ARG NETGEN_REF=vibeic/lvs-fidelity
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
ARG IVERILOG_REF=vibeic/sv-tb-coverage
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential git autoconf gperf flex bison ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/vibeic/iverilog.git /iverilog \
 && git config --global --add safe.directory /iverilog \
 && cd /iverilog && git checkout ${IVERILOG_REF} \
 && sh autoconf.sh && ./configure --prefix=/foss/tools/iverilog \
 && make -j"$(nproc)" && make install

# ---------------------------------------------------------------------------
# Stage 6 — vibeic/klayout (streamout: MANUFACTURINGGRID snap + merge-abutting + foundry layer-map)
#   Qt-less db-lib + pymod (the streamout path); shipped parallel as klayout-vibeic so the
#   base 0.30.6 GUI/DRC stays intact. Phase-3 streamout points here + sets the env shims.
# ---------------------------------------------------------------------------
FROM ubuntu:24.04 AS klayout-builder
ARG KLAYOUT_REF=vibeic/streamout-fixes
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential git python3-dev zlib1g-dev libexpat1-dev libcurl4-openssl-dev libpng-dev \
      qtbase5-dev qttools5-dev-tools ca-certificates \
 && rm -rf /var/lib/apt/lists/*
# build.sh needs qmake in PATH to drive the build system even with -without-qt.
RUN git clone https://github.com/vibeic/klayout.git /klayout \
 && cd /klayout && git checkout ${KLAYOUT_REF} \
 && ./build.sh -without-qt -noruby -nolibgit2 -j"$(nproc)" -bin /foss/tools/klayout-vibeic -build /klayout/bld
# verilator: forked, no honest fix warranted on v5.051 (see FIX_STATUS.md) — nothing to layer.

# ===========================================================================
# Runtime: layer the patched tools onto the iic-osic-tools base.
# ===========================================================================
FROM hpretl/iic-osic-tools:latest
LABEL org.opencontainers.image.title="vibeic-eda"
LABEL org.opencontainers.image.description="Forked+enhanced OSS EDA toolchain (vibeic): iic-osic-tools base + vibeic/* patched EDA-tool forks with gatekeeper-verified FAIL->PASS proofs (see FIX_STATUS.md)."
LABEL org.opencontainers.image.source="https://github.com/vibeic"

# --- vibeic/OpenROAD (native 24.04 build → RUNPATH /opt/or-tools, no lib bundling) ---
COPY --from=openroad-builder /opt/or-tools /opt/or-tools
COPY --from=openroad-builder /src/build/bin/openroad /foss/tools/openroad/bin/openroad
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
COPY --from=klayout-builder /foss/tools/klayout-vibeic /foss/tools/klayout-vibeic
# Re-point the /foss/tools/bin symlinks the base created to our installs.
RUN for t in yosys yosys-abc; do ln -sf /foss/tools/yosys/bin/$t /foss/tools/bin/$t 2>/dev/null || true; done \
 && ln -sf /foss/tools/ngspice/bin/ngspice /foss/tools/bin/ngspice 2>/dev/null || true \
 && ln -sf /foss/tools/magic/bin/magic /foss/tools/bin/magic 2>/dev/null || true \
 && ln -sf /foss/tools/netgen/bin/netgen /foss/tools/bin/netgen 2>/dev/null || true \
 && for t in iverilog vvp iverilog-vpi vvp; do ln -sf /foss/tools/iverilog/bin/$t /foss/tools/bin/$t 2>/dev/null || true; done
