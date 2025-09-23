from hologram_fan_uhd_47cm import HologramFanUhd
import time

# Create fan instance with listener enabled
fan = HologramFanUhd(device_id="10A5621B696E", listen=True)

# Step 1: Get status (verifies connection + format)
fan.get_status()
time.sleep(1)

# Step 2: Power ON
fan.power_on()
time.sleep(1)

# Step 3: Play file (use actual file_id if known)
fan.play_file(9)  # try file_id = 1 or a valid one from app
time.sleep(1)
fan.set_loop_mode(2) # Single repeat mode
time.sleep(30)

# Step 4: Upload video (NOT WORKING YET)
#fan.upload_video("C:/gitrepos/hologramfans/UltraHD-47CM/test.mp4", 10)

# Step 5: Turn off
fan.power_off()
time.sleep(2)