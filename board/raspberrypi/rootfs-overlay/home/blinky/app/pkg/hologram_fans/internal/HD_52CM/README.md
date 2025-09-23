# SpinDisplay Fan Controller (Python)

This script allows you to control compatible SpinDisplay hologram fan devices (F45, F52, F56, F65, F80, F100) using a TCP connection, according to the V1.1 third-party control protocol.

---

## ✅ Requirements

- Python 3.6+
- Device and your computer must be on the **same network** or you must be connected directly to the device's Wi-Fi hotspot.

---

## 📦 Setup

1. Clone or download this repo.
2. Connect to the SpinDisplay fan:
   - **Wi-Fi Direct**: Connect to the device's hotspot. IP: `10.10.10.1`
   - **LAN**: Connect both PC and device to the same network, then use find_spindisplay_ip.py or the official software to find the device's IP.

3. Enable "Third Party Control" via the **SpinDisplay PC software or mobile app**.
4. Power cycle the device (turn it off and on).
5. Install Python dependencies (standard library only, no extra packages required).

---

## 🚀 Usage

```python
from spindisplay_controller import SpinDisplayController

fan = SpinDisplayController("10.10.10.1")  # or LAN IP

fan.power_on()
fan.play_file(0)  # Play the first file
fan.brightness_up()
fan.pause()
fan.resume()
fan.power_off()
