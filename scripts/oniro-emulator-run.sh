#!/usr/bin/env bash
set -euo pipefail

image_dir="${1:-}"
connect_key="${2:-127.0.0.1:55555}"

if [ -z "$image_dir" ]; then
  echo "Usage: $0 <oniro-emulator-images-dir> [host:port]"
  exit 1
fi

if [[ "$connect_key" != *:* ]]; then
  echo "Error: expected connect key in host:port form, got '$connect_key'."
  exit 1
fi

forward_host="${connect_key%:*}"
forward_port="${connect_key##*:}"

if [ -z "$forward_host" ] || [ -z "$forward_port" ]; then
  echo "Error: expected connect key in host:port form, got '$connect_key'."
  exit 1
fi

if [[ ! "$forward_port" =~ ^[0-9]+$ ]]; then
  echo "Error: expected numeric port in connect key, got '$connect_key'."
  exit 1
fi

qemu_bin="${QEMU_BIN:-qemu-system-x86_64}"

if ! command -v "$qemu_bin" >/dev/null 2>&1; then
  echo "Error: $qemu_bin is not available on PATH."
  echo "Install QEMU and retry."
  exit 1
fi

required_files=(
  "bzImage"
  "ramdisk.img"
  "updater.img"
  "system.img"
  "vendor.img"
  "userdata.img"
)

for required_file in "${required_files[@]}"; do
  if [ ! -f "$image_dir/$required_file" ]; then
    echo "Error: expected $image_dir/$required_file"
    exit 1
  fi
done

host_os="$(uname -s)"
host_arch="$(uname -m)"
cpu_arg=()
accel_arg=()

case "$host_os" in
  Linux)
    if [ ! -e /dev/kvm ]; then
      echo "Error: /dev/kvm is not available. Enable hardware virtualization and KVM before starting the emulator."
      exit 1
    fi

    if [ ! -r /dev/kvm ] || [ ! -w /dev/kvm ]; then
      echo "Error: current user does not have access to /dev/kvm."
      echo "Add your user to the kvm group or otherwise grant read/write access to /dev/kvm, then try again."
      exit 1
    fi

    accel_arg=(-enable-kvm)
    cpu_arg=(-cpu host)
    ;;
  Darwin)
    if [ "$host_arch" = "x86_64" ]; then
      accel_arg=(-accel hvf)
      cpu_arg=(-cpu host)
    else
      accel_arg=(-accel tcg,thread=multi)
      cpu_arg=(-cpu max)
    fi
    ;;
  *)
    echo "Error: unsupported host OS: $host_os"
    exit 1
    ;;
esac

cd "$image_dir"

exec "$qemu_bin" \
  -machine q35 \
  -smp 6 \
  -m 4096M \
  -boot c \
  -nographic \
  -rtc base=utc,clock=host \
  -device es1370 \
  -initrd ramdisk.img \
  -kernel bzImage \
  -drive if=none,file=updater.img,format=raw,id=updater,index=0 \
  -device virtio-blk-pci,drive=updater \
  -drive if=none,file=system.img,format=raw,id=system,index=1 \
  -device virtio-blk-pci,drive=system \
  -drive if=none,file=vendor.img,format=raw,id=vendor,index=2 \
  -device virtio-blk-pci,drive=vendor \
  -drive if=none,file=userdata.img,format=raw,id=userdata,index=3 \
  -device virtio-blk-pci,drive=userdata \
  -append "ip=dhcp loglevel=4 console=ttyS0,115200 init=init root=/dev/ram0 rw ohos.boot.hardware=x86_general ohos.required_mount.system=/dev/block/vdb@/usr@ext4@ro,barrier=1@wait,required ohos.required_mount.vendor=/dev/block/vdc@/vendor@ext4@ro,barrier=1@wait,required ohos.required_mount.misc=/dev/block/vda@/misc@none@none=@wait,required" \
  "${accel_arg[@]}" \
  "${cpu_arg[@]}" \
  -netdev "user,id=net0,hostfwd=tcp:${forward_host}:${forward_port}-:55555" \
  -device virtio-net-pci,netdev=net0
