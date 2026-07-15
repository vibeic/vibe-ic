// ---------------------------------------------------------------------------
// apb_dsp_unit
// APB slave exposing a small DSP configuration register bank (0x0 - 0x5)
// in front of a 1 KB SRAM. The 10-bit paddr bus is overloaded: addresses
// 0x000-0x005 decode to the CSRs / computed result, every other address
// falls through to the backing SRAM (read and write datapaths).
//
// Register map (byte-wide registers, unit-spaced addresses):
//   0x0 : r_operand_1     - memory address of operand A
//   0x1 : r_operand_2     - memory address of operand B
//   0x2 : r_Enable        - 0: disabled, 1: add, 2: multiply, 3: data write
//   0x3 : r_write_address - SRAM address used in data-writing mode
//   0x4 : r_write_data    - data latched into SRAM in data-writing mode
//   0x5 : computed result (read-only, combinational from the ALU)
//
// Protocol: standard 2-cycle (SETUP + ACCESS) APB with no wait states,
// pready held high after reset. Read data is registered on the SETUP edge
// so prdata is stable for the whole ACCESS phase. CSR/memory writes commit
// on the qualified ACCESS edge (pselx && penable && pwrite).
//
// SRAM data-writing mode: on the rising edge of sram_valid (treated as a
// true clock), while r_Enable == 3, mem[r_write_address] <= r_write_data.
// ---------------------------------------------------------------------------
module apb_dsp_unit (
    // Clock & reset
    input  wire       pclk,
    input  wire       presetn,   // active-low asynchronous reset
    // APB interface
    input  wire [9:0] paddr,
    input  wire       pselx,
    input  wire       penable,
    input  wire       pwrite,
    input  wire [7:0] pwdata,
    output reg        pready,
    output reg  [7:0] prdata,
    output reg        pslverr,
    // SRAM interface
    input  wire       sram_valid
);

    // ------------------------------------------------------------------
    // Configuration registers
    // ------------------------------------------------------------------
    reg [7:0] r_operand_1;
    reg [7:0] r_operand_2;
    reg [7:0] r_Enable;
    reg [7:0] r_write_address;
    reg [7:0] r_write_data;

    // ------------------------------------------------------------------
    // 1 KB SRAM (1024 x 8) shared with the APB address space
    // ------------------------------------------------------------------
    reg [7:0] mem [0:1023];

    integer i;
    initial begin
        for (i = 0; i < 1024; i = i + 1)
            mem[i] = 8'h00;
    end

    // ------------------------------------------------------------------
    // DSP ALU: combinational result, exposed read-only at address 0x5
    // ------------------------------------------------------------------
    wire [7:0] op_a = mem[r_operand_1];
    wire [7:0] op_b = mem[r_operand_2];

    wire [7:0] alu_result = (r_Enable == 8'd1) ? (op_a + op_b) :
                            (r_Enable == 8'd2) ? (op_a * op_b) :
                                                 8'h00;

    // APB phase qualifiers
    wire apb_setup_rd = pselx && !penable && !pwrite; // SETUP edge of a read
    wire apb_access_wr = pselx &&  penable &&  pwrite; // ACCESS edge of a write

    // ------------------------------------------------------------------
    // pready: no wait states - held high whenever out of reset
    // ------------------------------------------------------------------
    always @(posedge pclk or negedge presetn) begin
        if (!presetn)
            pready <= 1'b0;
        else
            pready <= 1'b1;
    end

    // ------------------------------------------------------------------
    // Read datapath: capture the addressed value so it is valid during
    // the ACCESS phase (2-cycle, no-wait-state read contract).
    // Addresses above the reserved CSR band return SRAM contents.
    // ------------------------------------------------------------------
    always @(posedge pclk or negedge presetn) begin
        if (!presetn) begin
            prdata <= 8'h00;
        end else if (pselx && !pwrite) begin
            case (paddr)
                10'h000: prdata <= r_operand_1;
                10'h001: prdata <= r_operand_2;
                10'h002: prdata <= r_Enable;
                10'h003: prdata <= r_write_address;
                10'h004: prdata <= r_write_data;
                10'h005: prdata <= alu_result;      // read-only computed result
                default: prdata <= mem[paddr];      // SRAM fall-through
            endcase
        end
    end

    // ------------------------------------------------------------------
    // CSR write datapath (qualified ACCESS edge). Address 0x5 is read-only
    // and silently ignores writes; addresses >= 0x6 target the SRAM.
    // ------------------------------------------------------------------
    always @(posedge pclk or negedge presetn) begin
        if (!presetn) begin
            r_operand_1     <= 8'h00;
            r_operand_2     <= 8'h00;
            r_Enable        <= 8'h00;
            r_write_address <= 8'h00;
            r_write_data    <= 8'h00;
        end else if (apb_access_wr) begin
            case (paddr)
                10'h000: r_operand_1     <= pwdata;
                10'h001: r_operand_2     <= pwdata;
                10'h002: r_Enable        <= pwdata;
                10'h003: r_write_address <= pwdata;
                10'h004: r_write_data    <= pwdata;
                default: ;                          // 0x5 read-only / SRAM range
            endcase
        end
    end

    // ------------------------------------------------------------------
    // SRAM write datapath #1: direct APB writes to the memory range
    // ------------------------------------------------------------------
    always @(posedge pclk) begin
        if (presetn && apb_access_wr && (paddr > 10'h005))
            mem[paddr] <= pwdata;
    end

    // ------------------------------------------------------------------
    // SRAM write datapath #2: data-writing mode. sram_valid acts as a
    // clock - on its rising edge, while r_Enable == 3, latch r_write_data
    // into mem[r_write_address].
    // ------------------------------------------------------------------
    always @(posedge sram_valid) begin
        if (presetn && (r_Enable == 8'd3))
            mem[r_write_address] <= r_write_data;
    end

    // ------------------------------------------------------------------
    // pslverr: the 10-bit address space is fully mapped (CSRs + 1 KB SRAM),
    // so no qualified access targets an unmapped address; writes to the
    // read-only result register are silently ignored.
    // ------------------------------------------------------------------
    always @(posedge pclk or negedge presetn) begin
        if (!presetn)
            pslverr <= 1'b0;
        else
            pslverr <= 1'b0;
    end

endmodule
