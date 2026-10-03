"""Read-only check of the Habitat cloud client outside Home Assistant.

Logs in, discovers gateways and things, and prints a summary of each thing's shadow.
Usage: uv run --with pycognito --with boto3 --with aiohttp scripts/probe.py you@example.com
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import importlib.util
import json
import logging
import sys
from pathlib import Path

# Import the integration's modules without running its Home Assistant __init__
PACKAGE_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "habitat_homelink"
spec = importlib.util.spec_from_file_location(
    "habitat_homelink", PACKAGE_DIR / "__init__.py", submodule_search_locations=[str(PACKAGE_DIR)]
)
sys.modules["habitat_homelink"] = importlib.util.module_from_spec(spec)

from habitat_homelink import const
from habitat_homelink.api import HabitatApi

SUMMARY_KEYS = {
    const.LOCAL_TEMPERATURE: "temperature (°C×100)",
    const.HEATING_SETPOINT: "setpoint (°C×100)",
    const.SYSTEM_MODE: "system mode",
    const.FAN_MODE: "fan mode",
    const.RUNNING_STATE: "running state",
}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email")
    parser.add_argument("--raw", action="store_true", help="print full shadow documents")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING)

    api = HabitatApi(args.email, getpass.getpass("Habitat password: "))
    try:
        await api.authenticate()
        print("login ok")
        await api.get_aws_credentials()
        print("aws credentials ok")

        gateways = await api.get_gateways()
        print(f"gateways: {gateways}")
        for gateway in gateways:
            things = await api.get_gateway_things(gateway)
            print(f"\n{gateway}: {len(things)} things")
            for thing in things:
                shadow = await api.get_shadow(thing.name)
                reported = shadow.get("state", {}).get("reported", {})
                print(f"  {thing.model:<14} {thing.name}")
                for index, value in reported.items():
                    if not isinstance(value, dict) or "properties" not in value:
                        continue
                    properties = value["properties"]
                    for key, label in SUMMARY_KEYS.items():
                        if key in properties:
                            print(f"      [{index}] {label}: {properties[key]}")
                if args.raw:
                    print(json.dumps(shadow, indent=2))
    finally:
        await api.close()


if __name__ == "__main__":
    asyncio.run(main())
