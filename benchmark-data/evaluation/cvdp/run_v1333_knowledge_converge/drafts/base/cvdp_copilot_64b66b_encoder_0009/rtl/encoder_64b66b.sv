module encoder_64b66b (
    input  logic         clk_in,              // Clock signal
    input  logic         rst_in,              // Asynchronous reset (active high)
    input  logic [63:0]  encoder_data_in,     // 64-bit data input
    input  logic [7:0]   encoder_control_in,  // 8-bit control input
    output logic [65:0]  encoder_data_out     // 66-bit encoded output
);

    // ---------------------------------------------------------------------
    // Byte views of the 64-bit input (b7 is the most-significant byte)
    // ---------------------------------------------------------------------
    logic [7:0] b0, b1, b2, b3, b4, b5, b6, b7;
    assign b0 = encoder_data_in[7:0];
    assign b1 = encoder_data_in[15:8];
    assign b2 = encoder_data_in[23:16];
    assign b3 = encoder_data_in[31:24];
    assign b4 = encoder_data_in[39:32];
    assign b5 = encoder_data_in[47:40];
    assign b6 = encoder_data_in[55:48];
    assign b7 = encoder_data_in[63:56];

    // ---------------------------------------------------------------------
    // 7-bit control-code lookup for a single byte
    //   /I/ (Idle)  0x07 -> 7'h00
    //   /E/ (Error) 0xfe -> 7'h1e
    //   others (default) -> 7'h00
    // ---------------------------------------------------------------------
    function automatic logic [6:0] ctrl_code (input logic [7:0] x);
        case (x)
            8'h07:   ctrl_code = 7'h00; // Idle
            8'hfe:   ctrl_code = 7'h1e; // Error
            default: ctrl_code = 7'h00;
        endcase
    endfunction

    logic [6:0] c0, c1, c2, c3, c4, c5, c6, c7;
    assign c0 = ctrl_code(b0);
    assign c1 = ctrl_code(b1);
    assign c2 = ctrl_code(b2);
    assign c3 = ctrl_code(b3);
    assign c4 = ctrl_code(b4);
    assign c5 = ctrl_code(b5);
    assign c6 = ctrl_code(b6);
    assign c7 = ctrl_code(b7);

    // Special control-character values in the data stream
    localparam logic [7:0] START = 8'hfb; // /S/  Start of Frame
    localparam logic [7:0] TERM  = 8'hfd; // /T/  End   of Frame
    localparam logic [7:0] OSET  = 8'h9c; // /Q/  Ordered Set

    // ---------------------------------------------------------------------
    // Combinational next-value computation
    // ---------------------------------------------------------------------
    logic [1:0]  sync_n;
    logic [7:0]  type_n;
    logic [55:0] payload_n;
    logic [63:0] low64_n;

    always_comb begin
        // defaults
        sync_n    = 2'b10;
        type_n    = 8'h1e;
        payload_n = {c7, c6, c5, c4, c3, c2, c1, c0};
        low64_n   = 64'h0;

        if (encoder_control_in == 8'h00) begin
            // ----------------------------------------------------------
            // Data-only mode : sync 2'b01, full 64 bits are data,
            // no type field.
            // ----------------------------------------------------------
            sync_n  = 2'b01;
            low64_n = encoder_data_in;
        end
        else begin
            // ----------------------------------------------------------
            // Control-only / mixed mode : sync 2'b10, 8-bit type field,
            // 56-bit encoded payload.
            // ----------------------------------------------------------
            sync_n = 2'b10;

            if (encoder_control_in == 8'hff) begin
                // All bytes are control characters (Idle / Error).
                // Eight 7-bit control codes packed into 56 bits.
                type_n    = 8'h1e;
                payload_n = {c7, c6, c5, c4, c3, c2, c1, c0};
            end
            // ----- Terminate /T/ blocks (lowest terminate lane wins) ---
            else if (encoder_control_in[0] && (b0 == TERM)) begin
                type_n    = 8'h87;
                payload_n = {c7, c6, c5, c4, c3, c2, c1, 7'b0000000};
            end
            else if (encoder_control_in[1] && (b1 == TERM)) begin
                type_n    = 8'h99;
                payload_n = {c7, c6, c5, c4, c3, c2, 6'b000000, b0};
            end
            else if (encoder_control_in[2] && (b2 == TERM)) begin
                type_n    = 8'haa;
                payload_n = {c7, c6, c5, c4, c3, 5'b00000, b1, b0};
            end
            else if (encoder_control_in[3] && (b3 == TERM)) begin
                type_n    = 8'hb4;
                payload_n = {c7, c6, c5, c4, 4'b0000, b2, b1, b0};
            end
            else if (encoder_control_in[4] && (b4 == TERM)) begin
                type_n    = 8'hcc;
                payload_n = {c7, c6, c5, 3'b000, b3, b2, b1, b0};
            end
            else if (encoder_control_in[5] && (b5 == TERM)) begin
                type_n    = 8'hd2;
                payload_n = {c7, c6, 2'b00, b4, b3, b2, b1, b0};
            end
            else if (encoder_control_in[6] && (b6 == TERM)) begin
                type_n    = 8'he1;
                payload_n = {c7, 1'b0, b5, b4, b3, b2, b1, b0};
            end
            else if (encoder_control_in[7] && (b7 == TERM)) begin
                type_n    = 8'hff;
                payload_n = {b6, b5, b4, b3, b2, b1, b0};
            end
            // ----- Start /S/ blocks -----------------------------------
            else if (encoder_control_in[0] && (b0 == START)) begin
                type_n    = 8'h78;
                payload_n = {b7, b6, b5, b4, b3, b2, b1};
            end
            else if (encoder_control_in[4] && (b4 == START)) begin
                if (encoder_control_in[0] && (b0 == OSET)) begin
                    // Start at lane4 with an ordered set at lane0
                    type_n    = 8'h66;
                    payload_n = {b7, b6, b5, 8'b00001111, b3, b2, b1};
                end
                else begin
                    // Start at lane4 with idles below
                    type_n    = 8'h33;
                    payload_n = {b7, b6, b5, 4'b0000, c3, c2, c1, c0};
                end
            end
            // ----- Ordered-set /Q/ blocks -----------------------------
            else if (encoder_control_in[4] && (b4 == OSET) &&
                     encoder_control_in[0] && (b0 == OSET)) begin
                type_n    = 8'h55;
                payload_n = {b7, b6, b5, 8'b11111111, b3, b2, b1};
            end
            else if (encoder_control_in[4] && (b4 == OSET)) begin
                type_n    = 8'h2d;
                payload_n = {b7, b6, b5, 4'b1111, c3, c2, c1, c0};
            end
            else if (encoder_control_in[0] && (b0 == OSET)) begin
                type_n    = 8'h4b;
                payload_n = {c7, c6, c5, c4, b3, b2, b1, 4'b1111};
            end
            // ----- Fallback : pack every byte as a 7-bit control code --
            else begin
                type_n    = 8'h1e;
                payload_n = {c7, c6, c5, c4, c3, c2, c1, c0};
            end

            low64_n = {type_n, payload_n};
        end
    end

    // ---------------------------------------------------------------------
    // Output register : 1-clock latency, async active-high reset
    // ---------------------------------------------------------------------
    always_ff @(posedge clk_in or posedge rst_in) begin
        if (rst_in) begin
            encoder_data_out <= 66'b0;
        end
        else begin
            encoder_data_out <= {sync_n, low64_n};
        end
    end

endmodule
