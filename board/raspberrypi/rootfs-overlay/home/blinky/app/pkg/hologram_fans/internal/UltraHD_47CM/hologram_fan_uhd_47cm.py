import asyncio
import websockets
import requests
import json
import time
import threading
import os

class HologramFanUhd:
    def __init__(self, ip="192.168.43.1", ws_port=7110, http_port=8092, device_id="8CF710655A22", listen=True):
        self.ws_url = f"ws://{ip}:{ws_port}"
        self.http_url = f"http://{ip}:{http_port}"
        self.device_id = device_id
        self.cmd_order = 1  # increment with each command
        self.listen_enabled = listen
        if self.listen_enabled:
            self.listener_thread = threading.Thread(target=self._start_listener, daemon=True)
            self.listener_thread.start()

    def _log_device_message(self, msg):
        try:
            data = json.loads(msg)
            cmd = data.get("cmd")
            props = data.get("properties", {})
            if cmd == 0x1A:
                print("[📡] Status Report:", props)
            elif cmd == 0x1B:
                print("[📦] File Progress:", props)
            elif cmd == 0x1C:
                print("[✅] Command Feedback:", props)
            elif cmd == 0x1E:
                print("[📂] File List Report:", props)
            elif cmd == 0x40:
                print("[🆔] Device Info:", props)
            else:
                print("[📬] Unknown message:", data)
        except Exception as e:
            print("[!] Error parsing message:", e, msg)

    def _start_listener(self):
        async def listen():
            while True:
                try:
                    async with websockets.connect(self.ws_url) as websocket:
                        while True:
                            msg = await websocket.recv()
                            self._log_device_message(msg)
                except Exception as e:
                    print("[!] Listener error:", e)
                    await asyncio.sleep(2)
        asyncio.run(listen())

    async def _send_ws_command(self, cmd_id, props):
        # Force known-good control structure
        props["type"] = 0  # Enforce type=0 as required by spec and observed behavior
        props["id"] = self.device_id  # Always use explicit device_id

        message = {
            "cmd": cmd_id,
            "source": 0,
            "destination": "0",  # always broadcast to default
            "order": self.cmd_order,
            "version_code": 1,
            "pack_order": 1,
            "pack_count": 1,
            "properties": props
        }
        self.cmd_order = (self.cmd_order % 255) + 1

        async with websockets.connect(self.ws_url) as websocket:
            await websocket.send(json.dumps(message))
            print("[➤] Sent:", message)
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=2)
                self._log_device_message(response)
            except asyncio.TimeoutError:
                print("[!] No response from device.")
            except websockets.exceptions.ConnectionClosedOK:
                print("[ℹ️] Command sent. Device closed connection (code 1000).")

    def play_file(self, file_id):
        self._send_value_command(6, file_id=file_id)

    def set_brightness(self, level):
        self._send_value_command(7, brightness_value=level)

    def set_volume(self, level):
        self._send_value_command(0x0B, volume_value=level)

    def set_rotation(self, normal=True):
        value = 0x23 if normal else 0x24
        self._send_value_command(value)

    def set_loop_mode(self, mode=1):
        self._send_value_command(0x21, loop_mode=mode)

    def set_angle(self, increase=True):
        self._send_value_command(0x10, adjustment_value=1 if increase else 0)

    def open_angle(self):
        self._send_value_command(0x11)

    def close_angle(self):
        self._send_value_command(0x12)

    def remember_power_state(self, enabled=True):
        self._send_value_command(0x27, memory_enabled=1 if enabled else 0)

    def power_on(self):
        self._send_value_command(1)

    def power_off(self):
        self._send_value_command(0)

    def reboot(self):
        self._send_value_command(2)

    def delete_file(self, file_id=0):
        props = {
            "type": 1,
            "id": self.device_id,
            "file_id": file_id
        }
        asyncio.run(self._send_ws_command(0x43, props))

    def get_status(self):
        props = {"type": 1, "id": self.device_id}
        asyncio.run(self._send_ws_command(0x1A, props))

    def get_file_list(self):
        props = {
            "id": str(self.device_id),  # ensure string ID
            "type_id": "1",            # match spec format (string)
            "down_thum": "true"
        }
        asyncio.run(self._send_ws_command(0x1E, props))  # now correctly includes 'id'

    def upload_video(self, file_path, file_id=0):
        import os
        import time
        import asyncio
        import http.client

        file_name = os.path.basename(file_path).lower()
        print(f"[➤] Preparing to upload: {file_name} as file_id={file_id}")

        props = {
            "type": 1,
            "id": self.device_id,
            "file_id": file_id,
            "file_type": 2,
            "play_count": 1,
            "residence_time": 0,
            "file_name": file_name,
            "pack_number": 0
        }

        asyncio.run(self._send_ws_command(0x41, props))
        time.sleep(1)

        try:
            with open(file_path, "rb") as f:
                file_data = f.read()

            conn = http.client.HTTPConnection(self.http_url.split("//")[1])
            headers = {
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(file_data))
            }

            conn.request("POST", "/", body=file_data, headers=headers)
            response = conn.getresponse()
            print(f"[📨] HTTP POST response: {response.status} {response.reason}")
            print(response.read().decode(errors="ignore"))

        except Exception as e:
            print(f"[💥] Exception during raw upload: {e}")

    def upload_image_binary(self, image_bytes, pack_number=0, pack_count=1, pack_index=1):
        import struct
        header = b'\xFA\xF0\x42'  # 0xFA 0xF0 66
        payload = struct.pack('>BBB', pack_number, pack_count, pack_index)
        length = len(image_bytes)
        payload += struct.pack('>H', length)
        payload += image_bytes
        footer = b'\xFE'
        packet = header + payload + footer

        async def send_bin():
            async with websockets.connect(self.ws_url) as websocket:
                await websocket.send(packet)
                print("[⇨] Binary image sent.")

        asyncio.run(send_bin())

    def set_wifi(self, ssid, password):
        props = {
            "type": 1,
            "id": self.device_id,
            "mode": 0,
            "ishot": False,
            "ssid": ssid,
            "password": password
        }
        asyncio.run(self._send_ws_command(0x2F, props))

    def set_schedule(self, starttime, endtime, repeat_mask=0):
        props = {
            "type": 0,
            "id": self.device_id,
            "time": [
                {
                    "id": 0,
                    "starttime": starttime,
                    "endtime": endtime,
                    "devid": 0,
                    "mergeid": 0,
                    "houseid": 0,
                    "devsandweek": repeat_mask
                }
            ]
        }
        asyncio.run(self._send_ws_command(0x35, props))

    def set_reporting_interval(self, interval_seconds):
        props = {
            "type": 1,
            "id": self.device_id,
            "control_type": 17,
            "second": interval_seconds
        }
        asyncio.run(self._send_ws_command(0x34, props))

    def display_sn(self, show=True):
        props = {
            "type": 1,
            "id": self.device_id,
            "control_type": 19 if show else 20
        }
        asyncio.run(self._send_ws_command(0x34, props))

    def connect_bluetooth(self, name, password=""):
        props = {
            "type": 0,
            "id": self.device_id,
            "value": 1,
            "bluetooth": name,
            "password": password
        }
        asyncio.run(self._send_ws_command(0x30, props))

    def disconnect_bluetooth(self):
        props = {
            "type": 0,
            "id": self.device_id,
            "value": 0
        }
        asyncio.run(self._send_ws_command(0x30, props))

    def _send_value_command(self, value, **kwargs):
        props = {"type": 1, "id": self.device_id, "value": value}
        props.update(kwargs)
        asyncio.run(self._send_ws_command(0x2E, props))
