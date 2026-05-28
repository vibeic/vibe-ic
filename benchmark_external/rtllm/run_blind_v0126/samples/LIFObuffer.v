module LIFObuffer (
    input  [3:0] dataIn,
    input        RW,
    input        EN,
    input        Rst,
    input        Clk,
    output reg       EMPTY,
    output reg       FULL,
    output reg [3:0] dataOut
);

    // 4-entry, 4-bit-wide stack.  SP ranges 0..4.
    //   SP == 4 -> empty,  SP == 0 -> full.
    reg [3:0] stack_mem [0:3];
    reg [2:0] SP;
    integer i;

    always @(posedge Clk) begin
        if (EN) begin
            if (Rst) begin
                SP      <= 3'd4;          // empty
                dataOut <= 4'b0000;
                for (i = 0; i < 4; i = i + 1)
                    stack_mem[i] <= 4'b0000;
            end else begin
                if (RW == 1'b0) begin
                    // write / push when not full
                    if (SP > 3'd0) begin
                        stack_mem[SP - 3'd1] <= dataIn;
                        SP <= SP - 3'd1;
                    end
                end else begin
                    // read / pop when not empty
                    if (SP < 3'd4) begin
                        dataOut <= stack_mem[SP];
                        stack_mem[SP] <= 4'b0000;
                        SP <= SP + 3'd1;
                    end
                end
            end
        end
    end

    // Flags reflect current SP
    always @(*) begin
        EMPTY = (SP == 3'd4);
        FULL  = (SP == 3'd0);
    end

endmodule
