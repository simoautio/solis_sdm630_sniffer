# Changelog

## 0.2.0

- Add Grid import power and Grid export power sensors in W.
- Add a positive/negative grid-import power-sign option, changeable after setup.
- Add explicit creation of daily, monthly, and yearly import/export Utility Meter helpers from the meter's measured kWh counters.
- Reuse matching helpers, support renamed source entities, and keep helper accounting under Home Assistant's built-in Utility Meter integration.
- Preserve existing meter readings, entity IDs, and history. The power-sign option does not modify energy-counter direction or retarget existing helpers.
- Document Energy dashboard configuration and the distinction between grid exchange and gross solar production.

## 0.1.0

- Initial passive binary-MQTT Modbus RTU integration with UI setup, 39 meter sensors, CRC validation, frame buffering, request/response pairing, availability, and diagnostics.
