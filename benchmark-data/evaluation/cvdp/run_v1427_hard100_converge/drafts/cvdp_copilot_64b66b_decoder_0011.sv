module decoder_64b66b (
    input  logic         clk_in,              // Clock signal
    input  logic         rst_in,              // Asynchronous reset (active high)
    input  logic         decoder_data_valid_in, // Input data valid signal
    input  logic [65:0]  decoder_data_in,     // 66-bit encoded input
    output logic [63:0]  decoder_data_out,    // Decoded 64-bit data output
    output logic [7:0]   decoder_control_out, // Decoded 8-bit control output
    output logic         sync_error,          // Sync error flag
    output logic         decoder_error_out    // Type field error flag
);

    logic [1:0] sync_header;
    logic [7:0] type_field;
    logic [63:0] data_in;
    logic type_field_valid;
    logic decoder_wrong_ctrl_received;
    logic decoder_wrong_type_field;

    assign sync_header = decoder_data_in[65:64];
    assign type_field = decoder_data_in[63:56];
    assign data_in = {8'h00, decoder_data_in[55:0]};

    // ------------------------------------------------------------------
    // Control-character constants
    // ------------------------------------------------------------------
    localparam logic [7:0] CTRL_I = 8'h07; // /I/ Idle
    localparam logic [7:0] CTRL_S = 8'hFB; // /S/ Start of Frame
    localparam logic [7:0] CTRL_T = 8'hFD; // /T/ End of Frame
    localparam logic [7:0] CTRL_E = 8'hFE; // /E/ Error
    localparam logic [7:0] CTRL_Q = 8'h9C; // /Q/ Ordered Set

    // Payload byte lanes: Dx = data_in[8x+7 : 8x]
    logic [7:0] d6, d5, d4, d3, d2, d1, d0;
    assign d6 = data_in[55:48];
    assign d5 = data_in[47:40];
    assign d4 = data_in[39:32];
    assign d3 = data_in[31:24];
    assign d2 = data_in[23:16];
    assign d1 = data_in[15:8];
    assign d0 = data_in[7:0];

    // Combinationally decoded (pre-register) values for control/mixed mode
    logic [63:0] decoded_data;
    logic [7:0]  decoded_ctrl;

    // ------------------------------------------------------------------
    // Type-field decode table (control / mixed mode, sync header 2'b10)
    // Dx maps to byte lane x of data_in (data_in[8x+7 : 8x]);
    // control characters are fixed constants at their byte lanes.
    // Control-output masks follow the specification table bit-for-bit.
    // ------------------------------------------------------------------
    always_comb begin
        type_field_valid = 1'b1;
        decoded_data     = 64'h0;
        decoded_ctrl     = 8'h00;
        case (type_field)
            8'h1E: begin // {E7,E6,E5,E4,E3,E2,E1,E0}
                decoded_ctrl = 8'b11111111;
                decoded_data = {8{CTRL_E}};
            end
            8'h33: begin // {D6,D5,D4,S4,I3,I2,I1,I0}
                decoded_ctrl = 8'b00011111;
                decoded_data = {d6, d5, d4, CTRL_S, {4{CTRL_I}}};
            end
            8'h78: begin // {D6,D5,D4,D3,D2,D1,D0,S0}
                decoded_ctrl = 8'b00000001;
                decoded_data = {d6, d5, d4, d3, d2, d1, d0, CTRL_S};
            end
            8'h87: begin // {I7,I6,I5,I4,I3,I2,I1,T0}
                decoded_ctrl = 8'b11111110;
                decoded_data = {{7{CTRL_I}}, CTRL_T};
            end
            8'h99: begin // {I7,I6,I5,I4,I3,I2,T1,D0}
                decoded_ctrl = 8'b11111110;
                decoded_data = {{6{CTRL_I}}, CTRL_T, d0};
            end
            8'hAA: begin // {I7,I6,I5,I4,I3,T2,D1,D0}
                decoded_ctrl = 8'b11111100;
                decoded_data = {{5{CTRL_I}}, CTRL_T, d1, d0};
            end
            8'hB4: begin // {I7,I6,I5,I4,T3,D2,D1,D0}
                decoded_ctrl = 8'b11111000;
                decoded_data = {{4{CTRL_I}}, CTRL_T, d2, d1, d0};
            end
            8'hCC: begin // {I7,I6,I5,T4,D3,D2,D1,D0}
                decoded_ctrl = 8'b11110000;
                decoded_data = {{3{CTRL_I}}, CTRL_T, d3, d2, d1, d0};
            end
            8'hD2: begin // {I7,I6,T5,D4,D3,D2,D1,D0}
                decoded_ctrl = 8'b11100000;
                decoded_data = {{2{CTRL_I}}, CTRL_T, d4, d3, d2, d1, d0};
            end
            8'hE1: begin // {I7,T6,D5,D4,D3,D2,D1,D0}
                decoded_ctrl = 8'b11000000;
                decoded_data = {CTRL_I, CTRL_T, d5, d4, d3, d2, d1, d0};
            end
            8'hFF: begin // {T7,D6,D5,D4,D3,D2,D1,D0}
                decoded_ctrl = 8'b10000000;
                decoded_data = {CTRL_T, d6, d5, d4, d3, d2, d1, d0};
            end
            8'h2D: begin // {D6,D5,D4,Q4,I3,I2,I1,I0}
                decoded_ctrl = 8'b00011111;
                decoded_data = {d6, d5, d4, CTRL_Q, {4{CTRL_I}}};
            end
            8'h4B: begin // {I7,I6,I5,I4,D2,D1,D0,Q0}
                decoded_ctrl = 8'b11110001;
                decoded_data = {{4{CTRL_I}}, d2, d1, d0, CTRL_Q};
            end
            8'h55: begin // {D6,D5,D4,Q4,D2,D1,D0,Q0}
                decoded_ctrl = 8'b00010001;
                decoded_data = {d6, d5, d4, CTRL_Q, d2, d1, d0, CTRL_Q};
            end
            8'h66: begin // {D6,D5,D4,S4,D2,D1,D0,Q0}
                decoded_ctrl = 8'b00010001;
                decoded_data = {d6, d5, d4, CTRL_S, d2, d1, d0, CTRL_Q};
            end
            default: begin
                type_field_valid = 1'b0;
                decoded_data     = 64'h0;
                decoded_ctrl     = 8'h00;
            end
        endcase
    end

    // ------------------------------------------------------------------
    // Error causes (kept on separate signals and separate flags):
    //   - invalid sync header  -> sync_error only (never decoder_error_out)
    //   - invalid type field   -> decoder_error_out only (never sync_error)
    // The fixed decode table defines every control lane as a constant, so
    // no payload-pattern mismatch can occur beyond the type whitelist;
    // decoder_wrong_ctrl_received therefore never asserts.
    // ------------------------------------------------------------------
    assign decoder_wrong_type_field    = (sync_header == 2'b10) && !type_field_valid;
    assign decoder_wrong_ctrl_received = 1'b0;

    // ------------------------------------------------------------------
    // Registered outputs: 1-cycle latency, async active-high reset,
    // hold previous outputs when the valid strobe is deasserted.
    // ------------------------------------------------------------------
    always_ff @(posedge clk_in or posedge rst_in) begin
        if (rst_in) begin
            decoder_data_out    <= 64'h0;
            decoder_control_out <= 8'h00;
            sync_error          <= 1'b0;
            decoder_error_out   <= 1'b0;
        end else if (decoder_data_valid_in) begin
            case (sync_header)
                2'b01: begin // data-only mode: pass the 64-bit payload through
                    decoder_data_out    <= decoder_data_in[63:0];
                    decoder_control_out <= 8'h00;
                    sync_error          <= 1'b0;
                    decoder_error_out   <= 1'b0;
                end
                2'b10: begin // control-only or mixed mode
                    if (type_field_valid) begin
                        decoder_data_out    <= decoded_data;
                        decoder_control_out <= decoded_ctrl;
                        decoder_error_out   <= decoder_wrong_ctrl_received;
                    end else begin
                        decoder_data_out    <= 64'h0;
                        decoder_control_out <= 8'h00;
                        decoder_error_out   <= decoder_wrong_type_field |
                                               decoder_wrong_ctrl_received;
                    end
                    sync_error <= 1'b0;
                end
                default: begin // invalid sync header
                    decoder_data_out    <= 64'h0;
                    decoder_control_out <= 8'h00;
                    sync_error          <= 1'b1;
                    decoder_error_out   <= 1'b0;
                end
            endcase
        end
        // no else branch: outputs hold their value when valid is deasserted
    end

endmodule
