`timescale 1ns / 1ps
//-----------------------------------------------------------------------------
// precision_counter_axi
//
// AXI4-Lite slave managing a high-precision countdown counter.
//
// Register map (byte offsets):
//   0x00  slv_reg_ctl         RW  control (bit0: 1=start, 0=stop). Any write
//                                 to this register clears slv_reg_t to zero.
//   0x0C  ap_done status      RO  returns 1 when the countdown is complete
//                                 (slv_reg_v == 0), otherwise 0.
//   0x10  slv_reg_t           RW  elapsed-time counter; increments by 1 every
//                                 clock while the counter is running and the
//                                 countdown has finished (slv_reg_v == 0).
//   0x20  slv_reg_v           RW  countdown value; decrements by 1 every clock
//                                 while running; a write updates it even while
//                                 the counter is running.
//   0x24  slv_reg_irq_mask    RW  bit0 enables interrupt generation.
//   0x28  slv_reg_irq_thresh  RW  countdown value at which irq is raised.
//
// Responses: 2'b00 (OKAY) for decoded addresses, 2'b10 (SLVERR) for accesses
// outside the implemented map (such writes are ignored). Partial (byte-strobe)
// writes complete with OKAY and update only the strobed bytes.
//-----------------------------------------------------------------------------
module precision_counter_axi #(
    parameter integer C_S_AXI_DATA_WIDTH = 32,
    parameter integer C_S_AXI_ADDR_WIDTH = 8
) (
    // clock / reset
    input  wire                                axi_aclk,
    input  wire                                axi_aresetn,

    // AXI write address channel
    input  wire [C_S_AXI_ADDR_WIDTH-1:0]       axi_awaddr,
    input  wire                                axi_awvalid,
    output wire                                axi_awready,

    // AXI write data channel
    input  wire [C_S_AXI_DATA_WIDTH-1:0]       axi_wdata,
    input  wire [(C_S_AXI_DATA_WIDTH/8)-1:0]   axi_wstrb,
    input  wire                                axi_wvalid,
    output wire                                axi_wready,

    // AXI write response channel
    output wire [1:0]                          axi_bresp,
    output wire                                axi_bvalid,
    input  wire                                axi_bready,

    // AXI read address channel
    input  wire [C_S_AXI_ADDR_WIDTH-1:0]       axi_araddr,
    input  wire                                axi_arvalid,
    output wire                                axi_arready,

    // AXI read data channel
    output wire [C_S_AXI_DATA_WIDTH-1:0]       axi_rdata,
    output wire [1:0]                          axi_rresp,
    output wire                                axi_rvalid,
    input  wire                                axi_rready,

    // control outputs
    output wire                                axi_ap_done,
    output wire                                irq
);

    //-------------------------------------------------------------------------
    // local parameters
    //-------------------------------------------------------------------------
    localparam [1:0] RESP_OKAY   = 2'b00;
    localparam [1:0] RESP_SLVERR = 2'b10;

    localparam [C_S_AXI_ADDR_WIDTH-1:0] ADDR_CTL        = 'h00;
    localparam [C_S_AXI_ADDR_WIDTH-1:0] ADDR_DONE       = 'h0C;
    localparam [C_S_AXI_ADDR_WIDTH-1:0] ADDR_T          = 'h10;
    localparam [C_S_AXI_ADDR_WIDTH-1:0] ADDR_V          = 'h20;
    localparam [C_S_AXI_ADDR_WIDTH-1:0] ADDR_IRQ_MASK   = 'h24;
    localparam [C_S_AXI_ADDR_WIDTH-1:0] ADDR_IRQ_THRESH = 'h28;

    //-------------------------------------------------------------------------
    // AXI4-Lite interface registers
    //-------------------------------------------------------------------------
    reg                              axi_awready_q;
    reg                              axi_wready_q;
    reg  [1:0]                       axi_bresp_q;
    reg                              axi_bvalid_q;
    reg                              axi_arready_q;
    reg  [C_S_AXI_DATA_WIDTH-1:0]    axi_rdata_q;
    reg  [1:0]                       axi_rresp_q;
    reg                              axi_rvalid_q;
    reg  [C_S_AXI_ADDR_WIDTH-1:0]    axi_awaddr_q;
    reg  [C_S_AXI_ADDR_WIDTH-1:0]    axi_araddr_q;
    reg                              aw_en;

    //-------------------------------------------------------------------------
    // user registers (names per the specification)
    //-------------------------------------------------------------------------
    reg [C_S_AXI_DATA_WIDTH-1:0] slv_reg_ctl;
    reg [C_S_AXI_DATA_WIDTH-1:0] slv_reg_t;
    reg [C_S_AXI_DATA_WIDTH-1:0] slv_reg_v;
    reg [C_S_AXI_DATA_WIDTH-1:0] slv_reg_irq_mask;
    reg [C_S_AXI_DATA_WIDTH-1:0] slv_reg_irq_thresh;

    assign axi_awready = axi_awready_q;
    assign axi_wready  = axi_wready_q;
    assign axi_bresp   = axi_bresp_q;
    assign axi_bvalid  = axi_bvalid_q;
    assign axi_arready = axi_arready_q;
    assign axi_rdata   = axi_rdata_q;
    assign axi_rresp   = axi_rresp_q;
    assign axi_rvalid  = axi_rvalid_q;

    //-------------------------------------------------------------------------
    // write address channel: accept the address when both the address and the
    // data are valid; latch the address for the decode.
    //-------------------------------------------------------------------------
    always @(posedge axi_aclk or negedge axi_aresetn) begin
        if (!axi_aresetn) begin
            axi_awready_q <= 1'b0;
            axi_awaddr_q  <= {C_S_AXI_ADDR_WIDTH{1'b0}};
            aw_en         <= 1'b1;
        end else begin
            if (!axi_awready_q && axi_awvalid && axi_wvalid && aw_en) begin
                axi_awready_q <= 1'b1;
                axi_awaddr_q  <= axi_awaddr;
                aw_en         <= 1'b0;
            end else if (axi_bvalid_q && axi_bready) begin
                axi_awready_q <= 1'b0;
                aw_en         <= 1'b1;
            end else begin
                axi_awready_q <= 1'b0;
            end
        end
    end

    //-------------------------------------------------------------------------
    // write data channel
    //-------------------------------------------------------------------------
    always @(posedge axi_aclk or negedge axi_aresetn) begin
        if (!axi_aresetn) begin
            axi_wready_q <= 1'b0;
        end else begin
            if (!axi_wready_q && axi_wvalid && axi_awvalid && aw_en)
                axi_wready_q <= 1'b1;
            else
                axi_wready_q <= 1'b0;
        end
    end

    // register write strobe (single cycle)
    wire slv_reg_wren = axi_wready_q && axi_wvalid && axi_awready_q && axi_awvalid;

    // decode of the LATCHED write address
    wire write_addr_hit = (axi_awaddr_q == ADDR_CTL)      ||
                          (axi_awaddr_q == ADDR_T)        ||
                          (axi_awaddr_q == ADDR_V)        ||
                          (axi_awaddr_q == ADDR_IRQ_MASK) ||
                          (axi_awaddr_q == ADDR_IRQ_THRESH);

    //-------------------------------------------------------------------------
    // control / mask / threshold registers (byte-strobed writes)
    //-------------------------------------------------------------------------
    integer byte_index_c;
    always @(posedge axi_aclk or negedge axi_aresetn) begin
        if (!axi_aresetn) begin
            slv_reg_ctl        <= {C_S_AXI_DATA_WIDTH{1'b0}};
            slv_reg_irq_mask   <= {C_S_AXI_DATA_WIDTH{1'b0}};
            slv_reg_irq_thresh <= {C_S_AXI_DATA_WIDTH{1'b0}};
        end else if (slv_reg_wren) begin
            case (axi_awaddr_q)
                ADDR_CTL: begin
                    for (byte_index_c = 0; byte_index_c < C_S_AXI_DATA_WIDTH/8; byte_index_c = byte_index_c + 1)
                        if (axi_wstrb[byte_index_c])
                            slv_reg_ctl[byte_index_c*8 +: 8] <= axi_wdata[byte_index_c*8 +: 8];
                end
                ADDR_IRQ_MASK: begin
                    for (byte_index_c = 0; byte_index_c < C_S_AXI_DATA_WIDTH/8; byte_index_c = byte_index_c + 1)
                        if (axi_wstrb[byte_index_c])
                            slv_reg_irq_mask[byte_index_c*8 +: 8] <= axi_wdata[byte_index_c*8 +: 8];
                end
                ADDR_IRQ_THRESH: begin
                    for (byte_index_c = 0; byte_index_c < C_S_AXI_DATA_WIDTH/8; byte_index_c = byte_index_c + 1)
                        if (axi_wstrb[byte_index_c])
                            slv_reg_irq_thresh[byte_index_c*8 +: 8] <= axi_wdata[byte_index_c*8 +: 8];
                end
                default: ; // undefined addresses are ignored
            endcase
        end
    end

    //-------------------------------------------------------------------------
    // countdown register slv_reg_v:
    //  - a software write updates it (even while the counter is running)
    //  - while running (slv_reg_ctl[0]) it decrements by 1 each clock until 0
    //  - when stopped it retains its current value
    //-------------------------------------------------------------------------
    integer byte_index_v;
    always @(posedge axi_aclk or negedge axi_aresetn) begin
        if (!axi_aresetn) begin
            slv_reg_v <= {C_S_AXI_DATA_WIDTH{1'b0}};
        end else if (slv_reg_wren && (axi_awaddr_q == ADDR_V)) begin
            for (byte_index_v = 0; byte_index_v < C_S_AXI_DATA_WIDTH/8; byte_index_v = byte_index_v + 1)
                if (axi_wstrb[byte_index_v])
                    slv_reg_v[byte_index_v*8 +: 8] <= axi_wdata[byte_index_v*8 +: 8];
        end else if (slv_reg_ctl[0] && (slv_reg_v != {C_S_AXI_DATA_WIDTH{1'b0}})) begin
            slv_reg_v <= slv_reg_v - 1'b1;
        end
    end

    //-------------------------------------------------------------------------
    // elapsed time register slv_reg_t:
    //  - any write to the control register clears it to zero
    //  - a software write to 0x10 updates it
    //  - while running and the countdown is finished (slv_reg_v == 0) it
    //    increments by 1 every clock cycle
    //-------------------------------------------------------------------------
    integer byte_index_t;
    always @(posedge axi_aclk or negedge axi_aresetn) begin
        if (!axi_aresetn) begin
            slv_reg_t <= {C_S_AXI_DATA_WIDTH{1'b0}};
        end else if (slv_reg_wren && (axi_awaddr_q == ADDR_CTL)) begin
            slv_reg_t <= {C_S_AXI_DATA_WIDTH{1'b0}};
        end else if (slv_reg_wren && (axi_awaddr_q == ADDR_T)) begin
            for (byte_index_t = 0; byte_index_t < C_S_AXI_DATA_WIDTH/8; byte_index_t = byte_index_t + 1)
                if (axi_wstrb[byte_index_t])
                    slv_reg_t[byte_index_t*8 +: 8] <= axi_wdata[byte_index_t*8 +: 8];
        end else if (slv_reg_ctl[0] && (slv_reg_v == {C_S_AXI_DATA_WIDTH{1'b0}})) begin
            slv_reg_t <= slv_reg_t + 1'b1;
        end
    end

    //-------------------------------------------------------------------------
    // write response channel: OKAY for decoded addresses, SLVERR otherwise;
    // bvalid is held until the master acknowledges with bready.
    //-------------------------------------------------------------------------
    always @(posedge axi_aclk or negedge axi_aresetn) begin
        if (!axi_aresetn) begin
            axi_bvalid_q <= 1'b0;
            axi_bresp_q  <= RESP_OKAY;
        end else begin
            if (slv_reg_wren && !axi_bvalid_q) begin
                axi_bvalid_q <= 1'b1;
                axi_bresp_q  <= write_addr_hit ? RESP_OKAY : RESP_SLVERR;
            end else if (axi_bready && axi_bvalid_q) begin
                axi_bvalid_q <= 1'b0;
            end
        end
    end

    //-------------------------------------------------------------------------
    // read address channel: accept and latch the read address.
    //-------------------------------------------------------------------------
    always @(posedge axi_aclk or negedge axi_aresetn) begin
        if (!axi_aresetn) begin
            axi_arready_q <= 1'b0;
            axi_araddr_q  <= {C_S_AXI_ADDR_WIDTH{1'b0}};
        end else begin
            if (!axi_arready_q && axi_arvalid) begin
                axi_arready_q <= 1'b1;
                axi_araddr_q  <= axi_araddr;
            end else begin
                axi_arready_q <= 1'b0;
            end
        end
    end

    wire slv_reg_rden = axi_arready_q && axi_arvalid && !axi_rvalid_q;

    // decode of the LATCHED read address
    wire read_addr_hit = (axi_araddr_q == ADDR_CTL)      ||
                         (axi_araddr_q == ADDR_DONE)     ||
                         (axi_araddr_q == ADDR_T)        ||
                         (axi_araddr_q == ADDR_V)        ||
                         (axi_araddr_q == ADDR_IRQ_MASK) ||
                         (axi_araddr_q == ADDR_IRQ_THRESH);

    reg [C_S_AXI_DATA_WIDTH-1:0] reg_data_out;
    always @(*) begin
        case (axi_araddr_q)
            ADDR_CTL:        reg_data_out = slv_reg_ctl;
            ADDR_DONE:       reg_data_out = {{(C_S_AXI_DATA_WIDTH-1){1'b0}}, axi_ap_done};
            ADDR_T:          reg_data_out = slv_reg_t;
            ADDR_V:          reg_data_out = slv_reg_v;
            ADDR_IRQ_MASK:   reg_data_out = slv_reg_irq_mask;
            ADDR_IRQ_THRESH: reg_data_out = slv_reg_irq_thresh;
            default:         reg_data_out = {C_S_AXI_DATA_WIDTH{1'b0}};
        endcase
    end

    //-------------------------------------------------------------------------
    // read data channel: rvalid/rdata are held until the master acknowledges
    // with rready; SLVERR (and zero data) for undecoded addresses.
    //-------------------------------------------------------------------------
    always @(posedge axi_aclk or negedge axi_aresetn) begin
        if (!axi_aresetn) begin
            axi_rvalid_q <= 1'b0;
            axi_rresp_q  <= RESP_OKAY;
            axi_rdata_q  <= {C_S_AXI_DATA_WIDTH{1'b0}};
        end else begin
            if (slv_reg_rden) begin
                axi_rvalid_q <= 1'b1;
                axi_rresp_q  <= read_addr_hit ? RESP_OKAY : RESP_SLVERR;
                axi_rdata_q  <= read_addr_hit ? reg_data_out : {C_S_AXI_DATA_WIDTH{1'b0}};
            end else if (axi_rvalid_q && axi_rready) begin
                axi_rvalid_q <= 1'b0;
            end
        end
    end

    //-------------------------------------------------------------------------
    // control outputs
    //-------------------------------------------------------------------------
    // countdown complete when the countdown value has reached zero
    assign axi_ap_done = (slv_reg_v == {C_S_AXI_DATA_WIDTH{1'b0}});

    // interrupt: asserted while the counter is running, interrupts are enabled
    // and the countdown value matches the threshold; automatically cleared
    // when the countdown stops, the threshold condition is no longer met, or
    // reset is asserted.
    assign irq = slv_reg_ctl[0] && slv_reg_irq_mask[0] &&
                 (slv_reg_v == slv_reg_irq_thresh);

endmodule
