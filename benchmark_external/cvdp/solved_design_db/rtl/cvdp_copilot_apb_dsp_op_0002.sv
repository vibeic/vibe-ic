// APB DSP Operation Module (debugged / bug-fixed)
//  - Adds PSLVERR: asserted (PREADY still high, no wait-states) on an invalid
//    APB address or an out-of-bounds SRAM access during the access phase.
//  - Replaces the discouraged combinational clock MUX with a glitch-free clock
//    multiplexer (dual-flop, cross-disabled) that selects clk_dsp vs PCLK and
//    synchronises en_clk_dsp into each domain.
//  - SRAM lives in the DSP clock domain. A combinational read port feeds the
//    DSP operand capture (single-cycle, no read-latency skew) so the
//    multiply-accumulate sees the correct A/B/C even with back-to-back control
//    writes; the APB side reads the same array in the PCLK domain.
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

    // ---- APB register byte-address map (sized to the address bus) ----
    localparam [ADDR_WIDTH-1:0] PA_A     = 'h00; // 0x00 operand A (SRAM addr)
    localparam [ADDR_WIDTH-1:0] PA_B     = 'h04; // 0x04 operand B (SRAM addr)
    localparam [ADDR_WIDTH-1:0] PA_C     = 'h08; // 0x08 operand C (SRAM addr)
    localparam [ADDR_WIDTH-1:0] PA_O     = 'h0C; // 0x0C operand O (SRAM addr)
    localparam [ADDR_WIDTH-1:0] PA_CTRL  = 'h10; // 0x10 control
    localparam [ADDR_WIDTH-1:0] PA_WDATA = 'h14; // 0x14 SRAM write data
    localparam [ADDR_WIDTH-1:0] PA_SADDR = 'h18; // 0x18 SRAM address

    // ---- Control modes (held in reg_control) ----
    localparam [DATA_WIDTH-1:0] SRAM_WRITE     = 'd1;
    localparam [DATA_WIDTH-1:0] SRAM_READ      = 'd2;
    localparam [DATA_WIDTH-1:0] DSP_READ_OP_A  = 'd3;
    localparam [DATA_WIDTH-1:0] DSP_READ_OP_B  = 'd4;
    localparam [DATA_WIDTH-1:0] DSP_READ_OP_C  = 'd5;
    localparam [DATA_WIDTH-1:0] DSP_WRITE_OP_O = 'd6;

    // ---- SRAM geometry ----
    localparam integer SRAM_DEPTH = 64;
    localparam integer SRAM_AW    = 6;            // log2(SRAM_DEPTH)

    // ---- APB-domain registers ----
    logic [DATA_WIDTH-1:0] reg_operand_a;
    logic [DATA_WIDTH-1:0] reg_operand_b;
    logic [DATA_WIDTH-1:0] reg_operand_c;
    logic [DATA_WIDTH-1:0] reg_operand_o;
    logic [DATA_WIDTH-1:0] reg_control;
    logic [DATA_WIDTH-1:0] reg_wdata_sram;
    logic [DATA_WIDTH-1:0] reg_addr_sram;

    // ---- DSP-domain signals ----
    logic signed [DATA_WIDTH-1:0] wire_op_a;
    logic signed [DATA_WIDTH-1:0] wire_op_b;
    logic signed [DATA_WIDTH-1:0] wire_op_c;
    logic signed [DATA_WIDTH-1:0] wire_op_o;
    logic        [DATA_WIDTH-1:0] sram_data_in;
    logic                         sram_we;
    logic        [DATA_WIDTH-1:0] sram_addr;

    // =====================================================================
    // Glitch-free clock multiplexer: dsp_clk = en_clk_dsp ? clk_dsp : PCLK.
    // =====================================================================
    logic dsp_clk;
    logic selA_meta, selA;   // PCLK   path enable (en_clk_dsp == 0)
    logic selB_meta, selB;   // clk_dsp path enable (en_clk_dsp == 1)

    always_ff @(posedge PCLK or negedge PRESETn) begin
        if (!PRESETn) selA_meta <= 1'b0;
        else          selA_meta <= ~en_clk_dsp & ~selB;
    end
    always_ff @(negedge PCLK or negedge PRESETn) begin
        if (!PRESETn) selA <= 1'b0;
        else          selA <= selA_meta;
    end
    always_ff @(posedge clk_dsp or negedge PRESETn) begin
        if (!PRESETn) selB_meta <= 1'b0;
        else          selB_meta <= en_clk_dsp & ~selA;
    end
    always_ff @(negedge clk_dsp or negedge PRESETn) begin
        if (!PRESETn) selB <= 1'b0;
        else          selB <= selB_meta;
    end
    assign dsp_clk = (selA & PCLK) | (selB & clk_dsp);

    // =====================================================================
    // APB address-decode and error qualification (combinational)
    // =====================================================================
    logic addr_valid;
    always_comb begin
        case (PADDR)
            PA_A, PA_B, PA_C, PA_O, PA_CTRL, PA_WDATA, PA_SADDR: addr_valid = 1'b1;
            default:                                             addr_valid = 1'b0;
        endcase
    end

    // The control mode selects which address actually drives the SRAM; an
    // SRAM-touching mode with an address >= depth is an out-of-bounds access.
    logic sram_active;
    always_comb begin
        case (reg_control)
            SRAM_READ, SRAM_WRITE,
            DSP_READ_OP_A, DSP_READ_OP_B, DSP_READ_OP_C, DSP_WRITE_OP_O: sram_active = 1'b1;
            default:                                                     sram_active = 1'b0;
        endcase
    end
    logic sram_oob;
    assign sram_oob = sram_active & (sram_addr >= SRAM_DEPTH[DATA_WIDTH-1:0]);

    // =====================================================================
    // SRAM array (DSP clock domain for writes). mem is initialised to 0 so an
    // un-written read never yields X on the APB bus.
    // =====================================================================
    logic [DATA_WIDTH-1:0] mem [0:SRAM_DEPTH-1];
    integer mem_i;
    initial begin
        for (mem_i = 0; mem_i < SRAM_DEPTH; mem_i = mem_i + 1) mem[mem_i] = '0;
    end

    // =====================================================================
    // APB interface (PCLK). Registers, PRDATA, PREADY and PSLVERR.
    // No wait states: PREADY high in the access phase; PSLVERR flags an
    // invalid address / out-of-bounds SRAM access in that same phase.
    // =====================================================================
    always_ff @(posedge PCLK or negedge PRESETn) begin
        if (!PRESETn) begin
            reg_operand_a  <= 'd0;
            reg_operand_b  <= 'd0;
            reg_operand_c  <= 'd0;
            reg_operand_o  <= 'd0;
            reg_control    <= 'd0;
            reg_wdata_sram <= 'd0;
            reg_addr_sram  <= 'd0;
            PRDATA         <= 'd0;
            PREADY         <= 1'b0;
            PSLVERR        <= 1'b0;
        end else if (PSEL & PENABLE) begin
            PREADY  <= 1'b1;
            PSLVERR <= (~addr_valid) | sram_oob;
            if (PWRITE) begin
                case (PADDR)
                    PA_A     : reg_operand_a  <= PWDATA;
                    PA_B     : reg_operand_b  <= PWDATA;
                    PA_C     : reg_operand_c  <= PWDATA;
                    PA_O     : reg_operand_o  <= PWDATA;
                    PA_CTRL  : reg_control    <= PWDATA;
                    PA_WDATA : reg_wdata_sram <= PWDATA;
                    PA_SADDR : reg_addr_sram  <= PWDATA;
                    default  : ; // invalid address: no write (PSLVERR flagged)
                endcase
            end else begin
                if (reg_control == SRAM_READ) begin
                    // SRAM read: return the addressed memory word directly.
                    PRDATA <= mem[reg_addr_sram[SRAM_AW-1:0]];
                end else begin
                    case (PADDR)
                        PA_A     : PRDATA <= reg_operand_a;
                        PA_B     : PRDATA <= reg_operand_b;
                        PA_C     : PRDATA <= reg_operand_c;
                        PA_O     : PRDATA <= reg_operand_o;
                        PA_CTRL  : PRDATA <= reg_control;
                        PA_WDATA : PRDATA <= reg_wdata_sram;
                        PA_SADDR : PRDATA <= reg_addr_sram;
                        default  : PRDATA <= 'd0;
                    endcase
                end
            end
        end else begin
            PREADY  <= 1'b0;
            PSLVERR <= 1'b0;
        end
    end

    // =====================================================================
    // SRAM data-path control (combinational; sourced from the held APB regs)
    // =====================================================================
    always_comb begin
        sram_data_in = (reg_control == SRAM_WRITE) ? reg_wdata_sram : wire_op_o;

        if ((reg_control == SRAM_WRITE) || (reg_control == DSP_WRITE_OP_O))
            sram_we = 1'b1;
        else
            sram_we = 1'b0;

        case (reg_control)
            DSP_READ_OP_A  : sram_addr = reg_operand_a;
            DSP_READ_OP_B  : sram_addr = reg_operand_b;
            DSP_READ_OP_C  : sram_addr = reg_operand_c;
            DSP_WRITE_OP_O : sram_addr = reg_operand_o;
            default        : sram_addr = reg_addr_sram;
        endcase
    end

    // SRAM write (DSP clock domain).
    always_ff @(posedge dsp_clk) begin
        if (sram_we)
            mem[sram_addr[SRAM_AW-1:0]] <= sram_data_in;
    end

    // =====================================================================
    // DSP operand capture (DSP domain). Combinational SRAM read port: mem is
    // read in the same cycle the operand register selects it, so each operand
    // is captured one cycle after its control mode is applied -- no
    // registered-read skew, robust to back-to-back control writes.
    // Multiply-accumulate is combinational.
    // =====================================================================
    always_ff @(posedge dsp_clk or negedge PRESETn) begin
        if (!PRESETn) begin
            wire_op_a <= 'd0;
            wire_op_b <= 'd0;
            wire_op_c <= 'd0;
        end else begin
            case (reg_control)
                DSP_READ_OP_A  : wire_op_a <= mem[reg_operand_a[SRAM_AW-1:0]];
                DSP_READ_OP_B  : wire_op_b <= mem[reg_operand_b[SRAM_AW-1:0]];
                DSP_READ_OP_C  : wire_op_c <= mem[reg_operand_c[SRAM_AW-1:0]];
                default        : ; // hold
            endcase
        end
    end

    assign wire_op_o = (wire_op_a * wire_op_b) + wire_op_c;

endmodule
