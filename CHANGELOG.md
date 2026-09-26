# Changelog

## 0.5.2

- Show a Repairs issue after five consecutive failed logger polls; it clears on the next successful poll or unload. Diagnostics add last-success age and poll duration. The logger host is never included.
- Document the PUSR USR-DR134 as a passive capture path, separate from the actively polled (read-only) S2-WL-ST logger.
- Checkpoint estimated energy during continuous polling without repeatedly postponing disk writes.
- Expire every logger register group at its own freshness deadline, including when a poll stalls.
- Prevent duplicate logger endpoints across combined and inverter-only setup and Configure, while allowing distinct ports or unit IDs.

## 0.5.1

- Add **Meter mounted in reverse** (Configure → Meter) for meters whose import/export counters are swapped. The Import and Export energy entities (including per-phase) swap labels and helper sources; each entity keeps one continuous history, so statistics see no false jumps.

## 0.5.0

- Choose at setup what to monitor: meter and inverter, meter only (MQTT sniffer), or inverter only (logger Modbus TCP).
- Inverter-only installations do not need MQTT; MQTT is now an optional after-dependency.
- Each mode creates only entities it can populate: household power, estimated household energy and balance status need both sources.
- Configure shows only the pages and utility meter sources that apply to the entry. Existing entries keep working unchanged.

## 0.4.1

- Optionally enter the Solis logger IP address when adding the integration.
- Configure is now a menu: Meter, Inverter logger, and Create utility meters.
- Clearer inverter entity names (for example Temperature, L1 voltage, PV1 power, Solar power, Reported grid power). Unique IDs are unchanged, so history is kept; existing entity IDs stay as they are.
- Model, firmware and fault/status bit codes are shown as hex.
- Removing the integration also deletes its stored estimated-energy totals.

## 0.4.0

- Add optional read-only Modbus TCP polling of the Solis S2-WL-ST logger (function 04 only) with inverter entities on a separate device.
- Add Solar AC power, Household power (fresh, time-aligned meter and inverter samples only) and persisted Estimated solar/household energy.
- Add selectable utility meter cycles (quarter-hourly to yearly) and sources, including the estimated energy sensors.
- Add a redacted logger section to diagnostics. Existing meter entities and helpers are unchanged.

## 0.3.1

- Add diagnostic traffic status distinguishing recent requests without matched replies from healthy responses, inactivity, and disconnection.
- Count outstanding requests replaced before a reply is observed, and retain the last request range in diagnostics.
- Add regression coverage from the request-only field capture and document how to interpret missing replies without assuming a wiring fault.

## 0.3.0

- Add a configurable update interval in setup and Configure (1–86400 seconds, default 30 seconds). Existing installations also use 30 seconds unless configured otherwise.
- Publish the latest readings at the interval to reduce dashboard, automation, and history updates while continuing to decode all incoming traffic.
- Report first readings and availability changes immediately; keep freshness independent of the publication interval.
- Preserve entity IDs, existing history, and cumulative energy totals.

## 0.2.0

- Add Grid import power and Grid export power sensors in W.
- Add a positive/negative grid-import power-sign option, changeable after setup.
- Add explicit creation of daily, monthly, and yearly import/export Utility Meter helpers from the meter's measured kWh counters.
- Reuse matching helpers, support renamed source entities, and keep helper accounting under Home Assistant's built-in Utility Meter integration.
- Preserve existing meter readings, entity IDs, and history. The power-sign option does not modify energy-counter direction or retarget existing helpers.
- Document Energy dashboard configuration and the distinction between grid exchange and gross solar production.

## 0.1.0

- Initial passive binary-MQTT Modbus RTU integration with UI setup, 39 meter sensors, CRC validation, frame buffering, request/response pairing, availability, and diagnostics.
