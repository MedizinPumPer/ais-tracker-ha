"""Constants for AIS Ship Tracker."""

DOMAIN = "ais_tracker"

# ── Config / Options keys ─────────────────────────────────────────────────────
CONF_SOURCE    = "source"
CONF_API_KEY   = "api_key"
CONF_LATITUDE  = "latitude"
CONF_LONGITUDE = "longitude"
CONF_RADIUS    = "radius"
CONF_HOST      = "host"
CONF_PORT      = "port"
CONF_PROTOCOL  = "protocol"
CONF_WATCHLIST = "watchlist"   # comma-separated MMSIs

# ── Sources ───────────────────────────────────────────────────────────────────
SOURCE_AISSTREAM = "aisstream"
SOURCE_RTLSDR    = "rtlsdr"

# ── RTL-SDR protocols ─────────────────────────────────────────────────────────
PROTOCOL_UDP = "udp"
PROTOCOL_TCP = "tcp"

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_RADIUS_KM = 5
DEFAULT_HOST      = "127.0.0.1"
DEFAULT_PORT      = 12345
DEFAULT_PROTOCOL  = PROTOCOL_UDP

# ── Timing ────────────────────────────────────────────────────────────────────
SHIP_TIMEOUT_SECONDS = 300   # ship removed after 5 min without signal
CLEANUP_INTERVAL     = 30    # seconds between cleanup runs

# ── HA Event names ────────────────────────────────────────────────────────────
EVENT_SHIP_APPEARED = f"{DOMAIN}_ship_appeared"
EVENT_SHIP_DEPARTED = f"{DOMAIN}_ship_departed"

# ── AIS lookup tables ─────────────────────────────────────────────────────────
NAV_STATUS: dict[int, str] = {
    0:  "Underway (engine)",
    1:  "At anchor",
    2:  "Not under command",
    3:  "Restricted manoeuvrability",
    4:  "Constrained by draught",
    5:  "Moored",
    6:  "Aground",
    7:  "Engaged in fishing",
    8:  "Underway (sailing)",
    15: "Not defined",
}

SHIP_TYPES: dict[int, str] = {
    20: "Wing in ground",
    30: "Fishing",
    31: "Towing",
    32: "Towing (large)",
    33: "Dredger",
    34: "Diving ops",
    35: "Military",
    36: "Sailing",
    37: "Pleasure craft",
    40: "High speed craft",
    50: "Pilot vessel",
    51: "SAR",
    52: "Tug",
    53: "Port tender",
    55: "Law enforcement",
    60: "Passenger",
    70: "Cargo",
    80: "Tanker",
    90: "Other",
}
