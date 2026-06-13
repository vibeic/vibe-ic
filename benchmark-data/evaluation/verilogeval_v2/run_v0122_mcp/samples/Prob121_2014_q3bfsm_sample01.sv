module TopModule (
    input  clk,
    input  reset,
    input  x,
    output z
);

    reg [2:0] y;

    // Next-state logic from the state-assigned table
    function [2:0] next_state(input [2:0] s, input xi);
        case (s)
            3'b000: next_state = xi ? 3'b001 : 3'b000;
            3'b001: next_state = xi ? 3'b100 : 3'b001;
            3'b010: next_state = xi ? 3'b001 : 3'b010;
            3'b011: next_state = xi ? 3'b010 : 3'b001;
            3'b100: next_state = xi ? 3'b100 : 3'b011;
            default: next_state = 3'b000;
        endcase
    endfunction

    always @(posedge clk) begin
        if (reset)
            y <= 3'b000;
        else
            y <= next_state(y, x);
    end

    // Moore output: z=1 in states 011 and 100
    assign z = (y == 3'b011) || (y == 3'b100);

endmodule
