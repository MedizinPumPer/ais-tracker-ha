# 🚢 AIS Ship Tracker

> Verfolge Schiffe auf Flüssen und Wasserstraßen in Echtzeit – direkt in Home Assistant.  
> Unterstützt **aisstream.io** (kein Hardware) und **RTL-SDR / AIS-catcher** (lokal, kein Cloud-Abo).

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/yourusername/ais-tracker-ha/actions/workflows/validate.yml/badge.svg)](https://github.com/yourusername/ais-tracker-ha/actions)

---

## Konzept

| Was | Wie |
|-----|-----|
| **Dashboard** | Ein Übersichts-Sensor mit allen Schiffen als Attributliste |
| **Watchlist** | Persistente Entities für bestimmte Schiffe (per MMSI konfigurierbar) |
| **Automationen** | HA-Events – kein Entity-Chaos, reagiere auf jedes Schiff |

---

## Installation

### Via HACS (empfohlen)

1. **HACS** öffnen → **Integrations** → ⋮ → **Custom repositories**
2. URL: `https://github.com/yourusername/ais-tracker-ha` | Kategorie: **Integration**
3. **AIS Ship Tracker** suchen → **Herunterladen**
4. Home Assistant **neu starten**
5. **Einstellungen → Geräte & Dienste → + Hinzufügen → AIS Ship Tracker**

### Manuell

`custom_components/ais_tracker/` in dein HA-Konfigurationsverzeichnis kopieren → Neustart.

---

## Datenquellen

### Option A – aisstream.io

Kostenloses WebSocket-API mit globalem AIS-Empfang. Kein Hardware nötig.

1. Account anlegen: **https://aisstream.io** → API-Key kopieren
2. Im Setup-Wizard: Quelle = **aisstream.io** → Key, Standort, Radius eingeben

### Option B – RTL-SDR / AIS-catcher

Empfängt AIS-Signale direkt per USB-SDR-Stick (~15 €). Komplett lokal, kein Cloud-Abo.

**AIS-catcher installieren:**
```bash
# Raspberry Pi / Debian / Ubuntu
sudo apt install librtlsdr-dev cmake git build-essential
git clone https://github.com/jvde-github/AIS-catcher
cd AIS-catcher && mkdir build && cd build
cmake .. && make && sudo make install
```

**Als systemd-Dienst einrichten:**
```ini
# /etc/systemd/system/ais-catcher.service
[Unit]
Description=AIS-catcher
After=network.target

[Service]
ExecStart=/usr/local/bin/AIS-catcher -u 127.0.0.1 12345
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable --now ais-catcher
```

Im Setup-Wizard: Quelle = **RTL-SDR**, Host = `127.0.0.1`, Port = `12345`, Protokoll = **UDP**

---

## Entities

### Übersichts-Sensor
| Entity | Beschreibung |
|--------|-------------|
| `sensor.ais_schiffe_in_der_nahe` | Anzahl Schiffe im Radius |

Attribute:
- `ships` – Liste aller Schiffe, sortiert nach Entfernung
- `nearest` – Das nächste Schiff als Dict

### Watchlist-Sensors (optional)
Für MMSI-Nummern in der Watchlist (Einstellungen → Konfigurieren):

| Entity | State | Beschreibung |
|--------|-------|-------------|
| `sensor.ais_ms_weserdampfer` | `In Sicht` / `Nicht in Sicht` | Immer verfügbar, Verlauf möglich |

---

## HA-Events

Die Integration feuert Events sobald Schiffe erscheinen oder verschwinden.  
Kein Polling, keine permanenten Entities pro Schiff – sauber.

| Event | Wann |
|-------|------|
| `ais_tracker_ship_appeared` | Schiff betritt den Radius |
| `ais_tracker_ship_departed` | Schiff verlässt den Radius / Timeout |

**Event-Payload (beide Events):**
```json
{
  "mmsi": "211234567",
  "name": "MS WESERPERLE",
  "ship_type": "Cargo",
  "destination": "BREMEN",
  "speed": 8.4,
  "distance_km": 0.3,
  "latitude": 52.846,
  "longitude": 9.271,
  "callsign": "DABC"
}
```

---

## Dashboard-Karten

### Aktuelles Schiff (Markdown Card)
```yaml
type: markdown
title: 🚢 Weser – Aktuelles Schiff
content: >
  {% set s = state_attr('sensor.ais_schiffe_in_der_nahe', 'nearest') %}
  {% if s %}
  ## {{ s.name | default('Unbekannt') }}
  | | |
  |---|---|
  | 🏁 Ziel | {{ s.destination | default('–') }} |
  | 💨 Speed | {{ s.speed | default('–') }} kn |
  | 🧭 Kurs | {{ s.course | default('–') }}° |
  | 🚢 Typ | {{ s.ship_type_label | default('–') }} |
  | 📏 Entfernung | {{ s.distance_km | default('–') }} km |
  | ⚓ Status | {{ s.nav_status_label | default('–') }} |
  | 📻 Rufzeichen | {{ s.callsign | default('–') }} |
  {% else %}
  *Keine Schiffe in der Nähe.*
  {% endif %}
```

### Alle Schiffe (Markdown Table)
```yaml
type: markdown
title: 🚢 Alle Schiffe in der Nähe
content: >
  {% set ships = state_attr('sensor.ais_schiffe_in_der_nahe', 'ships') %}
  {% if ships %}
  | Schiff | Typ | Speed | Ziel | km |
  |--------|-----|-------|------|----|
  {% for s in ships %}| **{{ s.name | default('N/A') }}** | {{ s.ship_type_label | default('–') }} | {{ s.speed | default('?') }} kn | {{ s.destination | default('–') }} | {{ s.distance_km | default('?') }} |
  {% endfor %}
  {% else %}
  *Keine Schiffe erkannt.*
  {% endif %}
```

### Watchlist-Schiff (Entities Card)
```yaml
type: entities
title: MS Weserdampfer
entities:
  - entity: sensor.ais_ms_weserdampfer
    name: Status
  - type: attribute
    entity: sensor.ais_ms_weserdampfer
    attribute: speed_knots
    name: Geschwindigkeit (kn)
  - type: attribute
    entity: sensor.ais_ms_weserdampfer
    attribute: destination
    name: Ziel
  - type: attribute
    entity: sensor.ais_ms_weserdampfer
    attribute: distance_km
    name: Entfernung (km)
```

---

## Automationen

### Benachrichtigung wenn ein Schiff vorbeikommt
```yaml
automation:
  - alias: "Schiff in Sicht"
    trigger:
      - platform: event
        event_type: ais_tracker_ship_appeared
    action:
      - service: notify.mobile_app_mein_handy
        data:
          title: "🚢 Schiff in Sicht!"
          message: >
            {{ trigger.event.data.name }} ({{ trigger.event.data.ship_type }})
            ist {{ trigger.event.data.distance_km }} km entfernt
            {% if trigger.event.data.destination %}
            → {{ trigger.event.data.destination }}
            {% endif %}
```

### Nur bestimmtes Schiff beobachten (per MMSI)
```yaml
automation:
  - alias: "MS Weserdampfer vorbei"
    trigger:
      - platform: event
        event_type: ais_tracker_ship_appeared
        event_data:
          mmsi: "211234567"
    action:
      - service: notify.mobile_app_mein_handy
        data:
          message: "MS Weserdampfer ist gerade vorbeigefahren!"
```

### Watchlist-Entity nutzen (Verlauf / Conditional Card)
```yaml
automation:
  - alias: "Schiff auf Watchlist verschwunden"
    trigger:
      - platform: state
        entity_id: sensor.ais_ms_weserdampfer
        to: "Nicht in Sicht"
    action:
      - service: notify.mobile_app_mein_handy
        data:
          message: "MS Weserdampfer hat den Bereich verlassen."
```

---

## Optionen anpassen

**Einstellungen → Geräte & Dienste → AIS Ship Tracker → Konfigurieren**

| Option | Beschreibung |
|--------|-------------|
| Radius (km) | Wie weit soll gesucht werden? |
| Watchlist (MMSI) | Kommagetrennte MMSI-Nummern für persistente Entities |

MMSI-Nummern findet man auf [MarineTraffic](https://www.marinetraffic.com) oder [VesselFinder](https://www.vesselfinder.com).

---

## Lizenz

MIT
