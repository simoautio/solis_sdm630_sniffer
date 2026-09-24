"""Native push sensors for the documented meter registers."""

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SnifferConfigEntry
from .const import CONF_GRID_IMPORT_SIGN, DEFAULT_GRID_IMPORT_SIGN, DOMAIN
from .energy import split_grid_power
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
