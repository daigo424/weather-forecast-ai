"""kubectl port-forward wrapper that auto-reconnects on disconnect."""
import subprocess
import sys
import time


def main():
    # Usage: port_forward.py <svc-name> <namespace> <local-port>:<remote-port>
    svc, namespace, ports = sys.argv[1], sys.argv[2], sys.argv[3]
    while True:
        subprocess.run(["kubectl", "port-forward", f"svc/{svc}", "-n", namespace, ports])
        time.sleep(1)


if __name__ == "__main__":
    main()
