import socket
import ipaddress
import concurrent.futures
import psutil
import argparse
import time

PORT = 50200
TIMEOUT = 0.5

def get_local_subnet(forced_ip=None):
    if forced_ip:
        print(f"Using forced IP: {forced_ip}")
        network = ipaddress.IPv4Network(f"{forced_ip}/255.255.255.0", strict=False)
        return str(forced_ip), list(network.hosts())
    
    for iface, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                ip = addr.address
                netmask = addr.netmask
                if ip and netmask:
                    network = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)
                    return str(ip), list(network.hosts())
    raise RuntimeError("No active network interface found.")

def is_device_active(ip):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(TIMEOUT)
            s.connect((str(ip), PORT))
        return str(ip)
    except:
        return None

def scan_network(forced_ip=None):
    local_ip, hosts = get_local_subnet(forced_ip)
    print(f"Scanning from IP: {local_ip}")
    print(f"Scanning {len(hosts)} addresses...")

    found = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
        futures = [executor.submit(is_device_active, ip) for ip in hosts]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                print(f"✅ Found device: {result}")
                found.append(result)

    if not found:
        print("❌ No SpinDisplay device found.")
    return found

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scan for SpinDisplay device on local network.")
    parser.add_argument('--ip', type=str, help="Manually specify your local IP (e.g., 192.168.1.9)")
    args = parser.parse_args()

    start = time.time()
    devices = scan_network(args.ip)
    print(f"Scan completed in {time.time() - start:.2f}s.")
    if devices:
        print("SpinDisplay devices detected at:")
        for ip in devices:
            print(f" - {ip}")
