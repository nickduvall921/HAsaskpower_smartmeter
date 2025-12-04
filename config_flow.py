"""Config flow for SaskPower SmartMeter."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN

class SaskPowerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SaskPower SmartMeter."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # In a real component, you would validate the user input here,
            # for example by trying to log in. For now, we'll assume it's correct.
            # You can add the validation logic inside a self.hass.async_add_executor_job call
            # that uses the scraper.
            
            # Use account number to create a unique ID for this config entry
            await self.async_set_unique_id(user_input["account_number"])
            self._abort_if_unique_id_configured()

            return self.async_create_entry(title=f"SaskPower ({user_input['account_number']})", data=user_input)

        data_schema = vol.Schema(
            {
                vol.Required("username"): str,
                vol.Required("password"): str,
                vol.Required("account_number"): str,
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

