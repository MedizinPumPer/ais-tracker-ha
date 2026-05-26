"""Config flow – source setup + options (radius, watchlist)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_API_KEY, CONF_HOST, CONF_LATITUDE, CONF_LONGITUDE,
    CONF_PORT, CONF_PROTOCOL, CONF_RADIUS, CONF_SOURCE, CONF_WATCHLIST,
    DEFAULT_HOST, DEFAULT_PORT, DEFAULT_PROTOCOL, DEFAULT_RADIUS_KM,
    DOMAIN, PROTOCOL_TCP, PROTOCOL_UDP,
    SOURCE_AISSTREAM, SOURCE_RTLSDR,
)

_LOGGER = logging.getLogger(__name__)


async def _validate_aisstream_key(api_key: str) -> str | None:
    """Return error string or None on success."""
    try:
        import websockets
        async with websockets.connect(
            "wss://stream.aisstream.io/v0/stream", open_timeout=10
        ) as ws:
            await ws.send(json.dumps({
                "APIKey": api_key,
                "BoundingBoxes": [[[0, 0], [0.001, 0.001]]],
            }))
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                body = json.loads(raw)
                if "error" in str(body).lower() or "unauthorized" in str(body).lower():
                    return "invalid_api_key"
            except asyncio.TimeoutError:
                pass  # timeout = no error message = key is fine
        return None
    except Exception as exc:
        _LOGGER.debug("aisstream.io validation error: %s", exc)
        return "cannot_connect"


class AISTrackerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Three-step flow: source → credentials → done."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    # Step 1 – choose source
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            self._data[CONF_SOURCE] = user_input[CONF_SOURCE]
            if user_input[CONF_SOURCE] == SOURCE_AISSTREAM:
                return await self.async_step_aisstream()
            return await self.async_step_rtlsdr()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_SOURCE, default=SOURCE_AISSTREAM): vol.In({
                    SOURCE_AISSTREAM: "aisstream.io  (Internet, kostenlos)",
                    SOURCE_RTLSDR:    "RTL-SDR / AIS-catcher  (lokal, kein Internet)",
                }),
            }),
        )

    # Step 2a – aisstream.io
    async def async_step_aisstream(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        ha = self.hass.config

        if user_input is not None:
            err = await _validate_aisstream_key(user_input[CONF_API_KEY])
            if err:
                errors["base"] = err
            else:
                self._data.update(user_input)
                return self._finish()

        return self.async_show_form(
            step_id="aisstream",
            errors=errors,
            description_placeholders={"url": "https://aisstream.io"},
            data_schema=vol.Schema({
                vol.Required(CONF_API_KEY): str,
                vol.Required(CONF_LATITUDE,  default=round(ha.latitude,  5)): vol.Coerce(float),
                vol.Required(CONF_LONGITUDE, default=round(ha.longitude, 5)): vol.Coerce(float),
                vol.Required(CONF_RADIUS, default=DEFAULT_RADIUS_KM): vol.All(
                    vol.Coerce(float), vol.Range(min=0.5, max=100)
                ),
            }),
        )

    # Step 2b – RTL-SDR
    async def async_step_rtlsdr(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        ha = self.hass.config

        if user_input is not None:
            if user_input[CONF_PROTOCOL] == PROTOCOL_TCP:
                try:
                    r, w = await asyncio.wait_for(
                        asyncio.open_connection(user_input[CONF_HOST], user_input[CONF_PORT]),
                        timeout=5,
                    )
                    w.close()
                except Exception:
                    errors["base"] = "cannot_connect"

            if not errors:
                self._data.update(user_input)
                return self._finish()

        return self.async_show_form(
            step_id="rtlsdr",
            errors=errors,
            data_schema=vol.Schema({
                vol.Required(CONF_HOST,     default=DEFAULT_HOST):     str,
                vol.Required(CONF_PORT,     default=DEFAULT_PORT):     vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
                vol.Required(CONF_PROTOCOL, default=DEFAULT_PROTOCOL): vol.In({
                    PROTOCOL_UDP: "UDP  (AIS-catcher Standard: -u host port)",
                    PROTOCOL_TCP: "TCP",
                }),
                vol.Required(CONF_LATITUDE,  default=round(ha.latitude,  5)): vol.Coerce(float),
                vol.Required(CONF_LONGITUDE, default=round(ha.longitude, 5)): vol.Coerce(float),
                vol.Required(CONF_RADIUS, default=DEFAULT_RADIUS_KM): vol.All(
                    vol.Coerce(float), vol.Range(min=0.5, max=100)
                ),
            }),
        )

    def _finish(self) -> FlowResult:
        src = self._data[CONF_SOURCE]
        if src == SOURCE_AISSTREAM:
            title = f"AIS Tracker – aisstream.io ({self._data[CONF_LATITUDE]:.3f}, {self._data[CONF_LONGITUDE]:.3f})"
        else:
            title = f"AIS Tracker – RTL-SDR ({self._data[CONF_HOST]}:{self._data[CONF_PORT]})"
        return self.async_create_entry(title=title, data=self._data)

    @staticmethod
    @callback
    def async_get_options_flow(entry: config_entries.ConfigEntry) -> "AISTrackerOptionsFlow":
        return AISTrackerOptionsFlow(entry)


class AISTrackerOptionsFlow(config_entries.OptionsFlow):
    """
    Options: radius + watchlist.
    Changing either reloads the integration automatically.
    """

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_radius    = self._entry.options.get(CONF_RADIUS,    self._entry.data.get(CONF_RADIUS,    DEFAULT_RADIUS_KM))
        current_watchlist = self._entry.options.get(CONF_WATCHLIST, "")

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_RADIUS, default=current_radius): vol.All(
                    vol.Coerce(float), vol.Range(min=0.5, max=100)
                ),
                vol.Optional(CONF_WATCHLIST, default=current_watchlist): str,
            }),
            description_placeholders={
                "watchlist_hint": "z.B. 211234567, 211987654  (MMSI-Nummern, kommagetrennt)"
            },
        )
