module TopModule(
    input  clk,
    input  reset,
    output shift_ena
);
    // After reset, shift_ena=1 for 4 cycles then 0 forever.
    // State = number of enabled cycles already counted (saturating at 4).
    reg [2:0] cnt = 3'd4;   // power-up: not shifting

    always @(posedge clk) begin
        if (reset)
            cnt <= 3'd0;
        else if (cnt != 3'd4)
            cnt <= cnt + 3'd1;
    end

    // Moore output: high while fewer than 4 enabled cycles have elapsed.
    assign shift_ena = (cnt != 3'd4);
endmodule
