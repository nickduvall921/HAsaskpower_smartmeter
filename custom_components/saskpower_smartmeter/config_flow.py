"""Config flow for SaskPower SmartMeter."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN

_BACKFILL_DAYS_DEFAULT = 30
_UPDATE_INTERVAL_DEFAULT = 24


def _user_schema(
    backfill_days: int = _BACKFILL_DAYS_DEFAULT,
    update_interval_hours: int = _UPDATE_INTERVAL_DEFAULT,
) -> vol.Schema:
    """Return the data schema, with optional defaults for pre-filling (used by options flow)."""
    return vol.Schema(
        {
            vol.Required("username"): str,
            vol.Required("password"): str,
            vol.Required("account_number"): str,
            vol.Optional("backfill_days", default=backfill_days): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=365)
            ),
            vol.Optional("update_interval_hours", default=update_interval_hours): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=168)
            ),
        }
    )


def _options_schema(
    backfill_days: int = _BACKFILL_DAYS_DEFAULT,
    update_interval_hours: int = _UPDATE_INTERVAL_DEFAULT,
) -> vol.Schema:
    """Return the options schema (credentials not included — they don't change often)."""
    return vol.Schema(
        {
            vol.Optional("backfill_days", default=backfill_days): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=365)
            ),
            vol.Optional("update_interval_hours", default=update_interval_hours): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=168)
            ),
        }
    )


class SaskPowerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SaskPower SmartMeter."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input["account_number"])
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"SaskPower ({user_input['account_number']})",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(),
            errors=errors,
            description_placeholders={
                "backfill_info": "Days of historical data to import on first run (1–365)",
                "update_info": "How often to check for new data in hours (1–168)",
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "SaskPowerOptionsFlow":
        """Return the options flow handler for this integration."""
        return SaskPowerOptionsFlow(config_entry)


class SaskPowerOptionsFlow(config_entries.OptionsFlow):
    """
    Allow users to adjust backfill_days and update_interval_hours after initial setup
    via Settings → Integrations → SaskPower → Configure, without needing to
    delete and re-add the integration.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Pre-fill with current values so the user can see what's set.
        # Check entry.options first — that's where previously saved option
        # changes live. Fall back to entry.data (original setup values) if
        # the user has never visited the options form before (#9).
        current_backfill = self._config_entry.options.get(
            "backfill_days",
            self._config_entry.data.get("backfill_days", _BACKFILL_DAYS_DEFAULT),
        )
        current_interval = self._config_entry.options.get(
            "update_interval_hours",
            self._config_entry.data.get("update_interval_hours", _UPDATE_INTERVAL_DEFAULT),
        )

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(current_backfill, current_interval),
            description_placeholders={
                "backfill_info": "Days of historical data to import on next restart (1–365)",
                "update_info": "How often to check for new data in hours (1–168)",
            },
        )