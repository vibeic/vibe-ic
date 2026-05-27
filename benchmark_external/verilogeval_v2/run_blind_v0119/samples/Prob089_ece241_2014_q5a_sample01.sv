module TopModule (
    input  clk,
    input  areset,
    input  x,
    output z
);
    // Moore serial 2's complementer.
    // "seen1" tracks whether the first 1 (from the LSB) has been encountered.
    // Output rule per input bit: before & including first 1 -> copy x ;
    // after the first 1 -> invert x. Implemented as a Moore FSM by
    // registering the output (z is a function of registered state).
    reg seen1 = 1'b0;
    reg z_reg = 1'b0;

    always @(posedge clk or posedge areset) begin
        if (areset) begin
            seen1 <= 1'b0;
            z_reg <= 1'b0;
        end else begin
            // current bit's complemented output, registered (Moore)
            z_reg <= seen1 ? ~x : x;
            seen1 <= seen1 | x;
        end
    end

    assign z = z_reg;
endmodule
