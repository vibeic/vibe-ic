## Register Definitions

| 位址(hex) | 名稱 | R/W | 寬度 | 描述 |
|---|---|---|---|---|
| `0x00` | `NAME0` | R | 32 | Chip identifier word 0(magic 字串前 4 chars) |
| `0x01` | `NAME1` | R | 32 | Chip identifier word 1(magic 字串後 4 chars) |
| `0x02` | `VERSION` | R | 32 | Version string |
| `0x08` | `CTRL` | R/W | 32 | 控制 register(下表詳列 bit) |
| `0x09` | `STATUS` | R | 32 | 狀態 register(下表詳列 bit) |
| `0x10-0x1F` | `BLOCK0` ~ `BLOCK15` | W | 32 each | 512-bit message block input(16 個 32-bit word) |
| `0x20-0x27` | `DIGEST0` ~ `DIGEST7` | R | 32 each | 256-bit digest output(SHA-256 全 8;SHA-224 取前 7) |

