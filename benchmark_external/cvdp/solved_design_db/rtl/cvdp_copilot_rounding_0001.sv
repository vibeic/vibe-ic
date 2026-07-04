module rounding #(
  parameter WIDTH = 24
)(
  input  logic [WIDTH-1:0] in_data  , // Input value for rounding
  input  logic             sign     , // Indicates sign of input (1: negative, 0: positive)
  input  logic             roundin  , // Round bit
  input  logic             stickyin , // Sticky bit for precision
  input  logic [2:0]       rm       , // Rounding mode
  output logic [WIDTH-1:0] out_data , // Rounded output
  output logic             inexact  , // Indicates precision loss
  output logic             cout     , // Carry-out_data signal
  output logic             r_up       // Indicates rounding up
);

  localparam RNE = 3'b000;
  localparam RTZ = 3'b001;
  localparam RUP = 3'b010;
  localparam RDN = 3'b011;
  localparam RMM = 3'b100;

  logic rounding_up;
  logic inexact_w;

  // Precision loss whenever a round or sticky bit is set
  assign inexact_w = roundin | stickyin;

  always_comb begin
    case (rm)
      RNE:     rounding_up = roundin & (stickyin | in_data[0]); // tie-break to even
      RTZ:     rounding_up = 1'b0;                              // truncate
      RUP:     rounding_up = (~sign) & inexact_w;               // ceil
      RDN:     rounding_up = sign & inexact_w & (in_data != {WIDTH{1'b1}}); // floor
      RMM:     rounding_up = roundin;                           // away from zero
      default: rounding_up = 1'b0;                              // unsupported -> RTZ
    endcase
  end

  // Output assignments
  assign out_data = rounding_up ? (in_data + {{(WIDTH-1){1'b0}}, 1'b1}) : in_data;
  assign inexact  = inexact_w;
  assign cout     = (in_data == {WIDTH{1'b1}}) & rounding_up;
  assign r_up     = rounding_up;

endmodule
