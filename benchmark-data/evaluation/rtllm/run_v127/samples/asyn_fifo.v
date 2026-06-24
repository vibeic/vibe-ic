// asyn_fifo — configurable asynchronous (dual-clock) FIFO.
// Canonical Cummings architecture: binary pointer (ADDR_W+1 bits) registered;
// Gray pointer derived from it; 2-stage synchronizers cross each pointer into the
// opposite clock domain; FULL = write-Gray vs sync-read-Gray with the top TWO bits
// inverted, EMPTY = read-Gray == sync-write-Gray. RAM read is REGISTERED per the
// spec's `output reg rdata` declaration.
module dual_port_RAM #(
    parameter WIDTH = 8,
    parameter DEPTH = 16
)(
    input  wire                          wclk,
    input  wire                          wenc,
    input  wire [$clog2(DEPTH)-1:0]      waddr,
    input  wire [WIDTH-1:0]              wdata,
    input  wire                          rclk,
    input  wire                          renc,
    input  wire [$clog2(DEPTH)-1:0]      raddr,
    output reg  [WIDTH-1:0]              rdata
);
    reg [WIDTH-1:0] RAM_MEM [0:DEPTH-1];

    always @(posedge wclk) begin
        if (wenc)
            RAM_MEM[waddr] <= wdata;
    end

    always @(posedge rclk) begin
        if (renc)
            rdata <= RAM_MEM[raddr];   // registered read
    end
endmodule

module asyn_fifo #(
    parameter WIDTH = 8,
    parameter DEPTH = 16
)(
    input  wire              wclk,
    input  wire              rclk,
    input  wire              wrstn,
    input  wire              rrstn,
    input  wire              winc,
    input  wire              rinc,
    input  wire [WIDTH-1:0]  wdata,
    output wire              wfull,
    output wire              rempty,
    output wire [WIDTH-1:0]  rdata
);
    localparam ADDR_W = $clog2(DEPTH);

    // binary pointers carry one extra MSB to distinguish full from empty
    reg  [ADDR_W:0] waddr_bin, raddr_bin;
    reg  [ADDR_W:0] wptr, rptr;             // registered Gray pointers
    reg  [ADDR_W:0] wptr_buff, rptr_buff;   // 1st synchronizer stage
    reg  [ADDR_W:0] wptr_syn,  rptr_syn;    // 2nd synchronizer stage

    wire [ADDR_W:0] waddr_bin_next = waddr_bin + (winc & ~wfull);
    wire [ADDR_W:0] raddr_bin_next = raddr_bin + (rinc & ~rempty);

    // binary -> Gray
    wire [ADDR_W:0] wgray_next = waddr_bin_next ^ (waddr_bin_next >> 1);
    wire [ADDR_W:0] rgray_next = raddr_bin_next ^ (raddr_bin_next >> 1);

    wire            wen = winc & ~wfull;
    wire            ren = rinc & ~rempty;

    // ----- write domain -----
    always @(posedge wclk or negedge wrstn) begin
        if (!wrstn) begin
            waddr_bin <= 0;
            wptr      <= 0;
        end else begin
            waddr_bin <= waddr_bin_next;
            wptr      <= wgray_next;
        end
    end

    // ----- read domain -----
    always @(posedge rclk or negedge rrstn) begin
        if (!rrstn) begin
            raddr_bin <= 0;
            rptr      <= 0;
        end else begin
            raddr_bin <= raddr_bin_next;
            rptr      <= rgray_next;
        end
    end

    // ----- synchronize read pointer into write clock domain -----
    always @(posedge wclk or negedge wrstn) begin
        if (!wrstn) begin
            rptr_buff <= 0;
            rptr_syn  <= 0;
        end else begin
            rptr_buff <= rptr;
            rptr_syn  <= rptr_buff;
        end
    end

    // ----- synchronize write pointer into read clock domain -----
    always @(posedge rclk or negedge rrstn) begin
        if (!rrstn) begin
            wptr_buff <= 0;
            wptr_syn  <= 0;
        end else begin
            wptr_buff <= wptr;
            wptr_syn  <= wptr_buff;
        end
    end

    // FULL: wptr equals rptr_syn with the top two bits inverted
    assign wfull  = (wptr == {~rptr_syn[ADDR_W:ADDR_W-1], rptr_syn[ADDR_W-2:0]});
    // EMPTY: read Gray pointer equals synchronized write Gray pointer
    assign rempty = (rptr == wptr_syn);

    // dual-port RAM (lower ADDR_W bits of the binary pointer index memory)
    dual_port_RAM #(.WIDTH(WIDTH), .DEPTH(DEPTH)) u_ram (
        .wclk  (wclk),
        .wenc  (wen),
        .waddr (waddr_bin[ADDR_W-1:0]),
        .wdata (wdata),
        .rclk  (rclk),
        .renc  (ren),
        .raddr (raddr_bin[ADDR_W-1:0]),
        .rdata (rdata)
    );
endmodule
