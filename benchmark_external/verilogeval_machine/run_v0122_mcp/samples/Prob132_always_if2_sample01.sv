// Prob132_always_if2 — two combinational always blocks.
// shut_off_computer = cpu_overheated; keep_driving = !arrived ? !gas_tank_empty : 0.
module TopModule (
  input cpu_overheated,
  output reg shut_off_computer,
  input arrived,
  input gas_tank_empty,
  output reg keep_driving
);

  always @(*) begin
    if (cpu_overheated) shut_off_computer = 1'b1;
    else                shut_off_computer = 1'b0;
  end

  always @(*) begin
    if (!arrived) keep_driving = ~gas_tank_empty;
    else          keep_driving = 1'b0;
  end

endmodule
