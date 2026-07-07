# vibeic-eda — forked + enhanced OSS EDA toolchain (vibeic)
# = hpretl/iic-osic-tools runtime + vibeic/* patched EDA-tool forks.
#
# Stage 1 builds the patched OpenROAD in the NATIVE ubuntu24.04 dev env so the
# binary matches the iic-osic-tools runtime (python3.12 / glibc2.39) — an
# ubuntu22.04 build fails in the runtime (wants libpython3.10).
FROM openroad/ubuntu24.04-dev:latest AS openroad-builder
ARG OPENROAD_REF=vibeic/post-route-detailed-routing-repair
RUN git clone https://github.com/vibeic/OpenROAD.git /src \
 && cd /src && git checkout ${OPENROAD_REF} \
 && git submodule update --init --recursive --depth 1 \
 && ./etc/Build.sh -threads=$(nproc) -cmake="-DCMAKE_BUILD_TYPE=Release"

# Runtime: layer the patched tools onto the iic-osic-tools base.
FROM hpretl/iic-osic-tools:latest
LABEL org.opencontainers.image.title="vibeic-eda"
LABEL org.opencontainers.image.description="Forked+enhanced OSS EDA toolchain (vibeic): iic-osic-tools base + vibeic/* patched EDA-tool forks. P0: OpenROAD post-detailed-route repair on real parasitics (fixes Signal-11)."
LABEL org.opencontainers.image.source="https://github.com/vibeic/OpenROAD"
# --- vibeic/OpenROAD (post-detailed-route repair; native 24.04 build → no lib bundling) ---
COPY --from=openroad-builder /opt/or-tools /opt/or-tools
COPY --from=openroad-builder /src/build/bin/openroad /foss/tools/openroad/bin/openroad
