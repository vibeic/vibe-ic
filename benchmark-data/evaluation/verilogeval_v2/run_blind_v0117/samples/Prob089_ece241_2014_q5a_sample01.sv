module TopModule(
    input  clk,
    input  areset,
    input  x,
    output z
);
    // Moore serial 2's complementer, LSB first.
    // Rule: copy input bits up to and including the first 1, then invert the rest.
    // seen1 = a 1 has already been encountered on a previous cycle.
    // Output is registered (Moore): z is a state element only.
    reg seen1;
    reg z_reg;

    always @(posedge clk or posedge areset) begin
        if (areset) begin
            seen1 <= 1'b0;
            z_reg <= 1'b0;
        end else begin
            // bit produced this cycle: invert only after the first 1 has passed
            z_reg <= seen1 ? ~x : x;
            seen1 <= seen1 | x;
        end
    end

    assign z = z_reg;
endmodule
