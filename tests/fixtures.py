"""Fake cloud client and MQTT connection with shadows shaped like the real ones (identifiers are made up)."""

from __future__ import annotations

import copy
from typing import Any, ClassVar

from custom_components.habitat_homelink.api import HabitatThing

GATEWAY = "SAUPTZ1GW-001E5E000001"
COORDINATOR = f"{GATEWAY}-SAUPTZ1ZC-001E5E0000000001"
THERMOSTAT = f"{GATEWAY}-SAUPTZ1PT868-0000000000000000"
INDEX = "000000000003"

THERMOSTAT_PROPERTIES = {
    "ep0:sPTAC868:LocalTemperature_x100": 2313,
    "ep0:sPTAC868:HeatingSetpoint_x100": 2333,
    "ep0:sPTAC868:CoolingSetpoint_x100": 1000,
    "ep0:sPTAC868:MinHeatingSetpoint_x100": 500,
    "ep0:sPTAC868:MaxHeatingSetpoint_x100": 3500,
    "ep0:sPTAC868:SystemMode": 3,
    "ep0:sPTAC868:FanMode": 5,
    "ep0:sPTAC868:RunningMode": 0,
    "ep0:sPTAC868:RunningState": 0,
    "ep0:sPTAC868:HoldType": 0,
    "ep0:sPTAC868:FilterRunDays": 12,
    "ep0:sPTAC868:FilterDays": 90,
    "ep0:sPTAC868:PTACErrorCode": 0,
}


def shadow(properties: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a thermostat shadow document."""
    return {
        "state": {
            "reported": {
                "connected": "true",
                INDEX: {"model": "SAUPTZ1PT868", "properties": copy.deepcopy(properties or THERMOSTAT_PROPERTIES)},
            },
            "desired": {INDEX: {"properties": {"ep0:sPTAC868:SetSystemMode": 3}}},
        },
        "version": 1,
    }


class FakeApi:
    """Stands in for HabitatApi."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.shadows: dict[str, dict[str, Any]] = {THERMOSTAT: shadow()}

    async def authenticate(self) -> None:
        return None

    async def get_gateways(self) -> list[str]:
        return [GATEWAY]

    async def discover(self) -> list[HabitatThing]:
        return [HabitatThing(name, GATEWAY) for name in (GATEWAY, COORDINATOR, THERMOSTAT)]

    async def get_shadow(self, thing: str) -> dict[str, Any]:
        return copy.deepcopy(self.shadows[thing])

    async def get_aws_credentials(self) -> None:
        return None

    async def close(self) -> None:
        return None


class FakeConnection:
    """Stands in for HabitatMqttConnection and records publishes."""

    instances: ClassVar[list[FakeConnection]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.things: list[str] = []
        self.published: list[tuple[str, str, dict[str, Any]]] = []
        FakeConnection.instances.append(self)

    async def async_start(self, things: list[str]) -> None:
        self.things = things

    async def async_stop(self) -> None:
        return None

    def set_things(self, things: list[str]) -> None:
        self.things = things

    async def async_publish_shadow(self, thing: str, index: str, properties: dict[str, Any]) -> None:
        self.published.append((thing, index, properties))

    def push(self, thing: str, document: dict[str, Any]) -> None:
        """Deliver a shadow update as if it came from AWS IoT."""
        self.kwargs["on_shadow_document"](thing, document)
