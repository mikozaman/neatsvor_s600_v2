# Protocole Neatsvor S600 / JoyLife (rétro-ingénierie)

Statut : **[V]** validé sur robot réel · **[C]** confirmé dans le code décompilé · **[?]** hypothèse / non testé.
Sources : décompilation jadx des apps JoyLife (`com.blackvision.joylife`) et Neatsvor Home
(`com.haibaina.neatsvor`, protobuf généré lisible), captures MQTT réelles (oct. 2026).

## 1. MQTT (contrôle et état) — c'est le chemin principal

- **[V]** Broker cloud `de.mqtt.blackvision.net:8011` (autres régions : us/ru/sg/cn), sans TLS connu.
  Identifiants partagés par l'app : `appuser` / `Blackvisionuser`. Un client tiers peut se connecter
  en parallèle de l'app, sans MITM.
- **[V]** Payloads = protobuf compressé en **gzip**, non chiffré.
- Topics pour `<mac>` (format `AA-BB-CC-DD-EE-FF`) :

| Topic | Contenu |
|---|---|
| `STATE_<mac>` | état + batterie **[V]** |
| `DEVICE_ON_LINE_<mac>` | présence (champ 1 == 2 → en ligne) |
| `DP_APP_<mac>` | commandes (publication) et événements **[V]** |
| `MAP_<mac>` | carte, publiée en continu pendant le nettoyage **[V]** |
| `OTA_<mac>`, `response/<mac>` | non exploités |

### STATE
- `2.2` = batterie % **[V]**.
- `2.1` : 1 → immobile (arrêté / en charge / docké) ; 2 → en mouvement (nettoyage **ou** retour base,
  indistinguable) ; champ absent → pause **[V]**. L'intégration lève l'ambiguïté en mémorisant
  la dernière commande envoyée.

### Enveloppe de commande `bvsdk.SdkCom.MqttMsg` **[C][V]**
```
MqttMsg { header(1), body(2, repeated Any) }
header  { version(1)=1, macAddress(2, omis), loginName(3)="00000033314",
          cmdId(4, repeated int32 packed), cmdType(5)=1 }
Any     { type_url(1) = "type.googleapis.com/<type>", value(2) }
```
Les entiers négatifs (int32) sont encodés en varint 10 octets (complément à deux 64 bits).

| cmdId | Type | Effet | Statut |
|---|---|---|---|
| 1 | `bvsdk.MqttMsgBody{int_value(1)=2}` | démarrer / reprendre | **[V]** |
| 2 | idem | arrêter / retour base | **[V]** |
| 31 | `sweeper.Rooms{room_ids(1, packed), fan_level(2), water_level(3), mode(4)}` | nettoyage par pièces | **[V]** |
| 32 | `sweeper.ZoneClean{zones, times}` | nettoyage par zone | [C] non implémenté |
| 30 | `sweeper.UseMap{url, mapId, md5}` | changer de carte | [C] non implémenté |
| 46 | `sweeper.ForbiddenInfo{forbiddenZones, mopForbiddenZones, virtualWalls}` | zones interdites | [C] non implémenté |
| 18 | `sweeper.VoicePacketCmdInfo{audioId, audioName, url, audioVersion…}` | pack voix | [C] non implémenté |
| 9 | `bvsdk.MqttMsgBody{1:2}` | observé quand l'app change le niveau d'aspiration d'une pièce ; **pas de valeur de niveau visible** | [?] |

### Nettoyage par pièces (cmdId 31) — leçons validées
- L'app envoie `fan_level = water_level = mode = -1` (« utiliser les réglages enregistrés sur la carte
  pour chaque pièce ») : trame de **97 octets** bruts pour une pièce. C'est la méthode fiable **[V]**.
- Un `fan_level` explicite (ex. 2) n'a **pas** changé le comportement : le robot restait silencieux **[V]**.
  Le niveau par pièce semble porté par la carte / le cmdId 9 → non résolu.
- L'app propose 4 niveaux (silencieux, normal, fort, MAX) ; bac aspiration → fan, bac serpillière → water,
  jamais les deux.
- Contrôle de cohérence : trame start = 67 octets bruts / 83 gzip.

### Carte `MAP_<mac>` **[V] (partiel)**
`MqttMsg > Any(sweeper.MapData)` ; ~7,7 Ko gzip → ~177 Ko.
- `MapData` : 1 = id de carte, 2 = largeur, 3 = hauteur, 4 = résolution (5), 5.2 = pixels (364×485), 5.5 = {x,y} (base ?), 6.2 = {x,y,angle} (robot ?), 6.4 = trajectoire, 9 = zones interdites {x1,y1,x2,y2}.
  (type 1 sol, 2 mur, 0 vide).
- `8.1` = pièces `{1: id, 2: nom}` ; `8.2` = réglages par pièce `{1: id, 2: fan_level, 3: water_level, 4: clean_times, 5: inconnu (=2)}` **[V]** (valeurs confirmées avec l'app : séjour fan 4, cuisine/SDB/douche clean_times 2, autres 3/3/1). `fan_level` va donc au moins jusqu'à 4. Pixel : `(room<<2)|type`, mur rattaché à sa pièce.
- **Non décodés** : trajectoire, position du robot / base, zones. Utiliser `tools/mqtt_listen.py MAP`.

## 2. REST (données de compte) — secondaire, partiellement bloqué

Base `https://de.wisdom.blackvision.net`. Succès = `code "10000"`. Header d'auth : `token`.
- **[V]** `POST /mis/user/login/sdk` avec `{packageName:"com.haibaina.neatsvor", userId:<email>, appSecret, appKey,
  nickName, systemType, headUrl}` → token. Mais c'est un compte « léger » propre à l'app : `device/get/all`
  renvoie une liste vide. **Impasse** pour les vraies données.
- **[?]** `POST /mis/user/login/account` (mot de passe MD5, `loginName`, `countryCode="DE"`) : refusé (code 10200)
  même avec les bons identifiants — cause non identifiée (signature ?). Piste restante : capture mitmproxy.
- **[?]** `POST /mis/device/control {deviceId, dps:{"<n>":valeur}}` : dp 1 switch_clean, 2 switch_charge,
  9 fan, 10 water_tank, 11 locate, 31 room_clean, 32 zone_clean (31/32 = mêmes numéros que les cmdId MQTT).
  Jamais testé sur le robot.
- Autres endpoints : `/mis/home/query/rooms`, `/mis/device/query/map`, `/mis/product/query/audio`.

## 3. Pistes abandonnées
- Piège DNS (AdGuard Home + Mosquitto local) : le robot a un DNS codé en dur ; inutile, la connexion
  directe au broker cloud suffit.
- `blackboxprotobuf` : conflit de version avec `protobuf` de Home Assistant → décodeur maison `protobuf_lite.py`.

## 4. Reste à faire
1. Valider sur le vrai HA : entité image + capteur batterie + rendu de la carte (orientation éventuellement à corriger).
2. Décoder trajectoire / position / zones dans `MAP_<mac>`.
3. Niveaux d'aspiration/lavage explicites (cmdId 9 ?), signification de `mode`.
4. `ZoneClean` (32), zones interdites (46), packs voix (18).
5. Authentification REST réelle (pièces/cartes/voix) si besoin.
