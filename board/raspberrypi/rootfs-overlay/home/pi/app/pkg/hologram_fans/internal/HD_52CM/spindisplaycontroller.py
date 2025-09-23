import socket
import time
import os
import subprocess
import platform

DEBUG = False

class SpinDisplayController:
    def __init__(self, ip_address: str = "10.10.10.1", port: int = 50200, timeout: int = 3, wake: bool = True, repeat_cmd: int = 3):
        self.ip_address = ip_address
        self.port = port
        self.timeout = timeout
        self.wake = wake
        self.repeat_cmd = repeat_cmd

    def _wake_device(self):
        """Ping the device before sending a command to help it wake up (optional)."""
        if DEBUG: print(f"🔔 Pinging {self.ip_address} to wake up the device...")
        cmd = ["ping", "-n", "1", self.ip_address] if platform.system() == "Windows" else ["ping", "-c", "1", self.ip_address]
        cmdresult = subprocess.run(cmd, capture_output=True, text=True)
        if DEBUG: print(cmdresult)
        time.sleep(0.5)

    def _send_command(self, command_bytes: bytes, retries: int = 1, delay: float = 0.5):
        """Send a command with retry and optional ping wake-up."""
        if DEBUG: print("Sending command...")

        if self.wake:
            self._wake_device()

        for attempt in range(retries + 1):
            try:
                with socket.create_connection((self.ip_address, self.port), timeout=self.timeout) as sock:
                    sock.sendall(command_bytes)
                    time.sleep(0.3)  # Let device process the command
                    if DEBUG: print(f"[✓] Sent command: {command_bytes.hex()}")
                    return
            except Exception as e:
                if DEBUG: print(f"[!] Attempt {attempt + 1} failed: {command_bytes.hex()} — {e}")
                if attempt < retries:
                    time.sleep(delay)
        if DEBUG: print(f"[✗] Command failed after {retries + 1} attempts.")

    def _send_command_repeated(self, command_bytes: bytes):
        for _ in range(self.repeat_cmd):
            self._send_command(command_bytes)

    # ========================
    # Command Methods
    # ========================

    # Commands repeated for reliability

    def power_on(self):
        self._send_command_repeated(bytes([0x5B, 0x01, 0x00]))

    def power_off(self):
        self._send_command_repeated(bytes([0x5B, 0x02, 0x00]))

    def pause_playback(self):
        self._send_command_repeated(bytes([0x5B, 0x03, 0x00]))

    def resume_playback(self):
        self._send_command_repeated(bytes([0x5B, 0x04, 0x00]))

    def loop_current_file(self):
        self._send_command_repeated(bytes([0x5B, 0x05, 0x00]))

    def play_file(self, index: int):
        if 0 <= index <= 255:
            self._send_command_repeated(bytes([0x5B, 0x06, index]))
        else:
            print(f"[!] Invalid file index: {index} (must be 0–255)")

    
    # Commands which cannot be repeated for risk of double commanding
    
    def play_previous_file(self):
        self._send_command(bytes([0x5B, 0x07, 0x00]))

    def play_next_file(self):
        self._send_command(bytes([0x5B, 0x08, 0x00]))

    def increase_brightness(self):
        self._send_command(bytes([0x5B, 0x09, 0x00]))

    def decrease_brightness(self):
        self._send_command(bytes([0x5B, 0x0A, 0x00]))
