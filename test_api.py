#!/usr/bin/env python3
"""
Führe aus im HA Terminal:
  python3 /config/test_api.py
"""
import asyncio, json, math, sys

API_KEY = "4c56d1690959fc63da6a82fefdabc33619bea399"
LAT, LON = 52.850, 9.233   # Dörverden laut Wikipedia exakt
RADIUS_KM = 25             # Großer Radius zum Testen – Weser von Nienburg bis Bremen

def bbox(lat, lon, r):
    dlat = r / 111.0
    dlon = r / (111.0 * math.cos(math.radians(lat)))
    return [[lat - dlat, lon - dlon], [lat + dlat, lon + dlon]]

async def main():
    try:
        import websockets
    except ImportError:
        print("Installiere websockets: pip3 install websockets")
        sys.exit(1)

    box = bbox(LAT, LON, RADIUS_KM)
    print(f"\n{'='*55}")
    print(f" AIS API Test – Weser bei Dörverden ({RADIUS_KM} km Radius)")
    print(f"{'='*55}")
    print(f" BBox: SW={[round(x,3) for x in box[0]]}  NE={[round(x,3) for x in box[1]]}")
    print(f"{'='*55}\n")

    # Test 1: TCP-Verbindung
    print("[1/3] Prüfe TCP-Verbindung zu stream.aisstream.io:443 ...")
    try:
        r, w = await asyncio.wait_for(asyncio.open_connection("stream.aisstream.io", 443), timeout=5)
        w.close()
        print("      ✅ TCP erreichbar\n")
    except Exception as e:
        print(f"      ❌ TCP FEHLER: {e}")
        print("      → HA-Server kann aisstream.io nicht erreichen (Firewall?)")
        sys.exit(1)

    # Test 2: WebSocket + API Key
    print("[2/3] Verbinde WebSocket und sende API Key ...")
    try:
        async with websockets.connect("wss://stream.aisstream.io/v0/stream", open_timeout=10) as ws:
            await ws.send(json.dumps({"APIKey": API_KEY, "BoundingBoxes": [box]}))
            print("      ✅ WebSocket verbunden\n")

            # Test 3: Warte auf Daten
            print(f"[3/3] Warte 45s auf Schiffe (Radius {RADIUS_KM} km) ...")
            print("      (Abbruch mit Ctrl+C)\n")
            count = 0
            seen = set()
            try:
                end = asyncio.get_event_loop().time() + 45
                while asyncio.get_event_loop().time() < end:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                    except asyncio.TimeoutError:
                        left = int(end - asyncio.get_event_loop().time())
                        print(f"      ... {left}s verbleibend", end="\r")
                        continue

                    count += 1
                    msg = json.loads(raw)
                    mtype = msg.get("MessageType", "KEIN TYP")
                    meta = msg.get("MetaData", {})
                    mmsi = str(meta.get("MMSI", "?"))

                    if count <= 3:
                        # Erste 3 Nachrichten komplett ausgeben
                        print(f"\n      📦 Rohdaten Nachricht #{count}:")
                        print(f"         {raw[:400]}\n")

                    if mmsi not in seen:
                        seen.add(mmsi)
                        name = meta.get("ShipName", "").strip() or "(kein Name)"
                        lat_s = meta.get("latitude", "?")
                        lon_s = meta.get("longitude", "?")
                        print(f"      🚢 Neues Schiff: {name:25s} MMSI={mmsi}  [{mtype}]  pos=({lat_s},{lon_s})")

            except KeyboardInterrupt:
                pass

            print(f"\n{'='*55}")
            if count == 0:
                print(" ❌ Keine Nachrichten empfangen!")
                print("    → API Key ungültig ODER keine Schiffe im Radius")
                print(f"    → Prüfe marinetraffic.com für die Weser bei Dörverden")
            else:
                print(f" ✅ {count} Nachrichten, {len(seen)} verschiedene Schiffe")
                print(f"    → API und Verbindung funktionieren")
                if len(seen) == 0:
                    print(f"    ⚠️  Aber keine gültigen MMSI – Parsing-Problem?")
            print(f"{'='*55}\n")

    except Exception as e:
        print(f"      ❌ WebSocket FEHLER: {e}")
        print("      → Evtl. API Key abgelaufen oder gesperrt")

asyncio.run(main())
