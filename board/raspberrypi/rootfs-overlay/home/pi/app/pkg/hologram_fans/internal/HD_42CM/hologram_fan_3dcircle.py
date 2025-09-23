"""
Control library for 42‑cm “3D‑Circle” hologram fans (cheap 42 cm model).

– Keeps the rock‑solid framing/handshake discovered from the APK.
– Adds every *known* ASCII command observed in packet captures or de‑compiled code,
  except `read_password`, which stopped returning data from FW ≥ v1.58.

CAUTION commands (flash / NAND writes)
--------------------------------------
`delete_file`, `format_memory`, and `clear_table` trigger NAND writes that
block the MCU for ≈2 s.  These helpers therefore sleep `POST_FLASH_DELAY`
after TX to avoid tripping over the device while it is busy.

Typical use:
------------
>>> from hologram_fan_3dcircle_full import HologramFan3DCircle
>>> fan = HologramFan3DCircle()
>>> fan.power_toggle()
>>> fan.play_slot(3)
>>> fan.loop_repeat()
>>> fan.brightness_up()
>>> fan.power_toggle()
"""
from __future__ import annotations

import socket
import time
from typing import Optional, List

__all__ = ["HologramFan3DCircle"]


class HologramFan3DCircle:
    """Full‑featured driver for 3D‑Circle 42 cm fan."""

    TAIL = b"C0EEBDF9E5B7"
    DEFAULT_DEVICE_ID = "C0EEB7C9BAA3"  # label underneath the blades
    POST_FLASH_DELAY = 2.0              # seconds to wait after NAND ops

    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------
    @staticmethod
    def _len_field(n: int) -> bytes:
        """Encode *n* using funky 3‑byte rule seen in APK."""
        return bytes([
            n // 323,
            ((n // 17) % 19) + 99,
            ((n % 323) % 17) + 98,
        ])

    def _frame(self, payload: bytes) -> bytes:
        return self.device_id + self._len_field(len(payload)) + payload + self.TAIL

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def __init__(self,
                 host: str = "192.168.4.1",
                 port: int = 20320,
                 device_id: str = DEFAULT_DEVICE_ID,
                 timeout: float = 2.0):
        self.host = host
        self.port = port
        self.device_id = device_id.encode("ascii")
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None

    # --------------------------------------------------------------- private
    def _ensure_conn(self) -> None:
        if self.sock is not None and self.sock.fileno() != -1:
            return
        self.sock = socket.create_connection((self.host, self.port), self.timeout)
        # handshake (ID + tail) — fan echoes it back
        self.sock.sendall(self.device_id + self.TAIL)
        self.sock.recv(64)

    def _send(self, payload: bytes, post_delay: float = 0.0) -> None:
        """Low‑level send with optional post‑delay."""
        self._ensure_conn()
        self.sock.sendall(self._frame(payload))
        # always echoed, ignore
        self.sock.recv(64)
        if post_delay:
            time.sleep(post_delay)

    # ---------------------------------------------------------------- public
    # Power / playback -----------------------------------------------------
    def power_toggle(self):
        self._send(b"a")

    def pause_play_toggle(self):
        """Pauses or resumes current animation."""
        self._send(b"e")

    def next_file(self):
        self._send(b"c")

    def previous_file(self):
        self._send(b"d")

    def play_slot(self, index: int):
        if not 0 <= index <= 120:
            raise ValueError("index must be 0‑120")
        self._send(b"B" + bytes([index]))

    def loop_once(self):
        """Set play‑once mode."""
        self._send(b"h")

    def loop_repeat(self):
        """Set repeat‑forever mode."""
        self._send(b"g")

    # Brightness & rotation -----------------------------------------------
    def brightness_down(self):
        self._send(b"l")

    def brightness_up(self):
        self._send(b"m")

    def rotate_clockwise(self):
        self._send(b"p")

    def rotate_counterclockwise(self):
        self._send(b"q")

    # NAND / table operations (danger zone) -------------------------------
    def delete_file(self, index: int):
        if not 0 <= index <= 120:
            raise ValueError("index must be 0‑120")
        self._send(b"!" + bytes([index]), post_delay=self.POST_FLASH_DELAY)

    def format_memory(self):
        """Erase whole NAND (irreversible!)."""
        self._send(b"j", post_delay=self.POST_FLASH_DELAY)

    def clear_table(self):
        """Clear file table but keep data blocks (acts like quick‑format)."""
        self._send(b"k", post_delay=self.POST_FLASH_DELAY)

    # Debug helpers --------------------------------------------------------
    def send_raw_command(self, ascii_payload: str):
        """Send an *arbitrary* ASCII payload framed automatically."""
        self._send(ascii_payload.encode("ascii"))

    def list_files(self) -> List[int]:
        """Return list of IDs present in the file table (best‑effort)."""
        # build raw packet identical to legacy "gri" capture:
        payload = b"gri\x013\x030"
        self._ensure_conn()
        self.sock.sendall(self._frame(payload))
        # read echo + response (fan answers in one shot ≤1024 B)
        raw = self.sock.recv(2048)
        if not raw:
            return []
        # strip framing
        if raw.startswith(self.device_id):
            raw = raw[len(self.device_id)+3:]  # drop ID + len field
        if raw.endswith(self.TAIL):
            raw = raw[:-12]
        # locate marker "gri\x01"
        start = raw.find(b"gri")
        if start == -1:
            return []
        i = start + 4
        ids: List[int] = []
        while i + 5 < len(raw):
            flag = raw[i]
            if flag not in (0x05, 0x06):
                break
            file_id = raw[i+1]
            ids.append(file_id)
            i += 6
        return ids

    # ---------------------------------------------------------------------
    # Context mgr sugar
    # ---------------------------------------------------------------------
    def __enter__(self):
        self._ensure_conn()
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.sock:
            self.sock.close()
            self.sock = None
