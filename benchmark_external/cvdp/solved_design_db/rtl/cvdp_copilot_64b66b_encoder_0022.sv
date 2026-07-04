module encoder_64b66b (
    input  logic         clk_in,              // Clock signal
    input  logic         rst_in,              // Asynchronous reset (active high)
    input  logic [63:0]  encoder_data_in,     // 64-bit data input
    input  logic [7:0]   encoder_control_in,  // 8-bit control input
    output logic [65:0]  encoder_data_out     // 66-bit encoded output
);

    // ----------------------------------------------------------------
    // Area-optimized 64b/66b encoder.
    //
    // The original RTL evaluated the same wide pattern comparisons twice:
    // once inside get_output() to produce type_field and again inside the
    // encoded_ctrl_words case statement.  Here every (control, data) pattern
    // is matched exactly ONCE as a shared combinational term and reused for
    // both type_field and encoded_ctrl_words, removing the duplicated
    // comparator/mux network while keeping the one-cycle-latency behaviour.
    // ----------------------------------------------------------------

    logic [63:0] d;
    logic [7:0]  c;
    assign d = encoder_data_in;
    assign c = encoder_control_in;

    // Shared pattern-match terms (combinational on the current inputs).
    logic m_ff_07, m_ff_fe, m_ff_fd;
    logic m_fe, m_fc, m_f8, m_f0, m_e0, m_c0, m_80;
    logic m_1f_fb, m_1f_9c, m_01, m_f1, m_11_9c, m_11_fb;

    assign m_ff_07 = (c == 8'hFF) && (d == 64'h0707070707070707);
    assign m_ff_fe = (c == 8'hFF) && (d == 64'hFEFEFEFEFEFEFEFE);
    assign m_ff_fd = (c == 8'hFF) && (d == 64'h07070707070707FD);
    assign m_fe    = (c == 8'hFE) && (d[63:8]  == 56'h070707070707FD);
    assign m_fc    = (c == 8'hFC) && (d[63:16] == 48'h0707070707FD);
    assign m_f8    = (c == 8'hF8) && (d[63:24] == 40'h07070707FD);
    assign m_f0    = (c == 8'hF0) && (d[63:32] == 32'h070707FD);
    assign m_e0    = (c == 8'hE0) && (d[63:40] == 24'h0707FD);
    assign m_c0    = (c == 8'hC0) && (d[63:48] == 16'h07FD);
    assign m_80    = (c == 8'h80) && (d[63:56] == 8'hFD);
    assign m_1f_fb = (c == 8'h1F) && (d[39:0]  == 40'hFB07070707);
    assign m_1f_9c = (c == 8'h1F) && (d[39:0]  == 40'h9C07070707);
    assign m_01    = (c == 8'h01) && (d[7:0]   == 8'hFB);
    assign m_f1    = (c == 8'hF1) && ({d[63:32], d[7:0]} == 40'h070707079C);
    assign m_11_9c = (c == 8'h11) && ({d[39:32], d[7:0]} == 16'h9C9C);
    assign m_11_fb = (c == 8'h11) && ({d[39:32], d[7:0]} == 16'hFB9C);

    // Combinational next-state for type_field (mirrors get_output priority).
    logic [7:0]  type_field_n;
    always_comb begin
        if      (m_ff_07) type_field_n = 8'h1e;
        else if (m_ff_fe) type_field_n = 8'h1e;
        else if (m_ff_fd) type_field_n = 8'h87;
        else if (m_fe)    type_field_n = 8'h99;
        else if (m_fc)    type_field_n = 8'haa;
        else if (m_f8)    type_field_n = 8'hb4;
        else if (m_f0)    type_field_n = 8'hcc;
        else if (m_e0)    type_field_n = 8'hd2;
        else if (m_c0)    type_field_n = 8'he1;
        else if (m_80)    type_field_n = 8'hff;
        else if (m_1f_fb) type_field_n = 8'h33;
        else if (m_1f_9c) type_field_n = 8'h2d;
        else if (m_01)    type_field_n = 8'h78;
        else if (m_f1)    type_field_n = 8'h4b;
        else if (m_11_9c) type_field_n = 8'h55;
        else if (m_11_fb) type_field_n = 8'h66;
        else              type_field_n = 8'h00;
    end

    // Combinational next-state for encoded_ctrl_words (shares the same terms).
    logic [55:0] ctrl_words_n;
    always_comb begin
        if      (m_ff_fe) ctrl_words_n = 56'h3c78f1e3c78f1e; // {8{7'h1E}}
        else if (m_fe)    ctrl_words_n = {48'h0, d[7:0]};
        else if (m_fc)    ctrl_words_n = {40'h0, d[15:0]};
        else if (m_f8)    ctrl_words_n = {32'h0, d[23:0]};
        else if (m_f0)    ctrl_words_n = {24'h0, d[31:0]};
        else if (m_e0)    ctrl_words_n = {16'h0, d[39:0]};
        else if (m_c0)    ctrl_words_n = { 8'h0, d[47:0]};
        else if (m_80)    ctrl_words_n = d[55:0];
        else if (m_1f_fb) ctrl_words_n = {d[63:40], 32'h0};
        else if (m_1f_9c) ctrl_words_n = {d[63:40], 4'hF, 28'h0};
        else if (m_01)    ctrl_words_n = d[63:8];
        else if (m_f1)    ctrl_words_n = {28'h0, d[31:8], 4'hF};
        else if (m_11_9c) ctrl_words_n = {d[63:40], 8'hFF, d[31:8]};
        else if (m_11_fb) ctrl_words_n = {d[63:40], 8'h0F, d[31:8]};
        else              ctrl_words_n = 56'h0;
    end

    // Registered state (one clock-cycle latency, async active-high reset).
    logic [1:0]  sync_word;
    logic [63:0] encoded_data;
    logic [1:0]  sync_ctrl_word;
    logic [7:0]  type_field;
    logic [55:0] encoded_ctrl_words;

    always_ff @(posedge clk_in or posedge rst_in) begin
        if (rst_in) begin
            sync_word          <= 2'b00;
            encoded_data       <= 64'b0;
            sync_ctrl_word     <= 2'b00;
            type_field         <= 8'b0;
            encoded_ctrl_words <= 56'b0;
        end else begin
            // Data-path state (used when encoder_control_in == 0)
            sync_word    <= (c == 8'b0) ? 2'b01 : 2'b10;
            encoded_data <= (c == 8'b0) ? d     : 64'b0;
            // Control-path state (used when encoder_control_in != 0)
            if (c != 8'b0)
                sync_ctrl_word <= 2'b10;
            type_field         <= type_field_n;
            encoded_ctrl_words <= ctrl_words_n;
        end
    end

    // Output mux: select control vs data framing on the current control bus.
    always_comb begin
        if (|c)
            encoder_data_out = {sync_ctrl_word, type_field, encoded_ctrl_words};
        else
            encoder_data_out = {sync_word, encoded_data};
    end

endmodule
