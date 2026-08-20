"""`_ppa.backends` — one module per tool, and each one parses and nothing else.

A backend turns one tool's output into canonical metric records. It carries no
threshold, no verdict and no policy, so that adding a tool never changes a rule
and changing a rule never touches a tool. That split is frozen in
`docs/PPA_INTERFACES.md` section 4, and it is what lets a comparison add an
opponent's flow without anybody re-arguing what "better" means.

The one thing a backend IS entitled to state is a fact about the tool itself --
"this version of this tool computes power without an activity file, so its power
is vectorless". That is not a policy; it is the tool's behaviour, it is
measurable from the installed tool, and the module records how it was measured.
"""
