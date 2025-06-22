"""
Defines the sensor entities for the SaskPower SmartMeter integration.

This includes summary sensors for daily, weekly, and monthly usage, as well as
advanced sensors that backfill detailed 15-minute data into Home Assistant's
statistics for use in the Energy Dashboard.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    get_last_statistics,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the SaskPower SmartMeter sensors from a config entry."""
    coordinator_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = coordinator_data["coordinator"]
    config = coordinator_data["config"]
    
    async_add_entities(
        [
            # Summary Sensors
            SaskPowerDailyUsageSensor(coordinator, entry),
            SaskPowerWeeklyUsageSensor(coordinator, entry),
            SaskPowerMonthlyUsageSensor(coordinator, entry),
            SaskPowerLastUpdatedSensor(coordinator, entry),
            SaskPowerLastBillTotalChargesSensor(coordinator, entry),
            SaskPowerLastBillTotalUsageSensor(coordinator, entry),
            # Energy Dashboard Sensors (with backfill)
            SaskPowerTotalConsumptionSensor(coordinator, entry, config),
            SaskPowerTotalCostSensor(coordinator, entry, config),
        ]
    )


class SaskPowerBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for all SaskPower sensors, defining the device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DataUpdateCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor and set the device info."""
        super().__init__(coordinator)
        self._account_number = entry.data["account_number"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._account_number)},
            name=f"SaskPower Account {self._account_number}",
            manufacturer="SaskPower",
            model="Smart Meter",
            configuration_url="https://www.saskpower.com/profile/my-dashboard",
        )


class SaskPowerDailyUsageSensor(SaskPowerBaseSensor):
    """Sensor for the most recent full day of power usage."""

    _attr_state_class = SensorStateClass.TOTAL
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:counter"
    _attr_name = "Most Recent Day Usage"

    def __init__(self, coordinator: DataUpdateCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{self._account_number}_daily_usage"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        return self.coordinator.data.get("daily_usage") if self.coordinator.data else None


class SaskPowerWeeklyUsageSensor(SaskPowerBaseSensor):
    """Sensor for the last 7 days of available power usage."""

    _attr_state_class = SensorStateClass.TOTAL
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:counter"
    _attr_name = "Last 7 Days Usage"

    def __init__(self, coordinator: DataUpdateCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{self._account_number}_weekly_usage"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        return self.coordinator.data.get("weekly_usage") if self.coordinator.data else None


class SaskPowerMonthlyUsageSensor(SaskPowerBaseSensor):
    """Sensor for the previous calendar month's total power usage."""

    _attr_state_class = SensorStateClass.TOTAL
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:counter"
    _attr_name = "Previous Month Usage"

    def __init__(self, coordinator: DataUpdateCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{self._account_number}_monthly_usage"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        return self.coordinator.data.get("monthly_usage") if self.coordinator.data else None


class SaskPowerLastUpdatedSensor(SaskPowerBaseSensor):
    """Sensor for the timestamp of the last available data point."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-clock"
    _attr_name = "Last Data Point"

    def __init__(self, coordinator: DataUpdateCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{self._account_number}_last_updated"

    @property
    def native_value(self) -> datetime | None:
        """Return the state of the sensor."""
        return self.coordinator.data.get("latest_data_timestamp") if self.coordinator.data else None


class SaskPowerLastBillTotalChargesSensor(SaskPowerBaseSensor):
    """Sensor for the total charges on the last bill."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "CAD"
    _attr_icon = "mdi:cash"
    _attr_name = "Last Bill Total Charges"

    def __init__(self, coordinator: DataUpdateCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{self._account_number}_last_bill_charges"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        return self.coordinator.data.get("last_bill_total_charges") if self.coordinator.data else None


class SaskPowerLastBillTotalUsageSensor(SaskPowerBaseSensor):
    """Sensor for the total kWh usage on the last bill."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:flash"
    _attr_name = "Last Bill Total Usage"

    def __init__(self, coordinator: DataUpdateCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{self._account_number}_last_bill_usage"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        return self.coordinator.data.get("last_bill_total_usage") if self.coordinator.data else None


class StatisticsSensor(SaskPowerBaseSensor):
    """Base class for sensors that write to the statistics table."""

    def __init__(self, coordinator: DataUpdateCoordinator, entry: ConfigEntry, config: dict) -> None:
        """Initialize the statistics sensor."""
        super().__init__(coordinator, entry)
        self._attr_native_value = 0  # Start with 0 instead of None
        self._backfill_days = config.get("backfill_days", 30)

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        _LOGGER.info("Statistics sensor %s added to hass, coordinator data available: %s, backfill_days: %d", 
                     self.name, bool(self.coordinator.data), self._backfill_days)
        # Process any existing data when the entity is first added
        if self.coordinator.last_update_success and self.coordinator.data:
            _LOGGER.info("Processing existing data for %s", self.name)
            await self._async_handle_statistics_update()
        else:
            _LOGGER.info("No existing data to process for %s", self.name)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator updates and trigger statistics import."""
        _LOGGER.debug("Coordinator update received for %s, data available: %s", 
                      self.name, bool(self.coordinator.data))
        if self.coordinator.data:
            # Schedule the async statistics import
            self.hass.async_create_task(self._async_handle_statistics_update())
        self.async_write_ha_state()

    async def _async_handle_statistics_update(self) -> None:
        """
        Process new data and import statistics when the coordinator updates.
        This method must be implemented by subclasses.
        """
        raise NotImplementedError

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None


class SaskPowerTotalConsumptionSensor(StatisticsSensor):
    """Total consumption sensor for the Energy Dashboard, with backfill."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:transmission-tower"
    _attr_name = "Total Consumption"

    def __init__(self, coordinator: DataUpdateCoordinator, entry: ConfigEntry, config: dict) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, config)
        self._attr_unique_id = f"{entry.entry_id}_{self._account_number}_total_consumption"

    async def _async_handle_statistics_update(self) -> None:
        """Process new data and import consumption statistics."""
        if not self.coordinator.data or not (interval_readings := self.coordinator.data.get("interval_readings")):
            _LOGGER.debug("No interval readings available for consumption statistics")
            return
        
        await self._import_statistics(interval_readings)

    async def _import_statistics(self, readings: list[dict[str, Any]]) -> None:
        """Import historical consumption data into the statistics table."""
        if not self.entity_id:
            _LOGGER.warning("Entity ID for %s not yet available, skipping statistics import", self.name)
            return
        
        statistic_id = self.entity_id
        _LOGGER.info("Starting consumption statistics import for entity %s with %d readings", 
                     statistic_id, len(readings))

        # Get the last statistics entry to know where to continue from
        last_stats = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, {"sum"}
        )

        last_stat_row = last_stats.get(statistic_id, [{}])
        if last_stat_row and last_stat_row[0]:
            # Existing statistics found - only import newer data
            last_sum = last_stat_row[0].get("sum", 0) or 0
            last_start_timestamp = last_stat_row[0].get("start", 0) or 0
            last_end_time = datetime.fromtimestamp(last_start_timestamp, tz=timezone.utc)
            _LOGGER.debug("Found existing statistics: last_sum=%s, last_time=%s", last_sum, last_end_time)
            filter_time = last_end_time
            starting_sum = last_sum
        else:
            # No existing statistics - backfill using configured days
            backfill_days_ago = datetime.now(timezone.utc) - timedelta(days=self._backfill_days)
            filter_time = backfill_days_ago
            starting_sum = 0
            _LOGGER.info("No existing statistics found, backfilling last %d days from %s", 
                        self._backfill_days, backfill_days_ago)
        
        # Group readings by hour and filter based on our time threshold
        hourly_data = {}
        new_readings_count = 0
        for reading in readings:
            reading_time = reading["datetime"].astimezone(timezone.utc)  # Ensure UTC
            if reading_time > filter_time:
                hour_start = reading_time.replace(minute=0, second=0, microsecond=0)
                if hour_start not in hourly_data:
                    hourly_data[hour_start] = 0
                hourly_data[hour_start] += reading["usage"]
                new_readings_count += 1

        _LOGGER.info("Found %d readings to process for %s (filter_time: %s)", 
                     new_readings_count, self.name, filter_time)

        # Create statistics entries
        current_sum = starting_sum
        stats_to_import = []
        for hour_start in sorted(hourly_data.keys()):
            current_sum += hourly_data[hour_start]
            stats_to_import.append(StatisticData(start=hour_start, sum=current_sum))

        if stats_to_import:
            _LOGGER.info("Importing %d hourly consumption statistics for %s.", len(stats_to_import), self.name)
            metadata = StatisticMetaData(
                has_mean=False,
                has_sum=True,
                name=self.name,
                source="recorder", 
                statistic_id=statistic_id,
                unit_of_measurement=self._attr_native_unit_of_measurement,
            )
            # Import the statistics - this should not be awaited
            async_import_statistics(self.hass, metadata, stats_to_import)
            
            # Update the sensor's current value
            self._attr_native_value = current_sum
            _LOGGER.info("Updated %s native value to %s", self.name, current_sum)
        else:
            _LOGGER.info("No consumption statistics to import for %s, setting value to starting sum: %s", 
                        self.name, starting_sum)
            # Set the sensor value to the starting sum even if no new data
            self._attr_native_value = starting_sum
        
        # Always trigger a state update
        self.async_write_ha_state()


class SaskPowerTotalCostSensor(StatisticsSensor):
    """Total estimated cost sensor for the Energy Dashboard, with backfill."""
    
    _attr_state_class = SensorStateClass.TOTAL
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "CAD"
    _attr_icon = "mdi:cash-multiple"
    _attr_name = "Estimated Total Cost"

    def __init__(self, coordinator: DataUpdateCoordinator, entry: ConfigEntry, config: dict) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, config)
        self._attr_unique_id = f"{entry.entry_id}_{self._account_number}_total_cost"

    async def _async_handle_statistics_update(self) -> None:
        """Process new data and import cost statistics."""
        if (
            not self.coordinator.data
            or not (interval_readings := self.coordinator.data.get("interval_readings"))
            or (avg_cost := self.coordinator.data.get("avg_cost_per_kwh")) is None
        ):
            _LOGGER.debug("Missing data for cost statistics: readings=%s, avg_cost=%s", 
                         bool(interval_readings), avg_cost)
            return
        
        await self._import_statistics(interval_readings, avg_cost)

    async def _import_statistics(self, readings: list[dict[str, Any]], avg_cost: float) -> None:
        """Import historical cost data into the statistics table."""
        if not self.entity_id:
            _LOGGER.warning("Entity ID for %s not yet available, skipping statistics import", self.name)
            return

        statistic_id = self.entity_id
        _LOGGER.info("Starting cost statistics import for entity %s with %d readings and avg_cost=%s", 
                     statistic_id, len(readings), avg_cost)

        # Get the last statistics entry to know where to continue from
        last_stats = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, {"sum"}
        )

        last_stat_row = last_stats.get(statistic_id, [{}])
        if last_stat_row:
            last_sum = last_stat_row[0].get("sum", 0) or 0
            last_start_timestamp = last_stat_row[0].get("start", 0) or 0
            last_end_time = datetime.fromtimestamp(last_start_timestamp, tz=timezone.utc)
            _LOGGER.debug("Found existing cost statistics: last_sum=%s, last_time=%s", last_sum, last_end_time)
        else:
            last_sum = 0
            last_end_time = datetime.fromtimestamp(0, tz=timezone.utc)
            _LOGGER.debug("No existing cost statistics found, starting from zero")

        # Group readings by hour and calculate costs
        hourly_data = {}
        new_readings_count = 0
        for reading in readings:
            reading_time = reading["datetime"].astimezone(timezone.utc)  # Ensure UTC
            if reading_time > last_end_time:
                hour_start = reading_time.replace(minute=0, second=0, microsecond=0)
                if hour_start not in hourly_data:
                    hourly_data[hour_start] = 0
                hourly_data[hour_start] += reading["usage"] * avg_cost
                new_readings_count += 1

        _LOGGER.info("Found %d new readings to process for %s", new_readings_count, self.name)

        # Create statistics entries
        current_sum = last_sum
        stats_to_import = []
        for hour_start in sorted(hourly_data.keys()):
            current_sum += hourly_data[hour_start]
            stats_to_import.append(StatisticData(start=hour_start, sum=current_sum))

        if stats_to_import:
            _LOGGER.info("Importing %d new hourly cost statistics for %s.", len(stats_to_import), self.name)
            metadata = StatisticMetaData(
                has_mean=False,
                has_sum=True,
                name=self.name,
                source="recorder",
                statistic_id=statistic_id,
                unit_of_measurement=self._attr_native_unit_of_measurement,
            )
            # Import the statistics - this should not be awaited
            async_import_statistics(self.hass, metadata, stats_to_import)
            
            # Update the sensor's current value
            self._attr_native_value = current_sum
            _LOGGER.info("Updated %s native value to %s", self.name, current_sum)
        else:
            _LOGGER.info("No new cost statistics to import for %s, setting value to last sum: %s", self.name, last_sum)
            # Set the sensor value to the last known sum even if no new data
            self._attr_native_value = last_sum
        
        # Always trigger a state update
        self.async_write_ha_state()