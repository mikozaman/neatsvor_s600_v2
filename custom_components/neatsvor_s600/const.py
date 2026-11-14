"""Constantes pour l'intégration Neatsvor S600."""
from __future__ import annotations

DOMAIN = "neatsvor_s600"

# Broker MQTT cloud utilisé par l'app JoyLife (région "de").
# Identifiants partagés en dur par l'app elle-même — pas de secret par appareil.
MQTT_HOST = "de.mqtt.blackvision.net"
MQTT_PORT = 8011
MQTT_USERNAME = "appuser"
MQTT_PASSWORD = "Blackvisionuser"

# Codes observés dans STATE_<mac>.2.1 :
#   STATUS_IDLE   -> robot immobile (arrêté / en charge / docké)
#   STATUS_ACTIVE -> robot en mouvement (nettoyage OU retour base)
#   champ absent  -> robot en pause
STATUS_IDLE = 1
STATUS_ACTIVE = 2

# Codes envoyés dans DP_APP_<mac>, header.4 :
COMMAND_START_RESUME = 1  # démarrer le nettoyage ou reprendre après pause
COMMAND_STOP_RETURN = 2   # arrêter et rentrer à la base

# Identifiants de commandes Protobuf
CMD_ID_ROOMS = 31     # sweeper.Rooms : room_ids, fan_level, water_level, mode
CMD_ID_ZONE_CLEAN = 32  # sweeper.ZoneClean : zones, times

# Valeur sentinelle observée dans la trame de l'app officielle : « utiliser le
# réglage enregistré sur la carte pour cette pièce » (payload de 97 octets).
USE_MAP_SETTING = -1

# Niveaux d'aspiration/lavage explicites (4 niveaux dans l'app : silencieux,
# normal, fort, MAX). ATTENTION : un fan_level explicite envoyé via cmdId 31
# n'a PAS changé le comportement du robot lors des tests réels (il restait en
# silencieux) ; la valeur par défaut -1 est la seule voie validée.
FAN_LEVEL_MIN = 1
FAN_LEVEL_MAX = 4
WATER_LEVEL_MIN = 1
WATER_LEVEL_MAX = 4
MODE_MIN = 1
MODE_MAX = 5

# Topic de la carte : sweeper.MapData publié en continu pendant le nettoyage.
MAP_MIN_INTERVAL = 2.0  # secondes entre deux rendus PNG
MAP_RENDER_SCALE = 3  # agrandissement entier de l'image (1 cellule = 3 px), robot/trajet tracés dessus

# Backend REST du compte JoyLife (données de compte : pièces, cartes, packs voix)
REST_BASE_URL = "https://de.wisdom.blackvision.net"
REST_LOGIN_SDK_PATH = "/mis/user/login/sdk"
REST_ROOMS_PATH = "/mis/home/query/rooms"
REST_MAP_PATH = "/mis/device/query/map"
REST_AUDIO_PATH = "/mis/product/query/audio"
REST_DEVICES_PATH = "/mis/device/get/all"
REST_CONTROL_PATH = "/mis/device/control"

# Identité d'app utilisée par le "login SDK"
APP_PACKAGE = "com.haibaina.neatsvor"
APP_KEY = "89e3794786c13d3989b25eb4f5db7a0a"
APP_SECRET = "f03847c26702f6df1c44274e1331cf1d"
SYSTEM_TYPE = "2"  # 1=Android, 2=iOS

CONF_EMAIL = "email"
CONF_TOKEN = "app_token"