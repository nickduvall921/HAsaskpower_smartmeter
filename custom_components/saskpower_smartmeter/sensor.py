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
            # Summary sensors
            SaskPowerDailyUsageSensor(coordinator, entry),
            SaskPowerWeeklyUsageSensor(coordinator, entry),
            SaskPowerMonthlyUsageSensor(coordinator, entry),
            SaskPowerLastUpdatedSensor(coordinator, entry),
            SaskPowerLastBillTotalChargesSensor(coordinator, entry),
            SaskPowerLastBillTotalUsageSensor(coordinator, entry),
            # Energy Dashboard sensors (with historical backfill)
            SaskPowerTotalConsumptionSensor(coordinator, entry, config),
            SaskPowerTotalCostSensor(coordinator, entry, config),
        ]
    )


class SaskPowerBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for all SaskPower sensors, providing shared device info."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DataUpdateCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor and set device info."""
        super().__init__(coordinator)
        self._account_number = entry.data["account_number"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._account_number)},
            name=f"SaskPower Account {self._account_number}",
            manufacturer="SaskPower",
            model="Smart Meter",
            configuration_url="https://www.saskpower.com/profile/my-dashboard",
        )


# ---------------------------------------------------------------------------
# Summary sensors
# ---------------------------------------------------------------------------

class SaskPowerDailyUsageSensor(SaskPowerBaseSensor):
    """Most recent full day of power usage."""

    _attr_state_class = SensorStateClass.TOTAL
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:counter"
    _attr_name = "Most Recent Day Usage"

    def __init__(self, coordinator: DataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{self._account_number}_daily_usage"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.get("daily_usage") if self.coordinator.data else None


class SaskPowerWeeklyUsageSensor(SaskPowerBaseSensor):
    """Last 7 days of available power usage."""

    _attr_state_class = SensorStateClass.TOTAL
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:counter"
    _attr_name = "Last 7 Days Usage"

    def __init__(self, coordinator: DataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{self._account_number}_weekly_usage"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.get("weekly_usage") if self.coordinator.data else None


class SaskPowerMonthlyUsageSensor(SaskPowerBaseSensor):
    """Previous calendar month's total power usage."""

    _attr_state_class = SensorStateClass.TOTAL
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:counter"
    _attr_name = "Previous Month Usage"

    def __init__(self, coordinator: DataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{self._account_number}_monthly_usage"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.get("monthly_usage") if self.coordinator.data else None


class SaskPowerLastUpdatedSensor(SaskPowerBaseSensor):
    """Timestamp of the last available 15-minute data point."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-clock"
    _attr_name = "Last Data Point"

    def __init__(self, coordinator: DataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{self._account_number}_last_updated"

    @property
    def native_value(self) -> datetime | None:
        return (
            self.coordinator.data.get("latest_data_timestamp")
            if self.coordinator.data
            else None
        )


class SaskPowerLastBillTotalChargesSensor(SaskPowerBaseSensor):
    """Total charges on the most recent bill."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "CAD"
    _attr_icon = "mdi:cash"
    _attr_name = "Last Bill Total Charges"

    def __init__(self, coordinator: DataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{self._account_number}_last_bill_charges"

    @property
    def native_value(self) -> float | None:
        return (
            self.coordinator.data.get("last_bill_total_charges")
            if self.coordinator.data
            else None
        )


class SaskPowerLastBillTotalUsageSensor(SaskPowerBaseSensor):
    """Total kWh usage on the most recent bill."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:flash"
    _attr_name = "Last Bill Total Usage"

    def __init__(self, coordinator: DataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{self._account_number}_last_bill_usage"

    @property
    def native_value(self) -> float | None:
        return (
            self.coordinator.data.get("last_bill_total_usage")
            if self.coordinator.data
            else None
        )


# ---------------------------------------------------------------------------
# Statistics / Energy Dashboard sensors
# ---------------------------------------------------------------------------

class StatisticsSensor(SaskPowerBaseSensor):
    """
    Base class for sensors that write long-term statistics to the recorder.

    Subclasses implement `_async_handle_statistics_update` which is called
    both on first add (to trigger backfill) and on every coordinator update.
    """

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        entry: ConfigEntry,
        config: dict,
    ) -> None:
        super().__init__(coordinator, entry)
        # Leave native_value as None until the first statistics import completes.
        # Setting it to 0 here would make the sensor appear available with a
        # misleading zero reading before any real data has been imported (#12).
        # Subclasses define _attr_native_unit_of_measurement before this base
        # __init__ runs (as class-level attributes), so there is no window where
        # a value exists without a unit (#13).
        self._backfill_days: int = config.get("backfill_days", 30)

    async def async_added_to_hass(self) -> None:
        """Trigger an initial statistics import when the entity is first registered."""
        await super().async_added_to_hass()
        _LOGGER.info(
            "Statistics sensor '%s' added; data available: %s; backfill_days: %d",
            self.name,
            bool(self.coordinator.data),
            self._backfill_days,
        )
        if self.coordinator.last_update_success and self.coordinator.data:
            await self._async_handle_statistics_update()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Schedule a statistics import whenever the coordinator delivers new data."""
        if self.coordinator.data:
            self.hass.async_create_task(self._async_handle_statistics_update())
        self.async_write_ha_state()

    async def _async_handle_statistics_update(self) -> None:
        """Import new statistics into the recorder. Must be implemented by subclasses."""
        raise NotImplementedError

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self.coordinator.data is not None


class SaskPowerTotalConsumptionSensor(StatisticsSensor):
    """
    Cumulative consumption sensor for the Energy Dashboard.

    On first run it backfills up to `backfill_days` of hourly statistics.
    On subsequent runs it appends only readings newer than the last stored stat.
    """

    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:transmission-tower"
    _attr_name = "Total Consumption"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        entry: ConfigEntry,
        config: dict,
    ) -> None:
        super().__init__(coordinator, entry, config)
        self._attr_unique_id = (
            f"{entry.entry_id}_{self._account_number}_total_consumption"
        )

    async def _async_handle_statistics_update(self) -> None:
        if not self.coordinator.data:
            return
        interval_readings = self.coordinator.data.get("interval_readings")
        if not interval_readings:
            _LOGGER.debug("No interval readings available for consumption statistics.")
            return
        await self._import_statistics(interval_readings)

    async def _import_statistics(self, readings: list[dict[str, Any]]) -> None:
        """Build and import hourly consumption statistics into the recorder."""
        if not self.entity_id:
            _LOGGER.warning(
                "Entity ID not yet assigned for '%s', skipping statistics import.",
                self.name,
            )
            return

        statistic_id = self.entity_id
        _LOGGER.info(
            "Importing consumption statistics for '%s' (%d readings available).",
            statistic_id,
            len(readings),
        )

        # Query the recorder for the most recent existing statistic.
        # Signature: get_last_statistics(hass, number_of_stats, statistic_id,
        #   convert_units, types). convert_units=True normalises units to the
        # display unit (e.g. Wh → kWh). Despite earlier speculation it was
        # removed, the 5-argument signature is confirmed present in current HA.
        last_stats = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, {"sum"}
        )

        last_stat_row = last_stats.get(statistic_id, [{}])

        # Fix #3: check both that the list is non-empty AND the first element
        # has actual data (it can be an empty dict when no stats exist yet).
        if last_stat_row and last_stat_row[0]:
            last_sum = last_stat_row[0].get("sum", 0) or 0
            last_start_ts = last_stat_row[0].get("start", 0) or 0
            # Advance by one full hour: the last recorded stat covers the hour
            # starting at last_start_ts, so we only want readings from the NEXT
            # hour onwards. Using > last_start_ts would re-process the boundary hour.
            filter_time = datetime.fromtimestamp(last_start_ts, tz=timezone.utc) + timedelta(hours=1)
            starting_sum = last_sum
            _LOGGER.debug(
                "Existing consumption stats found: last_sum=%.3f, next_import_from=%s",
                last_sum,
                filter_time,
            )
        else:
            # No existing statistics — backfill from the configured number of days ago.
            filter_time = datetime.now(timezone.utc) - timedelta(days=self._backfill_days)
            starting_sum = 0.0
            _LOGGER.info(
                "No existing consumption statistics; backfilling last %d days from %s.",
                self._backfill_days,
                filter_time,
            )

        # Aggregate 15-minute readings into hourly buckets, keeping only new data.
        hourly_data: dict[datetime, float] = {}
        skipped = 0
        for reading in readings:
            reading_time = reading["datetime"].astimezone(timezone.utc)
            if reading_time > filter_time:
                hour_start = reading_time.replace(minute=0, second=0, microsecond=0)
                hourly_data[hour_start] = hourly_data.get(hour_start, 0) + reading["usage"]
            else:
                skipped += 1

        _LOGGER.debug(
            "Consumption: %d new readings to import, %d skipped as already recorded.",
            len(hourly_data),
            skipped,
        )

        current_sum = starting_sum
        stats_to_import = []
        for hour_start in sorted(hourly_data):
            current_sum += hourly_data[hour_start]
            stats_to_import.append(StatisticData(start=hour_start, sum=current_sum))

        if stats_to_import:
            _LOGGER.info(
                "Writing %d hourly consumption stats for '%s'.",
                len(stats_to_import),
                statistic_id,
            )
            metadata = StatisticMetaData(
                has_mean=False,
                has_sum=True,
                name=self.name,
                source="recorder",
                statistic_id=statistic_id,
                unit_of_measurement=self._attr_native_unit_of_measurement,
            )
            async_import_statistics(self.hass, metadata, stats_to_import)
            self._attr_native_value = current_sum
        else:
            _LOGGER.debug(
                "No new consumption stats to write for '%s'; current sum %.3f.",
                statistic_id,
                starting_sum,
            )
            self._attr_native_value = starting_sum

        self.async_write_ha_state()


class SaskPowerTotalCostSensor(StatisticsSensor):
    """
    Cumulative estimated cost sensor for the Energy Dashboard.

    Cost is estimated by multiplying each interval's kWh by the average
    cost-per-kWh derived from the most recent bill.
    """

    _attr_state_class = SensorStateClass.TOTAL
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "CAD"
    _attr_icon = "mdi:cash-multiple"
    _attr_name = "Estimated Total Cost"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        entry: ConfigEntry,
        config: dict,
    ) -> None:
        super().__init__(coordinator, entry, config)
        self._attr_unique_id = f"{entry.entry_id}_{self._account_number}_total_cost"

    async def _async_handle_statistics_update(self) -> None:
        if not self.coordinator.data:
            return

        interval_readings = self.coordinator.data.get("interval_readings")
        if not interval_readings:
            _LOGGER.debug("No interval readings available for cost statistics.")
            return

        # Fix #5: use `not avg_cost` (falsy) instead of `is None` so that a
        # genuine zero value (e.g. a $0 promotional bill) also causes a skip.
        avg_cost = self.coordinator.data.get("avg_cost_per_kwh")
        if not avg_cost:
            _LOGGER.debug(
                "avg_cost_per_kwh is missing or zero (%s); skipping cost statistics.",
                avg_cost,
            )
            return

        await self._import_statistics(interval_readings, avg_cost)

    async def _import_statistics(
        self, readings: list[dict[str, Any]], avg_cost: float
    ) -> None:
        """Build and import hourly cost statistics into the recorder."""
        if not self.entity_id:
            _LOGGER.warning(
                "Entity ID not yet assigned for '%s', skipping statistics import.",
                self.name,
            )
            return

        statistic_id = self.entity_id
        _LOGGER.info(
            "Importing cost statistics for '%s' (%d readings, avg_cost=%.4f CAD/kWh).",
            statistic_id,
            len(readings),
            avg_cost,
        )

        # Signature: get_last_statistics(hass, number_of_stats, statistic_id,
        #   convert_units, types). convert_units=True normalises units to the
        # display unit (e.g. Wh → kWh). Despite earlier speculation it was
        # removed, the 5-argument signature is confirmed present in current HA.
        last_stats = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, {"sum"}
        )

        last_stat_row = last_stats.get(statistic_id, [{}])

        # Fix #3: consistent empty-check — verify both list and first element have data.
        if last_stat_row and last_stat_row[0]:
            last_sum = last_stat_row[0].get("sum", 0) or 0
            last_start_ts = last_stat_row[0].get("start", 0) or 0
            # Advance by one full hour so the already-recorded boundary hour
            # is not re-imported on every update cycle.
            filter_time = datetime.fromtimestamp(last_start_ts, tz=timezone.utc) + timedelta(hours=1)
            starting_sum = last_sum
            _LOGGER.debug(
                "Existing cost stats found: last_sum=%.2f, next_import_from=%s",
                last_sum,
                filter_time,
            )
        else:
            # Fix #2: use backfill_days, not epoch zero.
            filter_time = datetime.now(timezone.utc) - timedelta(days=self._backfill_days)
            starting_sum = 0.0
            _LOGGER.info(
                "No existing cost statistics; backfilling last %d days from %s.",
                self._backfill_days,
                filter_time,
            )

        # Aggregate into hourly cost buckets.
        hourly_data: dict[datetime, float] = {}
        skipped = 0
        for reading in readings:
            reading_time = reading["datetime"].astimezone(timezone.utc)
            if reading_time > filter_time:
                hour_start = reading_time.replace(minute=0, second=0, microsecond=0)
                hourly_data[hour_start] = (
                    hourly_data.get(hour_start, 0) + reading["usage"] * avg_cost
                )
            else:
                skipped += 1

        _LOGGER.debug(
            "Cost: %d new hourly buckets to import, %d readings skipped.",
            len(hourly_data),
            skipped,
        )

        current_sum = starting_sum
        stats_to_import = []
        for hour_start in sorted(hourly_data):
            current_sum += hourly_data[hour_start]
            stats_to_import.append(StatisticData(start=hour_start, sum=current_sum))

        if stats_to_import:
            _LOGGER.info(
                "Writing %d hourly cost stats for '%s'.",
                len(stats_to_import),
                statistic_id,
            )
            metadata = StatisticMetaData(
                has_mean=False,
                has_sum=True,
                name=self.name,
                source="recorder",
                statistic_id=statistic_id,
                unit_of_measurement=self._attr_native_unit_of_measurement,
            )
            async_import_statistics(self.hass, metadata, stats_to_import)
            self._attr_native_value = current_sum
        else:
            _LOGGER.debug(
                "No new cost stats to write for '%s'; current sum %.2f.",
                statistic_id,
                starting_sum,
            )
            self._attr_native_value = starting_sum

        self.async_write_ha_state()