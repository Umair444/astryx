#!/usr/bin/env python3
"""astryx · imagegen MCP server — image generation over the owner's OpenAI key.

One tool: generate(prompt, models?, size?, quality?, n?). `models` is Optional[List[str]]
(owner spec, 2026-08-22): omitted -> the DEFAULT_MODEL only; a list -> the SAME prompt is
generated once per listed model, so models can be compared side by side in one call.

Key: OPENAI_API_KEY from the org's .env (single source of truth; never in the repo, never
echoed — error text is scrubbed). Images land in media/imagegen/ (gitignored) and the tool
returns file paths + per-model outcomes; a failed model never sinks its siblings.

COST: every call spends the owner's OpenAI credits. This capability is granted per charter
(`Grants: imagegen`), and local.md's external-spend line applies — agents use it for owner-
directed work, not decoration.
"""
from __future__ import annotations

import base64
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional

from mcp.server.fastmcp import FastMCP

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "media" / "imagegen"
API = "https://api.openai.com/v1/images/generations"
DEFAULT_MODEL = "gpt-image-1"
KNOWN_MODELS = ("gpt-image-1", "gpt-image-1-mini", "gpt-image-1.5", "gpt-image-2",
                "chatgpt-image-latest", "dall-e-3", "dall-e-2")

mcp = FastMCP("imagegen")


def _key() -> str:
    for line in (REPO / ".env").read_text().splitlines():
        if line.startswith("OPENAI_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("OPENAI_API_KEY missing from .env")


def _scrub(text: str) -> str:
    return re.sub(r"sk-[A-Za-z0-9_-]{16,}", "sk-<redacted>", str(text))[:300]


def _generate_one(key: str, model: str, prompt: str, size: str, quality: str,
                  n: int) -> dict:
    body = {"model": model, "prompt": prompt, "n": n, "size": size}
    if quality and model.startswith("gpt-image"):
        body["quality"] = quality
    req = urllib.request.Request(
        API, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode()).get("error", {}).get("message", "")
        except Exception:
            msg = f"HTTP {e.code}"
        return {"model": model, "ok": False, "error": _scrub(msg)}
    except Exception as e:
        return {"model": model, "ok": False, "error": _scrub(f"{type(e).__name__}: {e}")}

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    paths = []
    for i, item in enumerate(d.get("data", [])):
        if item.get("b64_json"):
            p = OUT / f"{stamp}-{model}-{i}.png"
            p.write_bytes(base64.b64decode(item["b64_json"]))
            paths.append(str(p))
        elif item.get("url"):
            paths.append(item["url"])          # dall-e-2/3 may return URLs
    return {"model": model, "ok": True, "images": paths,
            "revised_prompt": (d.get("data") or [{}])[0].get("revised_prompt")}


@mcp.tool()
def generate(prompt: str, models: Optional[List[str]] = None, size: str = "1024x1024",
             quality: str = "medium", n: int = 1) -> str:
    """Generate image(s) from a prompt via OpenAI. `models`: optional list of model ids —
    omitted uses gpt-image-1; a list runs the SAME prompt once per model (comparison).
    Known ids: gpt-image-1, gpt-image-1-mini, gpt-image-1.5, gpt-image-2,
    chatgpt-image-latest, dall-e-3, dall-e-2. size e.g. 1024x1024|1536x1024|1024x1536;
    quality low|medium|high (gpt-image models). Files land in media/imagegen/."""
    key = _key()
    todo = models or [DEFAULT_MODEL]
    results = [_generate_one(key, m, prompt, size, quality, max(1, min(n, 4)))
               for m in todo]
    return json.dumps({"results": results}, indent=1)


@mcp.tool()
def list_models() -> str:
    """Image-capable model ids currently visible to the org's OpenAI key (live query)."""
    key = _key()
    req = urllib.request.Request("https://api.openai.com/v1/models",
                                 headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            ids = [m["id"] for m in json.load(r).get("data", [])]
        return json.dumps(sorted(i for i in ids if "image" in i or "dall" in i))
    except Exception as e:
        return json.dumps({"error": _scrub(f"{type(e).__name__}: {e}"),
                           "known": list(KNOWN_MODELS)})


if __name__ == "__main__":
    mcp.run()
