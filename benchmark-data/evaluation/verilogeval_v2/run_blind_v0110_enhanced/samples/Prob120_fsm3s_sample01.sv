module TopModule (
    input  wire clk,
    input  wire reset,
    input  wire in,
    output wire out
);
    localparam A = 2'b00, B = 2'b01, C = 2'b10, D = 2'b11;
    reg [1:0] state;

    always @(posedge clk) begin
        if (reset)
            state <= A;
        else begin
            case (state)
                A: state <= in ? B : A;
                B: state <= in ? B : C;
                C: state <= in ? D : A;
                D: state <= in ? B : C;
                default: state <= A;
            endcase
        end
    end

    assign out = (state == D);
endmodule
