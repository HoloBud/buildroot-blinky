#!/bin/sh

set -u
set -e

# Verity enabler function
recursive_verity_() {
   local dir="$1"
   local key_file="$2"

   if [ ! -d "$dir" ]; then
      return 1
   fi

   echo "Processing directory: $dir"
   for i in "${dir}"/*; do
      if [ -f "$i" ]; then
         # Generate the signature of the file
         fsverity sign "$i" "$i".sig --key="$key_file"
         # Sign the file
         fsverity enable "$i" --signature="$i".sig
         # There's no need to keep the signature of the file in the host machine
         rm -f "$i".sig
         echo "Enabled verity on $i"
      fi
   done

   for subdir in "${dir}"/*; do
      if [ -d "$subdir" ]; then
         recursive_verity_ "$subdir" "$key_file"
      fi
   done
}

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
fi

# Create the necessary symbolic links of the custom services to be auto-called
mkdir -p "${TARGET_DIR}/etc/systemd/system/multi-user.target.wants"
ln -sf /etc/systemd/system/wifi-dongle.service \
   "${TARGET_DIR}/etc/systemd/system/multi-user.target.wants/wifi-dongle.service"

mkdir -p "${TARGET_DIR}/etc/systemd/system/wifi-dongle.service.wants"
ln -sf /etc/systemd/system/holo-device.service \
   "${TARGET_DIR}/etc/systemd/system/wifi-dongle.service.wants/holo-device.service"

echo "Copying WiFi firmware files..."
mkdir -p "${TARGET_DIR}/lib/firmware/rtw88"
mkdir -p "${TARGET_DIR}/lib/firmware/rtlwifi"

# Copy from build directory to target
cp output/build/linux-firmware-*/rtw88/* "${TARGET_DIR}/lib/firmware/rtw88/"
cp output/build/linux-firmware-*/rtlwifi/* "${TARGET_DIR}/lib/firmware/rtlwifi/"

# Enable verity over home/blinky files
SIGN_PRIVATE_KEY=/home/luisgiii/fs-verity-keys/combined-key.pem
LOOK_DIRECTORY="${TARGET_DIR}/home/blinky"

recursive_verity_ "$LOOK_DIRECTORY" "$SIGN_PRIVATE_KEY"
