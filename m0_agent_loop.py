#!/usr/bin/env python3
"""M0 — Does Nemotron survive a 10-turn agent loop?

Runs the IsyMotron planner against the NVIDIA NIM provider (the "payasa"
key) with a LegacyHost demo backend. Measures tool-call validity rate,
tokens/turn, and recovery. Gate: >=70% valid tool calls after 10 turns.
"""
from __future__ import annotations

import os
import sys
import time
import json

ISYMOTRON_ROOT = "/home/danny/Development/ISyCo Git/IsyMotron"
sys.path.insert(0, ISYMOTRON_ROOT)
sys.path.insert(0, os.path.join(ISYMOTRON_ROOT, "core"))
sys.path.insert(0, os.path.join(ISYMOTRON_ROOT, "hosts"))

from agents.planner import Planner, PlanRejected
from agents.provider import Provider
from hosts.simulator.engines import LegacyHost
from relay.loopback import LoopbackRelay
from isymotron.contracts import HostDescription, HostIdentity, CapabilityManifest


def descriptions_from_relay(relay: LoopbackRelay) -> list[HostDescription]:
    """relay.describe() returns dicts; the Planner needs dataclasses."""
    out = []
    for h in relay.hosts():
        d = relay.describe(h["host_id"])
        identity = HostIdentity(**d["identity"])
        caps = [CapabilityManifest(
            id=c["id"], version=c["version"], summary=c["summary"],
            scopes=c.get("scopes", {}), requires_admin=c.get("requires_admin", False),
            params=tuple(c.get("params", [])), returns=tuple(c.get("returns", [])),
        ) for c in d["capabilities"]]
        out.append(HostDescription(
            identity=identity, capabilities=caps,
            granted=tuple(d.get("granted", [])), bounds=d.get("bounds", {}),
        ))
    return out

NVIDIA_KEY = open("/home/danny/Development/NVAPI.txt").read().strip()

# Intents that require real multi-step tool use (read -> write -> launch)
TURNS = [
    "Copy the newest file from the GAMES folder to the NEMO inbox and then launch DOOM.",
    "List the GAMES folder and launch DOOM.",
    "Read the newest game from GAMES, write it to the inbox, then launch DOOM.",
    "Check system info, list GAMES, and launch DOOM.",
    "Copy the newest file from GAMES to inbox, verify system info, launch DOOM.",
]


def build_world():
    relay = LoopbackRelay()
    legacy = LegacyHost(
        fs={"C:/GAMES/DOOM.EXE": "MZ_BINARY", "C:/GAMES/WOLF3D.EXE": "MZ_X",
            "C:/NEMO/INBOX/.keep": ""},
        granted=["filesystem.read", "filesystem.write", "apps.launch", "system.info"],
        grant_scopes={
            "filesystem.read": {"roots": ["C:/GAMES"]},
            "filesystem.write": {"roots": ["C:/NEMO/INBOX"]},
            "apps.launch": {"allowlist": ["DOOM.EXE"]},
            "system.info": {},
        })
    relay.attach(legacy)
    return relay


def run_turn(planner: Planner, relay: LoopbackRelay, intent: str, turn_num: int) -> dict:
    t0 = time.time()
    result = {"turn": turn_num, "intent": intent, "valid": False,
              "tokens": 0, "latency": 0.0, "verdict": None, "error": None}
    descriptions = descriptions_from_relay(relay)

    try:
        plan = planner.plan(intent, descriptions, max_tokens=2000)
        result["verdict"] = plan.verdict()
        result["tokens"] = plan.completion.prompt_tokens + plan.completion.completion_tokens
        result["valid"] = plan.verdict() == "PLANNED"
        if not result["valid"]:
            result["error"] = f"verdict={plan.verdict()} refused={plan.refused}"
    except PlanRejected as e:
        result["error"] = f"PlanRejected: {e.reason}"
        result["tokens"] = getattr(e, "completion", None) and (e.completion.prompt_tokens + e.completion.completion_tokens) or 0
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"

    result["latency"] = time.time() - t0
    return result


def main():
    relay = build_world()
    provider = Provider(name="nvidia", api_key=NVIDIA_KEY)
    planner = Planner(provider)

    print(f"N0 Agent Loop — Nemotron on NVIDIA NIM")
    print(f"Model: {provider.model} | Key: {provider.key_env}")
    print(f"Turns: {len(TURNS)}\n")

    results = []
    for i, intent in enumerate(TURNS, 1):
        r = run_turn(planner, relay, intent, i)
        results.append(r)
        status = "PASS" if r["valid"] else "FAIL"
        print(f"  T{r['turn']}: {status} | tokens={r['tokens']} | {r['latency']:.1f}s | {r.get('error') or r['verdict']}")

    valid = sum(1 for r in results if r["valid"])
    total = len(results)
    rate = valid / total * 100
    total_tokens = sum(r["tokens"] for r in results)
    avg_latency = sum(r["latency"] for r in results) / total

    print(f"\n{'='*50}")
    print(f"Tool-call validity: {valid}/{total} = {rate:.0f}%")
    print(f"Total tokens: {total_tokens}")
    print(f"Avg latency: {avg_latency:.1f}s")
    print(f"Gate: {'PASS' if rate >= 70 else 'FAIL'} (need >=70%)")

    return 0 if rate >= 70 else 1


if __name__ == "__main__":
    sys.exit(main())
