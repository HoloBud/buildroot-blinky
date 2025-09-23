
from enum import Enum
import asyncio
import threading

# Import specific fan classes
from .internal.HD_42CM.hologram_fan_3dcircle import HologramFan3DCircle
from .internal.HD_52CM.spindisplaycontroller import SpinDisplayController
from .internal.UltraHD_47CM.hologram_fan_uhd_47cm import HologramFanUhd


class FanModel(Enum):
    NO_FAN = "NO_FAN" # Used only to indicate no fan is available in main application. Should not be passed to HologramFanController initializer
    HD_42CM = "HD_42CM"
    HD_52CM = "HD_52CM"
    UHD_47CM = "UHD_47CM"


class HologramFanController:
    def __init__(self, model: FanModel, ip = None):
        self.model = model

        if model == FanModel.HD_42CM:
            if ip:
                self.fan = HologramFan3DCircle(host=ip)
            else:
                self.fan = HologramFan3DCircle()
        elif model == FanModel.HD_52CM:
            if ip:
                self.fan = SpinDisplayController(ip_address=ip, wake=False)
            else:
                self.fan = SpinDisplayController(wake=False)
        elif model == FanModel.UHD_47CM:
            if ip:
                self.fan = HologramFanUhd(ip=ip)
            else:
                self.fan = HologramFanUhd()
        else:
            raise ValueError(f"Unsupported fan model: {model}")

    def turn_on(self):
        if self.model == FanModel.HD_42CM:
            self.fan.power_toggle()
        elif self.model == FanModel.HD_52CM:
            self.fan.power_on()
        elif self.model == FanModel.UHD_47CM:
            self.fan.power_on()

    def turn_off(self):
        if self.model == FanModel.HD_42CM:
            self.fan.power_toggle()
        elif self.model == FanModel.HD_52CM:
            self.fan.power_off()
        elif self.model == FanModel.UHD_47CM:
            self.fan.power_off()

    def play_animation(self, animation_entry: dict, loop_play: bool = False):
        file_id = animation_entry.get("file_id")

        if self.model == FanModel.HD_42CM:
            self.fan.play_slot(file_id-1) # Confirmed this HW is 0-based indexed
            if loop_play:
                self.fan.loop_repeat()
            else:
                self.fan.loop_once()

        elif self.model == FanModel.HD_52CM:
            self.fan.play_file(file_id-1) # Confirmed this HW is 0-based indexed
            if loop_play:
                self.fan.loop_current_file()

        elif self.model == FanModel.UHD_47CM:
            self.fan.play_file(9)
            if loop_play:
                self.fan.set_loop_mode(2)
            else:
                self.fan.set_loop_mode(1)
