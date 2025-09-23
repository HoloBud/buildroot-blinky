#!/bin/sh

echo "Switching mode of realtek wifi dongle..."
# You'll need to switch the mode of the USB dongle if it's in CD-ROM mode
# sudo apt install -y usb-modeswitch usb-modeswitch-data
usb_modeswitch -v 0bda -p 1a2b -V 0bda -P 1a2b -M "5553424312345678000000000000061b000000020000000000000000000000"

# Physically disconnect it won't be feasible on-field:
# 1-1 is the usb bus and port in the board, modify accordingly.
echo 0 > /sys/bus/usb/devices/1-1/authorized  # Deauthorize
sleep 1
echo 1 > /sys/bus/usb/devices/1-1/authorized  # Reauthorize

echo "Finalizing realtek wifi dongle switch mode."