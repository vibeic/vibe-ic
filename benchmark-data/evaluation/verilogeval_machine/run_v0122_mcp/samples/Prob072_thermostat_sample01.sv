// Prob072_thermostat — heating/cooling controller.
// heater on: heating mode & too cold.  aircon on: cooling mode & too hot.
// fan on: too_cold | too_hot | fan_on.
module TopModule (
  input mode,
  input too_cold,
  input too_hot,
  input fan_on,
  output heater,
  output aircon,
  output fan
);

  assign heater = mode & too_cold;
  assign aircon = ~mode & too_hot;
  assign fan    = too_cold | too_hot | fan_on;

endmodule
