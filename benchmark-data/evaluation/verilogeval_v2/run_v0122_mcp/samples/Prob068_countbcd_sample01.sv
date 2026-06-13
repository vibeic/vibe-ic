module TopModule (
    input         clk,
    input         reset,
    output [3:1]  ena,
    output reg [15:0] q
);

    wire ones_max = (q[3:0]   == 4'd9);
    wire tens_max = (q[7:4]   == 4'd9);
    wire hund_max = (q[11:8]  == 4'd9);

    assign ena[1] = ones_max;
    assign ena[2] = ones_max & tens_max;
    assign ena[3] = ones_max & tens_max & hund_max;

    always @(posedge clk) begin
        if (reset)
            q <= 16'd0;
        else begin
            // ones
            q[3:0]   <= ones_max ? 4'd0 : q[3:0] + 4'd1;
            // tens
            if (ena[1]) q[7:4]   <= tens_max ? 4'd0 : q[7:4] + 4'd1;
            // hundreds
            if (ena[2]) q[11:8]  <= hund_max ? 4'd0 : q[11:8] + 4'd1;
            // thousands
            if (ena[3]) q[15:12] <= (q[15:12] == 4'd9) ? 4'd0 : q[15:12] + 4'd1;
        end
    end

endmodule
