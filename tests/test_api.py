"""Tests for the REST client (HTTP mocked with aioclient_mock)."""
from __future__ import annotations

import pytest
from custom_components.neatsvor_s600.api import (
    NeatsvorApiClient,
    NeatsvorApiError,
    NeatsvorAuthError,
)
from custom_components.neatsvor_s600.const import (
    REST_BASE_URL,
    REST_LOGIN_SDK_PATH,
    REST_ROOMS_PATH,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

LOGIN_URL = f"{REST_BASE_URL}{REST_LOGIN_SDK_PATH}"
ROOMS_URL = f"{REST_BASE_URL}{REST_ROOMS_PATH}"
LOGIN_OK = {
    "code": 10000,
    "data": {"token": "abc", "userId": "u-1", "id": 5, "currentHomeId": 7},
}


@pytest.fixture
async def api(hass: HomeAssistant, aioclient_mock) -> NeatsvorApiClient:
    return NeatsvorApiClient(async_get_clientsession(hass))


async def test_login_success_stores_token_and_ids(api, aioclient_mock):
    aioclient_mock.post(LOGIN_URL, json=LOGIN_OK)
    assert await api.login("user@example.com") == "abc"
    assert (api.token, api.user_id, api.account_id, api.home_id) == ("abc", "u-1", 5, 7)


async def test_login_sends_email_without_password(api, aioclient_mock):
    aioclient_mock.post(LOGIN_URL, json=LOGIN_OK)
    await api.login("user@example.com")
    method, _, body, headers = aioclient_mock.mock_calls[0]
    assert method == "POST"
    assert body["userId"] == "user@example.com"
    assert "password" not in body
    assert "token" not in headers


async def test_login_without_token_is_auth_error(api, aioclient_mock):
    aioclient_mock.post(LOGIN_URL, json={"code": 10000, "data": {}})
    with pytest.raises(NeatsvorAuthError):
        await api.login("user@example.com")


@pytest.mark.parametrize("code", [10200, "10200", 401, "401"])
async def test_auth_codes_raise_auth_error(api, aioclient_mock, code):
    aioclient_mock.post(LOGIN_URL, json={"code": code, "msg": "refused"})
    with pytest.raises(NeatsvorAuthError):
        await api.login("user@example.com")


async def test_other_error_code_is_api_error_not_auth(api, aioclient_mock):
    aioclient_mock.post(LOGIN_URL, json={"code": 99999, "msg": "boom"})
    with pytest.raises(NeatsvorApiError) as err:
        await api.login("user@example.com")
    assert not isinstance(err.value, NeatsvorAuthError)


async def test_http_500_is_api_error(api, aioclient_mock):
    aioclient_mock.post(LOGIN_URL, status=500)
    with pytest.raises(NeatsvorApiError):
        await api.login("user@example.com")


async def test_non_json_body_is_api_error(api, aioclient_mock):
    aioclient_mock.post(LOGIN_URL, text="<html>oops</html>")
    with pytest.raises(NeatsvorApiError):
        await api.login("user@example.com")


async def test_json_list_body_is_api_error(api, aioclient_mock):
    aioclient_mock.post(LOGIN_URL, json=[1, 2, 3])
    with pytest.raises(NeatsvorApiError):
        await api.login("user@example.com")


async def test_timeout_is_api_error(api, aioclient_mock):
    aioclient_mock.post(LOGIN_URL, exc=TimeoutError)
    with pytest.raises(NeatsvorApiError):
        await api.login("user@example.com")


async def test_authenticated_call_without_token_is_auth_error(api, aioclient_mock):
    with pytest.raises(NeatsvorAuthError):
        await api.get_rooms()
    assert aioclient_mock.call_count == 0


async def test_authenticated_call_sends_token_header(api, aioclient_mock):
    aioclient_mock.get(ROOMS_URL, json={"code": 10000, "data": []})
    api.set_token("tok")
    await api.get_rooms()
    assert aioclient_mock.mock_calls[0][3]["token"] == "tok"


@pytest.mark.parametrize(
    "data",
    [[{"id": 1}], {"list": [{"id": 1}]}],
    ids=["bare-list", "wrapped-list"],
)
async def test_get_rooms_accepts_both_shapes(api, aioclient_mock, data):
    aioclient_mock.get(ROOMS_URL, json={"code": 10000, "data": data})
    api.set_token("tok")
    assert await api.get_rooms() == [{"id": 1}]
