module encoder_64b66b (
    input  logic         clk_in,              // Clock signal
    input  logic         rst_in,              // Asynchronous reset (active high)
    input  logic [63:0]  encoder_data_in,     // 64-bit data input
    input  logic [7:0]   encoder_control_in,  // 8-bit control input
    output logic [65:0]  encoder_data_out     // 66-bit encoded output
);

    logic [1:0] sync_word;     
    logic [63:0] encoded_data; 

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

    always_ff @(posedge clk_in or posedge rst_in) begin
        if (rst_in) begin
            encoded_data <= 64'b0;         
        end 
        else begin
            if (encoder_control_in == 8'b00000000) begin
                encoded_data <= encoder_data_in; 
            end
            else begin
                encoded_data <= 64'b0; 
            end
        end
    end

    assign encoder_data_out = {sync_word, encoded_data};

endmodule