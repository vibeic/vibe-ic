// float_multi: IEEE-754 single-precision (binary32) floating-point multiplier.
// Multi-cycle, counter-sequenced. Restores the implicit leading 1, adds the
// exponents with a single bias-127 subtraction, multiplies the 24-bit mantissas,
// normalizes, and rounds to nearest-even. Handles zero / NaN / infinity.
module float_multi (
    input              clk,
    input              rst,
    input      [31:0]  a,
    input      [31:0]  b,
    output reg [31:0]  z
);

    reg [2:0]   counter;

    reg [23:0]  a_mantissa, b_mantissa, z_mantissa;
    reg [9:0]   a_exponent, b_exponent, z_exponent;
    reg         a_sign, b_sign, z_sign;
    reg [49:0]  product;
    reg         guard_bit, round_bit, sticky;

    // Latched class flags for the operands.
    reg a_is_zero, b_is_zero, a_is_inf, b_is_inf, a_is_nan, b_is_nan;

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            counter <= 3'd0;
            z       <= 32'd0;
        end
        else begin
            case (counter)
                // Stage 0: unpack operands, restore implicit leading 1, classify.
                3'd0: begin
                    a_sign     <= a[31];
                    b_sign     <= b[31];
                    a_exponent <= {2'b00, a[30:23]};
                    b_exponent <= {2'b00, b[30:23]};
                    a_mantissa <= (a[30:23] == 8'd0) ? {1'b0, a[22:0]} : {1'b1, a[22:0]};
                    b_mantissa <= (b[30:23] == 8'd0) ? {1'b0, b[22:0]} : {1'b1, b[22:0]};

                    a_is_zero <= (a[30:0] == 31'd0);
                    b_is_zero <= (b[30:0] == 31'd0);
                    a_is_inf  <= (a[30:23] == 8'hFF) && (a[22:0] == 23'd0);
                    b_is_inf  <= (b[30:23] == 8'hFF) && (b[22:0] == 23'd0);
                    a_is_nan  <= (a[30:23] == 8'hFF) && (a[22:0] != 23'd0);
                    b_is_nan  <= (b[30:23] == 8'hFF) && (b[22:0] != 23'd0);

                    z_sign  <= a[31] ^ b[31];
                    counter <= 3'd1;
                end

                // Stage 1: sign + exponent combine, mantissa multiply.
                3'd1: begin
                    z_exponent <= a_exponent + b_exponent - 10'd127;
                    product    <= a_mantissa * b_mantissa;
                    counter    <= 3'd2;
                end

                // Stage 2: normalize. product is 48 bits significant (1.x * 1.x in [1,4)).
                3'd2: begin
                    if (product[47]) begin
                        // result in [2,4): shift right by 1, bump exponent.
                        z_mantissa <= product[47:24];
                        guard_bit  <= product[23];
                        round_bit  <= product[22];
                        sticky     <= |product[21:0];
                        z_exponent <= z_exponent + 10'd1;
                    end
                    else begin
                        // result in [1,2): already normalized.
                        z_mantissa <= product[46:23];
                        guard_bit  <= product[22];
                        round_bit  <= product[21];
                        sticky     <= |product[20:0];
                    end
                    counter <= 3'd3;
                end

                // Stage 3: round-to-nearest-even.
                3'd3: begin
                    if (guard_bit && (round_bit || sticky || z_mantissa[0])) begin
                        z_mantissa <= z_mantissa + 24'd1;
                        if (z_mantissa == 24'hFFFFFF)
                            z_exponent <= z_exponent + 10'd1; // carry-out renormalize
                    end
                    counter <= 3'd4;
                end

                // Stage 4: assemble result, apply special cases / overflow / underflow.
                3'd4: begin
                    if (a_is_nan || b_is_nan ||
                        (a_is_inf && b_is_zero) || (b_is_inf && a_is_zero)) begin
                        // NaN (incl inf*0)
                        z <= {1'b0, 8'hFF, 23'h400000};
                    end
                    else if (a_is_inf || b_is_inf) begin
                        z <= {z_sign, 8'hFF, 23'd0};                 // infinity
                    end
                    else if (a_is_zero || b_is_zero) begin
                        z <= {z_sign, 31'd0};                        // zero
                    end
                    else if (z_exponent >= 10'd255) begin
                        z <= {z_sign, 8'hFF, 23'd0};                 // overflow -> inf
                    end
                    else if (z_exponent[9] || z_exponent == 10'd0) begin
                        z <= {z_sign, 31'd0};                        // underflow -> zero
                    end
                    else begin
                        z <= {z_sign, z_exponent[7:0], z_mantissa[22:0]};
                    end
                    counter <= 3'd0;
                end

                default: counter <= 3'd0;
            endcase
        end
    end

endmodule
