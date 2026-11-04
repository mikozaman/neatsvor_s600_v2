"""Tests for the Neatsvor MQTT client (no network, paho is mocked)."""
from __future__ import annotations

import gzip
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from custom_components.neatsvor_s600.mqtt_client import NeatsvorMqttClient
from custom_components.neatsvor_s600.protobuf_lite import (
    decode_fields,
    first,
    length_delimited_field,
    varint_field,
)

MAC = "12-34-56-78-9A-BC"
STATE_TOPIC = f"STATE_{MAC}"
ONLINE_TOPIC = f"DEVICE_ON_LINE_{MAC}"


@pytest.fixture
def paho():
    """Replace the paho client class and yield the instance the code creates."""
    with patch("custom_components.neatsvor_s600.mqtt_client.mqtt.Client") as client_cls:
        instance = client_cls.return_value
        instance.publish.return_value = MagicMock(rc=0, mid=1)
        instance.publish.return_value.is_published.return_value = True
        yield instance


def _message(topic: str, body_fields: bytes) -> SimpleNamespace:
    raw = length_delimited_field(2, body_fields)
    return SimpleNamespace(topic=topic, payload=gzip.compress(raw))


def _published_frame(paho) -> tuple[dict, dict]:
    args, _ = paho.publish.call_args
    top = decode_fields(gzip.decompress(args[1]))
    return decode_fields(first(top, 1)), decode_fields(first(top, 2))


def test_parse_state_message(paho):
    updates = []
    client = NeatsvorMqttClient(MAC, updates.append)
    body = varint_field(1, 2) + varint_field(2, 87)
    client._handle_message(None, None, _message(STATE_TOPIC, body))
    assert updates == [{"status_code": 2, "battery": 87}]


def test_parse_state_without_status_field(paho):
    updates = []
    client = NeatsvorMqttClient(MAC, updates.append)
    client._handle_message(None, None, _message(STATE_TOPIC, varint_field(2, 50)))
    assert updates == [{"status_code": None, "battery": 50}]


@pytest.mark.parametrize(("value", "expected"), [(2, True), (1, False)])
def test_parse_online_message(paho, value, expected):
    updates = []
    client = NeatsvorMqttClient(MAC, updates.append)
    client._handle_message(None, None, _message(ONLINE_TOPIC, varint_field(1, value)))
    assert updates == [{"online": expected}]


@pytest.mark.parametrize(
    "payload",
    [
        b"definitely not gzip",
        bytes(256_001),
        gzip.compress(bytes(1_000_001)),
        gzip.compress(length_delimited_field(2, varint_field(1, 2))) + b"trailing",
    ],
    ids=["not-gzip", "oversized-compressed", "decompression-bomb", "trailing-bytes"],
)
def test_rejects_bad_payloads(paho, payload):
    updates = []
    client = NeatsvorMqttClient(MAC, updates.append)
    client._handle_message(None, None, SimpleNamespace(topic=STATE_TOPIC, payload=payload))
    assert updates == []


@pytest.mark.parametrize(("command", "cmd_id"), [(1, 1), (2, 2)])
def test_simple_command_frame(paho, command, cmd_id):
    client = NeatsvorMqttClient(MAC, lambda _: None)
    client.send_command(command)
    args, kwargs = paho.publish.call_args
    assert args[0] == f"DP_APP_{MAC}"
    assert kwargs == {"qos": 1}
    header, body = _published_frame(paho)
    assert first(header, 1) == 1
    assert first(header, 3) == b"00000033314"
    assert first(header, 4) == bytes([cmd_id])
    assert first(header, 5) == 1
    assert first(body, 1) == b"type.googleapis.com/bvsdk.MqttMsgBody"
    assert first(body, 2) == b"\x08\x02"


def test_room_clean_frame(paho):
    client = NeatsvorMqttClient(MAC, lambda _: None)
    client.send_room_clean([1, 2], fan_level=2, water_level=2, mode=1)
    header, body = _published_frame(paho)
    assert first(header, 4) == bytes([31])
    assert first(body, 1) == b"type.googleapis.com/sweeper.Rooms"
    assert first(body, 2) == b"\x0a\x02\x01\x02\x10\x02\x18\x02\x20\x01"


def test_publish_failure_raises(paho):
    paho.publish.return_value = MagicMock(rc=1, mid=1)
    client = NeatsvorMqttClient(MAC, lambda _: None)
    with pytest.raises(ConnectionError):
        client.send_command(1)


def test_publish_timeout_raises(paho):
    paho.publish.return_value.is_published.return_value = False
    client = NeatsvorMqttClient(MAC, lambda _: None)
    with pytest.raises(TimeoutError):
        client.send_command(1)


def test_connection_callbacks(paho):
    states = []
    NeatsvorMqttClient(MAC, lambda _: None, on_connection=states.append)
    paho.on_connect(paho, None, {}, 0, None)
    paho.subscribe.assert_called_once_with([(STATE_TOPIC, 0), (ONLINE_TOPIC, 0)])
    paho.on_disconnect(paho, None, None, 7, None)
    paho.on_connect(paho, None, {}, 5, None)
    assert states == [True, False, False]


def test_is_connected_delegates_to_paho(paho):
    client = NeatsvorMqttClient(MAC, lambda _: None)
    paho.is_connected.return_value = True
    assert client.is_connected() is True
    paho.is_connected.return_value = False
    assert client.is_connected() is False
