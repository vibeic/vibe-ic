// -----------------------------------------------------------------------------
// axi_register — AXI4-Lite slave register block
//
//   Offset 0x100 : Beat      (R/W, 20-bit counter value, reflected on beat_o)
//   Offset 0x200 : Start     (R/W, 1-bit trigger,        reflected on start_o)
//   Offset 0x300 : Done      (R/W, 1-bit status; hardware-set via done_i,
//                              write-1-to-clear the internal done status)
//   Offset 0x400 : Writeback (R/W, 1-bit trigger,        reflected on writeback_o)
//   Offset 0x500 : ID        (RO,  fixed 32'h0001_0001; writes -> SLVERR)
//
//   * Each channel is an independent one-shot handshake FSM: the *ready is
//     asserted only while the FSM waits for the matching *valid, the address
//     is latched at accept time, and bvalid/rvalid are held until bready/rready.
//   * Full-strobe writes update the register; partial-strobe writes are
//     acknowledged (OKAY) without modifying the register.
//   * Writes to the read-only ID register or to undefined offsets return
//     SLVERR; reads of undefined offsets return SLVERR with zero data.
//   * Async active-low reset: beat_o/start_o/writeback_o and all internal
//     registers are cleared; ready/valid outputs are driven low during reset.
// -----------------------------------------------------------------------------
module axi_register #(
    parameter int ADDR_WIDTH = 32,
    parameter int DATA_WIDTH = 32
) (
    input  logic                      clk_i,
    input  logic                      rst_n_i,

    // Write address channel
    input  logic [ADDR_WIDTH-1:0]     awaddr_i,
    input  logic                      awvalid_i,
    output logic                      awready_o,

    // Write data channel
    input  logic [DATA_WIDTH-1:0]     wdata_i,
    input  logic                      wvalid_i,
    input  logic [(DATA_WIDTH/8)-1:0] wstrb_i,
    output logic                      wready_o,

    // Write response channel
    output logic [1:0]                bresp_o,
    output logic                      bvalid_o,
    input  logic                      bready_i,

    // Read address channel
    input  logic [ADDR_WIDTH-1:0]     araddr_i,
    input  logic                      arvalid_i,
    output logic                      arready_o,

    // Read data channel
    output logic [DATA_WIDTH-1:0]     rdata_o,
    output logic                      rvalid_o,
    output logic [1:0]                rresp_o,
    input  logic                      rready_i,

    // Hardware interface
    input  logic                      done_i,
    output logic [19:0]               beat_o,
    output logic                      start_o,
    output logic                      writeback_o
);

    // -------------------------------------------------------------------------
    // Constants
    // -------------------------------------------------------------------------
    localparam logic [1:0] RESP_OKAY   = 2'b00;
    localparam logic [1:0] RESP_SLVERR = 2'b10;

    localparam logic [11:0] ADDR_BEAT      = 12'h100;
    localparam logic [11:0] ADDR_START     = 12'h200;
    localparam logic [11:0] ADDR_DONE      = 12'h300;
    localparam logic [11:0] ADDR_WRITEBACK = 12'h400;
    localparam logic [11:0] ADDR_ID        = 12'h500;

    localparam logic [31:0] ID_VALUE = 32'h0001_0001;

    // Wide read bus (> 32 bits) so every zero-extension below has a strictly
    // positive pad width for any DATA_WIDTH >= 8.
    localparam int RD_W = ((DATA_WIDTH > 32) ? DATA_WIDTH : 32) + 1;

    // -------------------------------------------------------------------------
    // Registers
    // -------------------------------------------------------------------------
    logic [19:0] beat_q;
    logic        start_q;
    logic        done_q;
    logic        writeback_q;

    logic [11:0] awaddr_q;      // latched write address (decode on this)
    logic [1:0]  bresp_q;

    logic [DATA_WIDTH-1:0] rdata_q;
    logic [1:0]            rresp_q;

    // Zero-extended write data so the 20-bit beat slice works for any
    // DATA_WIDTH >= 8.
    logic [DATA_WIDTH+19:0] wdata_ext;
    assign wdata_ext = {20'b0, wdata_i};

    // -------------------------------------------------------------------------
    // Write channel FSM: IDLE (accept AW) -> DATA (accept W) -> RESP (B)
    // -------------------------------------------------------------------------
    typedef enum logic [1:0] {W_IDLE, W_DATA, W_RESP} wstate_e;
    wstate_e wstate_q;

    always_ff @(posedge clk_i or negedge rst_n_i) begin
        if (!rst_n_i) begin
            wstate_q    <= W_IDLE;
            awaddr_q    <= '0;
            bresp_q     <= RESP_OKAY;
            beat_q      <= '0;
            start_q     <= 1'b0;
            done_q      <= 1'b0;
            writeback_q <= 1'b0;
        end else begin
            // Hardware sets the done status; a write-1-to-clear in the same
            // cycle (assigned below) has priority.
            if (done_i)
                done_q <= 1'b1;

            case (wstate_q)
                W_IDLE: begin
                    if (awvalid_i) begin        // awready_o is high in W_IDLE
                        awaddr_q <= awaddr_i[11:0];
                        wstate_q <= W_DATA;
                    end
                end

                W_DATA: begin
                    if (wvalid_i) begin         // wready_o is high in W_DATA
                        case (awaddr_q)
                            ADDR_BEAT: begin
                                bresp_q <= RESP_OKAY;
                                if (&wstrb_i)
                                    beat_q <= wdata_ext[19:0];
                            end
                            ADDR_START: begin
                                bresp_q <= RESP_OKAY;
                                if (&wstrb_i)
                                    start_q <= wdata_i[0];
                            end
                            ADDR_DONE: begin
                                bresp_q <= RESP_OKAY;
                                if (&wstrb_i && wdata_i[0])
                                    done_q <= 1'b0;   // W1C beats hardware set
                            end
                            ADDR_WRITEBACK: begin
                                bresp_q <= RESP_OKAY;
                                if (&wstrb_i)
                                    writeback_q <= wdata_i[0];
                            end
                            default: begin
                                // Read-only ID register or undefined offset
                                bresp_q <= RESP_SLVERR;
                            end
                        endcase
                        wstate_q <= W_RESP;
                    end
                end

                W_RESP: begin
                    if (bready_i)               // bvalid_o held until bready_i
                        wstate_q <= W_IDLE;
                end

                default: wstate_q <= W_IDLE;
            endcase
        end
    end

    assign awready_o = rst_n_i && (wstate_q == W_IDLE);
    assign wready_o  = rst_n_i && (wstate_q == W_DATA);
    assign bvalid_o  = (wstate_q == W_RESP);
    assign bresp_o   = bresp_q;

    // -------------------------------------------------------------------------
    // Read channel FSM: IDLE (accept AR, capture data) -> RESP (R)
    // -------------------------------------------------------------------------
    typedef enum logic {R_IDLE, R_RESP} rstate_e;
    rstate_e rstate_q;

    // Combinational read decode of the address being accepted; the result is
    // registered at the accept edge so rdata_o is stable while rvalid_o holds.
    logic [RD_W-1:0] rd_wide;
    logic [1:0]      rresp_n;
    logic [11:0]     araddr_lo;

    assign araddr_lo = araddr_i[11:0];

    always_comb begin
        rd_wide = '0;
        rresp_n = RESP_OKAY;
        case (araddr_lo)
            ADDR_BEAT:      rd_wide = {{(RD_W-20){1'b0}}, beat_q};
            ADDR_START:     rd_wide = {{(RD_W-1){1'b0}}, start_q};
            ADDR_DONE:      rd_wide = {{(RD_W-1){1'b0}}, done_q};
            ADDR_WRITEBACK: rd_wide = {{(RD_W-1){1'b0}}, writeback_q};
            ADDR_ID:        rd_wide = {{(RD_W-32){1'b0}}, ID_VALUE};
            default: begin
                rd_wide = '0;
                rresp_n = RESP_SLVERR;
            end
        endcase
    end

    always_ff @(posedge clk_i or negedge rst_n_i) begin
        if (!rst_n_i) begin
            rstate_q <= R_IDLE;
            rdata_q  <= '0;
            rresp_q  <= RESP_OKAY;
        end else begin
            case (rstate_q)
                R_IDLE: begin
                    if (arvalid_i) begin        // arready_o is high in R_IDLE
                        rdata_q  <= rd_wide[DATA_WIDTH-1:0];
                        rresp_q  <= rresp_n;
                        rstate_q <= R_RESP;
                    end
                end

                R_RESP: begin
                    if (rready_i)               // rvalid_o held until rready_i
                        rstate_q <= R_IDLE;
                end

                default: rstate_q <= R_IDLE;
            endcase
        end
    end

    assign arready_o = rst_n_i && (rstate_q == R_IDLE);
    assign rvalid_o  = (rstate_q == R_RESP);
    assign rdata_o   = rdata_q;
    assign rresp_o   = rresp_q;

    // -------------------------------------------------------------------------
    // Hardware-facing outputs
    // -------------------------------------------------------------------------
    assign beat_o      = beat_q;
    assign start_o     = start_q;
    assign writeback_o = writeback_q;

endmodule
