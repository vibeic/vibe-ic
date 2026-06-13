module TopModule (
    input  clk,
    input  reset,
    output shift_ena
);
    // On (synchronous) reset, restart: assert shift_ena for exactly 4 cycles
    // then 0 forever. Count the 4 enabled cycles with a saturating counter.
    reg [2:0] cnt = 3'd4;   // 4 = "done" (idle, shift_ena low)

    always @(posedge clk) begin
        if (reset)
            cnt <= 3'd0;
        else if (cnt < 3'd4)
            cnt <= cnt + 3'd1;
    end

    assign shift_ena = (cnt < 3'd4);
endmodule
