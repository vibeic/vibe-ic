module TopModule (
    input  clk,
    input  reset,
    output shift_ena
);
    // After reset, assert shift_ena for exactly 4 cycles, then 0 forever.
    // Count saturates at 4. shift_ena high while fewer than 4 cycles elapsed.
    reg [2:0] count;
    always @(posedge clk) begin
        if (reset)
            count <= 3'd0;
        else if (count < 3'd4)
            count <= count + 3'd1;
    end
    assign shift_ena = (count < 3'd4);
endmodule
