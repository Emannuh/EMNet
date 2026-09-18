"""
Adds deenet.localhost to the Windows hosts file.
Run as Administrator:
    python scripts/add_hosts.py
"""
import sys

HOSTS_FILE = r"C:\Windows\System32\drivers\etc\hosts"
ENTRY = "127.0.0.1   deenet.localhost"

try:
    with open(HOSTS_FILE, "r") as f:
        content = f.read()

    if "deenet.localhost" in content:
        print("deenet.localhost already in hosts file.")
        sys.exit(0)

    with open(HOSTS_FILE, "a") as f:
        f.write(f"\n{ENTRY}\n")

    print(f"Added: {ENTRY}")

except PermissionError:
    print("ERROR: Run this script as Administrator.")
    sys.exit(1)
