module TopModule(
    input  clk,
    input  reset,
    output [2:0] ena,
    output reg [15:0] q
);
    wire ones_max  = (q[3:0]   == 4'd9);
    wire tens_max  = (q[7:4]   == 4'd9);
    wire huns_max  = (q[11:8]  == 4'd9);

    // ena[i] indicates digit i should increment this cycle
    wire ena1 = ones_max;                       // tens digit
    wire ena2 = ones_max & tens_max;            // hundreds digit
    wire ena3 = ones_max & tens_max & huns_max; // thousands digit
    assign ena = {ena3, ena2, ena1};

    always @(posedge clk) begin
        if (reset) begin
            q <= 16'd0;
        end else begin
            // ones
            q[3:0]   <= ones_max ? 4'd0 : q[3:0] + 4'd1;
            // tens
            if (ena1)
                q[7:4] <= tens_max ? 4'd0 : q[7:4] + 4'd1;
            // hundreds
            if (ena2)
                q[11:8] <= huns_max ? 4'd0 : q[11:8] + 4'd1;
            // thousands
            if (ena3)
                q[15:12] <= (q[15:12] == 4'd9) ? 4'd0 : q[15:12] + 4'd1;
        end
    end
endmodule
