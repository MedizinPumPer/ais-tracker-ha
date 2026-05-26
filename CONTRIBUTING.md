# Contributing

## Development Setup

```bash
git clone https://github.com/MedizinPumPer/ais-tracker-ha
cd ais-tracker-ha

# Symlink into a local HA dev instance
ln -s $(pwd)/custom_components/ais_tracker \
      ~/.homeassistant/custom_components/ais_tracker
```

## Testing aisstream.io locally

```python
# quick_test.py – verifies your API key works
import asyncio, json, websockets

API_KEY = "your_key_here"

async def test():
    async with websockets.connect("wss://stream.aisstream.io/v0/stream") as ws:
        await ws.send(json.dumps({
            "APIKey": API_KEY,
            "BoundingBoxes": [[[52.51, 13.39], [52.51, 13.39]]]
        }))
        print("Connected! Waiting for ships…")
        msg = await asyncio.wait_for(ws.recv(), timeout=30)
        print(json.dumps(json.loads(msg), indent=2))

asyncio.run(test())
```

## Testing RTL-SDR locally

```bash
# Send fake NMEA sentences to UDP port 12345
echo '!AIVDM,1,1,,A,15M67N0P00G?Uf6E4W?BUP000000,0*5F' | nc -u 127.0.0.1 12345
```

## Submitting to HACS default store

1. Ensure the repo is public on GitHub
2. All GitHub Actions pass (HACS Validation + hassfest)
3. Submit via https://hacs.xyz/docs/publish/start
