"""Config flow pour Neatsvor S600.

Deux étapes : l'adresse MAC du robot (pour le contrôle MQTT, déjà
fonctionnel), puis l'e-mail du compte JoyLife/Neatsvor (pour le "login
SDK" REST — pièces, cartes, packs voix). Pas de mot de passe requis :
l'authentification SDK ne demande que l'e-mail + l'identité de l'app
(voir api.py et const.py).
"""
from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import aiohttp_client

from .api import NeatsvorApiClient, NeatsvorApiError, NeatsvorAuthError
from .const import CONF_EMAIL, CONF_TOKEN, DOMAIN

_LOGGER = logging.getLogger(__name__)

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}-){5}[0-9A-Fa-f]{2}$")
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _normalise_email(value: str) -> str | None:
    """Retourne l'e-mail nettoyé, ou None s'il est invalide."""
    email = value.strip().lower()
    if not email or len(email) > 254 or not _EMAIL_RE.fullmatch(email):
        return None
    return email


class NeatsvorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Gère la configuration via l'UI : MAC du robot, puis compte JoyLife."""

    VERSION = 1

    def __init__(self) -> None:
        self._mac: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            mac = user_input["mac"].strip().upper().replace(":", "-")
            if not _MAC_RE.match(mac):
                errors["mac"] = "invalid_mac"
            else:
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured()
                self._mac = mac
                return await self.async_step_account()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required("mac"): str}),
            errors=errors,
            description_placeholders={"format": "12-34-56-78-9A-BC"},
        )

    async def _async_login(self, raw_email: str) -> tuple[str | None, str | None, str | None]:
        """Valide l'e-mail puis tente le login SDK.

        Retourne (email, token, clé d'erreur) ; la clé d'erreur est None en cas de succès.
        """
        email = _normalise_email(raw_email)
        if email is None:
            return None, None, "invalid_email"
        api = NeatsvorApiClient(aiohttp_client.async_get_clientsession(self.hass))
        try:
            token = await api.login(email)
        except NeatsvorAuthError as err:
            _LOGGER.warning("Login JoyLife refusé : %s", err)
            return email, None, "invalid_auth"
        except NeatsvorApiError as err:
            _LOGGER.warning("Échec de connexion à l'API JoyLife : %s", err, exc_info=True)
            return email, None, "cannot_connect"
        return email, token, None

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            email, token, error = await self._async_login(user_input[CONF_EMAIL])
            if error is None:
                return self.async_create_entry(
                    title=f"Neatsvor S600 ({self._mac})",
                    data={"mac": self._mac, CONF_EMAIL: email, CONF_TOKEN: token},
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="account",
            data_schema=vol.Schema({vol.Required(CONF_EMAIL): str}),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> config_entries.ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            email, token, error = await self._async_login(user_input[CONF_EMAIL])
            if error is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_EMAIL: email, CONF_TOKEN: token}
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {vol.Required(CONF_EMAIL, default=entry.data.get(CONF_EMAIL, "")): str}
            ),
            errors=errors,
        )
