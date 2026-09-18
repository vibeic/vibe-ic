## 同步行為

| 訊號 | 行為 |
|---|---|
| `clk` | 系統時脈,所有 reg 取樣於上升沿 |
| `reset_n` | **同步 reset, active-LOW**(注意:active-LOW,與先前 pilot 的 active-HIGH 相反!)|
| Reset assert(`reset_n = 0`)| 內部 state machine 歸 idle;register file 進入預設值;ready bit set |
| Reset release | chip ready 接收新 INIT 命令 |

### 控制狀態機(control state machine,可觀察狀態)

The hash engine's control state machine has two externally observable states, IDLE and BUSY, reported through STATUS.READY:

- On reset, the state machine is in IDLE (STATUS.READY = 1, STATUS.VALID = 0).
- The FSM transitions from IDLE to BUSY when a CTRL write with INIT = 1 or NEXT = 1 is accepted (STATUS.READY = 0 while BUSY).
- The FSM transitions from BUSY to IDLE when the 
