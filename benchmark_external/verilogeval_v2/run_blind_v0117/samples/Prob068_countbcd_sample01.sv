module TopModule(
    input  clk,
    input  reset,
    output [3:1] ena,
    output reg [15:0] q
);
    wire ones_max = (q[3:0]   == 4'd9);
    wire tens_max = (q[7:4]   == 4'd9);
    wire huns_max = (q[11:8]  == 4'd9);

    assign ena[1] = ones_max;
    assign ena[2] = ones_max & tens_max;
    assign ena[3] = ones_max & tens_max & huns_max;

    always @(posedge clk) begin
        if (reset) begin
            q <= 16'd0;
        end else begin
            // ones digit
            if (ones_max) q[3:0] <= 4'd0;
            else          q[3:0] <= q[3:0] + 4'd1;
            // tens digit
            if (ena[1]) begin
                if (tens_max) q[7:4] <= 4'd0;
                else          q[7:4] <= q[7:4] + 4'd1;
            end
            // hundreds digit
            if (ena[2]) begin
                if (huns_max) q[11:8] <= 4'd0;
                else          q[11:8] <= q[11:8] + 4'd1;
            end
            // thousands digit
            if (ena[3]) begin
                if (q[15:12] == 4'd9) q[15:12] <= 4'd0;
                else                  q[15:12] <= q[15:12] + 4'd1;
            end
        end
    end
endmodule
