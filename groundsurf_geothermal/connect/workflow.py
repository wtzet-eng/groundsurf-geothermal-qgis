"""GroundSurf workflow wire contract. This module has no QGIS or provider dependency."""

import json
from pathlib import Path

CONTRACT = json.loads(Path(__file__).with_name("assistant-contract.json").read_text(encoding="utf8"))
TOOLS = {tool["id"]: tool for tool in CONTRACT["tools"]}
PLAN = CONTRACT["planSchema"]


def check_plan(plan):
    if not isinstance(plan, dict) or set(plan) != {"version", "steps"} or plan["version"] != "1.0":
        raise ValueError("Unsupported workflow format.")
    steps = plan["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= len(TOOLS):
        raise ValueError("Choose one or more workflow steps.")
    if any(not isinstance(s, str) or s not in TOOLS for s in steps) or len(set(steps)) != len(steps):
        raise ValueError("Unknown or repeated tool. Review the workflow.")
    writers = {"acquire_landscape", "create_transfer_package"}
    if len(writers.intersection(steps)) > 1:
        raise ValueError("Choose one package source for this workflow.")
    for i, step in enumerate(steps):
        remaining = steps[i + 1 :]
        if step in {"validate_transfer_package", "open_studio"} and writers.intersection(remaining):
            raise ValueError("Prepare the transfer before validation and handoff.")
        if step == "open_studio" and remaining:
            raise ValueError("Place the Studio handoff last.")
    return list(steps)


def response_plan(calls):
    if len(calls) != 1 or calls[0].get("name") != "propose_workflow":
        raise ValueError(
            "The model did not return one recognised workflow proposal. Edit the request or use Manual."
        )
    args = calls[0]["arguments"]
    return check_plan(json.loads(args) if isinstance(args, str) else args)


def default_steps(automatic):
    return [
        "define_area",
        "discover_data",
        "acquire_landscape" if automatic else "create_transfer_package",
        "validate_transfer_package",
        "open_studio",
    ]


def describe_steps(steps):
    return "\n".join(
        f"{i}. {TOOLS[key]['title']} · {', '.join(TOOLS[key]['permissions'])}"
        for i, key in enumerate(steps, 1)
    )
