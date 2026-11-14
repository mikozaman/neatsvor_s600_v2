"""Client MQTT pour le broker cloud Neatsvor/JoyLife.

Ce n'est PAS le broker MQTT local de Home Assistant : l'app officielle
parle directement à un broker cloud (de.mqtt.blackvision.net:8011) avec
des identifiants partagés par tous les utilisateurs. On se connecte donc
en parallèle, comme un deuxième client, sans toucher au robot.

Les payloads sont du protobuf compressé en gzip, sans chiffrement. La
structure utilisée ci-dessous a été déduite de captures réelles de
trafic (pas d'un .proto officiel) : elle couvre les champs utiles
(statut, batterie, commande) mais pas forcément la totalité du schéma.
Le décodage/encodage protobuf est fait à la main (protobuf_lite.py) pour
éviter la dépendance blackboxprotobuf, dont la version de protobuf
exigée entre en conflit avec d'autres intégrations.
"""
from __future__ import annotations

import gzip
import logging
import time
import zlib
from collections.abc import Callable
from typing import Any

import paho.mqtt.client as mqtt

from .const import (
    CMD_ID_ROOMS,
    MAP_MIN_INTERVAL,
    MAP_RENDER_SCALE,
    MQTT_HOST,
    MQTT_PASSWORD,
    MQTT_PORT,
    MQTT_USERNAME,
    USE_MAP_SETTING,
)
from .map_decoder import decode_map, render_png
from .protobuf_lite import (
    decode_fields,
    first,
    length_delimited_field,
    packed_varint_field,
    varint_field,
)

_LOGGER = logging.getLogger(__name__)

# Valeurs fixes observées dans chaque commande capturée. "session_id" ne
# semble pas être lié au compte utilisateur (même valeur vue pour tout le
# monde dans ce type d'app) ; à surveiller si les commandes échouent.
_SESSION_ID = b"00000033314"
_MAX_COMPRESSED_PAYLOAD = 256_000
_MAX_DECOMPRESSED_PAYLOAD = 1_000_000


class NeatsvorMqttClient:
    """Encapsule la connexion paho-mqtt vers le broker Neatsvor/JoyLife."""

    def __init__(
        self,
        mac: str,
        on_update: Callable[[dict[str, Any]], None],
        on_connection: Callable[[bool], None] | None = None,
    ) -> None:
        self._mac = mac
        self._on_update = on_update
        self._on_connection = on_connection
        self._topic_state = f"STATE_{mac}"
        self._topic_online = f"DEVICE_ON_LINE_{mac}"
        self._topic_app = f"DP_APP_{mac}"
        self._topic_map = f"MAP_{mac}"
        self._last_map_render = float("-inf")

        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        # The vendor endpoint currently uses the documented legacy port 8011.
        # Do not enable TLS blindly: the vendor's TLS endpoint/port is unknown.
        # This limitation is documented for users rather than silently
        # connecting to an unverified endpoint.
        self._client.on_connect = self._handle_connect
        self._client.on_message = self._handle_message
        self._client.on_disconnect = self._handle_disconnect
        # Backoff explicite pour les reconnexions automatiques de paho
        # (la valeur par défaut dépend de la version installée) : on
        # réessaie entre 1 et 30 secondes en cas de coupure réseau.
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)

    # -- Connexion ---------------------------------------------------
    def connect(self) -> None:
        """Connexion bloquante + démarrage de la boucle réseau en arrière-plan.

        À appeler via hass.async_add_executor_job depuis l'entité.
        """
        # Async connect keeps a transient cloud outage from blocking HA setup.
        self._client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=60)
        self._client.loop_start()

    def disconnect(self) -> None:
        self._client.disconnect()
        self._client.loop_stop()

    def is_connected(self) -> bool:
        """Indique si la session MQTT avec le broker cloud est établie."""
        return bool(self._client.is_connected())

    # -- Callbacks paho ------------------------------------------------
    def _handle_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if reason_code != 0:
            _LOGGER.error(
                "Échec de connexion au broker Neatsvor (%s:%s) pour %s : code %s",
                MQTT_HOST,
                MQTT_PORT,
                self._mac,
                reason_code,
            )
            self._notify_connection(False)
            return
        _LOGGER.debug("Connecté au broker Neatsvor pour %s", self._mac)
        client.subscribe([(self._topic_state, 0), (self._topic_online, 0), (self._topic_map, 0)])
        self._notify_connection(True)

    def _handle_disconnect(
        self, client, userdata, disconnect_flags, reason_code, properties=None
    ) -> None:
        _LOGGER.warning("Déconnecté du broker Neatsvor pour %s (code %s)", self._mac, reason_code)
        self._notify_connection(False)

    def _notify_connection(self, connected: bool) -> None:
        if self._on_connection is not None:
            self._on_connection(connected)

    def _handle_message(self, client, userdata, msg) -> None:
        # Tout le traitement d'un message (décompression, parsing protobuf,
        # interprétation des champs, callback vers l'entité) est protégé :
        # un paquet corrompu ou inattendu (coupure Wi-Fi côté robot, etc.)
        # ne doit jamais faire remonter d'exception dans le thread réseau
        # de paho, au risque de perturber la boucle d'abonnement MQTT.
        try:
            if len(msg.payload) > _MAX_COMPRESSED_PAYLOAD:
                raise ValueError("MQTT payload exceeds compressed size limit")
            decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
            raw = decompressor.decompress(msg.payload, _MAX_DECOMPRESSED_PAYLOAD + 1)
            if (
                len(raw) > _MAX_DECOMPRESSED_PAYLOAD
                or decompressor.unconsumed_tail
                or not decompressor.eof
                or decompressor.unused_data
            ):
                raise ValueError("Invalid or oversized compressed MQTT payload")
            if msg.topic == self._topic_map:
                parsed = self._parse_map(raw)
                if parsed:
                    self._on_update(parsed)
                return
            top_fields = decode_fields(raw)

            if msg.topic == self._topic_state:
                self._on_update(self._parse_state(top_fields))
            elif msg.topic == self._topic_online:
                self._on_update(self._parse_online(top_fields))
        except Exception:  # noqa: BLE001 - payload externe non garanti
            _LOGGER.warning("Message MQTT illisible sur %s", msg.topic, exc_info=True)

    # -- Décodage --------------------------------------------------------
    @staticmethod
    def _parse_state(top_fields: dict[int, list[Any]]) -> dict[str, Any]:
        body_bytes = first(top_fields, 2)
        body = decode_fields(body_bytes) if body_bytes else {}
        status = first(body, 1)  # absent => robot en pause
        battery = first(body, 2)
        return {
            "status_code": int(status) if status is not None else None,
            "battery": int(battery) if battery is not None else None,
        }

    @staticmethod
    def _parse_online(top_fields: dict[int, list[Any]]) -> dict[str, Any]:
        body_bytes = first(top_fields, 2)
        body = decode_fields(body_bytes) if body_bytes else {}
        online = first(body, 1)
        return {"online": online == 2}

    def _parse_map(self, raw: bytes) -> dict[str, Any]:
        """Décode + rend la carte, au plus une fois par MAP_MIN_INTERVAL secondes.

        La carte est republiée en continu pendant le nettoyage (~177 Ko
        décompressés) : on ignore les messages trop rapprochés pour ne pas
        saturer le thread paho ni l'enregistreur de Home Assistant.
        """
        now = time.monotonic()
        if now - self._last_map_render < MAP_MIN_INTERVAL:
            return {}
        map_data = decode_map(raw)
        self._last_map_render = now
        return {
            "map_png": render_png(map_data, scale=MAP_RENDER_SCALE, overlay=True),
            "map_rooms": map_data.rooms,
            "map_size": (map_data.width, map_data.height),
            "map_room_settings": map_data.room_settings,
            "map_dock": map_data.dock,
            "map_robot": map_data.robot,
        }

    # -- Commandes ---------------------------------------------------
    def _publish_mqtt_msg(self, cmd_id: int, type_name: str, message_bytes: bytes) -> None:
        """Construit et publie une trame SdkCom.MqttMsg sur DP_APP_<mac>.

        Structure confirmée par du vrai code protobuf généré (pas de la
        rétro-ingénierie bytecode) dans l'app officielle "Neatsvor Home"
        le 25 oct 2026 — bvsdk.SdkCom.MqttMsgHeader :
        version(1)=1, macAddress(2, omis — optionnel, confirmé par le
        fonctionnement de start/stop sans ce champ), loginName(3, on y
        met toujours le même "session id" de l'app d'origine, dont le
        vrai rôle exact reste incertain mais qui fonctionne tel quel),
        cmdId(4, liste empaquetée — un seul élément ici), cmdType(5)=1.
        Le corps est un google.protobuf.Any{type_url, value=message_bytes}
        dans bvsdk.SdkCom.MqttMsg.body (champ 2, repeated — un seul
        élément envoyé).
        """
        header = b"".join(
            [
                varint_field(1, 1),
                length_delimited_field(3, _SESSION_ID),
                packed_varint_field(4, [cmd_id]),
                varint_field(5, 1),
            ]
        )
        body = b"".join(
            [
                length_delimited_field(1, f"type.googleapis.com/{type_name}".encode()),
                length_delimited_field(2, message_bytes),
            ]
        )
        raw = length_delimited_field(1, header) + length_delimited_field(2, body)
        compressed = gzip.compress(raw)

        _LOGGER.info(
            "Envoi cmdId=%s (type=%s) sur %s (%d octets gzip, connecté=%s)",
            cmd_id,
            type_name,
            self._topic_app,
            len(compressed),
            self._client.is_connected(),
        )
        info = self._client.publish(self._topic_app, compressed, qos=1)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError(f"MQTT publish failed with return code {info.rc}")
        info.wait_for_publish(timeout=5)
        if not info.is_published():
            raise TimeoutError(f"MQTT command {cmd_id} was not acknowledged in time")
        _LOGGER.debug("MQTT command %s published (mid=%s)", cmd_id, info.mid)

    def send_command(self, command_code: int) -> None:
        """Publie une commande simple (start/stop) sur DP_APP_<mac>.

        command_code : COMMAND_START_RESUME (1) ou COMMAND_STOP_RETURN (2).
        À appeler via hass.async_add_executor_job depuis l'entité.
        """
        # Le corps est toujours {int_value: 2} quelle que soit la
        # commande : le vrai sélecteur est le cmdId dans le header.
        message_bytes = varint_field(1, 2)
        self._publish_mqtt_msg(command_code, "bvsdk.MqttMsgBody", message_bytes)

    def send_room_clean(
        self,
        room_ids: list[int],
        fan_level: int = USE_MAP_SETTING,
        water_level: int = USE_MAP_SETTING,
        mode: int = USE_MAP_SETTING,
    ) -> None:
        """Nettoyage ciblé par pièce(s) (sweeper.Rooms, cmdId 31).

        VALIDÉ sur le robot réel (25-31 oct 2026) avec les valeurs par défaut
        -1/-1/-1 : le robot applique alors les réglages enregistrés sur la
        carte pour chaque pièce, et la trame fait 97 octets bruts, identique
        à celle de l'app officielle. Un fan_level explicite (ex. 2) n'a PAS
        changé le niveau d'aspiration constaté sur le robot.
        """
        message_bytes = b"".join(
            [
                packed_varint_field(1, room_ids),
                varint_field(2, fan_level),
                varint_field(3, water_level),
                varint_field(4, mode),
            ]
        )
        self._publish_mqtt_msg(CMD_ID_ROOMS, "sweeper.Rooms", message_bytes)
