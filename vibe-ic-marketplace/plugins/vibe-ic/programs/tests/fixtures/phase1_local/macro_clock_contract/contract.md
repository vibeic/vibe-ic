# Neutral mixed macro assembly

## External Interface
Top module name: `neutral_shell`

| Signal | Direction | Width | Description |
|---|---|---|---|
| source_rail | inout | 1 | analog supply |
| return_rail | inout | 1 | analog return |
| reference_i | input | 1 | analog reference |
| sample_i | input | 1 | clock input |
| service_i | input | 1 | clock input |
| result_o | output | 1 | analog output |

## Declared connectivity
```json
{
  "nets": [{"name": "regulated_local"}],
  "analog_blocks": [
    {"name": "bias_source", "type": "regulator", "instances": [
      {"name": "regulator_unit", "master": "regulator_macro", "ports": [
        {"name": "source", "type": "power", "direction": "input", "net": "source_rail"},
        {"name": "return", "type": "ground", "direction": "inout", "net": "return_rail"},
        {"name": "sense", "type": "analog", "direction": "input", "net": "reference_i"},
        {"name": "regulated", "type": "power", "direction": "output", "net": "regulated_local"}
      ]}
    ]},
    {"name": "processing", "type": "integrator", "instances": [
      {"name": "processing_unit", "master": "integrator_macro", "ports": [
        {"name": "supply", "type": "power", "direction": "input", "net": "regulated_local"},
        {"name": "return", "type": "ground", "direction": "inout", "net": "return_rail"},
        {"name": "sample", "type": "clock", "direction": "input", "net": "sample_i"},
        {"name": "result", "type": "analog", "direction": "output", "net": "result_o"}
      ]}
    ]}
  ],
  "clock_groups": [
    {"name": "sampling_service", "clocks": ["sample_i", "service_i"], "relationship": "asynchronous"}
  ]
}
```
