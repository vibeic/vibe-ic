#!/usr/bin/env python3
"""J98 — the claim was "the two pad-site branches are gone from the remote".
It was PUBLISHED as `git ls-remote --heads | grep -c jself` == 0.

Those are not the same statement.  The grep is a SUBSTRING PROXY, and it held
only for as long as no other branch of mine shared the substring.  At 21:49 on
2026-08-22 the one-branch-per-agent rule put `next/jself` on the remote, the
proxy went 0 -> 1, and four sentences in RESULT.md that read `0 matching jself`
became false -- while the thing they were actually asserting stayed TRUE.

This is J94's defect with the sign flipped a second time: J94 withdrew a
comparison made because two searches SHARED a name; J96 drew a conclusion
because one search did NOT find a name; here a stability claim was carried by a
substring that a later branch of my own started matching.

So the claim is measured BY NAME, and the run carries its own positive control:
if the two absent branches read ABSENT but a branch that certainly EXISTS also
reads ABSENT, the `ABSENT`s are a broken query and not a measurement.
"""
import os, subprocess, sys

# J98: the repo the query runs in is overridable so this file's OWN positive
# control can be exercised -- point it at a non-repo and the PRESENT rows must
# read ABSENT and the run must exit 1.
WT = os.environ.get("J98_WT", "/home/reyerchu/_jself_priv/wt/vibe-ic-marketplace")
GONE = ["jself/pad-site-declared-in-pdk-tool-config",
        "jself/pad-site-declared-in-pdk-tool-config-on-v1.11.68"]
PRESENT = ["main", "next/jself"]          # positive control


def head(ref):
    out = subprocess.run(["git", "ls-remote", "--heads", "origin",
                          f"refs/heads/{ref}"], cwd=WT, capture_output=True,
                         text=True, timeout=120).stdout.strip()
    return out.split()[0][:9] if out else None


ok = True
print("CLAIM (load-bearing): these are NOT on the remote")
for b in GONE:
    h = head(b)
    print(f"  {b:<55} {'ABSENT' if h is None else 'PRESENT ' + h}")
    if h is not None:
        ok = False
print("POSITIVE CONTROL: these ARE on the remote (if one of these reads")
print("ABSENT the query is broken and every ABSENT above is worthless)")
for b in PRESENT:
    h = head(b)
    print(f"  {b:<55} {'ABSENT' if h is None else 'PRESENT ' + h}")
    if h is None:
        ok = False
        print("    ^^ CONTROL FAILED")

sub = subprocess.run("git ls-remote --heads origin | grep -c jself || true",
                     shell=True, cwd=WT, capture_output=True, text=True,
                     timeout=120).stdout.strip()
tot = subprocess.run("git ls-remote --heads origin | wc -l", shell=True,
                     cwd=WT, capture_output=True, text=True,
                     timeout=120).stdout.strip()
print(f"\nthe retired proxy, reported and never asserted: "
      f"{sub} head(s) match the substring 'jself' out of {tot} "
      f"(J74/J79 published this as 0; it is 1 because `next/jself` is mine)")
print("\nCLAIM_BY_NAME_OK" if ok else "\nCLAIM_BY_NAME_BROKEN")
sys.exit(0 if ok else 1)
