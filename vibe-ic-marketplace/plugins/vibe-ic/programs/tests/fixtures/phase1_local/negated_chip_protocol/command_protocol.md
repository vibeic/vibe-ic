**沒有**:
- chip-level SPI / I2C / UART command interface
- opcode-encoded command parsing(SoC 沒做)
- software register write-based control(no SW-visible chip register;見 L5)

**有**(屬於 firmware 層級,不是 chip-level 規格):
- RV32I 指令集語意:**這是 firmware 寫的程式碼層級**,屬 RISC-V ISA 標準,不在本 chip spec 的 L4 範圍內
- GPIO 輸出可作為 UART tx(by firmware bit-banging GPIO):這是 application,**不是 chip 提供的 protocol**

→ Plugin 不需產生任何 chip-level protocol decoder。
