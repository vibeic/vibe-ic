// width_8to16 — collect two 8-bit inputs into one 16-bit output.
// First arriving byte -> HIGH 8 bits; second byte -> LOW 8 bits.
// valid_out/data_out appear the cycle after the SECOND valid byte arrives.
module width_8to16 (
    input  wire        clk,
    input  wire        rst_n,        // active-low reset
    input  wire        valid_in,
    input  wire [7:0]  data_in,
    output reg         valid_out,
    output reg [15:0]  data_out
);

    reg [7:0] data_lock; // holds the first (high) byte
    reg       flag;      // 0 = waiting for first byte, 1 = waiting for second byte

    // capture / concatenate
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            data_out  <= 16'd0;
            data_lock <= 8'd0;
            flag      <= 1'b0;
            valid_out <= 1'b0;
        end else if (valid_in) begin
            if (!flag) begin
                // first byte: store it as the high half, no output yet
                data_lock <= data_in;
                flag      <= 1'b1;
                valid_out <= 1'b0;
            end else begin
                // second byte: concatenate {first, second} and emit
                data_out  <= {data_lock, data_in};
                flag      <= 1'b0;
                valid_out <= 1'b1;
            end
        end else begin
            // no new input this cycle: drop the one-cycle valid pulse
            valid_out <= 1'b0;
        end
    end

endmodule
