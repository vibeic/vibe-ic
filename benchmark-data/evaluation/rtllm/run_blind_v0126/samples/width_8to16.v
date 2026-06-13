module width_8to16 (
    input             clk,
    input             rst_n,
    input             valid_in,
    input      [7:0]  data_in,
    output reg        valid_out,
    output reg [15:0] data_out
);

    reg [7:0] data_lock;   // holds the first arriving byte (high 8 bits)
    reg       flag;        // 0: waiting for first byte, 1: waiting for second byte

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            data_lock <= 8'b0;
            flag      <= 1'b0;
        end else if (valid_in) begin
            if (!flag)
                data_lock <= data_in;  // store first byte
            flag <= ~flag;
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            data_out  <= 16'b0;
            valid_out <= 1'b0;
        end else if (valid_in && flag) begin
            // second byte arriving: concatenate {first, second}
            data_out  <= {data_lock, data_in};
            valid_out <= 1'b1;
        end else begin
            valid_out <= 1'b0;
        end
    end

endmodule
