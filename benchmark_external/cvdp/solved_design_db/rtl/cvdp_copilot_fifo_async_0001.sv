// -----------------------------------------------------------------------------
// fifo_async : Dual-clock (asynchronous) FIFO with Gray-coded pointers
//
// First-word-fall-through (show-ahead) read interface: r_data continuously
// presents mem[read_address]; r_inc advances the read pointer on the next
// r_clk rising edge when the FIFO is not empty.
//
// Cross-domain pointer hand-off uses 2-flop synchronizers on the Gray-coded
// pointers to avoid metastability.  Pointers carry one extra (MSB) bit so the
// full/empty conditions can be distinguished:
//   - empty : read Gray pointer == synchronized write Gray pointer
//   - full  : write Gray pointer == synchronized read Gray pointer with its
//             top two bits inverted (the classic Gray-code wrap detection that
//             realizes "MSB differs, all remaining bits equal" in binary).
// -----------------------------------------------------------------------------
module fifo_async #(
    parameter DATA_WIDTH = 32,
    parameter DEPTH      = 8
) (
    // Write clock domain
    input  wire                  w_clk,
    input  wire                  w_rst,
    input  wire                  w_inc,
    input  wire [DATA_WIDTH-1:0] w_data,
    // Read clock domain
    input  wire                  r_clk,
    input  wire                  r_rst,
    input  wire                  r_inc,
    // Status / data outputs
    output wire                  w_full,
    output wire                  r_empty,
    output wire [DATA_WIDTH-1:0] r_data
);

    // Address width derived from depth; pointers use one extra (overflow) bit.
    localparam ADDR_WIDTH = (DEPTH > 1) ? $clog2(DEPTH) : 1;

    // ------------------------------------------------------------------
    // Storage
    // ------------------------------------------------------------------
    reg [DATA_WIDTH-1:0] mem [0:DEPTH-1];

    // Binary + Gray pointers (ADDR_WIDTH+1 bits each)
    reg  [ADDR_WIDTH:0] w_bin,  w_gray;
    reg  [ADDR_WIDTH:0] r_bin,  r_gray;

    // 2-flop synchronizers
    reg  [ADDR_WIDTH:0] wq1, wq2;   // write Gray pointer  -> read  domain
    reg  [ADDR_WIDTH:0] rq1, rq2;   // read  Gray pointer  -> write domain

    // ------------------------------------------------------------------
    // Write pointer (write clock domain)
    // ------------------------------------------------------------------
    wire                  w_en       = w_inc & ~w_full;
    wire [ADDR_WIDTH:0]   w_bin_next = w_bin + {{ADDR_WIDTH{1'b0}}, w_en};
    wire [ADDR_WIDTH:0]   w_gray_next= (w_bin_next >> 1) ^ w_bin_next;
    wire [ADDR_WIDTH-1:0] w_addr     = w_bin[ADDR_WIDTH-1:0];

    always @(posedge w_clk or posedge w_rst) begin
        if (w_rst) begin
            w_bin  <= {(ADDR_WIDTH+1){1'b0}};
            w_gray <= {(ADDR_WIDTH+1){1'b0}};
        end else begin
            w_bin  <= w_bin_next;
            w_gray <= w_gray_next;
        end
    end

    // Memory write
    always @(posedge w_clk) begin
        if (w_en)
            mem[w_addr] <= w_data;
    end

    // ------------------------------------------------------------------
    // Read pointer (read clock domain)
    // ------------------------------------------------------------------
    wire                  r_en       = r_inc & ~r_empty;
    wire [ADDR_WIDTH:0]   r_bin_next = r_bin + {{ADDR_WIDTH{1'b0}}, r_en};
    wire [ADDR_WIDTH:0]   r_gray_next= (r_bin_next >> 1) ^ r_bin_next;
    wire [ADDR_WIDTH-1:0] r_addr     = r_bin[ADDR_WIDTH-1:0];

    always @(posedge r_clk or posedge r_rst) begin
        if (r_rst) begin
            r_bin  <= {(ADDR_WIDTH+1){1'b0}};
            r_gray <= {(ADDR_WIDTH+1){1'b0}};
        end else begin
            r_bin  <= r_bin_next;
            r_gray <= r_gray_next;
        end
    end

    // First-word-fall-through read data
    assign r_data = mem[r_addr];

    // ------------------------------------------------------------------
    // Synchronizers
    // ------------------------------------------------------------------
    // write Gray pointer into read domain
    always @(posedge r_clk or posedge r_rst) begin
        if (r_rst) begin
            wq1 <= {(ADDR_WIDTH+1){1'b0}};
            wq2 <= {(ADDR_WIDTH+1){1'b0}};
        end else begin
            wq1 <= w_gray;
            wq2 <= wq1;
        end
    end

    // read Gray pointer into write domain
    always @(posedge w_clk or posedge w_rst) begin
        if (w_rst) begin
            rq1 <= {(ADDR_WIDTH+1){1'b0}};
            rq2 <= {(ADDR_WIDTH+1){1'b0}};
        end else begin
            rq1 <= r_gray;
            rq2 <= rq1;
        end
    end

    // ------------------------------------------------------------------
    // Flags
    // ------------------------------------------------------------------
    // Empty: read Gray pointer equals synchronized write Gray pointer
    assign r_empty = (r_gray == wq2);

    // Full: write Gray pointer equals synchronized read Gray pointer with the
    // top two bits inverted (Gray-code wrap condition).
    assign w_full =
        (w_gray == {~rq2[ADDR_WIDTH:ADDR_WIDTH-1], rq2[ADDR_WIDTH-2:0]});

endmodule
