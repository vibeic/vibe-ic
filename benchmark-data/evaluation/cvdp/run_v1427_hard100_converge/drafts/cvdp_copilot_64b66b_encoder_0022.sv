// ---------------------------------------------------------------------------
// encoder_64b66b — area-optimized implementation (functionally equivalent).
//
// Optimization strategy (structural, survives synthesis):
//   1. Shared pattern comparators. The original compared the same data bytes
//      against the same constants twice — once inside the get_output()
//      function and once inside the encoded_ctrl_words case statement, using
//      wide (16..64-bit) comparators. All encoding conditions are now derived
//      from ONE set of per-byte comparators (byte == 0x07 / 0xFD) plus a
//      single prefix-AND chain for the leading 0x07 runs, so every input byte
//      is compared against every constant exactly once and each wide pattern
//      is just a 2-3 input AND of shared terms.
//   2. Merged result registers. The original held three result registers —
//      encoded_data (64b), type_field (8b) and encoded_ctrl_words (56b) —
//      that are mutually exclusive by construction: when the registered
//      control is zero the {type_field, encoded_ctrl_words} pair is all-zero,
//      and when it is non-zero encoded_data is all-zero. They are merged into
//      ONE shared 64-bit payload register (132 -> 68 flops), and the original
//      register values are reconstructed through the already-registered
//      sync_word qualifier bits.
//   3. Flat select planes. The two long priority chains (16-branch function,
//      12-branch case) are replaced by flat AND-OR planes over the mutually
//      exclusive match terms.
//
// Interface, module name, one-clock-cycle latency, asynchronous reset
// behaviour and every encoding condition — including the 56'hFFFFFFF
// fall-back for control 8'b11110000 and the hold behaviour of
// sync_ctrl_word — are bit-identical to the original module.
// ---------------------------------------------------------------------------
module encoder_64b66b (
    input  logic         clk_in,              // Clock signal
    input  logic         rst_in,              // Asynchronous reset (active high)
    input  logic [63:0]  encoder_data_in,     // 64-bit data input
    input  logic [7:0]   encoder_control_in,  // 8-bit control input
    output logic [65:0]  encoder_data_out     // 66-bit encoded output
);

    // ------------------------------------------------------------------
    // Shared per-byte pattern comparators (each byte compared once).
    // ------------------------------------------------------------------
    wire [7:0] byte_is_07;   // byte k == 8'h07
    wire [7:0] byte_is_fd;   // byte k == 8'hFD
    generate
        genvar gi;
        for (gi = 0; gi < 8; gi = gi + 1) begin : g_bytecmp
            assign byte_is_07[gi] = (encoder_data_in[8*gi +: 8] == 8'h07);
            assign byte_is_fd[gi] = (encoder_data_in[8*gi +: 8] == 8'hFD);
        end
    endgenerate

    // Prefix runs: run07[k] == "bytes 7 down to k are all 0x07".
    wire [7:1] run07;
    assign run07[7] = byte_is_07[7];
    assign run07[6] = run07[7] & byte_is_07[6];
    assign run07[5] = run07[6] & byte_is_07[5];
    assign run07[4] = run07[5] & byte_is_07[4];
    assign run07[3] = run07[4] & byte_is_07[3];
    assign run07[2] = run07[3] & byte_is_07[2];
    assign run07[1] = run07[2] & byte_is_07[1];
    wire all_07  = run07[1] & byte_is_07[0];
    wire low4_07 = byte_is_07[3] & byte_is_07[2] & byte_is_07[1] & byte_is_07[0];

    wire all_fe = (encoder_data_in == 64'hFEFEFEFEFEFEFEFE);
    wire b4_fb  = (encoder_data_in[39:32] == 8'hFB);
    wire b4_9c  = (encoder_data_in[39:32] == 8'h9C);
    wire b0_fb  = (encoder_data_in[7:0]   == 8'hFB);
    wire b0_9c  = (encoder_data_in[7:0]   == 8'h9C);

    // ------------------------------------------------------------------
    // Control decodes (shared by every match term).
    // ------------------------------------------------------------------
    wire ctrl_zero = (encoder_control_in == 8'b00000000);
    wire c_ff = (encoder_control_in == 8'b11111111);
    wire c_1f = (encoder_control_in == 8'b00011111);
    wire c_01 = (encoder_control_in == 8'b00000001);
    wire c_fe = (encoder_control_in == 8'b11111110);
    wire c_fc = (encoder_control_in == 8'b11111100);
    wire c_f8 = (encoder_control_in == 8'b11111000);
    wire c_f0 = (encoder_control_in == 8'b11110000);
    wire c_e0 = (encoder_control_in == 8'b11100000);
    wire c_c0 = (encoder_control_in == 8'b11000000);
    wire c_80 = (encoder_control_in == 8'b10000000);
    wire c_f1 = (encoder_control_in == 8'b11110001);
    wire c_11 = (encoder_control_in == 8'b00010001);

    // ------------------------------------------------------------------
    // Encoding-condition matches (pairwise mutually exclusive).
    // ------------------------------------------------------------------
    wire m_idle   = c_ff & all_07;                    // type 8'h1e
    wire m_allfe  = c_ff & all_fe;                    // type 8'h1e
    wire m_term8  = c_ff & run07[1] & byte_is_fd[0];  // type 8'h87
    wire m_st4_fb = c_1f & b4_fb & low4_07;           // type 8'h33
    wire m_st4_9c = c_1f & b4_9c & low4_07;           // type 8'h2d
    wire m_st0    = c_01 & b0_fb;                     // type 8'h78
    wire m_term7  = c_fe & run07[2] & byte_is_fd[1];  // type 8'h99
    wire m_term6  = c_fc & run07[3] & byte_is_fd[2];  // type 8'haa
    wire m_term5  = c_f8 & run07[4] & byte_is_fd[3];  // type 8'hb4
    wire m_term4  = c_f0 & run07[5] & byte_is_fd[4];  // type 8'hcc
    wire m_term3  = c_e0 & run07[6] & byte_is_fd[5];  // type 8'hd2
    wire m_term2  = c_c0 & run07[7] & byte_is_fd[6];  // type 8'he1
    wire m_term1  = c_80 & byte_is_fd[7];             // type 8'hff
    wire m_ord4   = c_f1 & run07[4] & b0_9c;          // type 8'h4b
    wire m_ord0a  = c_11 & b4_9c & b0_9c;             // type 8'h55
    wire m_ord0b  = c_11 & b4_fb & b0_9c;             // type 8'h66

    // ------------------------------------------------------------------
    // Flat AND-OR select planes (valid because matches are exclusive).
    // ------------------------------------------------------------------
    wire [7:0] type_code =
          ({8{m_idle | m_allfe}} & 8'h1e)
        | ({8{m_term8 }} & 8'h87)
        | ({8{m_st4_fb}} & 8'h33)
        | ({8{m_st4_9c}} & 8'h2d)
        | ({8{m_st0   }} & 8'h78)
        | ({8{m_term7 }} & 8'h99)
        | ({8{m_term6 }} & 8'haa)
        | ({8{m_term5 }} & 8'hb4)
        | ({8{m_term4 }} & 8'hcc)
        | ({8{m_term3 }} & 8'hd2)
        | ({8{m_term2 }} & 8'he1)
        | ({8{m_term1 }} & 8'hff)
        | ({8{m_ord4  }} & 8'h4b)
        | ({8{m_ord0a }} & 8'h55)
        | ({8{m_ord0b }} & 8'h66);

    wire [55:0] ctrl_words =
          ({56{m_allfe }} & {8{7'h1E}})
        | ({56{m_st4_fb}} & {encoder_data_in[63:40], 32'h00000000})
        | ({56{m_st4_9c}} & {encoder_data_in[63:40], 4'hF, 28'h0000000})
        | ({56{m_st0   }} & encoder_data_in[63:8])
        | ({56{m_term7 }} & {48'h000000000000, encoder_data_in[7:0]})
        | ({56{m_term6 }} & {40'h0000000000, encoder_data_in[15:0]})
        | ({56{m_term5 }} & {32'h00000000, encoder_data_in[23:0]})
        | ({56{m_term4 }} & {24'h000000, encoder_data_in[31:0]})
        | ({56{m_term3 }} & {16'h0000, encoder_data_in[39:0]})
        | ({56{m_term2 }} & {8'h00, encoder_data_in[47:0]})
        | ({56{m_term1 }} & encoder_data_in[55:0])
        | ({56{m_ord4  }} & {28'h0000000, encoder_data_in[31:8], 4'hF})
        | ({56{m_ord0a }} & {encoder_data_in[63:40], 8'hFF, encoder_data_in[31:8]})
        | ({56{m_ord0b }} & {encoder_data_in[63:40], 8'h0F, encoder_data_in[31:8]})
        | ({56{c_f0 & ~m_term4}} & 56'h0000000FFFFFFF); // original F0 fall-back

    // ------------------------------------------------------------------
    // Merged sequential stage (one clock cycle latency, async reset).
    // {type_code, ctrl_words} is all-zero whenever ctrl_zero holds, so the
    // data and control payloads share one 64-bit register.
    // ------------------------------------------------------------------
    wire [63:0] payload_next =
          ({64{ctrl_zero}} & encoder_data_in)  // data payload (idle control)
        | {type_code, ctrl_words};             // control payload

    logic [63:0] payload_q;
    logic [1:0]  sync_word;
    logic [1:0]  sync_ctrl_word;

    always_ff @(posedge clk_in or posedge rst_in) begin
        if (rst_in) begin
            payload_q      <= 64'h0;
            sync_word      <= 2'b00;
            sync_ctrl_word <= 2'b00;
        end else begin
            payload_q <= payload_next;
            sync_word <= ctrl_zero ? 2'b01 : 2'b10;
            if (!ctrl_zero)
                sync_ctrl_word <= 2'b10;   // holds its value while control is idle
        end
    end

    // Original register views, reconstructed bit-identically from the shared
    // payload through the registered sync_word qualifiers.
    wire [63:0] encoded_data       = sync_word[0] ? payload_q        : 64'h0;
    wire [7:0]  type_field         = sync_word[1] ? payload_q[63:56] : 8'h0;
    wire [55:0] encoded_ctrl_words = sync_word[1] ? payload_q[55:0]  : 56'h0;

    always_comb begin
        if (|encoder_control_in)
            encoder_data_out = {sync_ctrl_word, type_field, encoded_ctrl_words};
        else
            encoder_data_out = {sync_word, encoded_data};
    end

endmodule
