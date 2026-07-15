module encoder_64b66b (
    input  logic         clk_in,              // Clock signal
    input  logic         rst_in,              // Asynchronous reset (active high)
    input  logic [63:0]  encoder_data_in,     // 64-bit data input
    input  logic [7:0]   encoder_control_in,  // 8-bit control input
    output logic [65:0]  encoder_data_out     // 66-bit encoded output
);

    // ------------------------------------------------------------------
    // Valid control-character byte values on the input
    // ------------------------------------------------------------------
    localparam logic [7:0] CHAR_I = 8'h07;   // /I/ Idle
    localparam logic [7:0] CHAR_S = 8'hfb;   // /S/ Start of Frame
    localparam logic [7:0] CHAR_T = 8'hfd;   // /T/ End of Frame
    localparam logic [7:0] CHAR_E = 8'hfe;   // /E/ Error
    localparam logic [7:0] CHAR_Q = 8'h9c;   // /Q/ Ordered Set

    // 7-bit encoded control codes
    localparam logic [6:0] CODE_I = 7'h00;   // /I/ -> 7'h00
    localparam logic [6:0] CODE_E = 7'h1e;   // /E/ -> 7'h1e

    logic [1:0]  sync_word;
    logic [63:0] encoded_data;

    // Input byte lanes (byte i is qualified by encoder_control_in[i])
    logic [7:0] d7, d6, d5, d4, d3, d2, d1, d0;

    assign d7 = encoder_data_in[63:56];
    assign d6 = encoder_data_in[55:48];
    assign d5 = encoder_data_in[47:40];
    assign d4 = encoder_data_in[39:32];
    assign d3 = encoder_data_in[31:24];
    assign d2 = encoder_data_in[23:16];
    assign d1 = encoder_data_in[15:8];
    assign d0 = encoder_data_in[7:0];

    // 7-bit control-code lookup for a control byte carried in a C lane
    function automatic logic [6:0] ccode(input logic [7:0] b);
        case (b)
            CHAR_I:  ccode = CODE_I;
            CHAR_E:  ccode = CODE_E;
            default: ccode = CODE_E; // any other character in a C lane -> error code
        endcase
    endfunction

    // ------------------------------------------------------------------
    // Sync word: 2'b01 = data-only, 2'b10 = control-only / mixed
    // ------------------------------------------------------------------
    always_ff @(posedge clk_in or posedge rst_in) begin
        if (rst_in) begin
            sync_word <= 2'b00;
        end
        else begin
            if (encoder_control_in == 8'b00000000) begin
                sync_word <= 2'b01;
            end
            else begin
                sync_word <= 2'b10;
            end
        end
    end

    // ------------------------------------------------------------------
    // Encoded data word:
    //   data-only      -> raw 64-bit data (no type field)
    //   control/mixed  -> {8-bit type field, 56-bit encoded payload}
    // ------------------------------------------------------------------
    always_ff @(posedge clk_in or posedge rst_in) begin
        if (rst_in) begin
            encoded_data <= 64'b0;
        end
        else begin
            case (encoder_control_in)
                // Data-only mode: pass data through unchanged
                8'b00000000: encoded_data <= encoder_data_in;

                // All-control lanes:
                //   I7..I1,T0                -> type 0x87
                //   all idle / all error     -> type 0x1e
                8'b11111111: begin
                    if (d0 == CHAR_T) begin
                        encoded_data <= {8'h87, ccode(d7), ccode(d6), ccode(d5),
                                         ccode(d4), ccode(d3), ccode(d2), ccode(d1),
                                         7'b0000000};
                    end
                    else begin
                        encoded_data <= {8'h1e,
                                         1'b0, ccode(d6), 1'b0, ccode(d5),
                                         1'b0, ccode(d4), 1'b0, ccode(d3),
                                         1'b0, ccode(d2), 1'b0, ccode(d1),
                                         1'b0, ccode(d0)};
                    end
                end

                // I7..I2,T1,D0 -> type 0x99  (also tolerate T0 driven with this mask)
                8'b11111110: begin
                    if (d1 == CHAR_T) begin
                        encoded_data <= {8'h99, ccode(d7), ccode(d6), ccode(d5),
                                         ccode(d4), ccode(d3), ccode(d2),
                                         6'b000000, d0};
                    end
                    else if (d0 == CHAR_T) begin
                        encoded_data <= {8'h87, ccode(d7), ccode(d6), ccode(d5),
                                         ccode(d4), ccode(d3), ccode(d2), ccode(d1),
                                         7'b0000000};
                    end
                    else begin
                        encoded_data <= {8'h99, ccode(d7), ccode(d6), ccode(d5),
                                         ccode(d4), ccode(d3), ccode(d2),
                                         6'b000000, d0};
                    end
                end

                // I7..I3,T2,D1,D0 -> type 0xaa
                8'b11111100: encoded_data <= {8'haa, ccode(d7), ccode(d6), ccode(d5),
                                              ccode(d4), ccode(d3), 5'b00000, d1, d0};

                // I7..I4,T3,D2..D0 -> type 0xb4
                8'b11111000: encoded_data <= {8'hb4, ccode(d7), ccode(d6), ccode(d5),
                                              ccode(d4), 4'b0000, d2, d1, d0};

                // I7..I5,T4,D3..D0 -> type 0xcc
                8'b11110000: encoded_data <= {8'hcc, ccode(d7), ccode(d6), ccode(d5),
                                              3'b000, d3, d2, d1, d0};

                // I7,I6,T5,D4..D0 -> type 0xd2
                8'b11100000: encoded_data <= {8'hd2, ccode(d7), ccode(d6),
                                              2'b00, d4, d3, d2, d1, d0};

                // I7,T6,D5..D0 -> type 0xe1
                8'b11000000: encoded_data <= {8'he1, ccode(d7),
                                              1'b0, d5, d4, d3, d2, d1, d0};

                // T7,D6..D0 -> type 0xff
                8'b10000000: encoded_data <= {8'hff, d6, d5, d4, d3, d2, d1, d0};

                // D7,D6,D5,{S4|Q4},I3..I0 -> type 0x33 (S4) / 0x2d (Q4)
                8'b00011111: begin
                    if (d4 == CHAR_Q) begin
                        encoded_data <= {8'h2d, d7, d6, d5, 4'b1111,
                                         ccode(d3), ccode(d2), ccode(d1), ccode(d0)};
                    end
                    else begin
                        encoded_data <= {8'h33, d7, d6, d5, 4'b0000,
                                         ccode(d3), ccode(d2), ccode(d1), ccode(d0)};
                    end
                end

                // D7..D1,S0 -> type 0x78
                8'b00000001: encoded_data <= {8'h78, d7, d6, d5, d4, d3, d2, d1};

                // I7..I4,D3..D1,Q0 -> type 0x4b
                8'b11110001: encoded_data <= {8'h4b, ccode(d7), ccode(d6), ccode(d5),
                                              ccode(d4), d3, d2, d1, 4'b1111};

                // D7,D6,D5,{Q4|S4},D3,D2,D1,Q0 -> type 0x55 (Q4) / 0x66 (S4)
                8'b00010001: begin
                    if (d4 == CHAR_S) begin
                        encoded_data <= {8'h66, d7, d6, d5, 8'b00001111, d3, d2, d1};
                    end
                    else begin
                        encoded_data <= {8'h55, d7, d6, d5, 8'b11111111, d3, d2, d1};
                    end
                end

                // Any other control pattern has no valid mapping: zero payload
                default: encoded_data <= 64'b0;
            endcase
        end
    end

    assign encoder_data_out = {sync_word, encoded_data};

endmodule
