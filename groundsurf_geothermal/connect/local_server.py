"""Discover explicitly requested, existing loopback llama.cpp services.

Discovery lists model identifiers only; it never sends prompts or installs software.
An operator must trust the local server before sending a request.
"""

import re
from .inference import request

PORTS = (8080, 18090, 18089)


def existing_servers(cancel=lambda: False):
    result = []
    for port in PORTS:
        if cancel():
            raise InterruptedError("Local AI detection cancelled.")
        try:
            data = request(f"http://127.0.0.1:{port}/v1/models", timeout=2)
        except (ValueError, OSError):
            # A missing or invalid local endpoint is not a detected service.
            data = {}
        if not isinstance(data, dict):
            continue
        # llama.cpp advertises both these arrays. Do not treat arbitrary
        # OpenAI-compatible proxies as verified llama.cpp services.
        models = data.get("models")
        if not isinstance(models, list) or not isinstance(data.get("data"), list):
            continue
        for model in models[:12]:
            if not isinstance(model, dict):
                continue
            name = model.get("name", "")
            if (
                isinstance(name, str)
                and re.fullmatch(r"[A-Za-z0-9_./:-]{1,160}", name)
                and not name.lower().endswith("cloud")
                and not model.get("remote_host")
                and not model.get("remote_model")
            ):
                entry = (port, name)
                if entry not in result:
                    result.append(entry)
    if cancel():
        raise InterruptedError("Local AI detection cancelled.")
    return result
