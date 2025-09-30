#!/bin/bash

set -e

BOARD_DIR="$(dirname $0)"
BOARD_NAME="$(basename ${BOARD_DIR})"
GENIMAGE_CFG="${BOARD_DIR}/genimage-${BOARD_NAME}.cfg"
GENIMAGE_TMP="${BUILD_DIR}/genimage.tmp"

# Generate hash tree and add it at the beginning of the partition
sudo dd if=/dev/zero of="${BINARIES_DIR}/hashtree.bin" bs=1M count=4

VERITY_OUTPUT=$(veritysetup format "${BINARIES_DIR}/rootfs.ext2" "${BINARIES_DIR}/hashtree.bin" --hash=sha256 --data-block-size=1024 2>&1)
echo "$VERITY_OUTPUT"

# Obtain here root hash + salt of partition and add it to bootargs
TREE_ROOT_HASH=$(echo "$VERITY_OUTPUT" | grep -oP "Root hash:\s+\K[a-f0-9]+")
TREE_SALT=$(echo "$VERITY_OUTPUT" | grep -oP "Salt:\s+\K[a-f0-9]+")
DATA_BLOCKS=$(echo "$VERITY_OUTPUT" | grep -oP "Data blocks:\s+\K[0-9]+")
DATA_BLOCK_SIZE=$(echo "$VERITY_OUTPUT" | grep -oP "Data block size:\s+\K[0-9]+")
HASH_BLOCK_SIZE=$(echo "$VERITY_OUTPUT" | grep -oP "Hash block size:\s+\K[0-9]+")
HASH_ALGORITHM=$(echo "$VERITY_OUTPUT" | grep -oP "Hash algorithm:\s+\K[a-z0-9-]+")

DATA_SIZE_BYTES=$((DATA_BLOCKS * DATA_BLOCK_SIZE))
DATA_SIZE_SECTORS=$((DATA_SIZE_BYTES / 512))

DM_PARAMETER="dm-mod.waitfor=/dev/mmcblk0p2,/dev/mmcblk0p3 dm-mod.create=\"vroot,,0,ro,0 $DATA_SIZE_SECTORS verity 1 179:2 179:3 $DATA_BLOCK_SIZE $HASH_BLOCK_SIZE \
$DATA_BLOCKS 1 $HASH_ALGORITHM $TREE_ROOT_HASH $TREE_SALT\""

echo "$DM_PARAMETER" >> "${BINARIES_DIR}/rpi-firmware/cmdline.txt"

# generate genimage from template if a board specific variant doesn't exists
if [ ! -e "${GENIMAGE_CFG}" ]; then
	GENIMAGE_CFG="${BINARIES_DIR}/genimage.cfg"
	FILES=()

	for i in "${BINARIES_DIR}"/*.dtb "${BINARIES_DIR}"/rpi-firmware/*; do
		FILES+=( "${i#${BINARIES_DIR}/}" )
	done

	KERNEL=$(sed -n 's/^kernel=//p' "${BINARIES_DIR}/rpi-firmware/config.txt")
	FILES+=( "${KERNEL}" )

	BOOT_FILES=$(printf '\\t\\t\\t"%s",\\n' "${FILES[@]}")
	sed "s|#BOOT_FILES#|${BOOT_FILES}|" "${BOARD_DIR}/genimage.cfg.in" \
		> "${GENIMAGE_CFG}"
fi

# Pass an empty rootpath. genimage makes a full copy of the given rootpath to
# ${GENIMAGE_TMP}/root so passing TARGET_DIR would be a waste of time and disk
# space. We don't rely on genimage to build the rootfs image, just to insert a
# pre-built one in the disk image.

trap 'rm -rf "${ROOTPATH_TMP}"' EXIT
ROOTPATH_TMP="$(mktemp -d)"

rm -rf "${GENIMAGE_TMP}"

genimage \
	--rootpath "${ROOTPATH_TMP}"   \
	--tmppath "${GENIMAGE_TMP}"    \
	--inputpath "${BINARIES_DIR}"  \
	--outputpath "${BINARIES_DIR}" \
	--config "${GENIMAGE_CFG}"

exit $?
