module multi_booth_8bit (
    input             clk,
    input             reset,
    input      [7:0]  a,
    input      [7:0]  b,
    output reg [15:0] p,
    output reg        rdy
);

    reg [15:0] multiplier;
    reg [15:0] multiplicand;
    reg [4:0]  ctr;

    always @(posedge clk or posedge reset) begin
        if (reset) begin
            multiplier   <= {{8{a[7]}}, a};
            multiplicand <= {{8{b[7]}}, b};
            ctr          <= 5'd0;
            p            <= 16'd0;
            rdy          <= 1'b0;
        end else begin
            if (ctr < 16) begin
                multiplicand <= multiplicand << 1;
                if (multiplier[ctr])
                    p <= p + multiplicand;
                ctr <= ctr + 1'b1;
                if (ctr == 15)
                    rdy <= 1'b1;
            end
        end
    end

endmodule
