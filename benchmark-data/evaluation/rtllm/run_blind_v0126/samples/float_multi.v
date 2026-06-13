module float_multi (
    input  wire        clk,
    input  wire        rst,
    input  wire [31:0] a,
    input  wire [31:0] b,
    output reg  [31:0] z
);

    reg [2:0]  counter;
    reg [23:0] a_mantissa, b_mantissa, z_mantissa;
    reg [9:0]  a_exponent, b_exponent, z_exponent;
    reg        a_sign, b_sign, z_sign;
    reg [49:0] product;
    reg        guard_bit, round_bit, sticky;

    always @(posedge clk) begin
        if (rst) begin
            counter <= 3'd0;
            z       <= 32'd0;
        end
        else begin
            case (counter)
                // Cycle 0: unpack operands
                3'd0: begin
                    a_sign     <= a[31];
                    b_sign     <= b[31];
                    a_exponent <= {2'b00, a[30:23]};
                    b_exponent <= {2'b00, b[30:23]};
                    // Restore the implicit leading 1 for normal numbers.
                    a_mantissa <= (a[30:23] == 8'd0) ? {1'b0, a[22:0]} : {1'b1, a[22:0]};
                    b_mantissa <= (b[30:23] == 8'd0) ? {1'b0, b[22:0]} : {1'b1, b[22:0]};
                    counter    <= 3'd1;
                end

                // Cycle 1: handle special cases, sign and exponent base
                3'd1: begin
                    z_sign <= a_sign ^ b_sign;
                    // NaN: exponent all ones and nonzero mantissa
                    if ((a_exponent == 10'd255 && a_mantissa[22:0] != 0) ||
                        (b_exponent == 10'd255 && b_mantissa[22:0] != 0)) begin
                        z       <= {1'b0, 8'hFF, 23'h400000}; // quiet NaN
                        counter <= 3'd0;
                    end
                    // Infinity (either operand exponent all ones, mantissa zero)
                    else if (a_exponent == 10'd255 || b_exponent == 10'd255) begin
                        // inf * 0 = NaN
                        if ((a_exponent == 0 && a_mantissa == 0) ||
                            (b_exponent == 0 && b_mantissa == 0)) begin
                            z       <= {1'b0, 8'hFF, 23'h400000};
                            counter <= 3'd0;
                        end
                        else begin
                            z       <= {a_sign ^ b_sign, 8'hFF, 23'd0};
                            counter <= 3'd0;
                        end
                    end
                    // Zero operand -> zero result
                    else if ((a_exponent == 0 && a_mantissa[22:0] == 0) ||
                             (b_exponent == 0 && b_mantissa[22:0] == 0)) begin
                        z       <= {a_sign ^ b_sign, 31'd0};
                        counter <= 3'd0;
                    end
                    else begin
                        z_exponent <= a_exponent + b_exponent - 10'd127;
                        counter    <= 3'd2;
                    end
                end

                // Cycle 2: multiply mantissas
                3'd2: begin
                    product <= a_mantissa * b_mantissa;
                    counter <= 3'd3;
                end

                // Cycle 3: normalize
                3'd3: begin
                    // product is 48 bits significant (bit 47 or 46 leading).
                    if (product[47]) begin
                        z_mantissa <= product[47:24];
                        guard_bit  <= product[23];
                        round_bit  <= product[22];
                        sticky     <= |product[21:0];
                        z_exponent <= z_exponent + 10'd1;
                    end
                    else begin
                        z_mantissa <= product[46:23];
                        guard_bit  <= product[22];
                        round_bit  <= product[21];
                        sticky     <= |product[20:0];
                    end
                    counter <= 3'd4;
                end

                // Cycle 4: round (round-to-nearest-even)
                3'd4: begin
                    if (guard_bit && (round_bit || sticky || z_mantissa[0])) begin
                        z_mantissa <= z_mantissa + 24'd1;
                        if (z_mantissa == 24'hFFFFFF)
                            z_exponent <= z_exponent + 10'd1;
                    end
                    counter <= 3'd5;
                end

                // Cycle 5: pack result
                3'd5: begin
                    if (z_exponent >= 10'd255)
                        // overflow -> infinity
                        z <= {z_sign, 8'hFF, 23'd0};
                    else if (z_exponent[9] || z_exponent == 0)
                        // underflow -> zero
                        z <= {z_sign, 31'd0};
                    else
                        z <= {z_sign, z_exponent[7:0], z_mantissa[22:0]};
                    counter <= 3'd0;
                end

                default: counter <= 3'd0;
            endcase
        end
    end

endmodule
