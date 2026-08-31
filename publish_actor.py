#!/usr/bin/env python3
"""Publish the Apify actor with the FULL file set the Dockerfile copies.

The 2026-08-28 lesson: PUT sourceFiles is a full replace. Publishing only the
.actor/ files produces a green build whose image has no scripts/, no core/ and
no campaign bodies, and every run dies on the first import. This script uploads
the repo-layout mirror that the working 2026-08-09 build used, plus the English
body.
"""

import os
import sys
from pathlib import Path

import httpx

API = "https://api.apify.com/v2"
ACTOR_ID = "QonxRkaUpM4tcPsWs"
VERSION = "0.1"

# ponytail: explicit list over rglob, so a stray cache file can never ship
FILES = [
    ".actor/Dockerfile",
    ".actor/actor.json",
    ".actor/input_schema.json",
    ".actor/main.py",
    ".actor/requirements.txt",
    "core/config.py",
    "core/twitch.py",
    "scripts/prospect_leads.py",
    "scripts/build_campaign_batches.py",
    "scripts/send_campaign_batch.py",
    "scripts/campaign_stats.py",
    "ai-generated-messages/broadcast-body.html",
    "ai-generated-messages/broadcast-body-en.html",
]


def main() -> int:
    token = os.environ.get("APIFY_USER_TOKEN")
    if not token:
        print("ERROR: APIFY_USER_TOKEN not set")
        return 1

    source_files = []
    for name in FILES:
        path = Path(name)
        if not path.is_file():
            print(f"ERROR: {name} not found; run from the worktree root")
            return 1
        content = path.read_text(encoding="utf-8")
        print(f"  {name} ({len(content)} bytes)")
        source_files.append({"name": name, "content": content})

    http = httpx.Client(params={"token": token}, timeout=300)

    print(f"\nPUT {API}/acts/{ACTOR_ID}/versions/{VERSION} ({len(source_files)} files)")
    resp = http.put(
        f"{API}/acts/{ACTOR_ID}/versions/{VERSION}",
        json={"sourceFiles": source_files},  # omit envVars: preserves secrets
    )
    if resp.status_code != 200:
        print(f"PUT failed: {resp.status_code}\n{resp.text[:500]}")
        return 1
    stored = resp.json()["data"].get("sourceFiles", [])
    print(f"OK, version now holds {len(stored)} files")
    if len(stored) != len(FILES):
        print("ERROR: stored file count differs from what was sent")
        return 1

    print("POST build (tag=latest, waitForFinish=240)")
    resp = http.post(
        f"{API}/acts/{ACTOR_ID}/builds",
        params={"version": VERSION, "tag": "latest", "waitForFinish": 240},
    )
    if resp.status_code not in (200, 201):
        print(f"Build request failed: {resp.status_code}\n{resp.text[:500]}")
        return 1
    data = resp.json()["data"]
    print(f"Build {data.get('id')}: {data.get('status')}")
    return 0 if data.get("status") == "SUCCEEDED" else 1


if __name__ == "__main__":
    sys.exit(main())
