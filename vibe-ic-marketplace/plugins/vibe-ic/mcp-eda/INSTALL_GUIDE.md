# MCP EDA Server — Marketplace Installation Guide

The supported installation route is the `vibe-ic` marketplace plugin. The
plugin packages the MCP server and registers it through its shipped `.mcp.json`;
users do not clone, install, or register a second MCP server.

## Prerequisites

Install these host tools first:

| Requirement | Minimum | Check |
|---|---:|---|
| Linux | current supported release | `uname -a` |
| Docker | 20.10 | `docker --version` |
| Node.js | 18 | `node --version` |
| Python | 3.10 | `python3 --version` |
| Claude Code | current | `claude --version` |

The EDA image is large. Confirm that the Docker data root has enough free space
before pulling it.

## 1. Install the marketplace plugin

Install from the repository marketplace:

```bash
claude plugin marketplace add https://github.com/vibeic/vibe-ic
claude plugin install vibe-ic
```

For a local source checkout, add its marketplace directory instead:

```bash
git clone https://github.com/vibeic/vibe-ic.git
cd vibe-ic
claude plugin marketplace add ./vibe-ic-marketplace
claude plugin install vibe-ic
```

One plugin install provides the skills, deterministic programs, MCP server,
bootstrap wrapper, and the container-remediation helper.

## 2. Pull the EDA image

```bash
docker pull ghcr.io/vibeic/vibeic-eda:latest
```

Pulling a newer tag does not update an existing container. Docker resolves the
tag only when the container is created, so use the helper in the next section
to create or replace the named container.

## 3. Create the `vibeic-eda` container

Choose an existing directory that contains, or will contain, your design
projects. The helper deliberately refuses a missing directory because Docker
would otherwise create a root-owned bind-mount source.

Run the helper from the installed plugin root (the directory containing
`.mcp.json`, `mcp-eda/`, `programs/`, and `tools/`):

```bash
export VIBEIC_DESIGNS="/absolute/path/to/your/projects"
[ -d "$VIBEIC_DESIGNS" ] || { echo "choose an existing projects directory"; exit 1; }

DESIGNS_DIR="$VIBEIC_DESIGNS" \
  bash tools/vibeic-eda/restart-eda.sh ghcr.io/vibeic/vibeic-eda:latest
```

The helper:

- preserves an existing container's mounts, command, user, and working directory;
- creates both the host-path identity mount and `/foss/designs` mount on a fresh install;
- derives matching `--memory` and `--memory-swap` limits from the host policy;
- refuses to replace a container while an EDA process is running unless the
  operator explicitly sets `FORCE=1`;
- verifies that the replacement container uses the requested image ID.

To select the newest locally available image by immutable digest, omit the
image argument. To choose an explicit memory ceiling, set
`VIBEIC_DOCKER_MEMORY` (for example, `VIBEIC_DOCKER_MEMORY=32g`). Setting it to
`0` is an explicit opt-out; the default never silently creates an unbounded
container.

No host ports are required. The MCP server reaches the toolchain with
`docker exec`, not through a browser or VNC listener.

## 4. MCP auto-registration

The plugin ships this registration in `.mcp.json`:

```json
{
  "mcpServers": {
    "eda-tools": {
      "type": "stdio",
      "command": "node",
      "args": ["${CLAUDE_PLUGIN_ROOT}/mcp-eda/src/bootstrap.mjs"],
      "env": {
        "EDA_CONTAINER": "vibeic-eda"
      }
    }
  }
}
```

`bootstrap.mjs` is the supported entry point. It checks the server's Node
dependencies and performs the self-healing install before importing
`src/index.js`. Bypassing it with a direct `index.js` registration removes that
recovery path and can also create a duplicate `eda-tools` server.

Do not separately clone `mcp-eda`, run a manual dependency install, or add a
second MCP registration. After installing or updating the plugin, start a new
Claude Code session so it loads the shipped registration.

## 5. Verify the installation

First confirm the named container and its memory ceiling:

```bash
docker ps --filter 'name=^/vibeic-eda$'
docker inspect vibeic-eda \
  --format 'image={{.Config.Image}} memory={{.HostConfig.Memory}} memory_swap={{.HostConfig.MemorySwap}}'
```

Then ask the agent to run the MCP tool:

```text
eda_doctor(skip_versions=false)
```

Read the returned checks and image identity. A missing summary, a tool call that
did not execute, or an absent report is not a successful verification. Resolve
every failed check before running a design flow.

For a direct container sanity check:

```bash
docker exec vibeic-eda yosys --version
docker exec vibeic-eda openroad -version
```

## Updating or repairing the container

Pull the desired image, then run the packaged helper again from the plugin root:

```bash
docker pull ghcr.io/vibeic/vibeic-eda:latest
bash tools/vibeic-eda/restart-eda.sh ghcr.io/vibeic/vibeic-eda:latest
```

The helper reuses the existing container configuration. When there is no
existing container, provide `DESIGNS_DIR` or `VIBEIC_DESIGNS` as shown above.

## Troubleshooting

### Duplicate `eda-tools` server

If the client lists more than one server with that name, remove the manually
created registration and keep the marketplace-owned entry whose command ends
in `${CLAUDE_PLUGIN_ROOT}/mcp-eda/src/bootstrap.mjs`. Restart the client and run
`eda_doctor` again.

### `ERR_MODULE_NOT_FOUND`

Confirm that the marketplace registration points to `bootstrap.mjs`, not
directly to `src/index.js`. The bootstrap wrapper owns dependency recovery. If
it still fails, inspect its stderr and confirm that Node and npm are available
on the host.

### Container exists but runs an old image

A moved tag does not change a running container. Pull the desired image and use
`tools/vibeic-eda/restart-eda.sh`; do not rely on `docker restart`, which starts
the same old container again.

### No memory ceiling

Recreate the container with the packaged helper. It supplies matching memory
and swap ceilings and refuses when it cannot determine them. Use
`VIBEIC_DOCKER_MEMORY=<size>` only when an operator needs an explicit value.

### Project path is unavailable inside the container

The fresh-container route creates two mounts for the chosen projects directory:
the same absolute host path inside the container, plus `/foss/designs`. If an
older container lacks either mount, recreate it with `DESIGNS_DIR` set to the
existing projects directory.

## Architecture

```text
Claude Code
  └─ marketplace plugin .mcp.json
       └─ mcp-eda/src/bootstrap.mjs
            └─ mcp-eda/src/index.js
                 └─ docker exec vibeic-eda ...
                      └─ project files through the two required bind mounts
```

The marketplace plugin is the ownership boundary for the MCP server. The
Docker container is the execution environment; it is not a separate MCP
installation route.
