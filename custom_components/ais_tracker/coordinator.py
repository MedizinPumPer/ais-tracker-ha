"""
AIS Coordinator
───────────────
Manages one persistent connection (aisstream.io WebSocket or RTL-SDR NMEA socket).
Ships are kept in an internal dict; the coordinator pushes updates to HA via
async_set_updated_data().  When ships appear or disappear HA events are fired
so automations can react without needing individual entities.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from typing import Any

import websockets
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CLEANUP_INTERVAL,
    CONF_API_KEY,
    CONF_HOST,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_PORT,
    CONF_PROTOCOL,
    CONF_RADIUS,
    CONF_SOURCE,
    DOMAIN,
    EVENT_SHIP_APPEARED,
    EVENT_SHIP_DEPARTED,
    NAV_STATUS,
    PROTOCOL_TCP,
    PROTOCOL_UDP,
    SHIP_TIMEOUT_SECONDS,
    SHIP_TYPES,
    SOURCE_AISSTREAM,
    SOURCE_RTLSDR,
)

_LOGGER = logging.getLogger(__name__)


# ── Geo helpers ───────────────────────────────────────────────────────────────

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bounding_box(lat: float, lon: float, radius_km: float) -> list[list[float]]:
    """SW / NE corners for aisstream.io subscription."""
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * math.cos(math.radians(lat)))
    return [[lat - dlat, lon - dlon], [lat + dlat, lon + dlon]]


def ship_type_label(code: int | None) -> str:
    if code is None:
        return "Unknown"
    for k, v in SHIP_TYPES.items():
        if code == k or (code // 10 == k // 10 and k % 10 == 0):
            return v
    return f"Type {code}"


def parse_watchlist(raw: str) -> list[str]:
    """'211234567, 211987654' → ['211234567', '211987654']"""
    return [m.strip() for m in raw.split(",") if m.strip().isdigit()]


# ── Coordinator ───────────────────────────────────────────────────────────────

class AISCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Push-based coordinator – no polling interval."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self._entry = entry
        self._ships: dict[str, dict[str, Any]] = {}
        self._source: str        = entry.data[CONF_SOURCE]
        self._home_lat: float    = entry.data[CONF_LATITUDE]
        self._home_lon: float    = entry.data[CONF_LONGITUDE]
        self._radius_km: float   = entry.options.get(CONF_RADIUS, entry.data[CONF_RADIUS])
        self._main_task: asyncio.Task | None    = None
        self._cleanup_task: asyncio.Task | None = None
        self._nmea_parts: dict[tuple, dict]     = {}
        self._msg_count: int = 0  # total messages received (for debugging)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_start(self) -> None:
        _LOGGER.info(
            "AIS Tracker starting – source=%s lat=%.4f lon=%.4f radius=%.1f km",
            self._source, self._home_lat, self._home_lon, self._radius_km,
        )
        if self._source == SOURCE_AISSTREAM:
            self._main_task = self.hass.async_create_task(
                self._aisstream_loop(), name="ais_tracker_aisstream"
            )
        else:
            self._main_task = self.hass.async_create_task(
                self._rtlsdr_loop(), name="ais_tracker_rtlsdr"
            )
        self._cleanup_task = self.hass.async_create_task(
            self._cleanup_loop(), name="ais_tracker_cleanup"
        )

    async def async_stop(self) -> None:
        for task in (self._main_task, self._cleanup_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    # ── Internal ship management ──────────────────────────────────────────────

    def _update_ship(self, mmsi: str, patch: dict[str, Any]) -> None:
        is_new = mmsi not in self._ships
        ship = self._ships.setdefault(mmsi, {"mmsi": mmsi})

        for k, v in patch.items():
            if v is not None and v != "":
                ship[k] = v

        ship["last_seen"] = time.time()
        ship["nav_status_label"] = NAV_STATUS.get(ship.get("nav_status"), "Unknown")
        ship["ship_type_label"]  = ship_type_label(ship.get("ship_type"))

        if ship.get("lat") and ship.get("lon"):
            ship["distance_km"] = round(
                haversine_km(self._home_lat, self._home_lon, ship["lat"], ship["lon"]), 2
            )

        if is_new:
            _LOGGER.info(
                "AIS: ✅ new ship – name='%s' mmsi=%s dist=%.2f km",
                ship.get("name", "?"), mmsi, ship.get("distance_km", -1),
            )
            self.hass.bus.async_fire(EVENT_SHIP_APPEARED, self._event_data(ship))
        else:
            _LOGGER.debug(
                "AIS: update – name='%s' mmsi=%s speed=%s kn",
                ship.get("name", "?"), mmsi, ship.get("speed"),
            )

        self.async_set_updated_data(dict(self._ships))

    def _remove_ship(self, mmsi: str) -> None:
        ship = self._ships.pop(mmsi, {})
        _LOGGER.info("AIS: ship left – name='%s' mmsi=%s", ship.get("name", "?"), mmsi)
        self.hass.bus.async_fire(EVENT_SHIP_DEPARTED, self._event_data(ship))

    @staticmethod
    def _event_data(ship: dict) -> dict[str, Any]:
        return {
            "mmsi":        ship.get("mmsi"),
            "name":        ship.get("name", f"MMSI {ship.get('mmsi')}"),
            "ship_type":   ship.get("ship_type_label"),
            "destination": ship.get("destination"),
            "speed":       ship.get("speed"),
            "distance_km": ship.get("distance_km"),
            "latitude":    ship.get("lat"),
            "longitude":   ship.get("lon"),
            "callsign":    ship.get("callsign"),
        }

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(CLEANUP_INTERVAL)
            cutoff = time.time() - SHIP_TIMEOUT_SECONDS
            stale = [m for m, s in self._ships.items() if s.get("last_seen", 0) < cutoff]
            for mmsi in stale:
                self._remove_ship(mmsi)
            if stale:
                self.async_set_updated_data(dict(self._ships))

    # ── aisstream.io ──────────────────────────────────────────────────────────

    async def _aisstream_loop(self) -> None:
        bbox = bounding_box(self._home_lat, self._home_lon, self._radius_km)
        subscribe = {
            "APIKey": self._entry.data[CONF_API_KEY],
            "BoundingBoxes": [bbox],
            # No FilterMessageTypes → receive ALL types so we can log unexpected ones
        }

        _LOGGER.info("AIS aisstream.io: bounding box = %s", bbox)

        while True:
            try:
                _LOGGER.debug("AIS aisstream.io: connecting...")
                async with websockets.connect(
                    "wss://stream.aisstream.io/v0/stream",
                    ping_interval=20,
                    ping_timeout=30,
                ) as ws:
                    await ws.send(json.dumps(subscribe))
                    _LOGGER.info("AIS aisstream.io: ✅ connected, subscription sent")

                    async for raw in ws:
                        self._msg_count += 1
                        try:
                            msg = json.loads(raw)
                            mtype = msg.get("MessageType", "")

                            # Log first 10 messages in full so we can debug
                            if self._msg_count <= 10:
                                _LOGGER.info(
                                    "AIS raw msg #%d type=%s: %s",
                                    self._msg_count, mtype, raw[:300],
                                )
                            elif self._msg_count % 50 == 0:
                                _LOGGER.debug("AIS: %d messages received so far", self._msg_count)

                            if mtype in ("PositionReport", "ShipStaticData"):
                                self._handle_aisstream(msg)
                            elif mtype:
                                _LOGGER.debug("AIS: unhandled MessageType=%s", mtype)
                            else:
                                # Could be an error/status message from aisstream.io
                                _LOGGER.warning("AIS aisstream.io: no MessageType in msg: %s", raw[:200])

                        except Exception as exc:
                            _LOGGER.error("AIS: parse error on msg #%d: %s | raw: %s", self._msg_count, exc, raw[:200])

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _LOGGER.warning("AIS aisstream.io: disconnected (%s) – retry in 30 s", exc)
                await asyncio.sleep(30)

    def _handle_aisstream(self, msg: dict) -> None:
        mtype = msg.get("MessageType", "")
        meta  = msg.get("MetaData", {})
        mmsi  = str(meta.get("MMSI", "")).strip()

        if not mmsi or mmsi == "0":
            _LOGGER.debug("AIS: skipping msg with no MMSI, type=%s", mtype)
            return

        if mtype == "PositionReport":
            pr = msg.get("Message", {}).get("PositionReport", {})
            self._update_ship(mmsi, {
                "name":       meta.get("ShipName", "").strip() or None,
                "lat":        meta.get("latitude"),
                "lon":        meta.get("longitude"),
                "speed":      pr.get("Sog"),
                "heading":    pr.get("TrueHeading"),
                "course":     pr.get("Cog"),
                "nav_status": pr.get("NavigationalStatus"),
            })

        elif mtype == "ShipStaticData":
            sd  = msg.get("Message", {}).get("ShipStaticData", {})
            dim = sd.get("Dimension", {})
            length = (dim.get("A") or 0) + (dim.get("B") or 0)
            self._update_ship(mmsi, {
                "name":        sd.get("Name", "").strip() or None,
                "ship_type":   sd.get("Type"),
                "destination": sd.get("Destination", "").strip() or None,
                "callsign":    sd.get("CallSign", "").strip() or None,
                "imo":         sd.get("ImoNumber") or None,
                "length_m":    length if length > 0 else None,
            })

    # ── RTL-SDR / AIS-catcher ─────────────────────────────────────────────────

    async def _rtlsdr_loop(self) -> None:
        host     = self._entry.data[CONF_HOST]
        port     = self._entry.data[CONF_PORT]
        protocol = self._entry.data[CONF_PROTOCOL]
        while True:
            try:
                if protocol == PROTOCOL_UDP:
                    await self._nmea_udp(host, port)
                else:
                    await self._nmea_tcp(host, port)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _LOGGER.warning("AIS RTL-SDR: error (%s) – retry in 10 s", exc)
                await asyncio.sleep(10)

    async def _nmea_udp(self, host: str, port: int) -> None:
        loop  = asyncio.get_running_loop()
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=500)

        class _UDP(asyncio.DatagramProtocol):
            def datagram_received(self, data: bytes, addr: tuple) -> None:
                for line in data.decode("ascii", errors="ignore").splitlines():
                    line = line.strip()
                    if line:
                        try:
                            queue.put_nowait(line)
                        except asyncio.QueueFull:
                            pass

        transport, _ = await loop.create_datagram_endpoint(_UDP, local_addr=(host, port))
        _LOGGER.info("AIS RTL-SDR: ✅ listening NMEA UDP %s:%s", host, port)
        try:
            while True:
                self._parse_nmea(await queue.get())
        finally:
            transport.close()

    async def _nmea_tcp(self, host: str, port: int) -> None:
        reader, writer = await asyncio.open_connection(host, port)
        _LOGGER.info("AIS RTL-SDR: ✅ connected NMEA TCP %s:%s", host, port)
        try:
            while True:
                line = await reader.readline()
                self._parse_nmea(line.decode("ascii", errors="ignore").strip())
        finally:
            writer.close()

    def _parse_nmea(self, sentence: str) -> None:
        if not sentence.startswith(("!AIVDM", "!AIVDO")):
            return
        try:
            from pyais import decode as ais_decode

            parts     = sentence.split(",")
            total     = int(parts[1])
            part_num  = int(parts[2])
            seq_id    = parts[3] or "0"

            if total == 1:
                self._process_decoded(ais_decode(sentence))
            else:
                key = (seq_id, total)
                self._nmea_parts.setdefault(key, {})[part_num] = sentence
                if len(self._nmea_parts[key]) == total:
                    ordered = [self._nmea_parts.pop(key)[i] for i in range(1, total + 1)]
                    self._process_decoded(ais_decode(*ordered))
        except Exception as exc:
            _LOGGER.debug("AIS NMEA parse error: %s | '%s'", exc, sentence)

    def _process_decoded(self, decoded: Any) -> None:
        try:
            d = decoded.asdict()
        except Exception:
            return

        mmsi     = str(d.get("mmsi", "")).strip()
        msg_type = d.get("msg_type", 0)
        lat      = d.get("lat")
        lon      = d.get("lon")

        if not mmsi:
            return

        if lat is not None and lon is not None:
            if haversine_km(self._home_lat, self._home_lon, lat, lon) > self._radius_km:
                return

        if msg_type in (1, 2, 3, 18, 19):
            self._update_ship(mmsi, {
                "lat":        lat,
                "lon":        lon,
                "speed":      d.get("speed"),
                "heading":    d.get("heading"),
                "course":     d.get("course"),
                "nav_status": d.get("status"),
            })
        elif msg_type == 5:
            self._update_ship(mmsi, {
                "name":        d.get("shipname", "").strip() or None,
                "ship_type":   d.get("ship_type"),
                "destination": d.get("destination", "").strip() or None,
                "callsign":    d.get("callsign", "").strip() or None,
                "imo":         d.get("imo") or None,
            })
        elif msg_type == 24:
            self._update_ship(mmsi, {
                "name":     d.get("shipname", "").strip() or None,
                "callsign": d.get("callsign", "").strip() or None,
            })
