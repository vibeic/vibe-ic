# Which host can reach which — measured, not inherited

`bin/rsh`'s key map is written from .120's point of view and does not transfer. Three agents
have now measured it from three different seats and got three different answers, so this
records the probes rather than a conclusion.

Measured from **.105 (8HD-9)**, 2026-08-22:

| target | direct from .105 | via .102 (8HD-7) | via 1.34.17.159 (8HD-a) | via .108 (8HD-6) |
|---|---|---|---|---|
| .102 8HD-7 | OK | — | — | — |
| .108 8HD-6 | OK | — | — | — |
| 1.34.17.159 8HD-a | OK | — | — | — |
| .114 8HD-8 | denied | **OK** | OK | denied |
| .120 8HD-4 | denied | **OK** | OK | denied |
| .112 8HD-d | denied | **OK** | OK | — |
| .121 8hd-3 | denied | **OK** | denied | — |
| .107 8HD-c | **port 22 timeout** | **timeout** | **timeout** | — |

**8HD-7 (.102) is the master key on this fleet.** It reaches .114, .120, .112 and .121.
jharv3 measured from .108 that only .105 answers, and .105 on its own is indeed a dead end —
two independent confirmations agreeing. The wall is not that the hosts are unreachable; it is
that .105 and .108 are the wrong seat.

The form that works is a plain nested ssh with no inner quoting, and to run real work, pipe a
script rather than judging over the wire:

    ssh reyerchu@192.168.1.102 ssh -o BatchMode=yes reyerchu@192.168.1.121 hostname
    ssh reyerchu@192.168.1.102 ssh reyerchu@192.168.1.114 bash -s < judge.sh

That is how shard B's 102 rows on .114 were judged without an account there: ship the judge to
the host, run it locally, carry the measurements back.

**.107 (8HD-c) is the one genuine UNREACHABLE.** Port 22 times out from three different
hosts — down, not key-refused. Any row on it must be UNREACHABLE, and that is not ABANDON.

## The local-path origin trap, measured — and it bit me

jharv3 flagged that a clone whose `origin` is a LOCAL PATH fetches a stale branch and exits 0.
It is worse than stale. On **.121**, four clones have `origin = /home/reyerchu/vibe-ic`, and
`git fetch origin main` against a local path fetches that path's **local branch** `main` — not
its `origin/main`. Those four were already correct at `a00f53f2094`; my fetch moved them
**backwards** to `f6db3e921e6` and exited 0.

    OK /home/reyerchu/_j4reds2/tree     a00f53f2094 -> f6db3e921e6   /home/reyerchu/vibe-ic/.
    OK /home/reyerchu/_smrg_priv/smrg_tree a00f53f2094 -> f6db3e921e6   /home/reyerchu/vibe-ic

"Fetch first" is the right rule and it made the reference **worse** on those four. Repaired by
fetching the remote-tracking ref explicitly from a clone on the same host that has a real
https origin, which restores it offline without rewriting anyone's remote config:

    git -C <clone> fetch <good-clone> +refs/remotes/origin/main:refs/remotes/origin/main

All four back at `a00f53f2094`, verified before judging, and the judging run **refuses to
start** unless every clone it will use reads that sha. The rows those clones produced say so
in their own evidence.

Audited for the same fault elsewhere: **.105 zero** local-origin clones (23/23 at a00f53f2094),
**.102 zero** (81/82 at a00f53f2094; the 82nd is a bare path the normaliser mangled and it owns
zero rows), **.114 zero** (3/3 real https origins). The fault is confined to .121.
