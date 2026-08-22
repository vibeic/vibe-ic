# The three read-only probes, and the route that reaches .112 and .121

`.112` and `.121` refuse a direct `ssh` from `.108`. `.102` is authorised on both,
and `ProxyJump` does NOT work — it forwards the origin key and fails identically.
The route that works is a plain nested `ssh`, with the probe piped in on stdin so
nothing is ever written on the far host:

    ssh reyerchu@192.168.1.102 \
      "ssh reyerchu@192.168.1.112 'bash -s -- <path> <path> ...'" < probe1_untracked.sh

| probe | what it answers |
|---|---|
| `probe1_untracked.sh` | `--untracked-files=all` and tracked modifications, each with sha256 and size |
| `probe2_content.sh` | HEAD, whether its commit OBJECT still exists, tree, merge-base, owned set vs `origin/main` blob by blob, ignored-entry count, clone stashes |
| `probe3_ignored.sh` | every ignored entry by name, with file count and byte count, plus every stash |

`probe2` exists because a pruned HEAD scores 0 on every ancestry query, and 0 is
byte-identical to clean. It asks `cat-file -e HEAD^{commit}` before believing any
count that came after it.

All three write nothing: no file, no index, no ref, no fetch. They `cd` into each
directory and read.
