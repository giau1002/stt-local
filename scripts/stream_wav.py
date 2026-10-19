#!/usr/bin/env python3
"""Paced WAV client and timing capture against YOUR local server."""
import argparse
import asyncio
import getpass
import json
import os
from pathlib import Path
import struct
import time
import wave
import httpx
from websockets.asyncio.client import connect


async def main(args):
    key = os.getenv("APP_KEY") or getpass.getpass("APP_KEY: ")
    async with httpx.AsyncClient(base_url=args.url, trust_env=False) as client:
        login = await client.post("/api/login", json={"key": key})
        login.raise_for_status()
        cookie = "; ".join(f"{k}={v}" for k, v in client.cookies.items())
    with wave.open(str(args.wav), "rb") as wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2):
            raise SystemExit("WAV must be PCM16, mono, 16000 Hz; convert with ffmpeg first.")
        pcm = wav.readframes(wav.getnframes())
    url = args.url.replace("https://", "wss://").replace("http://", "ws://").rstrip("/") + "/api/stream"
    events = []
    async with connect(url, additional_headers={"Cookie": cookie}, origin=args.url.rstrip("/"), proxy=None, max_size=4194304) as ws:
        await ws.send(json.dumps({"type":"start", "sample_rate":16000, "encoding":"pcm_s16le", "title":args.wav.stem}))
        start = json.loads(await ws.recv())
        if start["type"] != "started":
            raise SystemExit(str(start))
        events.append(start)
        begin = time.monotonic()

        async def receive():
            async for raw in ws:
                event = json.loads(raw)
                event["client_elapsed"] = round(time.monotonic() - begin, 3)
                events.append(event)
                if event["type"] in ("partial", "final", "done", "error"):
                    print(json.dumps(event, ensure_ascii=False), flush=True)
                if event["type"] == "done":
                    return
                if event["type"] == "error":
                    raise RuntimeError(event["message"])
        receiver = asyncio.create_task(receive())
        for seq, offset in enumerate(range(0, len(pcm), 3200)):
            if receiver.done():
                await receiver
                break
            chunk = pcm[offset:offset + 3200]
            # A microphone can send a packet only after capturing all of its samples.
            await asyncio.sleep(max(0, begin + (offset + len(chunk)) / 32000 - time.monotonic()))
            await ws.send(struct.pack("<I", seq) + chunk)
        await ws.send(json.dumps({"type":"end"}))
        await asyncio.wait_for(receiver, 120)
    if not events or events[-1].get("type") != "done":
        raise RuntimeError("Connection closed without final completion")
    args.output.write_text(json.dumps(events, ensure_ascii=False, indent=2))
    print(f"Saved {args.output}; session={start['session_id']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("wav", type=Path)
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--output", type=Path, default=Path("benchmark-events.json"))
    asyncio.run(main(parser.parse_args()))
