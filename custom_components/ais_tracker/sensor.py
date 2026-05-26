"""
Sensor platform for AIS Ship Tracker
─────────────────────────────────────
Two types of entities – that's it:

  AISOverviewSensor      – 1 per integration, state = ship count,
                           attributes carry the full sorted ship list
                           → perfect for Markdown / template cards

  AISWatchedShipSensor   – 1 per MMSI in the watchlist (configured in Options),
                           always available, state = "In Sicht" / "Nicht in Sicht"
                           → use for automations & individual dashboard tiles

For everything else (fire-and-forget reactions) use HA events:
  ais_tracker_ship_appeared / ais_tracker_ship_departed
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_WATCHLIST, DOMAIN
from .coordinator import AISCoordinator, parse_watchlist

_LOGGER = logging.getLogger(__name__)

STATE_IN_RANGE  = "In Sicht"
STATE_OUT_RANGE = "Nicht in Sicht"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AISCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = [AISOverviewSensor(coordinator, entry)]

    watchlist = parse_watchlist(entry.options.get(CONF_WATCHLIST, ""))
    for mmsi in watchlist:
        entities.append(AISWatchedShipSensor(coordinator, entry, mmsi))

    async_add_entities(entities, update_before_add=False)


# ── Overview sensor ───────────────────────────────────────────────────────────

class AISOverviewSensor(CoordinatorEntity[AISCoordinator], SensorEntity):
    """
    Single sensor summarising all ships currently in range.

    state      : int  – number of ships
    attributes : ships (list, sorted by distance), nearest (dict)
    """

    _attr_icon                       = "mdi:ferry"
    _attr_state_class                = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "ships"
    _attr_has_entity_name            = True

    def __init__(self, coordinator: AISCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id   = f"{entry.entry_id}_overview"
        self._attr_name        = "Schiffe in der Nähe"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ships = sorted(
            (self.coordinator.data or {}).values(),
            key=lambda s: s.get("distance_km", 9999),
        )
        return {
            "ships":   ships,
            "nearest": ships[0] if ships else None,
        }


# ── Watched ship sensor ───────────────────────────────────────────────────────

class AISWatchedShipSensor(CoordinatorEntity[AISCoordinator], SensorEntity):
    """
    Persistent sensor for a specific MMSI (configured in Options → Watchlist).

    state      : "In Sicht" | "Nicht in Sicht"
    attributes : full ship data when in range, basic info when not
    available  : always True  → no dead entities, clean history graph
    """

    _attr_icon            = "mdi:ferry"
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AISCoordinator,
        entry: ConfigEntry,
        mmsi: str,
    ) -> None:
        super().__init__(coordinator)
        self._mmsi             = mmsi
        self._attr_unique_id   = f"{entry.entry_id}_watch_{mmsi}"
        self._attr_name        = f"Schiff {mmsi}"   # updated once name is known
        self._attr_device_info = _device_info(entry)

    # Always available – we just report "not in sight"
    @property
    def available(self) -> bool:
        return True

    @property
    def _ship(self) -> dict[str, Any] | None:
        return (self.coordinator.data or {}).get(self._mmsi)

    @property
    def native_value(self) -> str:
        return STATE_IN_RANGE if self._ship else STATE_OUT_RANGE

    @property
    def icon(self) -> str:
        return "mdi:ferry" if self._ship else "mdi:ferry-off"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ship = self._ship
        if ship:
            return {
                "mmsi":         self._mmsi,
                "name":         ship.get("name"),
                "callsign":     ship.get("callsign"),
                "imo":          ship.get("imo"),
                "ship_type":    ship.get("ship_type_label"),
                "destination":  ship.get("destination"),
                "speed_knots":  ship.get("speed"),
                "heading":      ship.get("heading"),
                "course":       ship.get("course"),
                "nav_status":   ship.get("nav_status_label"),
                "latitude":     ship.get("lat"),
                "longitude":    ship.get("lon"),
                "distance_km":  ship.get("distance_km"),
                "length_m":     ship.get("length_m"),
            }
        return {"mmsi": self._mmsi, "in_range": False}

    @callback
    def _handle_coordinator_update(self) -> None:
        # Keep entity name in sync with received ship name
        ship = self._ship
        if ship and ship.get("name"):
            self._attr_name = ship["name"]
        super()._handle_coordinator_update()


# ── Shared device info ────────────────────────────────────────────────────────

def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="AIS Ship Tracker",
        manufacturer="Community",
        model="AIS Tracker",
        entry_type=DeviceEntryType.SERVICE,
    )
