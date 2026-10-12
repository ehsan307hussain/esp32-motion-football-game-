import re
import time
import threading

import serial
import serial.tools.list_ports

from flask import Flask, render_template
from flask_socketio import SocketIO


BAUD_RATE = 115200

app = Flask(__name__)

socketio = SocketIO(
    app,
    cors_allowed_origins="*"
)

serial_connection = None


def find_esp32():
    ports = serial.tools.list_ports.comports()

    for port in ports:
        if (
            "ttyUSB" in port.device
            or "ttyACM" in port.device
        ):
            return port.device

    return None


def serial_worker():

    global serial_connection

    while True:

        port = find_esp32()

        if port is None:
            socketio.emit(
                "status",
                {"connected": False}
            )

            time.sleep(1)
            continue

        try:
            print("Connecting to", port)

            serial_connection = serial.Serial(
                port,
                BAUD_RATE,
                timeout=1
            )

            time.sleep(2)

            print("ESP32 connected:", port)

            socketio.emit(
                "status",
                {
                    "connected": True,
                    "port": port
                }
            )

            while True:

                line = (
                    serial_connection
                    .readline()
                    .decode(
                        "utf-8",
                        errors="ignore"
                    )
                    .strip()
                )

                if not line:
                    continue


                # -----------------------------
                # AIM
                # -----------------------------

                match = re.match(
                    r"AIM:(-?\d+)",
                    line
                )

                if match:

                    aim = int(
                        match.group(1)
                    )

                    aim = max(
                        -100,
                        min(100, aim)
                    )

                    socketio.emit(
                        "aim",
                        {"value": aim}
                    )

                    continue


                # -----------------------------
                # KICK
                # -----------------------------

                match = re.match(
                    r"KICK:(\d+)",
                    line
                )

                if match:

                    power = int(
                        match.group(1)
                    )

                    power = max(
                        1,
                        min(100, power)
                    )

                    print(
                        "KICK:",
                        power
                    )

                    socketio.emit(
                        "kick",
                        {"power": power}
                    )


        except Exception as e:

            print(
                "Serial error:",
                e
            )

            socketio.emit(
                "status",
                {"connected": False}
            )

            try:
                if serial_connection:
                    serial_connection.close()
            except:
                pass

            serial_connection = None

            time.sleep(1)


@app.route("/")
def index():
    return render_template(
        "index.html"
    )


if __name__ == "__main__":

    threading.Thread(
        target=serial_worker,
        daemon=True
    ).start()

    socketio.run(
        app,
        host="127.0.0.1",
        port=5000,
        debug=False,
        allow_unsafe_werkzeug=True
    )