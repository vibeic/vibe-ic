module encoder_64b66b (
    input  logic         clk_in,              // Clock signal
    input  logic         rst_in,              // Asynchronous reset (active high)
    input  logic [63:0]  encoder_data_in,     // 64-bit data input
    input  logic [7:0]   encoder_control_in,  // 8-bit control input
    output logic [65:0]  encoder_data_out     // 66-bit encoded output
);

    // Per-byte views (B7 = MSB byte data_in[63:56], B0 = LSB byte data_in[7:0])
    logic [7:0] B7, B6, B5, B4, B3, B2, B1, B0;
    assign B7 = encoder_data_in[63:56];
    assign B6 = encoder_data_in[55:48];
    assign B5 = encoder_data_in[47:40];
    assign B4 = encoder_data_in[39:32];
    assign B3 = encoder_data_in[31:24];
    assign B2 = encoder_data_in[23:16];
    assign B1 = encoder_data_in[15:8];
    assign B0 = encoder_data_in[7:0];

    // 7-bit control-code lookup
    function automatic logic [6:0] code7(input logic [7:0] b);
        case (b)
            8'h07:   code7 = 7'h00; // /I/ Idle
            8'hfe:   code7 = 7'h1e; // /E/ Error
            8'hfb:   code7 = 7'h00; // /S/ Start (4'b0000)
            8'hfd:   code7 = 7'h00; // /T/ Terminate (4'b0000)
            8'h9c:   code7 = 7'h0f; // /Q/ Ordered Set (4'b1111)
            default: code7 = 7'h00;
        endcase
    endfunction

    // 4-bit control-code lookup (merged O/S nibbles)
    function automatic logic [3:0] code4(input logic [7:0] b);
        case (b)
            8'hfb:   code4 = 4'b0000; // /S/
            8'hfd:   code4 = 4'b0000; // /T/
            8'h9c:   code4 = 4'b1111; // /Q/
            8'h07:   code4 = 4'b0000; // /I/
            default: code4 = 4'b0000;
        endcase
    endfunction

    logic [1:0]  sync_next;
    logic [7:0]  type_next;
    logic [55:0] pay_next;
    logic [65:0] out_next;

    always_comb begin
        sync_next = 2'b10;
        type_next = 8'h00;
        pay_next  = 56'h0;
        out_next  = 66'h0;

        if (encoder_control_in == 8'b00000000) begin
            // Data-only mode: no type field, full 64 bits are data
            sync_next = 2'b01;
            out_next  = {sync_next, encoder_data_in};
        end
        else begin
            sync_next = 2'b10;
            case (encoder_control_in)

                // Control-only mode (all 8 bytes control): 7 byte-slots, type=0x1e
                8'b11111111: begin
                    type_next = 8'h1e;
                    pay_next  = { {1'b0, code7(B7)},
                                  {1'b0, code7(B6)},
                                  {1'b0, code7(B5)},
                                  {1'b0, code7(B4)},
                                  {1'b0, code7(B3)},
                                  {1'b0, code7(B2)},
                                  {1'b0, code7(B1)} };
                end

                // Start of frame lane 0 (S0)
                8'b00000001: begin
                    type_next = 8'h78;
                    pay_next  = { B7, B6, B5, B4, B3, B2, B1 }; // D7..D1
                end

                // 0x00011111 : S4 (0x33) or Q4 (0x2d)
                8'b00011111: begin
                    if (B4 == 8'h9c) begin
                        type_next = 8'h2d;
                        pay_next  = { B7, B6, B5, 4'b1111,
                                      code7(B3), code7(B2), code7(B1), code7(B0) };
                    end
                    else begin
                        type_next = 8'h33;
                        pay_next  = { B7, B6, B5, 4'b0000,
                                      code7(B3), code7(B2), code7(B1), code7(B0) };
                    end
                end

                // 0x11111110 : T0 (0x87) or T1 (0x99)
                8'b11111110: begin
                    if (B0 == 8'hfd) begin
                        type_next = 8'h87;
                        pay_next  = { code7(B7), code7(B6), code7(B5), code7(B4),
                                      code7(B3), code7(B2), code7(B1), 7'b0000000 };
                    end
                    else begin
                        type_next = 8'h99;
                        pay_next  = { code7(B7), code7(B6), code7(B5), code7(B4),
                                      code7(B3), code7(B2), 6'b000000, B0 };
                    end
                end

                // T2 (0xaa)
                8'b11111100: begin
                    type_next = 8'haa;
                    pay_next  = { code7(B7), code7(B6), code7(B5), code7(B4),
                                  code7(B3), 5'b00000, B1, B0 };
                end

                // T3 (0xb4)
                8'b11111000: begin
                    type_next = 8'hb4;
                    pay_next  = { code7(B7), code7(B6), code7(B5), code7(B4),
                                  4'b0000, B2, B1, B0 };
                end

                // T4 (0xcc)
                8'b11110000: begin
                    type_next = 8'hcc;
                    pay_next  = { code7(B7), code7(B6), code7(B5),
                                  3'b000, B3, B2, B1, B0 };
                end

                // T5 (0xd2)
                8'b11100000: begin
                    type_next = 8'hd2;
                    pay_next  = { code7(B7), code7(B6),
                                  2'b00, B4, B3, B2, B1, B0 };
                end

                // T6 (0xe1)
                8'b11000000: begin
                    type_next = 8'he1;
                    pay_next  = { code7(B7),
                                  1'b0, B5, B4, B3, B2, B1, B0 };
                end

                // T7 (0xff)
                8'b10000000: begin
                    type_next = 8'hff;
                    pay_next  = { B6, B5, B4, B3, B2, B1, B0 }; // D6..D0
                end

                // 0x11110001 : Ordered-set lane 0 (0x4b)
                8'b11110001: begin
                    type_next = 8'h4b;
                    pay_next  = { code7(B7), code7(B6), code7(B5), code7(B4),
                                  B3, B2, B1, 4'b1111 };
                end

                // 0x00010001 : Q4/Q0 (0x55) or S4/Q0 (0x66)
                8'b00010001: begin
                    if (B4 == 8'hfb) begin
                        type_next = 8'h66;
                        pay_next  = { B7, B6, B5, {code4(B4), code4(B0)}, B3, B2, B1 };
                    end
                    else begin
                        type_next = 8'h55;
                        pay_next  = { B7, B6, B5, {code4(B4), code4(B0)}, B3, B2, B1 };
                    end
                end

                default: begin
                    type_next = 8'h00;
                    pay_next  = { B6, B5, B4, B3, B2, B1, B0 };
                end
            endcase

            out_next = {sync_next, type_next, pay_next};
        end
    end

    always_ff @(posedge clk_in or posedge rst_in) begin
        if (rst_in)
            encoder_data_out <= 66'b0;
        else
            encoder_data_out <= out_next;
    end

endmodule
