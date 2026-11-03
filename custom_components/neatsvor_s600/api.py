"""Client REST (aiohttp) pour le backend compte JoyLife/Neatsvor/Blackvision.

Ce client NE sert PAS à contrôler le robot au quotidien : le contrôle
confirmé (start/stop/retour base) passe par MQTT, voir mqtt_client.py.
Ce client REST sert aux données liées au compte (pièces, cartes, packs
voix) et, potentiellement, à un chemin de contrôle REST alternatif plus
simple que le protobuf MQTT.

Authentification : Via le "login SDK" (/mis/user/login/sdk) qui ne nécessite 
que l'e-mail du compte et les constantes d'app (APP_KEY/APP_SECRET).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

from .const import (
    APP_KEY,
    APP_PACKAGE,
    APP_SECRET,
    REST_AUDIO_PATH,
    REST_BASE_URL,
    REST_CONTROL_PATH,
    REST_DEVICES_PATH,
    REST_LOGIN_SDK_PATH,
    REST_MAP_PATH,
    REST_ROOMS_PATH,
    SYSTEM_TYPE,
)

_LOGGER = logging.getLogger(__name__)


class NeatsvorApiError(Exception):
    """Erreur générique de l'API REST (réseau, serveur, etc.)."""


class NeatsvorAuthError(NeatsvorApiError):
    """Échec d'authentification : compte refusé ou token expiré."""


class NeatsvorApiClient:
    """Client REST asynchrone pour le compte Blackvision/JoyLife/Neatsvor.

    Conçu pour utiliser la session aiohttp partagée de Home Assistant
    (homeassistant.helpers.aiohttp_client.async_get_clientsession).
    """

    def __init__(self, session: aiohttp.ClientSession, base_url: str = REST_BASE_URL) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._token: str | None = None
        self.user_id: str | None = None
        self.account_id: int | None = None
        self.home_id: int | None = None

    @property
    def token(self) -> str | None:
        return self._token

    def set_token(self, token: str) -> None:
        """Réutilise un token déjà obtenu précédemment (évite un login à chaque démarrage)."""
        self._token = token

    async def login(self, email: str) -> str:
        """Authentifie via le "login SDK" (e-mail + identité d'app, pas de mot de passe).

        Lève NeatsvorAuthError si le compte est refusé par le serveur.
        """
        payload = {
            "packageName": APP_PACKAGE,
            "userId": email,
            "appSecret": APP_SECRET,
            "nickName": f"user-{email}",
            "systemType": SYSTEM_TYPE,
            "appKey": APP_KEY,
        }
        data = await self._request("POST", REST_LOGIN_SDK_PATH, json_body=payload, auth=False)
        token = (data or {}).get("token") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token.strip():
            raise NeatsvorAuthError("Réponse de connexion sans token")

        self._token = token
        self.user_id = data.get("userId")
        self.account_id = data.get("id")
        self.home_id = data.get("currentHomeId")
        return token

    async def get_devices(self) -> list[dict[str, Any]]:
        """Liste des appareils liés au compte."""
        data = await self._request("GET", REST_DEVICES_PATH)
        return data if isinstance(data, list) else (data or {}).get("devices", [])

    async def get_rooms(self) -> list[dict[str, Any]]:
        """Pièces connues du compte (pour mapper les room_id utilisés par SweeperAny.Rooms)."""
        data = await self._request("GET", REST_ROOMS_PATH)
        return data if isinstance(data, list) else (data or {}).get("list", [])

    async def get_device_map(self, device_id: str) -> list[dict[str, Any]]:
        """Cartes enregistrées pour un appareil."""
        data = await self._request("GET", REST_MAP_PATH, params={"deviceId": device_id})
        return data if isinstance(data, list) else (data or {}).get("list", [])

    async def get_voice_packs(self) -> list[dict[str, Any]]:
        """Packs de voix/annonces disponibles."""
        data = await self._request("GET", REST_AUDIO_PATH)
        return data if isinstance(data, list) else (data or {}).get("list", [])

    async def send_command_dp(self, device_id: int, dp_number: int, value: Any) -> None:
        """Chemin de contrôle REST alternatif."""
        payload = {"deviceId": device_id, "dps": {str(dp_number): value}}
        await self._request("POST", REST_CONTROL_PATH, json_body=payload)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> Any:
        headers = {"Accept-Language": "fr"}
        if auth:
            if not self._token:
                raise NeatsvorAuthError("Appel authentifié tenté sans token — login() requis d'abord")
            headers["token"] = self._token

        url = f"{self._base_url}{path}"
        try:
            async with self._session.request(
                method,
                url,
                json=json_body,
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                raw_text = await response.text()
                if response.status < 200 or response.status >= 300:
                    raise NeatsvorApiError(
                        f"HTTP {response.status} returned by JoyLife endpoint {path}"
                    )
        except NeatsvorApiError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, TimeoutError) as err:
            raise NeatsvorApiError(f"Erreur réseau sur {path}") from err

        try:
            body = json.loads(raw_text) if raw_text else {}
        except json.JSONDecodeError as err:
            raise NeatsvorApiError(f"Réponse non JSON sur {path}") from err

        if not isinstance(body, dict):
            raise NeatsvorApiError(f"Réponse inattendue sur {path} (objet JSON attendu)")

        code = body.get("code")
        if code not in (None, "10000", 10000, "0", 0):
            message = body.get("msg", "erreur inconnue")
            if code in ("10200", 10200, "401", 401, "-2"):
                raise NeatsvorAuthError(message)
            raise NeatsvorApiError(f"{path} a renvoyé une erreur ({code}) : {message}")

        return body.get("data")