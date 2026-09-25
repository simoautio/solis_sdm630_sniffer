"""Native push sensors for the documented meter registers."""

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SnifferConfigEntry
from .const import CONF_GRID_IMPORT_SIGN, DEFAULT_GRID_IMPORT_SIGN, DOMAIN
from .energy import split_grid_power
from .inverter_registers import REGISTERS as INVERTER_REGISTERS
from .registers import REGISTERS

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SnifferSensorDescription(SensorEntityDescription):
    """Connect sensor metadata to a zero-based register address."""

    address: int
    grid_direction: str | None = None


DESCRIPTIONS = tuple(
    SnifferSensorDescription(
        key=register.key,
        name=register.name,
        address=address,
        native_unit_of_measurement=register.unit,
        device_class=SensorDeviceClass(register.device_class),
        state_class=SensorStateClass(register.state_class),
    )
    for address, register in REGISTERS.items()
)

GRID_DESCRIPTIONS = tuple(
    SnifferSensorDescription(
        key=f"grid_{direction}_power",
        name=f"Grid {direction} power",
        address=52,
        grid_direction=direction,
        native_unit_of_measurement="W",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    )
    for direction in ("import", "export")
)


def _inverter_description(key, name, unit, device_class, state_class, diagnostic):
    return SensorEntityDescription(
        key=key,
        name=name,
        native_unit_of_measurement=unit,
        device_class=SensorDeviceClass(device_class) if device_class else None,
        state_class=SensorStateClass(state_class) if state_class else None,
        entity_category=EntityCategory.DIAGNOSTIC if diagnostic else None,
    )


INVERTER_DESCRIPTIONS = (
    *(
        _inverter_description(
            r.key, r.name, r.unit, r.device_class, r.state_class, r.diagnostic
        )
        for r in INVERTER_REGISTERS
    ),
    *(
        _inverter_description(key, name, unit, device_class, state_class, False)
        for key, name, unit, device_class, state_class in (
            ("pv1_power", "PV1 power", "W", "power", "measurement"),
            ("pv2_power", "PV2 power", "W", "power", "measurement"),
            ("solar_ac_power", "Solar power", "W", "power", "measurement"),
            ("household_power", "Household power", "W", "power", "measurement"),
            (
                "estimated_solar_energy",
                "Estimated solar energy",
                "kWh",
                "energy",
                "total_increasing",
            ),
            (
                "estimated_household_energy",
                "Estimated household energy",
                "kWh",
                "energy",
                "total_increasing",
            ),
        )
    ),
)

BALANCE_STATUSES = [
    "waiting_for_sources",
    "ok",
    "meter_unavailable",
    "unaligned_samples",
    "inverter_output_unavailable",
    "negative_household_balance",
    "logger_unavailable",
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SnifferConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Expose sensors; unobserved readings remain unavailable."""
    async_add_entities(
        SnifferSensor(entry, description)
        for description in (*DESCRIPTIONS, *GRID_DESCRIPTIONS)
    )
    if entry.runtime_data.logger:
        async_add_entities(
            [
                *(InverterSensor(entry, item) for item in INVERTER_DESCRIPTIONS),
                BalanceStatusSensor(entry),
            ]
        )


class SnifferSensor(SensorEntity):
    """One native meter reading, updated only by received traffic."""

    entity_description: SnifferSensorDescription
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self, entry: SnifferConfigEntry, description: SnifferSensorDescription
    ) -> None:
        self.entity_description = description
        self._runtime = entry.runtime_data
        self._import_sign = entry.options.get(
            CONF_GRID_IMPORT_SIGN, DEFAULT_GRID_IMPORT_SIGN
        )
        identifier = (
            description.key if description.grid_direction else description.address
        )
        self._attr_unique_id = f"{entry.entry_id}_{identifier}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Solis SDM630 meter",
            manufacturer="Eastron",
            model="SDM630MCT (passive MQTT)",
        )

    @property
    def native_value(self) -> float | None:
        """Return the unrounded meter value for HA's native unit handling."""
        value = self._runtime.values.get(self.entity_description.address)
        if self.entity_description.grid_direction:
            imported, exported = split_grid_power(value, self._import_sign)
            return (
                imported
                if self.entity_description.grid_direction == "import"
                else exported
            )
        return value

    @property
    def available(self) -> bool:
        """A sensor cannot be available before its register has been observed."""
        return self._runtime.is_available(self.entity_description.address)

    async def async_added_to_hass(self) -> None:
        """Attach the push listener and register its cleanup."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._runtime.async_add_listener(self.async_write_ha_state)
        )


class InverterSensor(SensorEntity):
    """One read-only logger reading or a value derived from fresh sources."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self, entry: SnifferConfigEntry, description: SensorEntityDescription
    ) -> None:
        self.entity_description = description
        self._logger = entry.runtime_data.logger
        self._attr_unique_id = f"{entry.entry_id}_inverter_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_inverter")},
            name="Solis inverter",
            manufacturer="Solis",
            model="S6-EH3P10K-H (read-only Modbus TCP)",
        )

    @property
    def native_value(self) -> float | str | None:
        return self._logger.values.get(self.entity_description.key)

    @property
    def available(self) -> bool:
        return self._logger.is_available(self.entity_description.key)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._logger.async_add_listener(self.async_write_ha_state))


class BalanceStatusSensor(InverterSensor):
    """Why household power is or is not currently calculated."""

    def __init__(self, entry: SnifferConfigEntry) -> None:
        super().__init__(
            entry,
            SensorEntityDescription(
                key="balance_status",
                translation_key="balance_status",
                name="Household balance status",
                device_class=SensorDeviceClass.ENUM,
                options=BALANCE_STATUSES,
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
        )

    @property
    def native_value(self) -> str:
        return self._logger.balance_status

    @property
    def available(self) -> bool:
        return self._logger.running
