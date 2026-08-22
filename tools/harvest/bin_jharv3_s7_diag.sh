#!/bin/bash
# READ-ONLY diagnostics: what does git itself say differs?
for p in /home/reyerchu/_a1456 /home/reyerchu/vibe-ic-wt-caravel-slew-drv2; do
  cd "$p" || continue
  echo "=== $p"
  echo "HEAD: $(git rev-parse HEAD)"
  echo "status -uall lines: $(git status --porcelain=v1 -uall | wc -l)"
  git status --porcelain=v1 -uall | head -5
  echo "diff --name-only HEAD: $(git diff --name-only HEAD | wc -l)"
  git diff --name-only HEAD | head -5
  echo "ls-files --cached: $(git ls-files --cached | wc -l)   ls-tree blobs: $(git ls-tree -r HEAD | grep -c blob)"
  echo "ls-files --deleted: $(git ls-files --deleted | wc -l)"
  echo "sparse checkout: $(git config core.sparseCheckout) cone=$(git config core.sparseCheckoutCone)"
  echo "lfs filter: $(git config filter.lfs.clean)"
  echo "gitattributes filters:"; git ls-files -- '.gitattributes' '**/.gitattributes' | head -3
  echo
done
