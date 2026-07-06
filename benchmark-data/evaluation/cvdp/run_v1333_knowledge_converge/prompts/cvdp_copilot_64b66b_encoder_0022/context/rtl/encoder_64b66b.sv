module encoder_64b66b (
    input  logic         clk_in,              // Clock signal
    input  logic         rst_in,              // Asynchronous reset (active high)
    input  logic [63:0]  encoder_data_in,     // 64-bit data input
    input  logic [7:0]   encoder_control_in,  // 8-bit control input
    output logic [65:0]  encoder_data_out     // 66-bit encoded output
);

    logic [1:0]  sync_word;
    logic [63:0] encoded_data;

    // Synchronize sync_word based on encoder_control_in
    always_ff @(posedge clk_in or posedge rst_in) begin
        if (rst_in) begin
            sync_word <= 2'b00;
        end else begin
            if (encoder_control_in == 8'b00000000) begin
                sync_word <= 2'b01;
            end else begin
                sync_word <= 2'b10;
            end
        end
    end

    // Synchronize encoded_data based on encoder_control_in
    always_ff @(posedge clk_in or posedge rst_in) begin
        if (rst_in) begin
            encoded_data <= 64'b0;
        end else begin
            if (encoder_control_in == 8'b00000000) begin
                encoded_data <= encoder_data_in;
            end else begin
                encoded_data <= 64'b0;
            end
        end
    end

    // Function to determine the output based on control and data inputs
    function [7:0] get_output(input [63:0] data_in, input [7:0] control_input);
        if (data_in == 64'h0707070707070707 && control_input == 8'b11111111) get_output = 8'h1e;
        else if (data_in == 64'hFEFEFEFEFEFEFEFE && control_input == 8'b11111111) get_output = 8'h1e;
        else if (data_in == 64'h07070707070707FD && control_input == 8'b11111111) get_output = 8'h87;
        else if (data_in[39:0] == 40'hFB07070707 && control_input == 8'b00011111) get_output = 8'h33;
        else if (data_in[39:0] == 40'h9C07070707 && control_input == 8'b00011111) get_output = 8'h2d;
        else if (data_in[7:0] == 8'hFB && control_input == 8'b00000001) get_output = 8'h78;
        else if (data_in[63:8] == 56'h070707070707FD && control_input == 8'b11111110) get_output = 8'h99;
        else if (data_in[63:16] == 48'h0707070707FD && control_input == 8'b11111100) get_output = 8'haa;
        else if (data_in[63:24] == 40'h07070707FD && control_input == 8'b11111000) get_output = 8'hb4;
        else if (data_in[63:32] == 32'h070707FD && control_input == 8'b11110000) get_output = 8'hcc;
        else if (data_in[63:40] == 24'h0707FD && control_input == 8'b11100000) get_output = 8'hd2;
        else if (data_in[63:48] == 16'h07FD && control_input == 8'b11000000) get_output = 8'he1;
        else if (data_in[63:56] == 8'hFD && control_input == 8'b10000000) get_output = 8'hff;
        else if ({data_in[63:32], data_in[7:0]} == 40'h070707079C && control_input == 8'b11110001) get_output = 8'h4b;
        else if ({data_in[39:32], data_in[7:0]} == 16'h9C9C && control_input == 8'b00010001) get_output = 8'h55;
        else if ({data_in[39:32], data_in[7:0]} == 16'hFB9C && control_input == 8'b00010001) get_output = 8'h66;
        else get_output = 8'b0;
    endfunction

    logic [1:0] sync_ctrl_word;
    logic [7:0] type_field;
    logic [55:0] encoded_ctrl_words;

    // Synchronize sync_ctrl_word, type_field, and encoded_ctrl_words based on encoder_control_in
    always @(posedge clk_in or posedge rst_in) begin
        if (rst_in) begin
            encoded_ctrl_words <= 56'b0;
        end else begin
            case (encoder_control_in)
                8'b11111111: begin
                    if (encoder_data_in == 64'h0707070707070707) encoded_ctrl_words <= {7'h00, 7'h00, 7'h00, 7'h00, 7'h00, 7'h00, 7'h00, 7'h00};
                    else if (encoder_data_in == 64'hFEFEFEFEFEFEFEFE) encoded_ctrl_words <= {7'h1E, 7'h1E, 7'h1E, 7'h1E, 7'h1E, 7'h1E, 7'h1E, 7'h1E};
                    else if (encoder_data_in == 64'h07070707070707FD) encoded_ctrl_words <= {7'h00, 7'h00, 7'h00, 7'h00, 7'h00, 7'h00, 7'h00, 7'h00};
                    else encoded_ctrl_words <= 56'h0000000;
                end
                8'b00011111: begin
                    if (encoder_data_in[39:0] == 40'hFB07070707) encoded_ctrl_words <= {encoder_data_in[63:40], 4'h0, 7'h00, 7'h00, 7'h00, 7'h00};
                    else if (encoder_data_in[39:0] == 40'h9C07070707) encoded_ctrl_words <= {encoder_data_in[63:40], 4'hF, 7'h00, 7'h00, 7'h00, 7'h00};
                    else encoded_ctrl_words <= 56'h0000000;
                end
                8'b00000001: begin
                    if (encoder_data_in[7:0] == 8'hFB) encoded_ctrl_words <= {encoder_data_in[63:8]};
                    else encoded_ctrl_words <= 56'h0000000;
                end
                8'b11111110: begin
                    if (encoder_data_in[63:8] == 56'h070707070707FD) encoded_ctrl_words <= {7'h00, 7'h00, 7'h00, 7'h00, 7'h00, 7'h00, 6'b000000, encoder_data_in[7:0]};
                    else encoded_ctrl_words <= 56'h0000000;
                end
                8'b11111100: begin
                    if (encoder_data_in[63:16] == 48'h0707070707FD) encoded_ctrl_words <= {7'h00, 7'h00, 7'h00, 7'h00, 7'h00, 5'b00000, encoder_data_in[15:0]};
                    else encoded_ctrl_words <= 56'h0000000;
                end
                8'b11111000: begin
                    if (encoder_data_in[63:24] == 40'h07070707FD) encoded_ctrl_words <= {7'h00, 7'h00, 7'h00, 7'h00, 4'b0000, encoder_data_in[23:0]};
                    else encoded_ctrl_words <= 56'h0000000;
                end
                8'b11110000: begin
                    if (encoder_data_in[63:32] == 32'h070707FD) encoded_ctrl_words <= {7'h00, 7'h00, 7'h00, 3'b000, encoder_data_in[31:0]};
                    else encoded_ctrl_words <= 56'hFFFFFFF;
                end
                8'b11100000: begin
                    if (encoder_data_in[63:40] == 24'h0707FD) encoded_ctrl_words <= {7'h00, 7'h00, 2'b00, encoder_data_in[39:0]};
                    else encoded_ctrl_words <= 56'h0000000;
                end
                8'b11000000: begin
                    if (encoder_data_in[63:48] == 16'h07FD) encoded_ctrl_words <= {7'h00, 1'b0, encoder_data_in[47:0]};
                    else encoded_ctrl_words <= 56'h0000000;
                end
                8'b10000000: begin
                    if (encoder_data_in[63:56] == 8'hFD) encoded_ctrl_words <= encoder_data_in[55:0];
                    else encoded_ctrl_words <= 56'h0000000;
                end
                8'b11110001: begin
                    if ({encoder_data_in[63:32], encoder_data_in[7:0]} == 40'h070707079C) encoded_ctrl_words <= {7'h00, 7'h00, 7'h00, 7'h00, encoder_data_in[31:8], 4'b1111};
                    else encoded_ctrl_words <= 56'h0000000;
                end
                8'b00010001: begin
                    if ({encoder_data_in[39:32], encoder_data_in[7:0]} == 16'h9C9C) encoded_ctrl_words <= {encoder_data_in[63:40], 8'hFF, encoder_data_in[31:8]};
                    else if ({encoder_data_in[39:32], encoder_data_in[7:0]} == 16'hFB9C) encoded_ctrl_words <= {encoder_data_in[63:40], 8'h0F, encoder_data_in[31:8]};
                    else encoded_ctrl_words <= 56'd0;
                end
                default: encoded_ctrl_words <= 56'd0;
            endcase
        end
    end

    always @(posedge clk_in or posedge rst_in) begin
        if (rst_in) begin
            sync_ctrl_word <= 2'b00;
            type_field <= 8'b0;
        end else begin
            if (encoder_control_in != 8'b00000000)
                sync_ctrl_word <= 2'b10;
            type_field <= get_output(encoder_data_in, encoder_control_in);
        end
    end

    always_comb begin
        if (|encoder_control_in)
            encoder_data_out = {sync_ctrl_word, type_field, encoded_ctrl_words};
        else
            encoder_data_out = {sync_word, encoded_data};
    end

endmodule