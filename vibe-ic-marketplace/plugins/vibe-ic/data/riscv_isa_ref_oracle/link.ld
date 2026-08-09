/* subservient memory map: shared SRAM = 1024 bytes at 0x00000000.
 * servile_mux: adr[31:30]==00 -> SRAM, !=00 -> extension bus (GPIO).
 * reset_pc = 0x00000000 (L2/L3).
 */
OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY
{
  SRAM (rwx) : ORIGIN = 0x00000000, LENGTH = 1024
}
SECTIONS
{
  .text 0x00000000 : { *(.text.init) *(.text*) } > SRAM
  . = 0x00000380;
  .data 0x00000380 : { *(.data*) *(.rodata*) *(.bss*) } > SRAM
  .htif 0x000003F0 : { *(.htif) } > SRAM
}
