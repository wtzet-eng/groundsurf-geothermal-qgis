"""Fixed loopback Ollama setup. Never installs software or pulls arbitrary models."""

import json
import re
from urllib.request import Request, ProxyHandler, build_opener

from .inference import NoRedirect, ProviderError, request

BASE = "http://127.0.0.1:11434"
RECOMMENDED = "qwen3:4b"


def installed_models(cancel=lambda: False):
    data = request(BASE + "/api/tags", timeout=5)
    entries = data.get("models", [])
    names = []
    for entry in entries[:100]:
        name = entry.get("name", "")
        if (
            re.fullmatch(r"[A-Za-z0-9_./:-]{1,160}", name)
            and not name.lower().endswith("cloud")
            and not entry.get("remote_model")
            and not entry.get("remote_host")
            and isinstance(entry.get("size"), (int, float))
            and entry["size"] > 0
        ):
            names.append(name)
    ready = []
    for name in sorted(set(names), key=lambda n: (n != RECOMMENDED, n))[:12]:
        if cancel():
            raise InterruptedError("Detection cancelled.")
        info = request(BASE + "/api/show", {"model": name}, timeout=5)
        if (
            info.get("model_info")
            and not info.get("remote_model")
            and not info.get("remote_host")
            and "tools" in info.get("capabilities", [])
        ):
            ready.append(name)
    return ready


def pull_recommended(cancel):
    if RECOMMENDED in installed_models(cancel):
        return installed_models(cancel)
    if cancel():
        raise InterruptedError("Download cancelled.")
    body = json.dumps({"model": RECOMMENDED, "stream": True}).encode()
    client = build_opener(ProxyHandler({}), NoRedirect())
    with client.open(
        Request(BASE + "/api/pull", body, {"Content-Type": "application/json"}), timeout=60
    ) as stream:
        for _ in range(1000000):
            if cancel():
                raise InterruptedError("Download cancelled; Ollama may retain partial data.")
            line = stream.readline(65537)
            if not line or len(line) > 65536:
                break
            event = json.loads(line)
            if event.get("error"):
                raise ProviderError("Ollama could not download the recommended model.")
            if event.get("status") == "success":
                models = installed_models(cancel)
                if RECOMMENDED in models:
                    return models
                break
    raise ProviderError("Download not verified. Detect models again.")
