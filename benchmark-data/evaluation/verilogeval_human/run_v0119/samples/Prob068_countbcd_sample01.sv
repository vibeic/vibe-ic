module TopModule (
    input clk,
    input reset,
    output [3:1] ena,
    output reg [15:0] q
);
    wire ones9  = (q[3:0]   == 4'd9);
    wire tens9  = (q[7:4]   == 4'd9);
    wire huns9  = (q[11:8]  == 4'd9);

    assign ena[1] = ones9;
    assign ena[2] = ones9 & tens9;
    assign ena[3] = ones9 & tens9 & huns9;

    always @(posedge clk) begin
        if (reset)
            q <= 16'd0;
        else begin
            // ones digit
            q[3:0]   <= ones9 ? 4'd0 : q[3:0] + 4'd1;
            // tens digit
            if (ena[1]) q[7:4]   <= tens9 ? 4'd0 : q[7:4] + 4'd1;
            // hundreds digit
            if (ena[2]) q[11:8]  <= huns9 ? 4'd0 : q[11:8] + 4'd1;
            // thousands digit
            if (ena[3]) q[15:12] <= (q[15:12] == 4'd9) ? 4'd0 : q[15:12] + 4'd1;
        end
    end
endmodule
