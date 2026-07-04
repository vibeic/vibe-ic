module axi_register #(
    parameter ADDR_WIDTH = 32,
    parameter DATA_WIDTH = 32
)(
    input                          clk_i,
    input                          rst_n_i,        // active-low async reset

    // Write address / data
    input      [ADDR_WIDTH-1:0]    awaddr_i,
    input                          awvalid_i,
    output reg                     awready_o,
    input      [DATA_WIDTH-1:0]    wdata_i,
    input                          wvalid_i,
    input      [(DATA_WIDTH/8)-1:0] wstrb_i,
    output reg                     wready_o,
    // Write response
    output reg [1:0]               bresp_o,
    output reg                     bvalid_o,
    input                          bready_i,

    // Read address / data
    input      [ADDR_WIDTH-1:0]    araddr_i,
    input                          arvalid_i,
    output reg                     arready_o,
    output reg [DATA_WIDTH-1:0]    rdata_o,
    output reg                     rvalid_o,
    output reg [1:0]               rresp_o,
    input                          rready_i,

    // Hardware-side
    input                          done_i,
    output reg [19:0]              beat_o,
    output reg                     start_o,
    output reg                     writeback_o
);

    localparam [1:0] RESP_OKAY   = 2'b00;
    localparam [1:0] RESP_SLVERR = 2'b10;

    // Register offsets (decoded on the low address bits)
    localparam [11:0] OFF_BEAT = 12'h100;
    localparam [11:0] OFF_STRT = 12'h200;
    localparam [11:0] OFF_DONE = 12'h300;
    localparam [11:0] OFF_WB   = 12'h400;
    localparam [11:0] OFF_ID   = 12'h500;

    reg [ADDR_WIDTH-1:0] awaddr_q;
    reg [ADDR_WIDTH-1:0] araddr_q;
    reg                  aw_en;
    reg                  done_status;

    wire full_strb = &wstrb_i;

    // ---------------- Write address handshake ----------------
    always @(posedge clk_i or negedge rst_n_i) begin
        if (!rst_n_i) begin
            awready_o <= 1'b0;
            awaddr_q  <= {ADDR_WIDTH{1'b0}};
            aw_en     <= 1'b1;
        end else begin
            if (!awready_o && awvalid_i && wvalid_i && aw_en) begin
                awready_o <= 1'b1;
                awaddr_q  <= awaddr_i;
                aw_en     <= 1'b0;
            end else if (bvalid_o && bready_i) begin
                awready_o <= 1'b0;
                aw_en     <= 1'b1;
            end else begin
                awready_o <= 1'b0;
            end
        end
    end

    // ---------------- Write data handshake ----------------
    always @(posedge clk_i or negedge rst_n_i) begin
        if (!rst_n_i)
            wready_o <= 1'b0;
        else if (!wready_o && wvalid_i && awvalid_i && aw_en)
            wready_o <= 1'b1;
        else
            wready_o <= 1'b0;
    end

    wire wr_fire = awready_o && awvalid_i && wready_o && wvalid_i;

    // ---------------- Register update + write response ----------------
    always @(posedge clk_i or negedge rst_n_i) begin
        if (!rst_n_i) begin
            beat_o      <= 20'd0;
            start_o     <= 1'b0;
            writeback_o <= 1'b0;
            done_status <= 1'b0;
            bvalid_o    <= 1'b0;
            bresp_o     <= RESP_OKAY;
        end else begin
            // hardware completion sets the done status
            if (done_i)
                done_status <= 1'b1;

            if (wr_fire) begin
                bvalid_o <= 1'b1;
                case (awaddr_q[11:0])
                    OFF_BEAT: begin
                        if (full_strb) beat_o <= wdata_i[19:0];
                        bresp_o <= RESP_OKAY;
                    end
                    OFF_STRT: begin
                        if (full_strb) start_o <= wdata_i[0];
                        bresp_o <= RESP_OKAY;
                    end
                    OFF_DONE: begin
                        // writing LSB=1 clears the done status
                        if (wstrb_i[0] && wdata_i[0]) done_status <= 1'b0;
                        bresp_o <= RESP_OKAY;
                    end
                    OFF_WB: begin
                        if (full_strb) writeback_o <= wdata_i[0];
                        bresp_o <= RESP_OKAY;
                    end
                    OFF_ID:  bresp_o <= RESP_SLVERR;  // read-only
                    default: bresp_o <= RESP_SLVERR;  // invalid address
                endcase
            end else if (bvalid_o && bready_i) begin
                bvalid_o <= 1'b0;
            end
        end
    end

    // ---------------- Read channel ----------------
    always @(posedge clk_i or negedge rst_n_i) begin
        if (!rst_n_i) begin
            arready_o <= 1'b0;
            araddr_q  <= {ADDR_WIDTH{1'b0}};
            rvalid_o  <= 1'b0;
            rdata_o   <= {DATA_WIDTH{1'b0}};
            rresp_o   <= RESP_OKAY;
        end else begin
            if (!arready_o && arvalid_i && !rvalid_o) begin
                arready_o <= 1'b1;
                araddr_q  <= araddr_i;
            end else begin
                arready_o <= 1'b0;
            end

            if (arready_o && arvalid_i && !rvalid_o) begin
                rvalid_o <= 1'b1;
                case (araddr_q[11:0])
                    OFF_BEAT: begin rdata_o <= beat_o;             rresp_o <= RESP_OKAY;   end
                    OFF_STRT: begin rdata_o <= start_o;            rresp_o <= RESP_OKAY;   end
                    OFF_DONE: begin rdata_o <= done_status;        rresp_o <= RESP_OKAY;   end
                    OFF_WB:   begin rdata_o <= writeback_o;        rresp_o <= RESP_OKAY;   end
                    OFF_ID:   begin rdata_o <= 32'h0001_0001;      rresp_o <= RESP_OKAY;   end
                    default:  begin rdata_o <= {DATA_WIDTH{1'b0}}; rresp_o <= RESP_SLVERR; end
                endcase
            end else if (rvalid_o && rready_i) begin
                rvalid_o <= 1'b0;
            end
        end
    end

endmodule
