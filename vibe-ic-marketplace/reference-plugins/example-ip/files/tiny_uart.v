// tiny_uart — placeholder soft-IP for the example IP plugin.
// 8-N-1 UART transmitter only (no RX, no flow control). Generic baud divider.

module tiny_uart #(
    parameter integer CLK_HZ = 50_000_000,
    parameter integer BAUD   = 115_200
)(
    input  wire        clk,
    input  wire        rst_n,
    input  wire [7:0]  tx_data,
    input  wire        tx_valid,
    output reg         tx_ready,
    output reg         tx_pin
);
    localparam integer DIV = CLK_HZ / BAUD;

    reg [3:0]  state;
    reg [15:0] cnt;
    reg [9:0]  shifter;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state    <= 0;
            cnt      <= 0;
            tx_ready <= 1'b1;
            tx_pin   <= 1'b1;
        end else if (state == 0 && tx_valid && tx_ready) begin
            shifter  <= {1'b1, tx_data, 1'b0};   // stop, data, start
            state    <= 1;
            cnt      <= 0;
            tx_ready <= 1'b0;
        end else if (state != 0) begin
            if (cnt == DIV - 1) begin
                cnt    <= 0;
                tx_pin <= shifter[0];
                shifter <= {1'b1, shifter[9:1]};
                if (state == 10) begin
                    state    <= 0;
                    tx_ready <= 1'b1;
                end else begin
                    state <= state + 1;
                end
            end else begin
                cnt <= cnt + 1;
            end
        end
    end
endmodule
