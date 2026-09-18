## 邊界行為(corner cases)

| 情境 | 規定行為 |
|---|---|
| **Reset during operation**(計算進行中 reset:`reset_n` = 0 asserted while a block computation is in progress) | 進行中的計算立即終止且不會恢復(the in-flight computation is terminated, never resumed);internal state machine 歸 idle,STATUS.READY = 1、STATUS.VALID = 0,DIGEST0..7 讀回 0,CTRL 回到預設值(MODE = 1、INIT/NEXT = 0);reset release 後須重新 INIT。 |
| **Back-to-back transactions**(連續交易 / 連續 block:consecutive INIT/NEXT commands with no idle gap) | 只要 CTRL 寫入當下 STATUS.READY = 1,下一個 INIT 或 NEXT 可在 READY 重新拉高的同一個 cycle 立即發出(back-to-back block 允許,無需額外 idle gap);多 block 訊息以連續 NEXT 串接。READY = 0(busy)期間的 CTRL 寫入不被接受(not accepted):不排隊、不出錯,狀態機維持 BUSY。 |
| **INIT during BUSY / NEXT without prior INIT** | busy 期間的 INIT/NEXT 寫入不被接受(見上列);未曾 INIT 即發 NEXT 時,核心以目前 H[] 內容(reset 後為 0)繼續計算,不視為錯誤(`error` 不拉起)。 |
| **BLOCK write / DIGEST read during BUSY** | busy 期間寫 BLOCK0..15 不影響進行中的計算(schedule 已在啟動時載入);busy 期間讀 DIGEST0..7 回傳前一次結果或 0,且 STATUS.VALID = 0。 |

