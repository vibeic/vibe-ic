模式進入 / 離開條件(mode entry / exit conditions):

- The core enters SHA-256 mode when software writes CTRL with MODE (bit2) = 1 in the same write that sets INIT; it exits SHA-256 mode only upon a later INIT write whose MODE bit = 0. 核心於 CTRL 寫入 MODE=1 且同時 INIT=1 時進入 SHA-256 mode;直到下一次 MODE=0 的 INIT 寫入才離開。
- The core enters SHA-224 mode when software writes CTRL with MODE (bit2) = 0 in the same write that sets INIT; it exits SHA-224 mode only upon a later INIT write whose MODE bit = 1. 核心於 CTRL 寫入 MODE=0 且同時 INIT=1 時進入 SHA-224 mode;直到下一次 MODE=1 的 INIT 寫入才離開。
- The mode is latched at the accepted INIT; NEXT continues in the latched mode and never switches mode. Reset returns the mode selection to its default (MODE = 1, SHA-256) until the next INIT. 模式於 INIT 被接受時鎖存;NEXT 沿用鎖存模式,不會切換模式;reset 後 MODE 回到預設值 1(SHA-256),直到下一次 INIT。
