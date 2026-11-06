"""Écoute passive d'un topic du broker Neatsvor/JoyLife et sauvegarde les trames décompressées.

Usage : python tools/mqtt_listen.py <MAC> [STATE|MAP|DP_APP|DEVICE_ON_LINE|OTA|response] [secondes]

Sert à poursuivre la rétro-ingénierie (trajectoire, position du robot, zones sur MAP ;
valeurs de niveaux sur DP_APP pendant qu'on change un réglage dans l'app).
Chaque trame est écrite en .bin (protobuf brut) dans ./captures/. Ne publie jamais rien.
"""
from __future__ import annotations

import gzip
import pathlib
import sys
import time

import paho.mqtt.client as mqtt

HOST, PORT, USER, PASSWORD = "de.mqtt.blackvision.net", 8011, "appuser", "Blackvisionuser"


def main() -> None:
    mac = sys.argv[1]
    prefix = sys.argv[2] if len(sys.argv) > 2 else "MAP"
    duration = float(sys.argv[3]) if len(sys.argv) > 3 else 60.0
    topic = f"{prefix}_{mac}" if prefix != "response" else f"response/{mac}"
    out = pathlib.Path("captures")
    out.mkdir(exist_ok=True)
    count = 0

    def on_connect(client, userdata, flags, reason_code, properties=None):
        print("connecté :", reason_code, "->", topic)
        client.subscribe(topic)

    def on_message(client, userdata, msg):
        nonlocal count
        try:
            raw = gzip.decompress(msg.payload)
        except OSError:
            raw = msg.payload
        count += 1
        path = out / f"{prefix}_{int(time.time() * 1000)}_{count}.bin"
        path.write_bytes(raw)
        print(f"{path} ({len(msg.payload)} gzip -> {len(raw)} octets)")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(USER, PASSWORD)
    client.on_connect, client.on_message = on_connect, on_message
    client.connect(HOST, PORT, 60)
    client.loop_start()
    time.sleep(duration)
    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    main()
