module TopModule(
    input  clk,
    input  areset,
    input  x,
    output z
);
    // Moore serial 2's complementer.
    // Two states encode whether the first '1' has been seen:
    //   START  : no '1' seen yet -> output bit = x (copy)
    //   FLIP   : a '1' has been seen -> output bit = ~x (invert)
    // The output is registered so z depends only on the (registered) state,
    // making this a Moore machine.
    localparam START = 1'b0, FLIP = 1'b1;
    reg state;
    reg z_reg = 1'b0;

    always @(posedge clk or posedge areset) begin
        if (areset) begin
            state <= START;
            z_reg <= 1'b0;
        end else begin
            case (state)
                START: begin
                    // output the current bit unchanged; transition once a 1 arrives
                    z_reg <= x;
                    state <= x ? FLIP : START;
                end
                FLIP: begin
                    // after the first 1, output inverted bits
                    z_reg <= ~x;
                    state <= FLIP;
                end
                default: begin
                    z_reg <= 1'b0;
                    state <= START;
                end
            endcase
        end
    end

    assign z = z_reg;
endmodule
