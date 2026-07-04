module binary_multiplier #(
    parameter WIDTH = 32          // bit-width of operands A and B (min 1)
)(
    input                      clk,        // positive-edge clock
    input                      rst_n,      // active-low asynchronous reset
    input                      valid_in,   // A and B are valid (1-cycle pulse)
    input      [WIDTH-1:0]     A,          // operand A
    input      [WIDTH-1:0]     B,          // operand B
    output reg                 valid_out,  // Product is valid (1-cycle pulse)
    output reg [2*WIDTH-1:0]   Product     // multiplication result
);

    // Sequential add-shift multiplier.
    //   cycle 1            : latch A/B, raise `start`
    //   cycles 2 .. W+1    : WIDTH shift-and-accumulate steps
    //   cycle  W+2         : register Product, pulse valid_out
    // => Product is registered on the (WIDTH+2)-th clock cycle.
    reg                        start;
    reg [WIDTH-1:0]            a_reg;
    reg [WIDTH-1:0]            b_reg;
    reg [2*WIDTH-1:0]          acc;
    reg [$clog2(WIDTH+3)-1:0]  cnt;

    wire [2*WIDTH-1:0] b_ext = {{WIDTH{1'b0}}, b_reg};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            start     <= 1'b0;
            a_reg     <= {WIDTH{1'b0}};
            b_reg     <= {WIDTH{1'b0}};
            acc       <= {(2*WIDTH){1'b0}};
            cnt       <= {($clog2(WIDTH+3)){1'b0}};
            Product   <= {(2*WIDTH){1'b0}};
            valid_out <= 1'b0;
        end else begin
            valid_out <= 1'b0;                 // default: single-cycle pulse
            if (valid_in && !start) begin
                a_reg <= A;
                b_reg <= B;
                acc   <= {(2*WIDTH){1'b0}};
                cnt   <= {($clog2(WIDTH+3)){1'b0}};
                start <= 1'b1;
            end else if (start) begin
                if (cnt < WIDTH[$clog2(WIDTH+3)-1:0]) begin
                    if (a_reg[cnt]) acc <= acc + (b_ext << cnt);
                    cnt <= cnt + 1'b1;
                end else begin
                    // cnt == WIDTH : accumulation complete -> emit result
                    Product   <= acc;
                    valid_out <= 1'b1;
                    start     <= 1'b0;
                    cnt       <= {($clog2(WIDTH+3)){1'b0}};
                end
            end
        end
    end

endmodule
