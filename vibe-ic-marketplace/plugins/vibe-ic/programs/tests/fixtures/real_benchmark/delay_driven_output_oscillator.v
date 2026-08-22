// Hand-extracted and identifier-generalized real-benchmark shape.
// Structural anchor: a no-input output oscillator, literal initialization,
// and a parameterized half-period blocking self-toggle in initial/forever.
module oscillator #(
    parameter PERIOD = 10
) (
    output reg wave
);
    initial begin
        wave = 1'b0;
        forever #(PERIOD/2) wave = ~wave;
    end
endmodule
