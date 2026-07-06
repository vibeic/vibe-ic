module LIFObuffer(
    input  wire [3:0] dataIn,
    input  wire       RW,
    input  wire       EN,
    input  wire       Rst,
    input  wire       Clk,
    output reg        EMPTY,
    output reg        FULL,
    output reg  [3:0] dataOut
);

reg [3:0] stack_mem [0:3];
reg [2:0] SP; // 0..4 ; 4 = empty, 0 = full
integer   i;

always @(posedge Clk) begin
    if (EN) begin
        if (Rst) begin
            SP      <= 3'd4;
            dataOut <= 4'b0000;
            for (i = 0; i < 4; i = i + 1)
                stack_mem[i] <= 4'b0000;
        end else begin
            if (!RW && (SP != 3'd0)) begin
                // write / push
                stack_mem[SP - 1'b1] <= dataIn;
                SP <= SP - 1'b1;
            end else if (RW && (SP != 3'd4)) begin
                // read / pop
                dataOut       <= stack_mem[SP];
                stack_mem[SP] <= 4'b0000;
                SP            <= SP + 1'b1;
            end
        end
    end
end

always @(*) begin
    EMPTY = (SP == 3'd4);
    FULL  = (SP == 3'd0);
end

endmodule
