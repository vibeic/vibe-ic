module neuromorphic_array #(
    parameter NEURONS = 8,       // Number of neurons
    parameter INPUTS = 8,        // Number of inputs
    parameter OUTPUTS = 8         // Number of outputs
) (
    input  logic [7:0] ui_in,       // Control input
    input logic [7:0] uio_in,      // Input data
    output logic [7:0] uo_out,     // Output data
    input logic clk,                // Clock
    input logic rst_n               // Reset
);
    // Internal wires for neuron outputs
    logic [7:0] neuron_outputs [0:NEURONS-1];

    // Each neuron is an independent unit fed by the shared input data (broadcast).
    // All neurons share the control bit ui_in[0]; the last neuron drives the output.
    genvar i;
    generate
        for (i = 0; i < NEURONS; i = i + 1) begin : neuron_gen
            single_neuron_dut u_neuron (
                .clk    (clk),
                .rst_n  (rst_n),
                .control(ui_in[0]),
                .seq_in (uio_in),
                .seq_out(neuron_outputs[i])
            );
        end
    endgenerate

    // Combine outputs from the last neuron
    assign uo_out = neuron_outputs[NEURONS-1]; // Output from the last neuron

endmodule

module single_neuron_dut (
    input logic clk,
    input logic rst_n,
    input logic control,        // Control signal
    input logic [7:0] seq_in,   // Input sequence
    output logic [7:0] seq_out   // Output sequence
);
    // Store an 8-bit state; update it with seq_in when control is high, otherwise
    // retain the previous value.  Active-low reset clears the state.
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            seq_out <= 8'b0;
        else if (control)
            seq_out <= seq_in;
    end
endmodule
