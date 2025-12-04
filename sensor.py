"""Platform for sensor integration."""
from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
# Use the string 'CAD' directly for currency to avoid import errors on older HA versions
from homeassistant.const import UnitOfEnergy 
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the SaskPower SmartMeter sensors from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    # Create the sensor entities and add them to Home Assistant.
    async_add_entities(
        [
            SaskPowerDailyUsageSensor(coordinator, entry),
            SaskPowerWeeklyUsageSensor(coordinator, entry),
            SaskPowerMonthlyUsageSensor(coordinator, entry),
            SaskPowerLastUpdatedSensor(coordinator, entry),
            SaskPowerLastBillTotalChargesSensor(coordinator, entry),
            SaskPowerLastBillTotalUsageSensor(coordinator, entry),
            SaskPowerTotalConsumptionSensor(coordinator, entry),
            SaskPowerTotalCostSensor(coordinator, entry), # New cost sensor
        ]
    )


class SaskPowerBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class to define the device for all SaskPower sensors."""

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor and set the device info."""
        super().__init__(coordinator)
        account_number = entry.data["account_number"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, account_number)},
            name=f"SaskPower Account {account_number}",
            manufacturer="SaskPower",
            model="Smart Meter",
        )


class SaskPowerDailyUsageSensor(SaskPowerBaseSensor):
    """Representation of the most recent full day of power usage."""

    _attr_state_class = SensorStateClass.TOTAL
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        account_number = entry.data["account_number"]
        self._attr_name = f"SaskPower Most Recent Day Usage {account_number}"
        self._attr_unique_id = f"{entry.entry_id}_{account_number}_daily_usage"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if self.coordinator.data:
            return self.coordinator.data.get("daily_usage")
        return None


class SaskPowerWeeklyUsageSensor(SaskPowerBaseSensor):
    """Representation of the last 7 days of available power usage."""

    _attr_state_class = SensorStateClass.TOTAL
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        account_number = entry.data["account_number"]
        self._attr_name = f"SaskPower Last 7 Days Usage {account_number}"
        self._attr_unique_id = f"{entry.entry_id}_{account_number}_weekly_usage"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if self.coordinator.data:
            return self.coordinator.data.get("weekly_usage")
        return None


class SaskPowerMonthlyUsageSensor(SaskPowerBaseSensor):
    """Representation of the previous month's total power usage."""

    _attr_state_class = SensorStateClass.TOTAL
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        account_number = entry.data["account_number"]
        self._attr_name = f"SaskPower Previous Month Usage {account_number}"
        self._attr_unique_id = f"{entry.entry_id}_{account_number}_monthly_usage"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if self.coordinator.data:
            return self.coordinator.data.get("monthly_usage")
        return None


class SaskPowerLastUpdatedSensor(SaskPowerBaseSensor):
    """Representation of the last data update timestamp sensor."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        account_number = entry.data["account_number"]
        self._attr_name = f"SaskPower Last Data Point {account_number}"
        self._attr_unique_id = f"{entry.entry_id}_{account_number}_last_updated"

    @property
    def native_value(self) -> datetime | None:
        """Return the state of the sensor."""
        if self.coordinator.data:
            return self.coordinator.data.get("latest_data_timestamp")
        return None


class SaskPowerLastBillTotalChargesSensor(SaskPowerBaseSensor):
    """Representation of the total charges on the last bill."""

    _attr_device_class = SensorDeviceClass.MONETARY
    # Use the currency code 'CAD' directly for better compatibility
    _attr_native_unit_of_measurement = "CAD"
    _attr_icon = "mdi:cash"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        account_number = entry.data["account_number"]
        self._attr_name = f"SaskPower Last Bill Total Charges {account_number}"
        self._attr_unique_id = f"{entry.entry_id}_{account_number}_last_bill_charges"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if self.coordinator.data:
            return self.coordinator.data.get("last_bill_total_charges")
        return None


class SaskPowerLastBillTotalUsageSensor(SaskPowerBaseSensor):
    """Representation of the total usage on the last bill."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:flash"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        account_number = entry.data["account_number"]
        self._attr_name = f"SaskPower Last Bill Total Usage {account_number}"
        self._attr_unique_id = f"{entry.entry_id}_{account_number}_last_bill_usage"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if self.coordinator.data:
            return self.coordinator.data.get("last_bill_total_usage")
        return None


class SaskPowerTotalConsumptionSensor(SaskPowerBaseSensor):
    """Representation of the total consumption for the Energy Dashboard."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:transmission-tower"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        account_number = entry.data["account_number"]
        self._attr_name = f"SaskPower Total Consumption {account_number}"
        self._attr_unique_id = f"{entry.entry_id}_{account_number}_total_consumption"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if self.coordinator.data:
            return self.coordinator.data.get("total_consumption")
        return None


class SaskPowerTotalCostSensor(SaskPowerBaseSensor):
    """Representation of the total estimated cost for the Energy Dashboard."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "CAD"
    _attr_icon = "mdi:cash-multiple"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        account_number = entry.data["account_number"]
        self._attr_name = f"SaskPower Estimated Total Cost {account_number}"
        self._attr_unique_id = f"{entry.entry_id}_{account_number}_total_cost"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if self.coordinator.data:
            return self.coordinator.data.get("total_cost")
        return None
