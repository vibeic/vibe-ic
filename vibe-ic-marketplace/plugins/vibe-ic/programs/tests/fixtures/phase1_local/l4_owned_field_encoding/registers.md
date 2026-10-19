# Register map

| Name | Offset | Length | Description |
|:-----|:-------|-------:|:------------|
| CONFIG | 0x0 | 4 | Configuration register |

## CONFIG
- Offset: `0x0`

#### Fields

| Bits | Type | Reset | Name |
|:----:|:----:|:-----:|:-----|
| 11 | rw | 0x0 | ENABLE |
| 7:5 | rw | 0x1 | RATE |
| 4:2 | rw | 0x1 | SIZE |
| 1:0 | rw | 0x1 | ACTION |

#### CONFIG . RATE
Select rate.

| Value | Name | Description |
|:------|:-----|:------------|
| 0x1 | RATE_SLOW | 3'b001: Low rate. |
| 0x2 | RATE_FAST | 3'b010: High rate. |

#### CONFIG . SIZE
Select size.

| Value | Name | Description |
|:------|:-----|:------------|
| 0x1 | SIZE_SMALL | 3'b001: Small size. |
| 0x2 | SIZE_LARGE | 3'b010: Large size. |

#### CONFIG . ACTION
Select action.

| Value | Name | Description |
|:------|:-----|:------------|
| 0x1 | DO_READ | 2'b01: Read action. |
| 0x2 | DO_WRITE | 2'b10: Write action. |
