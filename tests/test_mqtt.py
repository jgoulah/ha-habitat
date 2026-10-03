"""Tests for the AWS IoT MQTT connection."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

from custom_components.habitat_homelink.api import AwsCredentials
from custom_components.habitat_homelink.mqtt import HabitatMqttConnection, create_signed_websocket_url

from .fixtures import GATEWAY, THERMOSTAT, shadow

CREDENTIALS = AwsCredentials("AKIDEXAMPLE", "secret", "token/with+chars", datetime(2026, 1, 1, tzinfo=UTC))


def test_signed_url() -> None:
    url = urlparse(
        create_signed_websocket_url(
            "example-ats.iot.us-west-2.amazonaws.com", "us-west-2", CREDENTIALS, datetime(2026, 1, 1, tzinfo=UTC)
        )
    )
    query = parse_qs(url.query)
    assert url.scheme == "wss" and url.path == "/mqtt"
    assert query["X-Amz-Credential"] == ["AKIDEXAMPLE/20260101/us-west-2/iotdevicegateway/aws4_request"]
    assert query["X-Amz-Security-Token"] == ["token/with+chars"]
    assert len(query["X-Amz-Signature"][0]) == 64


async def test_shadow_update_messages_are_delivered() -> None:
    received: list[tuple[str, dict[str, Any]]] = []
    connection = HabitatMqttConnection(
        credentials_provider=None,
        client_id_prefix=GATEWAY,
        on_shadow_document=lambda thing, document: received.append((thing, document)),
        on_push_available=lambda available: None,
    )
    connection._loop = asyncio.get_running_loop()
    client = object()
    connection._client = client
    document = shadow()

    connection._handle_message(client, f"$aws/things/{THERMOSTAT}/shadow/update", json.dumps(document).encode())
    connection._handle_message(client, f"$aws/things/{THERMOSTAT}/shadow/update/accepted", b"{}")
    connection._handle_message(client, f"$aws/things/{THERMOSTAT}/shadow/update", b"not json")
    connection._handle_message(object(), f"$aws/things/{THERMOSTAT}/shadow/update", json.dumps(document).encode())

    assert received == [(THERMOSTAT, document)]
