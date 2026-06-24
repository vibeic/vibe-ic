// parallel2serial: convert each 4-bit parallel word d to a serial bit stream
// MSB-first. dout is the MSB of the working register; valid_out pulses when a
// fresh word is loaded. Active-low rst_n, posedge clk. Per the spec impl:
//   if cnt==3: data<=d, cnt<=0, valid<=1
//   else     : cnt<=cnt+1, valid<=0, data<={data[2:0],data[3]} (rotate left)
module parallel2serial (
    input  wire       clk,
    input  wire       rst_n,
    input  wire [3:0] d,
    output wire       valid_out,
    output wire       dout
);

    reg [3:0] data;
    reg [1:0] cnt;
    reg       valid;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            data  <= 4'd0;
            cnt   <= 2'd0;
            valid <= 1'b0;
        end else if (cnt == 2'd3) begin
            data  <= d;            // reload with the next parallel word
            cnt   <= 2'd0;
            valid <= 1'b1;
        end else begin
            cnt   <= cnt + 2'd1;
            valid <= 1'b0;
            data  <= {data[2:0], data[3]};   // rotate left: MSB -> LSB
        end
    end

    assign dout      = data[3];   // serial output = current MSB
    assign valid_out = valid;

endmodule
