from time import sleep
from hologram_fan_3dcircle import HologramFan3DCircle

with HologramFan3DCircle() as fan:
    fan.power_toggle()      # first toggle wakes the blades
    sleep(1)
    fan.play_slot(1)    # slot 1
    sleep(1)
    fan.loop_repeat()
    sleep(15)
    fan.power_toggle()