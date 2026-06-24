// LIFObuffer — 4-bit-wide, 4-deep last-in-first-out (stack) buffer.
// Stack pointer SP starts at 4 (empty) and grows downward: push decrements SP,
// pop increments SP. Reset (active high, gated by EN) clears memory and SP=4.
// RW=0 => write/push (if not full); RW=1 => read/pop (if not empty).
module LIFObuffer (
    input  wire [3:0] dataIn,
    input  wire       RW,
    input  wire       EN,
    input  wire       Rst,
    input  wire       Clk,
    output reg        EMPTY,
    output reg        FULL,
    output reg  [3:0] dataOut
);
    reg [3:0] stack_mem [0:3];   // 4 entries of 4-bit data
    reg [2:0] SP;                 // stack pointer, 0..4 (4 = empty, 0 = full)
    integer i;

    always @(posedge Clk) begin
        if (EN) begin
            if (Rst) begin
                // initialize: empty stack, SP=4, all memory cleared
                SP      <= 3'd4;
                EMPTY   <= 1'b1;
                FULL    <= 1'b0;
                dataOut <= 4'b0000;
                for (i = 0; i < 4; i = i + 1)
                    stack_mem[i] <= 4'b0000;
            end else begin
                if (RW == 1'b0) begin
                    // write / push when not full
                    if (SP > 3'd0) begin
                        stack_mem[SP - 1] <= dataIn;
                        SP    <= SP - 3'd1;
                        EMPTY <= 1'b0;
                        FULL  <= (SP - 3'd1 == 3'd0) ? 1'b1 : 1'b0;
                    end
                end else begin
                    // read / pop when not empty
                    if (SP < 3'd4) begin
                        dataOut          <= stack_mem[SP];
                        stack_mem[SP]    <= 4'b0000;
                        SP    <= SP + 3'd1;
                        FULL  <= 1'b0;
                        EMPTY <= (SP + 3'd1 == 3'd4) ? 1'b1 : 1'b0;
                    end
                end
            end
        end
    end
endmodule
