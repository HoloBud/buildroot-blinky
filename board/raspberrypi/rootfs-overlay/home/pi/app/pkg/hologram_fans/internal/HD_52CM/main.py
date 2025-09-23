from spindisplaycontroller import SpinDisplayController
import time

# Pass the fan's IP address here 👇
fan = SpinDisplayController("10.10.10.1", wake=False)

print("Power on")
fan.power_on()
time.sleep(0.5)
print("Playing file 2")
fan.play_file(2)
time.sleep(0.5)
fan.loop_current_file()
print("All commands sent")
time.sleep(10)
print("Playing file 3")
fan.play_file(3)
time.sleep(0.5)
fan.loop_current_file()
print("All commands sent")
time.sleep(10)
print("Power off")
fan.power_off()