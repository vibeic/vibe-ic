module TopModule (
  input clk,
  input resetn,
  input [3:1] r,
  output [3:1] g
);
    localparam A = 2'd0,  // idle
               B = 2'd1,  // grant device 1
               C = 2'd2,  // grant device 2
               D = 2'd3;  // grant device 3

    reg [1:0] state, next;

    always @(*) begin
        case (state)
            A: begin
                if      (r[1]) next = B;
                else if (r[2]) next = C;
                else if (r[3]) next = D;
                else           next = A;
            end
            B: next = r[1] ? B : A;
            C: next = r[2] ? C : A;
            D: next = r[3] ? D : A;
            default: next = A;
        endcase
    end

    always @(posedge clk) begin
        if (!resetn) state <= A;
        else         state <= next;
    end

    assign g[1] = (state == B);
    assign g[2] = (state == C);
    assign g[3] = (state == D);
endmodule
