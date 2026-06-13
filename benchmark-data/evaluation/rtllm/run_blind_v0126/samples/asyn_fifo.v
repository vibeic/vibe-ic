module asyn_fifo #(
    parameter WIDTH = 8,
    parameter DEPTH = 16
)(
    input              wclk,
    input              rclk,
    input              wrstn,
    input              rrstn,
    input              winc,
    input              rinc,
    input  [WIDTH-1:0] wdata,
    output             wfull,
    output             rempty,
    output [WIDTH-1:0] rdata
);

    localparam ADDR = $clog2(DEPTH);   // 4 for DEPTH=16

    // Binary pointers carry one extra MSB for wrap detection.
    reg  [ADDR:0] waddr_bin;   // write pointer (binary)
    reg  [ADDR:0] raddr_bin;   // read  pointer (binary)
    reg  [ADDR:0] wptr;        // write pointer (Gray)
    reg  [ADDR:0] rptr;        // read  pointer (Gray)

    // Two-stage synchronizers
    reg  [ADDR:0] wptr_buff, wptr_syn; // write Gray ptr sync'd into rclk domain
    reg  [ADDR:0] rptr_buff, rptr_syn; // read  Gray ptr sync'd into wclk domain

    wire           wen, ren;
    wire [ADDR-1:0] waddr, raddr;

    // Next-value binary pointers
    wire [ADDR:0] waddr_bin_next = waddr_bin + (wen ? 1'b1 : 1'b0);
    wire [ADDR:0] raddr_bin_next = raddr_bin + (ren ? 1'b1 : 1'b0);

    // Gray code of the next pointer values
    wire [ADDR:0] wgray_next = (waddr_bin_next >> 1) ^ waddr_bin_next;
    wire [ADDR:0] rgray_next = (raddr_bin_next >> 1) ^ raddr_bin_next;

    // Only write when not full, only read when not empty
    assign wen   = winc & ~wfull;
    assign ren   = rinc & ~rempty;
    assign waddr = waddr_bin[ADDR-1:0];
    assign raddr = raddr_bin[ADDR-1:0];

    // ----- Write pointer (wclk domain) -----
    always @(posedge wclk or negedge wrstn) begin
        if (!wrstn) begin
            waddr_bin <= {(ADDR+1){1'b0}};
            wptr      <= {(ADDR+1){1'b0}};
        end else begin
            waddr_bin <= waddr_bin_next;
            wptr      <= wgray_next;
        end
    end

    // ----- Read pointer (rclk domain) -----
    always @(posedge rclk or negedge rrstn) begin
        if (!rrstn) begin
            raddr_bin <= {(ADDR+1){1'b0}};
            rptr      <= {(ADDR+1){1'b0}};
        end else begin
            raddr_bin <= raddr_bin_next;
            rptr      <= rgray_next;
        end
    end

    // ----- Read pointer synchronizer into write clock domain -----
    always @(posedge wclk or negedge wrstn) begin
        if (!wrstn) begin
            rptr_buff <= {(ADDR+1){1'b0}};
            rptr_syn  <= {(ADDR+1){1'b0}};
        end else begin
            rptr_buff <= rptr;
            rptr_syn  <= rptr_buff;
        end
    end

    // ----- Write pointer synchronizer into read clock domain -----
    always @(posedge rclk or negedge rrstn) begin
        if (!rrstn) begin
            wptr_buff <= {(ADDR+1){1'b0}};
            wptr_syn  <= {(ADDR+1){1'b0}};
        end else begin
            wptr_buff <= wptr;
            wptr_syn  <= wptr_buff;
        end
    end

    // Full: write Gray ptr equals read Gray ptr with the two MSBs inverted.
    assign wfull  = (wptr == {~rptr_syn[ADDR:ADDR-1], rptr_syn[ADDR-2:0]});
    // Empty: read Gray ptr equals synchronized write Gray ptr.
    assign rempty = (rptr == wptr_syn);

    // ----- Dual-port RAM instance -----
    dual_port_RAM #(.WIDTH(WIDTH), .DEPTH(DEPTH)) u_ram (
        .wclk  (wclk),
        .wenc  (wen),
        .waddr (waddr),
        .wdata (wdata),
        .rclk  (rclk),
        .renc  (ren),
        .raddr (raddr),
        .rdata (rdata)
    );

endmodule


module dual_port_RAM #(
    parameter WIDTH = 8,
    parameter DEPTH = 16
)(
    input                      wclk,
    input                      wenc,
    input  [$clog2(DEPTH)-1:0] waddr,
    input  [WIDTH-1:0]         wdata,
    input                      rclk,
    input                      renc,
    input  [$clog2(DEPTH)-1:0] raddr,
    output reg [WIDTH-1:0]     rdata
);

    reg [WIDTH-1:0] RAM_MEM [0:DEPTH-1];

    always @(posedge wclk) begin
        if (wenc)
            RAM_MEM[waddr] <= wdata;
    end

    always @(posedge rclk) begin
        if (renc)
            rdata <= RAM_MEM[raddr];
    end

endmodule
