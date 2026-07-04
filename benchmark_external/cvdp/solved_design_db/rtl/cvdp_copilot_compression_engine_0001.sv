module compression_engine (
  input   logic        clk,
  input   logic        reset,
  input   logic [23:0] num_i,
  output  logic [11:0] mantissa_o,
  output  logic [3:0]  exponent_o
);

  // --------------------------------------------------------
  // Internal wires and registers
  // --------------------------------------------------------
  logic [23:12] exp_oh;         // One-hot encoded exponent
  logic [3:0]   exp_bin;        // Binary exponent
  logic [3:0]   exponent;       // Adjusted exponent
  logic [11:0]  mantissa;       // Mantissa

  // --------------------------------------------------------
  // One-Hot Encoding of the Exponent
  // --------------------------------------------------------
  assign exp_oh[23] = num_i[23];

  // exp_oh[i] is set only at the most-significant set bit of num_i within
  // the [23:12] window.
  genvar gi;
  generate
    for (gi = 12; gi <= 22; gi = gi + 1) begin : gen_one_hot
      assign exp_oh[gi] = num_i[gi] & ~(|num_i[23:gi+1]);
    end
  endgenerate

  // Use the `onehot_to_bin` module to convert one-hot to binary exponent
  onehot_to_bin #(
    .ONE_HOT_W(12),
    .BIN_W(4)
  ) exp_oh_bin (
    .oh_vec_i(exp_oh),
    .bin_vec_o(exp_bin)
  );

  assign exponent = (|exp_oh) ? exp_bin + 4'h1 : exp_bin;

  // --------------------------------------------------------
  // Mantissa Extraction Logic
  // --------------------------------------------------------
  // The mantissa holds the 12 bits immediately BELOW the leading set bit
  // (the implicit leading 1 is excluded), as fixed by the worked-example
  // table (e.g. num_i=24'hFFC01D -> mantissa=12'hFF8). When the leading set
  // bit lies below bit 12 (exponent==0) the value already fits, so the
  // mantissa is the low 12 bits directly.
  always @(*) begin
    if (num_i == 24'h000000)
      mantissa = 12'h000;
    else if (exponent == 4'h0)
      mantissa = num_i[11:0];
    else
      // leading set-bit index = 12 + exp_bin; take the 12 bits just below it
      mantissa = num_i[(exp_bin + 5'd11) -: 12];
  end

  // --------------------------------------------------------
  // Output assignments
  // --------------------------------------------------------
  always @(posedge clk or posedge reset) begin
    if (reset) begin
      exponent_o <= 4'd0;
      mantissa_o <= 12'd0;
    end else begin
      exponent_o <= exponent;
      mantissa_o <= mantissa;
    end
  end

endmodule

module onehot_to_bin #(
  parameter ONE_HOT_W = 32,  // Width of the one-hot input
  parameter BIN_W     = 5    // Width of the binary output
)(
  input   wire [ONE_HOT_W-1:0]  oh_vec_i,  // One-hot encoded input
  output  logic [BIN_W-1:0]     bin_vec_o  // Binary encoded output
);

  integer i;

  // Priority-encode the one-hot vector to its binary bit-position index.
  always @(*) begin
    bin_vec_o = {BIN_W{1'b0}};
    for (i = 0; i < ONE_HOT_W; i = i + 1) begin
      if (oh_vec_i[i])
        bin_vec_o = i[BIN_W-1:0];
    end
  end

endmodule
