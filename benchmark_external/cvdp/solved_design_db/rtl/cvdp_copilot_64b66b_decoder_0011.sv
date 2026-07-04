module decoder_64b66b (
    input  logic         clk_in,                 // Clock signal
    input  logic         rst_in,                 // Asynchronous reset (active high)
    input  logic         decoder_data_valid_in,  // Input data valid signal
    input  logic [65:0]  decoder_data_in,        // 66-bit encoded input
    output logic [63:0]  decoder_data_out,       // Decoded 64-bit data output
    output logic [7:0]   decoder_control_out,    // Decoded 8-bit control output
    output logic         sync_error,             // Sync error flag
    output logic         decoder_error_out       // Type field error flag
);

    // ------------------------------------------------------------------
    // Field extraction
    // ------------------------------------------------------------------
    logic [1:0]  sync_header;
    logic [7:0]  type_field;
    logic [63:0] data_in;

    assign sync_header = decoder_data_in[65:64];
    assign type_field  = decoder_data_in[63:56];
    assign data_in     = {8'h00, decoder_data_in[55:0]};

    // ------------------------------------------------------------------
    // Control characters (XGMII representation)
    // ------------------------------------------------------------------
    localparam logic [7:0] CTRL_I = 8'h07; // /I/ Idle
    localparam logic [7:0] CTRL_S = 8'hFB; // /S/ Start of frame
    localparam logic [7:0] CTRL_T = 8'hFD; // /T/ End of frame
    localparam logic [7:0] CTRL_E = 8'hFE; // /E/ Error
    localparam logic [7:0] CTRL_Q = 8'h9C; // /Q/ Ordered set

    // 7-bit control-code -> control character decode
    function automatic logic [7:0] dec_ctrl(input logic [6:0] code);
        case (code)
            7'h00:   dec_ctrl = CTRL_I;
            7'h1E:   dec_ctrl = CTRL_E;
            default: dec_ctrl = CTRL_E;
        endcase
    endfunction

    // ------------------------------------------------------------------
    // Type-field validity
    // ------------------------------------------------------------------
    logic type_valid;
    always_comb begin
        case (type_field)
            8'h1E, 8'h33, 8'h78, 8'h87, 8'h99, 8'hAA, 8'hB4, 8'hCC,
            8'hD2, 8'hE1, 8'hFF, 8'h2D, 8'h4B, 8'h55, 8'h66:
                type_valid = 1'b1;
            default:
                type_valid = 1'b0;
        endcase
    end

    // ------------------------------------------------------------------
    // Input data bytes (8-bit lanes of data_in[55:0])
    // ------------------------------------------------------------------
    logic [7:0] IB0, IB1, IB2, IB3, IB4, IB5, IB6;
    assign IB0 = data_in[7:0];
    assign IB1 = data_in[15:8];
    assign IB2 = data_in[23:16];
    assign IB3 = data_in[31:24];
    assign IB4 = data_in[39:32];
    assign IB5 = data_in[47:40];
    assign IB6 = data_in[55:48];

    // 7-bit code groups (used by the all-control type 0x1E)
    logic [6:0] c0, c1, c2, c3, c4, c5, c6, c7;
    assign c0 = data_in[6:0];
    assign c1 = data_in[13:7];
    assign c2 = data_in[20:14];
    assign c3 = data_in[27:21];
    assign c4 = data_in[34:28];
    assign c5 = data_in[41:35];
    assign c6 = data_in[48:42];
    assign c7 = data_in[55:49];

    // ------------------------------------------------------------------
    // Combinational decode (next outputs)
    // ------------------------------------------------------------------
    logic [63:0] nxt_data;
    logic [7:0]  nxt_ctrl;
    logic        nxt_sync_err;
    logic        nxt_dec_err;

    always_comb begin
        nxt_data     = 64'd0;
        nxt_ctrl     = 8'd0;
        nxt_sync_err = 1'b0;
        nxt_dec_err  = 1'b0;

        case (sync_header)
            // ----------------------- Data-only mode -----------------------
            2'b01: begin
                nxt_data = decoder_data_in[63:0];
                nxt_ctrl = 8'd0;
            end

            // ------------------ Control / mixed mode ----------------------
            2'b10: begin
                if (!type_valid) begin
                    nxt_dec_err = 1'b1; // invalid type field -> decoder error
                end else begin
                    case (type_field)
                        8'h1E: begin
                            nxt_data = {dec_ctrl(c7), dec_ctrl(c6), dec_ctrl(c5), dec_ctrl(c4),
                                        dec_ctrl(c3), dec_ctrl(c2), dec_ctrl(c1), dec_ctrl(c0)};
                            nxt_ctrl = 8'hFF;
                        end
                        8'h33: begin
                            nxt_data = {IB6, IB5, IB4, CTRL_S, CTRL_I, CTRL_I, CTRL_I, CTRL_I};
                            nxt_ctrl = 8'h1F;
                        end
                        8'h78: begin
                            nxt_data = {IB6, IB5, IB4, IB3, IB2, IB1, IB0, CTRL_S};
                            nxt_ctrl = 8'h01;
                        end
                        8'h87: begin
                            nxt_data = {CTRL_I, CTRL_I, CTRL_I, CTRL_I, CTRL_I, CTRL_I, CTRL_I, CTRL_T};
                            nxt_ctrl = 8'hFE;
                        end
                        8'h99: begin
                            nxt_data = {CTRL_I, CTRL_I, CTRL_I, CTRL_I, CTRL_I, CTRL_I, CTRL_T, IB0};
                            nxt_ctrl = 8'hFE;
                        end
                        8'hAA: begin
                            nxt_data = {CTRL_I, CTRL_I, CTRL_I, CTRL_I, CTRL_I, CTRL_T, IB1, IB0};
                            nxt_ctrl = 8'hFC;
                        end
                        8'hB4: begin
                            nxt_data = {CTRL_I, CTRL_I, CTRL_I, CTRL_I, CTRL_T, IB2, IB1, IB0};
                            nxt_ctrl = 8'hF8;
                        end
                        8'hCC: begin
                            nxt_data = {CTRL_I, CTRL_I, CTRL_I, CTRL_T, IB3, IB2, IB1, IB0};
                            nxt_ctrl = 8'hF0;
                        end
                        8'hD2: begin
                            nxt_data = {CTRL_I, CTRL_I, CTRL_T, IB4, IB3, IB2, IB1, IB0};
                            nxt_ctrl = 8'hE0;
                        end
                        8'hE1: begin
                            nxt_data = {CTRL_I, CTRL_T, IB5, IB4, IB3, IB2, IB1, IB0};
                            nxt_ctrl = 8'hC0;
                        end
                        8'hFF: begin
                            nxt_data = {CTRL_T, IB6, IB5, IB4, IB3, IB2, IB1, IB0};
                            nxt_ctrl = 8'h80;
                        end
                        8'h2D: begin
                            nxt_data = {IB6, IB5, IB4, CTRL_Q, CTRL_I, CTRL_I, CTRL_I, CTRL_I};
                            nxt_ctrl = 8'h1F;
                        end
                        8'h4B: begin
                            // Ordered-set block: 3 data bytes occupy data_in[28:5]
                            nxt_data = {CTRL_I, CTRL_I, CTRL_I, CTRL_I,
                                        data_in[28:21], data_in[20:13], data_in[12:5], CTRL_Q};
                            nxt_ctrl = 8'hF1;
                        end
                        8'h55: begin
                            nxt_data = {IB6, IB5, IB4, CTRL_Q, IB2, IB1, IB0, CTRL_Q};
                            nxt_ctrl = 8'h11;
                        end
                        8'h66: begin
                            nxt_data = {IB6, IB5, IB4, CTRL_S, IB2, IB1, IB0, CTRL_Q};
                            nxt_ctrl = 8'h11;
                        end
                        default: begin
                            nxt_data = 64'd0;
                            nxt_ctrl = 8'd0;
                        end
                    endcase
                end
            end

            // -------------------- Invalid sync header ---------------------
            default: begin
                nxt_sync_err = 1'b1;
            end
        endcase
    end

    // ------------------------------------------------------------------
    // Registered outputs (1-cycle latency, async active-high reset)
    // ------------------------------------------------------------------
    always_ff @(posedge clk_in or posedge rst_in) begin
        if (rst_in) begin
            decoder_data_out    <= 64'd0;
            decoder_control_out <= 8'd0;
            sync_error          <= 1'b0;
            decoder_error_out   <= 1'b0;
        end else if (decoder_data_valid_in) begin
            decoder_data_out    <= nxt_data;
            decoder_control_out <= nxt_ctrl;
            sync_error          <= nxt_sync_err;
            decoder_error_out   <= nxt_dec_err;
        end
    end

endmodule
