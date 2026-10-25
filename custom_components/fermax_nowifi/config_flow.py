"""Config flow and Options flow for Fermax NOWIFI integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import FermaxAuthError, FermaxNowifiApi
from .const import (
    CONF_DOOR_PARAMS,
    CONF_FACE_RECOGNITION_AUTO_OPEN,
    CONF_FACE_RECOGNITION_ENABLED,
    CONF_FACE_RECOGNITION_THRESHOLD,
    CONF_FACE_RECOGNITION_URL,
    CONF_HOUSE_ID,
    CONF_HOUSE_TAG,
    CONF_PANEL_ID,
    CONF_STREAM_DURATION,
    DEFAULT_FACE_RECOGNITION_AUTO_OPEN,
    DEFAULT_FACE_RECOGNITION_ENABLED,
    DEFAULT_FACE_RECOGNITION_THRESHOLD,
    DEFAULT_FACE_RECOGNITION_URL,
    DEFAULT_STREAM_DURATION,
    DOMAIN,
    MAX_STREAM_DURATION,
    MIN_STREAM_DURATION,
)

_LOGGER = logging.getLogger(__name__)

USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)


class FermaxNowifiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Fermax NOWIFI.

    Only prompts for username (email) and password. All Firebase and Fermax cloud
    tokens/endpoints are configured automatically without manual intervention.
    """

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle initial step: user credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD].strip()

            api = FermaxNowifiApi(username, password)
            pairings: list[dict[str, Any]] = []

            try:
                await api.authenticate()
                pairings = await api.get_pairings()
            except FermaxAuthError:
                errors["base"] = "invalid_auth"
            except Exception as exc:
                _LOGGER.exception("Unexpected error connecting to Fermax Cloud: %s", exc)
                errors["base"] = "cannot_connect"
            finally:
                await api.close()

            if not errors:
                if not pairings:
                    errors["base"] = "no_devices"
                else:
                    first_p = pairings[0]
                    house_id = first_p.get("deviceId", "")
                    house_tag = first_p.get("tag", "Casa")

                    # Extraer panel_id dinámicamente de panelAccessDoors o installationId
                    panel_id = "203730463032500a006e004c"
                    panel_doors = first_p.get("panelAccessDoors", [])
                    if panel_doors and panel_doors[0].get("deviceId"):
                        panel_id = panel_doors[0]["deviceId"]
                    elif first_p.get("installationId"):
                        inst_id = first_p["installationId"]
                        if inst_id.startswith("inst_"):
                            panel_id = inst_id[5:]

                    # Extraer door_params de panelAccessDoors o accessDoorMap
                    door_params = {"block": 0, "subblock": 0, "number": 1}
                    if panel_doors and panel_doors[0].get("doorId"):
                        door_params = panel_doors[0]["doorId"]
                    else:
                        access_door_map = first_p.get("accessDoorMap", {})
                        if access_door_map:
                            first_key = list(access_door_map.keys())[0]
                            door_params = access_door_map[first_key].get(
                                "accessId", door_params
                            )

                    await self.async_set_unique_id(username.lower())
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=f"Fermax NOWIFI ({house_tag})",
                        data={
                            CONF_USERNAME: username,
                            CONF_PASSWORD: password,
                            CONF_HOUSE_ID: house_id,
                            CONF_PANEL_ID: panel_id,
                            CONF_HOUSE_TAG: house_tag,
                            CONF_DOOR_PARAMS: door_params,
                        },
                        options={
                            CONF_STREAM_DURATION: DEFAULT_STREAM_DURATION,
                        },
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=USER_DATA_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get options flow handler."""
        return FermaxNowifiOptionsFlowHandler(config_entry)


class FermaxNowifiOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for configuring stream timeout and preferences."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_duration = self.config_entry.options.get(
            CONF_STREAM_DURATION, DEFAULT_STREAM_DURATION
        )
        current_face_enabled = self.config_entry.options.get(
            CONF_FACE_RECOGNITION_ENABLED, DEFAULT_FACE_RECOGNITION_ENABLED
        )
        current_face_url = self.config_entry.options.get(
            CONF_FACE_RECOGNITION_URL, DEFAULT_FACE_RECOGNITION_URL
        )
        current_face_threshold = float(
            self.config_entry.options.get(
                CONF_FACE_RECOGNITION_THRESHOLD, DEFAULT_FACE_RECOGNITION_THRESHOLD
            )
        )
        current_face_auto_open = self.config_entry.options.get(
            CONF_FACE_RECOGNITION_AUTO_OPEN, DEFAULT_FACE_RECOGNITION_AUTO_OPEN
        )

        options_schema = vol.Schema(
            {
                vol.Required(CONF_STREAM_DURATION, default=current_duration): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_STREAM_DURATION,
                        max=MAX_STREAM_DURATION,
                        step=5,
                        unit_of_measurement="segundos",
                        mode=NumberSelectorMode.SLIDER,
                    )
                ),
                vol.Optional(
                    CONF_FACE_RECOGNITION_ENABLED, default=current_face_enabled
                ): BooleanSelector(),
                vol.Optional(
                    CONF_FACE_RECOGNITION_URL, default=current_face_url
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
                vol.Optional(
                    CONF_FACE_RECOGNITION_THRESHOLD, default=current_face_threshold
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.50,
                        max=0.99,
                        step=0.05,
                        mode=NumberSelectorMode.SLIDER,
                    )
                ),
                vol.Optional(
                    CONF_FACE_RECOGNITION_AUTO_OPEN, default=current_face_auto_open
                ): BooleanSelector(),
            }
        )

        return self.async_show_form(step_id="init", data_schema=options_schema)
