#!/bin/bash
set -e

echo "=== Creating Proper EXT4 with Verity ==="

# 1. Extract content from the EXT2/4 filesystem
echo "Extracting filesystem content..."
mkdir -p /tmp/rootfs-extract
debugfs -R "rdump / /tmp/rootfs-extract" "${BINARIES_DIR}/rootfs.ext2"

# 2. Create proper ext4 filesystem with verity
echo "Creating proper ext4 filesystem..."
mkfs.ext4 -F -O verity -d /tmp/rootfs-extract "${BINARIES_DIR}/rootfs-proper.ext4" 100M

# 3. Replace the original file
mv "${BINARIES_DIR}/rootfs-proper.ext4" "${BINARIES_DIR}/rootfs.ext4"

# 4. Mount and enable fs-verity on files
echo "Enabling fs-verity on files..."
MOUNT_DIR=$(mktemp -d)
sudo mount -o loop "${BINARIES_DIR}/rootfs.ext4" "$MOUNT_DIR"
sudo find "$MOUNT_DIR" -type f -exec fsverity enable {} \; 2>/dev/null
sudo umount "$MOUNT_DIR"
rmdir "$MOUNT_DIR"

echo "✓ Proper EXT4 rootfs with verity created"