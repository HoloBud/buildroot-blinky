#!/bin/sh

set -u
set -e

# Add a console on tty1
if [ -e ${TARGET_DIR}/etc/inittab ]; then
    grep -qE '^tty1::' ${TARGET_DIR}/etc/inittab || \
	sed -i '/GENERIC_SERIAL/a\
tty1::respawn:/sbin/getty -L  tty1 0 vt100 # HDMI console' ${TARGET_DIR}/etc/inittab
# systemd doesn't use /etc/inittab, enable getty.tty1.service instead
elif [ -d ${TARGET_DIR}/etc/systemd ]; then
    mkdir -p "${TARGET_DIR}/etc/systemd/system/getty.target.wants"
    ln -sf /lib/systemd/system/getty@.service \
       "${TARGET_DIR}/etc/systemd/system/getty.target.wants/getty@tty1.service"
    # Create the necessary symbolic links of the custom services
    mkdir -p "${TARGET_DIR}/etc/systemd/system/multi-user.target.wants"
    ln -sf /etc/systemd/system/wifi-dongle.service \
       "${TARGET_DIR}/etc/systemd/system/multi-user.target.wants/wifi-dongle.service"
    
    mkdir -p "${TARGET_DIR}/etc/systemd/system/wifi-dongle.service.wants"
    ln -sf /etc/systemd/system/holo-device.service \
       "${TARGET_DIR}/etc/systemd/system/wifi-dongle.service.wants/holo-device.service"
fi

# Delete unnecessary files after testing images if modifying configs turns out too challenging