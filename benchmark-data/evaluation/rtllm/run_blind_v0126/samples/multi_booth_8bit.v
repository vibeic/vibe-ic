module multi_booth_8bit (
    input  wire        clk,
    input  wire        reset,
    input  wire [7:0]  a,
    input  wire [7:0]  b,
    output reg  [15:0] p,
    output reg         rdy
);

    reg [15:0] multiplier;
    reg [15:0] multiplicand;
    reg [4:0]  ctr;

    always @(posedge clk or posedge reset) begin
        if (reset) begin
            multiplier   <= {{8{a[7]}}, a};
            multiplicand <= {{8{b[7]}}, b};
            p            <= 16'd0;
            rdy          <= 1'b0;
            ctr          <= 5'd0;
        end
        else begin
            if (ctr < 5'd16) begin
                if (multiplier[ctr])
                    p <= p + multiplicand;
                multiplicand <= multiplicand << 1;
                ctr <= ctr + 5'd1;
            end
            else begin
                rdy <= 1'b1;
            end
        end
    end

endmodule
