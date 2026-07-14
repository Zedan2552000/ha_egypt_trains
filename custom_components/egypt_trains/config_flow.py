"""Config flow for Egypt Trains integration."""
import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN, CONF_DEPARTURE, CONF_ARRIVAL, STATIONS

class EgyptTrainsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Egypt Trains."""
    
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            if user_input[CONF_DEPARTURE] == user_input[CONF_ARRIVAL]:
                errors["base"] = "same_station"
            else:
                title = f"{user_input[CONF_DEPARTURE]} to {user_input[CONF_ARRIVAL]}"
                return self.async_create_entry(title=title, data=user_input)

        data_schema = vol.Schema({
            vol.Required(CONF_DEPARTURE, default="Cairo"): vol.In(STATIONS),
            vol.Required(CONF_ARRIVAL, default="Alexandria"): vol.In(STATIONS),
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )