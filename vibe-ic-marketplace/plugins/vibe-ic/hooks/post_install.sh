#!/bin/bash
# SessionStart must never mutate the installed plugin or auth state.
# The existing MCP bootstrap prepares external dependencies on actual use.
# Silence and exit 0 are compatible with both Claude and Codex.
exit 0
