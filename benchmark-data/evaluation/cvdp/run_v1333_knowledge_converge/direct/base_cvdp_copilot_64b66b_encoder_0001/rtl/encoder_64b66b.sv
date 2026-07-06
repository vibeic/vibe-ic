module encoder_64b66b (
    input  wire        clk_in,
    input  wire        rst_in,
    input  wire [63:0] encoder_data_in,
    input  wire [7:0]  encoder_control_in,
    output reg  [65:0] encoder_data_out
);

    // 64b/66b encoder
    // - 2-bit sync header at the MSBs of the output
    //   2'b01 : all 8 octets are pure data (control word == 8'b0)
    //          -> data passed directly to output
    //   2'b10 : at least one control character present
    //          -> 64'd0 in the data field (control encoding unsupported)
    // - Output latency: 1 clock cycle
    // - rst_in: active-HIGH asynchronous reset -> output cleared

    always @(posedge clk_in or posedge rst_in) begin
        if (rst_in) begin
            encoder_data_out <= 66'd0;
        end else begin
            if (encoder_control_in == 8'b00000000) begin
                // Pure data encoding
                encoder_data_out <= {2'b01, encoder_data_in};
            end else begin
                // Control character present - not supported, emit zeros
                encoder_data_out <= {2'b10, 64'd0};
            end
        end
    end

endmodule
