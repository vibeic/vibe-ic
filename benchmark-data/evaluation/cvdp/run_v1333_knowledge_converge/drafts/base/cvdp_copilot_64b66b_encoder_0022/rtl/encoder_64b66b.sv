module encoder_64b66b (
    input  logic         clk_in,              // Clock signal
    input  logic         rst_in,              // Asynchronous reset (active high)
    input  logic [63:0]  encoder_data_in,     // 64-bit data input
    input  logic [7:0]   encoder_control_in,  // 8-bit control input
    output logic [65:0]  encoder_data_out     // 66-bit encoded output
);

    // Registered state (one clock cycle latency preserved)
    logic [1:0]  sync_word;
    logic [63:0] encoded_data;
    logic [1:0]  sync_ctrl_word;
    logic [7:0]  type_field;
    logic [55:0] encoded_ctrl_words;

    // -----------------------------------------------------------------
    // Shared data-pattern predicates.
    // These comparators were previously duplicated inside get_output()
    // (feeding type_field) and inside the encoded_ctrl_words case block.
    // Computing them once lets the synthesizer share the (wide) equality
    // comparators, cutting both cell and wire utilization.
    // -----------------------------------------------------------------
    logic p_all07, p_allFE, p_07FD;
    logic p_FB0707, p_9C0707;
    logic p_FB;
    logic p_56FD, p_48FD, p_40FD, p_32FD, p_24FD, p_16FD, p_08FD;
    logic p_9Chi, p_9C9C, p_FB9C;

    assign p_all07  = (encoder_data_in        == 64'h0707070707070707);
    assign p_allFE  = (encoder_data_in        == 64'hFEFEFEFEFEFEFEFE);
    assign p_07FD   = (encoder_data_in        == 64'h07070707070707FD);
    assign p_FB0707 = (encoder_data_in[39:0]  == 40'hFB07070707);
    assign p_9C0707 = (encoder_data_in[39:0]  == 40'h9C07070707);
    assign p_FB     = (encoder_data_in[7:0]   == 8'hFB);
    assign p_56FD   = (encoder_data_in[63:8]  == 56'h070707070707FD);
    assign p_48FD   = (encoder_data_in[63:16] == 48'h0707070707FD);
    assign p_40FD   = (encoder_data_in[63:24] == 40'h07070707FD);
    assign p_32FD   = (encoder_data_in[63:32] == 32'h070707FD);
    assign p_24FD   = (encoder_data_in[63:40] == 24'h0707FD);
    assign p_16FD   = (encoder_data_in[63:48] == 16'h07FD);
    assign p_08FD   = (encoder_data_in[63:56] == 8'hFD);
    assign p_9Chi   = ({encoder_data_in[63:32], encoder_data_in[7:0]}  == 40'h070707079C);
    assign p_9C9C   = ({encoder_data_in[39:32], encoder_data_in[7:0]}  == 16'h9C9C);
    assign p_FB9C   = ({encoder_data_in[39:32], encoder_data_in[7:0]}  == 16'hFB9C);

    logic ctrl_zero;
    assign ctrl_zero = (encoder_control_in == 8'b00000000);

    // -----------------------------------------------------------------
    // type_field next value (equivalent to the original get_output()).
    // Reuses the shared predicates above instead of re-instantiating the
    // wide comparators.
    // -----------------------------------------------------------------
    logic [7:0] type_field_n;
    always_comb begin
        if      (p_all07  && encoder_control_in == 8'hFF) type_field_n = 8'h1e;
        else if (p_allFE  && encoder_control_in == 8'hFF) type_field_n = 8'h1e;
        else if (p_07FD   && encoder_control_in == 8'hFF) type_field_n = 8'h87;
        else if (p_FB0707 && encoder_control_in == 8'h1F) type_field_n = 8'h33;
        else if (p_9C0707 && encoder_control_in == 8'h1F) type_field_n = 8'h2d;
        else if (p_FB     && encoder_control_in == 8'h01) type_field_n = 8'h78;
        else if (p_56FD   && encoder_control_in == 8'hFE) type_field_n = 8'h99;
        else if (p_48FD   && encoder_control_in == 8'hFC) type_field_n = 8'haa;
        else if (p_40FD   && encoder_control_in == 8'hF8) type_field_n = 8'hb4;
        else if (p_32FD   && encoder_control_in == 8'hF0) type_field_n = 8'hcc;
        else if (p_24FD   && encoder_control_in == 8'hE0) type_field_n = 8'hd2;
        else if (p_16FD   && encoder_control_in == 8'hC0) type_field_n = 8'he1;
        else if (p_08FD   && encoder_control_in == 8'h80) type_field_n = 8'hff;
        else if (p_9Chi   && encoder_control_in == 8'hF1) type_field_n = 8'h4b;
        else if (p_9C9C   && encoder_control_in == 8'h11) type_field_n = 8'h55;
        else if (p_FB9C   && encoder_control_in == 8'h11) type_field_n = 8'h66;
        else                                              type_field_n = 8'h00;
    end

    // -----------------------------------------------------------------
    // encoded_ctrl_words next value (equivalent to the original case).
    // Concatenations of constant 7'h00 fields collapsed to zero-extends.
    // The 8'hF0 non-match default of 56'hFFFFFFF is preserved verbatim.
    // -----------------------------------------------------------------
    logic [55:0] encoded_ctrl_words_n;
    always_comb begin
        case (encoder_control_in)
            8'hFF: encoded_ctrl_words_n = p_allFE  ? {8{7'h1E}} : 56'h0000000;
            8'h1F: encoded_ctrl_words_n = p_FB0707 ? {encoder_data_in[63:40], 32'h0} :
                                          p_9C0707 ? {encoder_data_in[63:40], 4'hF, 28'h0} :
                                                     56'h0000000;
            8'h01: encoded_ctrl_words_n = p_FB   ? encoder_data_in[63:8]            : 56'h0000000;
            8'hFE: encoded_ctrl_words_n = p_56FD ? {48'h0, encoder_data_in[7:0]}    : 56'h0000000;
            8'hFC: encoded_ctrl_words_n = p_48FD ? {40'h0, encoder_data_in[15:0]}   : 56'h0000000;
            8'hF8: encoded_ctrl_words_n = p_40FD ? {32'h0, encoder_data_in[23:0]}   : 56'h0000000;
            8'hF0: encoded_ctrl_words_n = p_32FD ? {24'h0, encoder_data_in[31:0]}   : 56'hFFFFFFF;
            8'hE0: encoded_ctrl_words_n = p_24FD ? {16'h0, encoder_data_in[39:0]}   : 56'h0000000;
            8'hC0: encoded_ctrl_words_n = p_16FD ? {8'h0,  encoder_data_in[47:0]}   : 56'h0000000;
            8'h80: encoded_ctrl_words_n = p_08FD ? encoder_data_in[55:0]            : 56'h0000000;
            8'hF1: encoded_ctrl_words_n = p_9Chi ? {28'h0, encoder_data_in[31:8], 4'b1111} : 56'h0000000;
            8'h11: encoded_ctrl_words_n = p_9C9C ? {encoder_data_in[63:40], 8'hFF, encoder_data_in[31:8]} :
                                          p_FB9C ? {encoder_data_in[63:40], 8'h0F, encoder_data_in[31:8]} :
                                                   56'd0;
            default: encoded_ctrl_words_n = 56'd0;
        endcase
    end

    // -----------------------------------------------------------------
    // Single sequential block (merged from four). sync_ctrl_word retains
    // its hold-on-ctrl-zero behavior (only updated when control != 0).
    // -----------------------------------------------------------------
    always_ff @(posedge clk_in or posedge rst_in) begin
        if (rst_in) begin
            sync_word          <= 2'b00;
            encoded_data       <= 64'b0;
            sync_ctrl_word     <= 2'b00;
            type_field         <= 8'b0;
            encoded_ctrl_words <= 56'b0;
        end else begin
            sync_word          <= ctrl_zero ? 2'b01 : 2'b10;
            encoded_data       <= ctrl_zero ? encoder_data_in : 64'b0;
            type_field         <= type_field_n;
            encoded_ctrl_words <= encoded_ctrl_words_n;
            if (!ctrl_zero)
                sync_ctrl_word <= 2'b10;
        end
    end

    // Output multiplexer (unchanged behavior)
    always_comb begin
        if (|encoder_control_in)
            encoder_data_out = {sync_ctrl_word, type_field, encoded_ctrl_words};
        else
            encoder_data_out = {sync_word, encoded_data};
    end

endmodule
