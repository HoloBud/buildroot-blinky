from scapy.all import rdpcap, TCP
import sys

# Customize these if needed
PCAP_FILE = "your_capture.pcap"
OUTPUT_FILE = "fan_packets_hex.txt"
TARGET_PORT = 20320

def extract_packets_to_hex(pcap_path, output_path, port):
    packets = rdpcap(pcap_path)
    with open(output_path, "w") as f:
        for pkt in packets:
            if pkt.haslayer(TCP):
                tcp = pkt[TCP]
                if tcp.dport == port and bytes(tcp.payload):
                    f.write(f"{pkt.time:.6f} - Packet to port {port}\n")
                    f.write(bytes(tcp.payload).hex(" ") + "\n\n")

    print(f"✅ Done. Saved to {output_path}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        PCAP_FILE = sys.argv[1]
    extract_packets_to_hex(PCAP_FILE, OUTPUT_FILE, TARGET_PORT)
