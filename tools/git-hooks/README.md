# Tracked git hook

Run `tools/install-git-hooks.sh` to install the tracked `pre-push` hook as a
symlink. Re-running preserves an existing hook; `--force` replaces it. The
installer only changes local hook configuration when explicitly run.

Before a push, the hook runs both mandatory NDA guards over every ref's newly
published commits:

- `programs/commit_msg_nda_check.py` scans commit messages.
- `programs/nda_diff_scan_check.py` scans added content and paths.

Both programs live under `vibe-ic-marketplace/plugins/vibe-ic/`. A finding,
an unreadable range, or a guard that cannot run blocks the push. Deletions and
ranges containing no new commits need no scan. The hook prints guard names and
exit codes without copying private scanner diagnostics.

A local hook runs on `git push`; it does not run for a server-side merge.

For a manual scan, run either guard with `--repo . --rev-range origin/main..HEAD`.
If a message is blocked, replace the sensitive name with a generic description
such as "commercial PDK" or "commercial foundry", then amend or reword it.
