"""Tests for cloud client helpers."""

from __future__ import annotations

from custom_components.habitat_homelink.api import HabitatThing, parse_device_list, thing_group_name

from .fixtures import COORDINATOR, GATEWAY, THERMOSTAT


def test_thing_models() -> None:
    assert HabitatThing(GATEWAY, GATEWAY).model == "SAUPTZ1GW"
    assert HabitatThing(COORDINATOR, GATEWAY).model == "SAUPTZ1ZC"
    assert HabitatThing(THERMOSTAT, GATEWAY).model == "SAUPTZ1PT868"


def test_thing_group_name() -> None:
    assert thing_group_name(GATEWAY) == "Gateway-001E5E000001"


def test_parse_device_list_map() -> None:
    items = [{"Own": {"M": {"list": {"L": [{"S": GATEWAY}]}}}, "Company": {"S": "PTac"}}]
    assert parse_device_list(items) == [GATEWAY]


def test_parse_device_list_json_string_and_duplicates() -> None:
    items = [
        {"Own": {"S": f'{{"list": ["{GATEWAY}"]}}'}},
        {"Own": {"S": f'{{"list": ["{GATEWAY}", "SAUPTZ1GW-001E5E000002"]}}'}},
        {"Company": {"S": "PTac"}},
    ]
    assert parse_device_list(items) == [GATEWAY, "SAUPTZ1GW-001E5E000002"]
