module float_multi (
    input             clk,
    input             rst,
    input      [31:0] a,
    input      [31:0] b,
    output reg [31:0] z
);

    reg [2:0]  counter;

    reg        a_sign, b_sign, z_sign;
    reg [9:0]  a_exponent, b_exponent, z_exponent;
    reg [23:0] a_mantissa, b_mantissa, z_mantissa;
    reg [49:0] product;
    reg        guard_bit, round_bit, sticky;

    reg        a_is_zero, b_is_zero;
    reg        a_is_nan, b_is_nan;
    reg        a_is_inf, b_is_inf;

    always @(posedge clk) begin
        if (rst) begin
            counter <= 3'd0;
            z       <= 32'd0;
        end else begin
            case (counter)
                3'd0: begin
                    // Input processing
                    a_sign     <= a[31];
                    b_sign     <= b[31];
                    a_exponent <= {2'b00, a[30:23]};
                    b_exponent <= {2'b00, b[30:23]};
                    a_mantissa <= (a[30:23] == 8'd0) ? {1'b0, a[22:0]} : {1'b1, a[22:0]};
                    b_mantissa <= (b[30:23] == 8'd0) ? {1'b0, b[22:0]} : {1'b1, b[22:0]};

                    a_is_zero  <= (a[30:23] == 8'd0) && (a[22:0] == 23'd0);
                    b_is_zero  <= (b[30:23] == 8'd0) && (b[22:0] == 23'd0);
                    a_is_nan   <= (a[30:23] == 8'hFF) && (a[22:0] != 23'd0);
                    b_is_nan   <= (b[30:23] == 8'hFF) && (b[22:0] != 23'd0);
                    a_is_inf   <= (a[30:23] == 8'hFF) && (a[22:0] == 23'd0);
                    b_is_inf   <= (b[30:23] == 8'hFF) && (b[22:0] == 23'd0);

                    counter <= counter + 1'b1;
                end

                3'd1: begin
                    // Multiply mantissas, combine exponent and sign
                    product    <= a_mantissa * b_mantissa;
                    z_exponent <= a_exponent + b_exponent - 10'd127;
                    z_sign     <= a_sign ^ b_sign;
                    counter    <= counter + 1'b1;
                end

                3'd2: begin
                    // Normalize the product.
                    // DB/IEEE-754 note: a_mantissa/b_mantissa are 24-bit (Q1.23), so their
                    // product is a full-width 48-bit value occupying product[47:0] --
                    // product[49:48] are ALWAYS 0 (product is declared 50 bits for margin,
                    // but only 48 bits are ever significant). The prior implementation
                    // tested product[49] (always false, 2 bit-positions too high), so the
                    // "needs one more normalizing shift" branch never fired even when the
                    // true top bit product[47] was set -- an off-by-2 bit-position bug that
                    // silently mis-normalized ~half of all products. Test product[47], the
                    // real MSB of the 48-bit product, instead.
                    if (product[47]) begin
                        z_mantissa <= product[47:24];
                        z_exponent <= z_exponent + 10'd1;
                        guard_bit  <= product[23];
                        round_bit  <= product[22];
                        sticky     <= |product[21:0];
                    end else begin
                        z_mantissa <= product[46:23];
                        guard_bit  <= product[22];
                        round_bit  <= product[21];
                        sticky     <= |product[20:0];
                    end
                    counter <= counter + 1'b1;
                end

                3'd3: begin
                    // Round to nearest, ties to even
                    if (guard_bit && (round_bit || sticky || z_mantissa[0])) begin
                        z_mantissa <= z_mantissa + 24'd1;
                    end
                    counter <= counter + 1'b1;
                end

                3'd4: begin
                    // Pack the result, handling special cases
                    if (a_is_nan || b_is_nan) begin
                        z <= {1'b0, 8'hFF, 1'b1, 22'd0};
                    end else if (a_is_inf || b_is_inf) begin
                        if (a_is_zero || b_is_zero)
                            z <= {1'b0, 8'hFF, 1'b1, 22'd0};
                        else
                            z <= {z_sign, 8'hFF, 23'd0};
                    end else if (a_is_zero || b_is_zero) begin
                        z <= {z_sign, 31'd0};
                    end else if (z_exponent[9] || z_exponent >= 10'd255) begin
                        z <= {z_sign, 8'hFF, 23'd0};
                    end else if (z_exponent <= 10'd0) begin
                        z <= {z_sign, 31'd0};
                    end else begin
                        z <= {z_sign, z_exponent[7:0], z_mantissa[22:0]};
                    end
                    counter <= 3'd0;
                end

                default: counter <= 3'd0;
            endcase
        end
    end

endmodule
