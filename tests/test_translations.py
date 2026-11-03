"""strings.json, en.json and fr.json must stay in sync."""
from __future__ import annotations

import json
import pathlib
import re

import pytest

BASE = pathlib.Path(__file__).parents[1] / "custom_components" / "neatsvor_s600"
FILES = {
    "strings": BASE / "strings.json",
    "en": BASE / "translations" / "en.json",
    "fr": BASE / "translations" / "fr.json",
}


def _flatten(data: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flatten(value, path))
        else:
            out[path] = value
    return out


@pytest.fixture(scope="module")
def flat() -> dict[str, dict[str, str]]:
    return {name: _flatten(json.loads(path.read_text("utf-8"))) for name, path in FILES.items()}


def test_same_keys_everywhere(flat):
    assert set(flat["strings"]) == set(flat["en"]) == set(flat["fr"])


def test_required_keys_present(flat):
    required = {
        "config.step.user.title",
        "config.step.account.title",
        "config.step.reauth_confirm.title",
        "config.error.invalid_mac",
        "config.error.invalid_auth",
        "config.error.cannot_connect",
        "config.error.invalid_email",
        "config.abort.already_configured",
        "config.abort.reauth_successful",
        "exceptions.not_connected.message",
        "exceptions.command_failed.message",
        "services.clean_rooms.name",
    }
    assert required <= set(flat["en"])


def test_placeholders_match(flat):
    for key, text in flat["en"].items():
        assert set(re.findall(r"\{(\w+)\}", text)) == set(
            re.findall(r"\{(\w+)\}", flat["fr"][key])
        ), key


def test_no_password_wording(flat):
    for key, text in flat["en"].items():
        if key.startswith("config.error"):
            assert "password" not in text.lower(), key
    for key, text in flat["fr"].items():
        if key.startswith("config.error"):
            assert "mot de passe" not in text.lower(), key
