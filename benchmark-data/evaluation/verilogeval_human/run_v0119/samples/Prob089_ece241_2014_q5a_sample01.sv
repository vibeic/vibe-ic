module TopModule (
  input clk,
  input areset,
  input x,
  output z
);
    // Moore serial 2's complementer.
    // mode: 0 = still copying (no '1' seen yet), 1 = inverting (after first '1')
    // Output z is registered (function of state) -> Moore.
    reg mode;
    reg z_reg;

    always @(posedge clk or posedge areset) begin
        if (areset) begin
            mode  <= 1'b0;
            z_reg <= 1'b0;
        end else begin
            if (mode == 1'b0) begin
                // copy bit as-is; first '1' flips into invert mode
                z_reg <= x;
                if (x)
                    mode <= 1'b1;
            end else begin
                // invert subsequent bits
                z_reg <= ~x;
            end
        end
    end

    assign z = z_reg;
endmodule
