"""The SaskPower SmartMeter integration."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .scraper import SaskPowerScraper

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SaskPower SmartMeter from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    username = entry.data["username"]
    password = entry.data["password"]
    account_number = entry.data["account_number"]
    
    # Get configurable settings with defaults
    backfill_days = entry.data.get("backfill_days", 30)
    update_interval_hours = entry.data.get("update_interval_hours", 24)
    
    # Create dynamic update interval based on user configuration
    scan_interval = timedelta(hours=update_interval_hours)
    
    _LOGGER.info(
        "Setting up SaskPower integration with %d days backfill and %d hour update interval",
        backfill_days, update_interval_hours
    )

    # The scraper will now create and manage its own synchronous requests.Session.
    scraper = SaskPowerScraper(username, password, account_number)

    async def async_update_data():
        """Fetch data from the API."""
        # Run the blocking I/O in a separate thread to avoid blocking Home Assistant's
        # event loop, which is critical for performance.
        # Pass the backfill_days to ensure we fetch enough data for the configured backfill
        return await hass.async_add_executor_job(scraper.get_data, max(60, backfill_days + 5))

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="saskpower_sensor",
        update_method=async_update_data,
        update_interval=scan_interval,
    )

    # Store the coordinator and config in hass.data to make it available to the platform setup.
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "config": {
            "backfill_days": backfill_days,
            "update_interval_hours": update_interval_hours,
        }
    }

    # Fetch initial data so we have it when platforms are set up.
    await coordinator.async_config_entry_first_refresh()

    # Forward the setup to the sensor platform.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok