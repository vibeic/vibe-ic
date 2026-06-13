module TopModule (
    input  clk,
    input  a,
    output reg q
);

    // Reset-less registered output: init to 0 (hygiene), updates on first posedge.
    initial q = 1'b0;

    always @(posedge clk) begin
        q <= ~a;
    end

endmodule
