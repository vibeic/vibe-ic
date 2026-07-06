`timescale 1ns/1ns

// Dual-port RAM submodule used for FIFO storage.
// rdata is a registered ("output reg") read, sampled on posedge rclk,
// per the spec's own port declaration.
module dual_port_RAM #(
    parameter DEPTH = 16,
    parameter WIDTH = 8
) (
    input  wire                        wclk,
    input  wire                        wenc,
    input  wire [$clog2(DEPTH)-1:0]    waddr,
    input  wire [WIDTH-1:0]            wdata,
    input  wire                        rclk,
    input  wire                        renc,
    input  wire [$clog2(DEPTH)-1:0]    raddr,
    output reg  [WIDTH-1:0]            rdata
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


module asyn_fifo #(
    parameter WIDTH = 8,
    parameter DEPTH = 16
) (
    input  wire             wclk,
    input  wire             rclk,
    input  wire             wrstn,
    input  wire             rrstn,
    input  wire             winc,
    input  wire             rinc,
    input  wire [WIDTH-1:0] wdata,
    output wire              wfull,
    output wire              rempty,
    output wire [WIDTH-1:0]  rdata
);

localparam ADDR_WIDTH = $clog2(DEPTH);

reg [ADDR_WIDTH:0] waddr_bin;
reg [ADDR_WIDTH:0] raddr_bin;

always @(posedge wclk or negedge wrstn) begin
    if (!wrstn)
        waddr_bin <= {ADDR_WIDTH+1{1'b0}};
    else if (!wfull && winc)
        waddr_bin <= waddr_bin + 1'b1;
end

always @(posedge rclk or negedge rrstn) begin
    if (!rrstn)
        raddr_bin <= {ADDR_WIDTH+1{1'b0}};
    else if (!rempty && rinc)
        raddr_bin <= raddr_bin + 1'b1;
end

// Binary-to-Gray conversion is combinational off the *current* binary
// pointer; the Gray pointer register (wptr/rptr) is updated in a SEPARATE
// always block on the same edge, so it registers the Gray code of the
// PRE-increment binary pointer -- the Gray pointer trails the binary
// pointer by exactly one clock (canonical Cummings async-FIFO structure).
wire [ADDR_WIDTH:0] waddr_gray = waddr_bin ^ (waddr_bin >> 1);
wire [ADDR_WIDTH:0] raddr_gray = raddr_bin ^ (raddr_bin >> 1);

reg [ADDR_WIDTH:0] wptr;
reg [ADDR_WIDTH:0] rptr;

always @(posedge wclk or negedge wrstn) begin
    if (!wrstn)
        wptr <= {ADDR_WIDTH+1{1'b0}};
    else
        wptr <= waddr_gray;
end

always @(posedge rclk or negedge rrstn) begin
    if (!rrstn)
        rptr <= {ADDR_WIDTH+1{1'b0}};
    else
        rptr <= raddr_gray;
end

// two-stage synchronizers across clock domains
reg [ADDR_WIDTH:0] rptr_buff, rptr_syn;
reg [ADDR_WIDTH:0] wptr_buff, wptr_syn;

always @(posedge wclk or negedge wrstn) begin
    if (!wrstn) begin
        rptr_buff <= {ADDR_WIDTH+1{1'b0}};
        rptr_syn  <= {ADDR_WIDTH+1{1'b0}};
    end else begin
        rptr_buff <= rptr;
        rptr_syn  <= rptr_buff;
    end
end

always @(posedge rclk or negedge rrstn) begin
    if (!rrstn) begin
        wptr_buff <= {ADDR_WIDTH+1{1'b0}};
        wptr_syn  <= {ADDR_WIDTH+1{1'b0}};
    end else begin
        wptr_buff <= wptr;
        wptr_syn  <= wptr_buff;
    end
end

// full: write pointer equals read pointer with the top two bits inverted
assign wfull  = (wptr == {~rptr_syn[ADDR_WIDTH:ADDR_WIDTH-1], rptr_syn[ADDR_WIDTH-2:0]});
// empty: exact Gray-pointer equality
assign rempty = (rptr == wptr_syn);

wire wen = winc & !wfull;
wire ren = rinc & !rempty;
wire [ADDR_WIDTH-1:0] waddr = waddr_bin[ADDR_WIDTH-1:0];
wire [ADDR_WIDTH-1:0] raddr = raddr_bin[ADDR_WIDTH-1:0];

dual_port_RAM #(.DEPTH(DEPTH), .WIDTH(WIDTH)) u_ram (
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
