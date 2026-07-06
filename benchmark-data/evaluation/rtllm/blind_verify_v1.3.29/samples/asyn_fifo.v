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
        if (wenc) begin
            RAM_MEM[waddr] <= wdata;
        end
    end

    // spec declares rdata as `output reg` -> registered (one-cycle-latency) read
    always @(posedge rclk) begin
        if (renc) begin
            rdata <= RAM_MEM[raddr];
        end
    end

endmodule


module asyn_fifo #(
    parameter DEPTH = 16,
    parameter WIDTH = 8
) (
    input  wire             wclk,
    input  wire             rclk,
    input  wire             wrstn,
    input  wire             rrstn,
    input  wire             winc,
    input  wire             rinc,
    input  wire [WIDTH-1:0] wdata,
    output wire             wfull,
    output wire             rempty,
    output wire [WIDTH-1:0] rdata
);

    localparam AW = $clog2(DEPTH);
    localparam PW = AW + 1;

    // ---- binary + gray pointers ----
    reg [PW-1:0] waddr_bin;
    reg [PW-1:0] wptr;      // gray write pointer
    reg [PW-1:0] raddr_bin;
    reg [PW-1:0] rptr;      // gray read pointer

    // 2-stage synchronizers across clock domains
    reg [PW-1:0] rptr_buff1, rptr_syn;   // read ptr synced into write domain
    reg [PW-1:0] wptr_buff1, wptr_syn;   // write ptr synced into read domain

    wire [AW-1:0] waddr = waddr_bin[AW-1:0];
    wire [AW-1:0] raddr = raddr_bin[AW-1:0];

    wire wenc = winc && !wfull;
    wire renc = rinc && !rempty;

    // ---- write-clock domain: write pointer (binary + gray) ----
    always @(posedge wclk or negedge wrstn) begin
        if (!wrstn) begin
            waddr_bin <= {PW{1'b0}};
            wptr      <= {PW{1'b0}};
        end else if (wenc) begin
            waddr_bin <= waddr_bin + {{(PW-1){1'b0}}, 1'b1};
            wptr      <= ((waddr_bin + {{(PW-1){1'b0}}, 1'b1}) >> 1) ^
                          (waddr_bin + {{(PW-1){1'b0}}, 1'b1});
        end
    end

    // read pointer synchronizer (2FF) into the write clock domain
    always @(posedge wclk or negedge wrstn) begin
        if (!wrstn) begin
            rptr_buff1 <= {PW{1'b0}};
            rptr_syn   <= {PW{1'b0}};
        end else begin
            rptr_buff1 <= rptr;
            rptr_syn   <= rptr_buff1;
        end
    end

    // full: write ptr equals read ptr with the top two bits inverted, rest same
    assign wfull = (wptr == {~rptr_syn[PW-1], ~rptr_syn[PW-2], rptr_syn[PW-3:0]});

    // ---- read-clock domain: read pointer (binary + gray) ----
    always @(posedge rclk or negedge rrstn) begin
        if (!rrstn) begin
            raddr_bin <= {PW{1'b0}};
            rptr      <= {PW{1'b0}};
        end else if (renc) begin
            raddr_bin <= raddr_bin + {{(PW-1){1'b0}}, 1'b1};
            rptr      <= ((raddr_bin + {{(PW-1){1'b0}}, 1'b1}) >> 1) ^
                          (raddr_bin + {{(PW-1){1'b0}}, 1'b1});
        end
    end

    // write pointer synchronizer (2FF) into the read clock domain
    always @(posedge rclk or negedge rrstn) begin
        if (!rrstn) begin
            wptr_buff1 <= {PW{1'b0}};
            wptr_syn   <= {PW{1'b0}};
        end else begin
            wptr_buff1 <= wptr;
            wptr_syn   <= wptr_buff1;
        end
    end

    // empty: read ptr equals synced write ptr (exact gray equality)
    assign rempty = (rptr == wptr_syn);

    dual_port_RAM #(
        .DEPTH (DEPTH),
        .WIDTH (WIDTH)
    ) u_ram (
        .wclk  (wclk),
        .wenc  (wenc),
        .waddr (waddr),
        .wdata (wdata),
        .rclk  (rclk),
        .renc  (renc),
        .raddr (raddr),
        .rdata (rdata)
    );

endmodule
