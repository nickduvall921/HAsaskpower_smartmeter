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

    # Support options flow overrides (fix #13 — options flow is now implemented).
    # Options take precedence over initial config data so the user can adjust
    # these without re-adding the integration.
    backfill_days = entry.options.get(
        "backfill_days", entry.data.get("backfill_days", 30)
    )
    update_interval_hours = entry.options.get(
        "update_interval_hours", entry.data.get("update_interval_hours", 24)
    )

    scan_interval = timedelta(hours=update_interval_hours)

    _LOGGER.info(
        "Setting up SaskPower integration: backfill=%d days, update_interval=%d h",
        backfill_days,
        update_interval_hours,
    )

    scraper = SaskPowerScraper(username, password, account_number)

    async def async_update_data() -> dict | None:
        """Fetch data in a thread so we don't block the event loop."""
        # Add a small buffer (5 days) over the backfill window so the scraper
        # fetches slightly more data than strictly needed, ensuring the full
        # backfill window is always covered even near month boundaries.
        return await hass.async_add_executor_job(
            scraper.get_data, max(60, backfill_days + 5)
        )

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="saskpower_sensor",
        update_method=async_update_data,
        update_interval=scan_interval,
    )

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "config": {
            "backfill_days": backfill_days,
            "update_interval_hours": update_interval_hours,
        },
    }

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok