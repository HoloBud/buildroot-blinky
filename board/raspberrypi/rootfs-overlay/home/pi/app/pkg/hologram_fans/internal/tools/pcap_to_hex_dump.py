#!/usr/bin/env python3
"""
pcap_to_hex_all.py  ––  Hex‑dump de *todos* los frames* de un .pcap o .pcapng

Uso:
    python3 pcap_to_hex_all.py captura.pcapng
    python3 pcap_to_hex_all.py cap1.pcap cap2.pcapng
"""
import sys, os, textwrap
from scapy.utils import RawPcapReader      # devuelve (bytes, metadata)


def _timestamp(meta) -> str:
    """Devuelve el timestamp como str con 6 decimales o 'n/a'."""
    if hasattr(meta, "sec") and hasattr(meta, "usec"):
        return f"{meta.sec + meta.usec / 1_000_000:.6f}"
    if hasattr(meta, "ts_sec") and hasattr(meta, "ts_usec"):
        return f"{meta.ts_sec + meta.ts_usec / 1_000_000:.6f}"
    if hasattr(meta, "ts_high") and hasattr(meta, "ts_low"):
        # pcapng con resol prec < 1 µs
        ts = (meta.ts_high << 32) | meta.ts_low
        return f"{ts / 1_000_000:.6f}"
    return "n/a"


def dump_pcap(path: str, wrap: int = 96) -> None:
    base = os.path.splitext(os.path.basename(path))[0]
    out  = f"{base}_raw.txt"

    with open(out, "w") as f:
        for idx, (pkt, meta) in enumerate(RawPcapReader(path), 1):
            f.write(f"{_timestamp(meta)} - Frame #{idx}\n")
            hexstr = " ".join(f"{b:02x}" for b in pkt)
            for line in textwrap.wrap(hexstr, wrap):
                f.write(line + "\n")
            f.write("\n")

    print(f"✅  {idx} frames volcados en {out}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 pcap_to_hex_all.py <cap1.pcap[ng]> [cap2 …]")
        sys.exit(1)

    for pcap in sys.argv[1:]:
        try:
            dump_pcap(pcap)
        except FileNotFoundError:
            print(f"⚠️  Archivo no encontrado: {pcap}")
