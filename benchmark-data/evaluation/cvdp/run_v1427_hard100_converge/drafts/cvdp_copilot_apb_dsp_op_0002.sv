// APB DSP Operation Module — bug-fixed
//
// Fixes vs. the original buggy RTL:
//  1. Added the missing PSLVERR output. It is registered so that it is valid
//     for the whole ACCESS phase (PSEL && PENABLE): asserted when PADDR is
//     outside the valid register range (0x00-0x06) or when the currently
//     active control mode targets an out-of-bounds SRAM address (> 63).
//     Cleared by the asynchronous reset.
//  2. Fixed the register address map: the spec defines word-index addresses
//     0x00..0x06 (the buggy code decoded 0x00, 0x04, 0x08, ... 0x18).
//  3. PREADY: initializes to 1'b0 at reset and is asserted (registered at the
//     SETUP edge) so it is high immediately during the ACCESS phase — the
//     slave supports no wait states. The buggy code asserted it one cycle
//     too late and never deasserted it.
//  4. PRDATA is registered at the SETUP edge so read data is valid
//     "immediately" while PENABLE is high (buggy code updated it one cycle
//     too late). Reads of invalid addresses return zero.
//  5. Replaced the raw combinational clock MUX with a glitch-free,
//     break-before-make clock switch: two cross-coupled enable registers,
//     each retimed on the negative edge of its own clock before AND-gating,
//     so the selected clock never produces runt pulses. en_clk_dsp crosses
//     into the clk_dsp domain through two flops (dual-flop synchronizer).
//     The async reset forces the selected clock low.
//  6. The SRAM and the DSP operand registers are clocked by the selected DSP
//     clock (same domain as the DSP), and SRAM accesses are bounds-guarded.
module apb_dsp_op #(
    parameter ADDR_WIDTH = 'd8,
    parameter DATA_WIDTH = 'd32
) (
    input  logic                  clk_dsp,    // Faster clock to DSP operation
    input  logic                  en_clk_dsp, // Enable DSP operation with faster clock
    input  logic                  PCLK,       // APB clock
    input  logic                  PRESETn,    // Active low asynchronous APB Reset
    input  logic [ADDR_WIDTH-1:0] PADDR,      // APB address
    input  logic                  PWRITE,     // Write/Read enable
    input  logic [DATA_WIDTH-1:0] PWDATA,     // Write data
    input  logic                  PSEL,       // DSP selector
    input  logic                  PENABLE,    // APB enable
    output logic [DATA_WIDTH-1:0] PRDATA,     // Read data
    output logic                  PREADY,     // Ready signal
    output logic                  PSLVERR     // Error signal
);

    // Internal registers address map (FIX: spec addresses are 0x00..0x06)
    localparam logic [ADDR_WIDTH-1:0] ADDRESS_A         = 'h00; // REG_OPERAND_A
    localparam logic [ADDR_WIDTH-1:0] ADDRESS_B         = 'h01; // REG_OPERAND_B
    localparam logic [ADDR_WIDTH-1:0] ADDRESS_C         = 'h02; // REG_OPERAND_C
    localparam logic [ADDR_WIDTH-1:0] ADDRESS_O         = 'h03; // REG_OPERAND_O
    localparam logic [ADDR_WIDTH-1:0] ADDRESS_CONTROL   = 'h04; // REG_CONTROL
    localparam logic [ADDR_WIDTH-1:0] ADDRESS_WDATA     = 'h05; // REG_WDATA_SRAM
    localparam logic [ADDR_WIDTH-1:0] ADDRESS_SRAM_ADDR = 'h06; // REG_ADDR_SRAM

    // Control modes
    localparam SRAM_WRITE     = 32'd1;
    localparam SRAM_READ      = 32'd2;
    localparam DSP_READ_OP_A  = 32'd3;
    localparam DSP_READ_OP_B  = 32'd4;
    localparam DSP_READ_OP_C  = 32'd5;
    localparam DSP_WRITE_OP_O = 32'd6;

    // SRAM depth (64 words)
    localparam int SRAM_DEPTH = 64;

    // Internal signals
    logic [DATA_WIDTH-1:0] reg_operand_a;
    logic [DATA_WIDTH-1:0] reg_operand_b;
    logic [DATA_WIDTH-1:0] reg_operand_c;
    logic [DATA_WIDTH-1:0] reg_operand_o;
    logic [DATA_WIDTH-1:0] reg_control;
    logic [DATA_WIDTH-1:0] reg_wdata_sram;
    logic [DATA_WIDTH-1:0] reg_addr_sram;

    logic signed [DATA_WIDTH-1:0] wire_op_a;
    logic signed [DATA_WIDTH-1:0] wire_op_b;
    logic signed [DATA_WIDTH-1:0] wire_op_c;
    logic signed [DATA_WIDTH-1:0] wire_op_o;
    logic        [DATA_WIDTH-1:0] sram_data_in;
    logic                         sram_we;
    logic        [DATA_WIDTH-1:0] sram_addr;
    logic        [DATA_WIDTH-1:0] sram_data_out = '0;

    // ------------------------------------------------------------------
    // Glitch-free clock selection between PCLK and clk_dsp (FIX #5)
    // Cross-coupled break-before-make enables; each enable is retimed on
    // the negative edge of its own clock so the AND mask only changes
    // while that clock is low -> no runt/glitch pulses on dsp_clk_sel.
    // en_clk_dsp (PCLK domain) is effectively double-flopped into the
    // clk_dsp domain (sel_dsp_meta -> sel_dsp_en).
    // ------------------------------------------------------------------
    logic sel_pclk_meta, sel_pclk_en;
    logic sel_dsp_meta,  sel_dsp_en;
    logic dsp_clk_sel;

    // PCLK-path enable: active when the fast clock is not requested and the
    // clk_dsp path has fully released the clock output.
    always_ff @(posedge PCLK or negedge PRESETn) begin
        if (!PRESETn) sel_pclk_meta <= 1'b0;
        else          sel_pclk_meta <= ~en_clk_dsp & ~sel_dsp_en;
    end
    always_ff @(negedge PCLK or negedge PRESETn) begin
        if (!PRESETn) sel_pclk_en <= 1'b0;
        else          sel_pclk_en <= sel_pclk_meta;
    end

    // clk_dsp-path enable: active when the fast clock is requested and the
    // PCLK path has fully released the clock output.
    always_ff @(posedge clk_dsp or negedge PRESETn) begin
        if (!PRESETn) sel_dsp_meta <= 1'b0;
        else          sel_dsp_meta <= en_clk_dsp & ~sel_pclk_en;
    end
    always_ff @(negedge clk_dsp or negedge PRESETn) begin
        if (!PRESETn) sel_dsp_en <= 1'b0;
        else          sel_dsp_en <= sel_dsp_meta;
    end

    // Async reset forces the selected clock low (both enables cleared).
    assign dsp_clk_sel = (PCLK & sel_pclk_en) | (clk_dsp & sel_dsp_en);

    // ------------------------------------------------------------------
    // APB error decode (FIX #1)
    // Invalid register address, or the active control mode performs an
    // SRAM access whose effective address is out of bounds.
    // ------------------------------------------------------------------
    logic apb_addr_invalid;
    logic sram_ctrl_active;
    logic sram_addr_oob;
    logic apb_err;

    assign apb_addr_invalid = (PADDR > ADDRESS_SRAM_ADDR);
    assign sram_ctrl_active = (reg_control >= SRAM_WRITE) &&
                              (reg_control <= DSP_WRITE_OP_O);
    assign sram_addr_oob    = sram_ctrl_active && (sram_addr >= SRAM_DEPTH);
    assign apb_err          = apb_addr_invalid | sram_addr_oob;

    // ------------------------------------------------------------------
    // APB interface logic
    // ------------------------------------------------------------------

    // Register writes commit at the end of the ACCESS phase. Writes to
    // invalid addresses are silently ignored (no register updated); they
    // are only flagged through PSLVERR. Never gate the write commit with
    // apb_err, otherwise an out-of-bounds SRAM address could never be
    // corrected again.
    always_ff @(posedge PCLK or negedge PRESETn) begin
        if (!PRESETn) begin
            reg_operand_a  <= 'd0;
            reg_operand_b  <= 'd0;
            reg_operand_c  <= 'd0;
            reg_operand_o  <= 'd0;
            reg_control    <= 'd0;
            reg_wdata_sram <= 'd0;
            reg_addr_sram  <= 'd0;
        end else if (PSEL && PENABLE && PWRITE) begin
            case (PADDR)
                ADDRESS_A         : reg_operand_a  <= PWDATA;
                ADDRESS_B         : reg_operand_b  <= PWDATA;
                ADDRESS_C         : reg_operand_c  <= PWDATA;
                ADDRESS_O         : reg_operand_o  <= PWDATA;
                ADDRESS_CONTROL   : reg_control    <= PWDATA;
                ADDRESS_WDATA     : reg_wdata_sram <= PWDATA;
                ADDRESS_SRAM_ADDR : reg_addr_sram  <= PWDATA;
                default           : ; // invalid address: ignore write
            endcase
        end
    end

    // PREADY (FIX #3): 0 out of reset; registered at the SETUP edge so it is
    // already high during the whole ACCESS phase (zero wait states).
    always_ff @(posedge PCLK or negedge PRESETn) begin
        if (!PRESETn) PREADY <= 1'b0;
        else          PREADY <= PSEL;
    end

    // PSLVERR (FIX #1): cleared on reset; evaluated at the SETUP edge so it
    // is valid during the same cycle PENABLE is high, and it deasserts after
    // the transaction ends.
    always_ff @(posedge PCLK or negedge PRESETn) begin
        if (!PRESETn) PSLVERR <= 1'b0;
        else          PSLVERR <= PSEL & apb_err;
    end

    // PRDATA (FIX #4): registered at the SETUP edge of a read so the data is
    // valid immediately when PENABLE is asserted and holds afterwards.
    always_ff @(posedge PCLK or negedge PRESETn) begin
        if (!PRESETn) begin
            PRDATA <= 'd0;
        end else if (PSEL && !PENABLE && !PWRITE) begin
            if (reg_control == SRAM_READ) begin
                PRDATA <= sram_data_out;
            end else begin
                case (PADDR)
                    ADDRESS_A         : PRDATA <= reg_operand_a;
                    ADDRESS_B         : PRDATA <= reg_operand_b;
                    ADDRESS_C         : PRDATA <= reg_operand_c;
                    ADDRESS_O         : PRDATA <= reg_operand_o;
                    ADDRESS_CONTROL   : PRDATA <= reg_control;
                    ADDRESS_WDATA     : PRDATA <= reg_wdata_sram;
                    ADDRESS_SRAM_ADDR : PRDATA <= reg_addr_sram;
                    default           : PRDATA <= 'd0; // invalid: return 0
                endcase
            end
        end
    end

    // ------------------------------------------------------------------
    // SRAM logic — clocked by the selected DSP clock (FIX #6)
    // ------------------------------------------------------------------
    logic [DATA_WIDTH-1:0] mem [SRAM_DEPTH-1:0];

    initial begin
        for (int i = 0; i < SRAM_DEPTH; i++) begin
            mem[i] = '0;
        end
    end

    always_comb begin
        sram_data_in = (reg_control == SRAM_WRITE) ? reg_wdata_sram : wire_op_o;

        if ((reg_control == SRAM_WRITE) || (reg_control == DSP_WRITE_OP_O)) begin
            sram_we = 1'b1;
        end else begin
            sram_we = 1'b0;
        end

        case (reg_control)
            DSP_READ_OP_A  : sram_addr = reg_operand_a;
            DSP_READ_OP_B  : sram_addr = reg_operand_b;
            DSP_READ_OP_C  : sram_addr = reg_operand_c;
            DSP_WRITE_OP_O : sram_addr = reg_operand_o;
            default        : sram_addr = reg_addr_sram;
        endcase
    end

    // SRAM in the DSP clock domain; accesses bounds-guarded so an
    // out-of-range address never corrupts memory or the read register.
    always_ff @(posedge dsp_clk_sel) begin
        if (sram_we) begin
            if (sram_addr < SRAM_DEPTH) begin
                mem[sram_addr[5:0]] <= sram_data_in;
            end
        end else begin
            if (sram_addr < SRAM_DEPTH) begin
                sram_data_out <= mem[sram_addr[5:0]];
            end
        end
    end

    // DSP operand capture — same (selected) DSP clock domain
    always_ff @(posedge dsp_clk_sel or negedge PRESETn) begin
        if (!PRESETn) begin
            wire_op_a <= 'd0;
            wire_op_b <= 'd0;
            wire_op_c <= 'd0;
        end else begin
            case (reg_control)
                DSP_READ_OP_A  : wire_op_a <= sram_data_out;
                DSP_READ_OP_B  : wire_op_b <= sram_data_out;
                DSP_READ_OP_C  : wire_op_c <= sram_data_out;
                default        : ;
            endcase
        end
    end

    assign wire_op_o = (wire_op_a * wire_op_b) + wire_op_c;

endmodule
