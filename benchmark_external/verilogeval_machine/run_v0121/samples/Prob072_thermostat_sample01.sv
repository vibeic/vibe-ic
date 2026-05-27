module TopModule (
  input mode,
  input too_cold,
  input too_hot,
  input fan_on,
  output heater,
  output aircon,
  output fan
);
  assign heater = mode & too_cold;       // heat in heating mode when cold
  assign aircon = ~mode & too_hot;       // cool in cooling mode when hot
  assign fan    = too_cold | too_hot | fan_on;  // per prompt's explicit fan condition
endmodule
