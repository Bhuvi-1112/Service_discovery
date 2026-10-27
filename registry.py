import argparse
import threading
import time

from common import *


def stamp():
    return time.strftime("%H:%M:%S")


class Registry:
    def __init__(self, port, notify_ip, timeout):
        self.sock = make_socket(port=port)
        self.ctl_sock = make_socket(broadcast=True)
        self.notify_ip = notify_ip
        self.timeout = timeout
        self.services = {}
        self.lock = threading.Lock()

    def log(self, text):
        print("[%s] %s" % (stamp(), text), flush=True)

    def notify(self, action, ip):
        if not self.notify_ip:
            return
        data = ("%s %s" % (action, ip)).encode()
        try:
            self.ctl_sock.sendto(data, (self.notify_ip, CONTROL_PORT))
        except OSError as err:
            self.log("could not notify controller: %s" % err)

    def ip_still_used(self, ip):
        with self.lock:
            return any(s["ip"] == ip for s in self.services.values())

    def on_advert(self, msg, addr):
        port = int(msg["port"])
        key = (addr[0], port)
        with self.lock:
            is_new = key not in self.services
            self.services[key] = {
                "name": str(msg.get("name", "unknown")),
                "service": str(msg.get("service", "echo")),
                "ip": addr[0],
                "port": port,
                "load": int(msg.get("load", 0)),
                "last_seen": time.time(),
            }
            entry = self.services[key]
        if is_new:
            self.log("REGISTERED %s %s:%d service=%s" % (entry["name"], entry["ip"], port, entry["service"]))
            self.notify("ALLOW", addr[0])
        self.sock.sendto(pack(type="ACK"), addr)

    def on_deregister(self, msg, addr):
        key = (addr[0], int(msg["port"]))
        with self.lock:
            entry = self.services.pop(key, None)
        if entry is None:
            return
        self.log("DEREGISTERED %s %s" % (entry["name"], entry["ip"]))
        if not self.ip_still_used(entry["ip"]):
            self.notify("BLOCK", entry["ip"])

    def on_query(self, msg, addr):
        wanted = msg.get("service", "*")
        with self.lock:
            found = [s for s in self.services.values() if wanted == "*" or s["service"] == wanted]
        found.sort(key=lambda s: (s["load"], s["name"]))
        servers = [{"name": s["name"], "ip": s["ip"], "port": s["port"],
                    "service": s["service"], "load": s["load"]} for s in found]
        self.sock.sendto(pack(type="RESULT", id=msg.get("id"), servers=servers), addr)
        self.log("QUERY service=%s from %s -> %d server(s)" % (wanted, addr[0], len(servers)))

    def watch(self):
        last_sync = time.time()
        while True:
            time.sleep(1)
            now = time.time()
            dead = []
            with self.lock:
                for key in list(self.services):
                    entry = self.services[key]
                    if now - entry["last_seen"] > self.timeout:
                        dead.append((entry, now - entry["last_seen"]))
                        del self.services[key]
            for entry, silent in dead:
                self.log("TIMEOUT %s %s:%d no heartbeat for %.1f s" % (entry["name"], entry["ip"], entry["port"], silent))
                if not self.ip_still_used(entry["ip"]):
                    self.notify("BLOCK", entry["ip"])
            if now - last_sync >= 5:
                last_sync = now
                with self.lock:
                    alive = set(s["ip"] for s in self.services.values())
                for ip in alive:
                    self.notify("ALLOW", ip)

    def serve(self):
        threading.Thread(target=self.watch, daemon=True).start()
        self.log("registry listening on UDP %d" % self.sock.getsockname()[1])
        while True:
            data, addr = self.sock.recvfrom(BUFFER_SIZE)
            msg = unpack(data)
            if msg is None:
                continue
            kind = msg["type"]
            try:
                if kind in ("REGISTER", "HEARTBEAT"):
                    self.on_advert(msg, addr)
                elif kind == "DEREGISTER":
                    self.on_deregister(msg, addr)
                elif kind == "QUERY":
                    self.on_query(msg, addr)
            except (KeyError, ValueError, TypeError):
                self.log("bad %s message from %s" % (kind, addr[0]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=REGISTRY_PORT)
    parser.add_argument("--notify", default="10.0.0.255")
    parser.add_argument("--no-notify", action="store_true")
    parser.add_argument("--timeout", type=float, default=SERVICE_TIMEOUT)
    args = parser.parse_args()
    notify_ip = None if args.no_notify else args.notify
    registry = Registry(args.port, notify_ip, args.timeout)
    try:
        registry.serve()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
