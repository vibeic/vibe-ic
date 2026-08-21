// Hand-extracted and identifier-generalized real-benchmark shape.
// Structural anchor: a legal Verilog-2005 instance identifier that became a
// reserved keyword in SystemVerilog, plus an output-only functional marker.
module tb;
    wire y;
    dut checker(.y(y));
    initial begin
        #1;
        if (y) $display("__MARKER__");
        $finish;
    end
endmodule
