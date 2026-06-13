module TopModule (
    input  clk,
    input  reset,
    output [2:0] ena,
    output reg [15:0] q
);
    wire d0_roll = (q[3:0]   == 4'd9);
    wire d1_roll = (q[7:4]   == 4'd9);
    wire d2_roll = (q[11:8]  == 4'd9);

    assign ena[0] = d0_roll;
    assign ena[1] = d0_roll & d1_roll;
    assign ena[2] = d0_roll & d1_roll & d2_roll;

    always @(posedge clk) begin
        if (reset)
            q <= 16'd0;
        else begin
            // ones digit
            q[3:0]   <= d0_roll ? 4'd0 : q[3:0] + 4'd1;
            // tens digit
            if (ena[0])
                q[7:4]   <= d1_roll ? 4'd0 : q[7:4] + 4'd1;
            // hundreds digit
            if (ena[1])
                q[11:8]  <= d2_roll ? 4'd0 : q[11:8] + 4'd1;
            // thousands digit
            if (ena[2])
                q[15:12] <= (q[15:12] == 4'd9) ? 4'd0 : q[15:12] + 4'd1;
        end
    end
endmodule
