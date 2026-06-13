module TopModule (
    input  clk,
    input  areset,
    input  x,
    output z
);
    // Moore serial 2's complementer.
    // Algorithm: scan from LSB, copy bits up to and including the first 1,
    // then invert all subsequent bits. Equivalent to subtract-from-zero with borrow.
    // state = borrow:  A (0) = no 1 seen yet, B (1) = first 1 seen (borrow active).
    // Registered (Moore) output: z holds the 2's-complement bit.
    localparam A = 1'b0, B = 1'b1;
    reg state;
    reg z_r;

    always @(posedge clk or posedge areset) begin
        if (areset) begin
            state <= A;
            z_r   <= 1'b0;
        end else begin
            case (state)
                A: begin
                    z_r   <= x;          // copy bit; first 1 passes through
                    state <= x ? B : A;  // once a 1 is seen, switch to invert mode
                end
                B: begin
                    z_r   <= ~x;         // invert subsequent bits
                    state <= B;
                end
                default: begin
                    z_r   <= 1'b0;
                    state <= A;
                end
            endcase
        end
    end

    assign z = z_r;
endmodule
