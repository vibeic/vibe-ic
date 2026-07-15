//======================================================================
// Asynchronous (dual-clock) FIFO
//   - configurable DATA_WIDTH and DEPTH
//   - (ADDR_WIDTH+1)-bit Gray-coded write/read pointers
//   - 2-flop cross-clock synchronizers for each pointer
//   - empty : local read gray == synchronized write gray
//   - full  : local write gray == synchronized read gray with the
//             top TWO bits inverted (Gray-domain form of "MSB differs,
//             all lower bits equal")
//   - combinational read data (r_data is a plain wire output)
//======================================================================
module asynchronous_fifo #(
    parameter DATA_WIDTH = 8,
    parameter DEPTH      = 16
)(
    input  wire                  w_clk,
    input  wire                  w_rst,
    input  wire                  w_inc,
    input  wire [DATA_WIDTH-1:0] w_data,
    input  wire                  r_clk,
    input  wire                  r_rst,
    input  wire                  r_inc,
    output wire                  w_full,
    output wire                  r_empty,
    output wire [DATA_WIDTH-1:0] r_data
);

    // Address width; pointers carry one extra MSB to detect wrap/overflow
    localparam ADDR_WIDTH = $clog2(DEPTH);

    // Storage
    reg [DATA_WIDTH-1:0] mem [0:DEPTH-1];

    //------------------------------------------------------------------
    // Write clock domain: binary + gray pointer, full flag
    //------------------------------------------------------------------
    reg  [ADDR_WIDTH:0]   w_bin, w_gray;
    wire [ADDR_WIDTH:0]   w_bin_next  = w_bin + (w_inc & ~w_full);
    wire [ADDR_WIDTH:0]   w_gray_next = (w_bin_next >> 1) ^ w_bin_next;
    wire [ADDR_WIDTH-1:0] w_addr      = w_bin[ADDR_WIDTH-1:0];

    // synchronized read pointer (into write domain)
    reg  [ADDR_WIDTH:0]   wq1_r_gray, wq2_r_gray;

    reg  w_full_r;
    wire w_full_next = (w_gray_next ==
                        {~wq2_r_gray[ADDR_WIDTH:ADDR_WIDTH-1],
                          wq2_r_gray[ADDR_WIDTH-2:0]});

    always @(posedge w_clk or posedge w_rst) begin
        if (w_rst) begin
            w_bin  <= {(ADDR_WIDTH+1){1'b0}};
            w_gray <= {(ADDR_WIDTH+1){1'b0}};
        end else begin
            w_bin  <= w_bin_next;
            w_gray <= w_gray_next;
        end
    end

    always @(posedge w_clk or posedge w_rst) begin
        if (w_rst) w_full_r <= 1'b0;
        else       w_full_r <= w_full_next;
    end

    assign w_full = w_full_r;

    // memory write
    always @(posedge w_clk) begin
        if (w_inc & ~w_full_r)
            mem[w_addr] <= w_data;
    end

    //------------------------------------------------------------------
    // Read clock domain: binary + gray pointer, empty flag
    //------------------------------------------------------------------
    reg  [ADDR_WIDTH:0]   r_bin, r_gray;
    wire [ADDR_WIDTH:0]   r_bin_next  = r_bin + (r_inc & ~r_empty);
    wire [ADDR_WIDTH:0]   r_gray_next = (r_bin_next >> 1) ^ r_bin_next;
    wire [ADDR_WIDTH-1:0] r_addr      = r_bin[ADDR_WIDTH-1:0];

    // synchronized write pointer (into read domain)
    reg  [ADDR_WIDTH:0]   rq1_w_gray, rq2_w_gray;

    reg  r_empty_r;
    wire r_empty_next = (r_gray_next == rq2_w_gray);

    always @(posedge r_clk or posedge r_rst) begin
        if (r_rst) begin
            r_bin  <= {(ADDR_WIDTH+1){1'b0}};
            r_gray <= {(ADDR_WIDTH+1){1'b0}};
        end else begin
            r_bin  <= r_bin_next;
            r_gray <= r_gray_next;
        end
    end

    always @(posedge r_clk or posedge r_rst) begin
        if (r_rst) r_empty_r <= 1'b1;
        else       r_empty_r <= r_empty_next;
    end

    assign r_empty = r_empty_r;

    // combinational (first-word-fall-through) read
    assign r_data = mem[r_addr];

    //------------------------------------------------------------------
    // Cross-clock 2-flop synchronizers
    //------------------------------------------------------------------
    // read pointer -> write clock domain
    always @(posedge w_clk or posedge w_rst) begin
        if (w_rst) begin
            wq1_r_gray <= {(ADDR_WIDTH+1){1'b0}};
            wq2_r_gray <= {(ADDR_WIDTH+1){1'b0}};
        end else begin
            wq1_r_gray <= r_gray;
            wq2_r_gray <= wq1_r_gray;
        end
    end

    // write pointer -> read clock domain
    always @(posedge r_clk or posedge r_rst) begin
        if (r_rst) begin
            rq1_w_gray <= {(ADDR_WIDTH+1){1'b0}};
            rq2_w_gray <= {(ADDR_WIDTH+1){1'b0}};
        end else begin
            rq1_w_gray <= w_gray;
            rq2_w_gray <= rq1_w_gray;
        end
    end

endmodule
