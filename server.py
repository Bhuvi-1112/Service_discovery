import argparse
import signal
import sys
import threading
import time

from common import *


class ServiceServer:
    def __init__(self, args):
        self.name = args.name
        self.service = args.service
        self.port = args.port
        self.registry = (args.registry, args.registry_port)
        self.interval = args.interval
        self.register = not args.no_register
        self.sock = make_socket(port=self.port)
        self.adv_sock = make_socket()
        self.recent = []
        self.lock = threading.Lock()
        self.running = True

    def log(self, text):
        print("[%s] %s" % (time.strftime("%H:%M:%S"), text), flush=True)

    def current_load(self):
        now = time.time()
        with self.lock:
            self.recent = [t for t in self.recent if now - t < 10]
            return len(self.recent)

    def advertise(self, kind):
        msg = pack(type=kind, name=self.name, service=self.service,
                   port=self.port, load=self.current_load())
        self.adv_sock.sendto(msg, self.registry)

    def advert_loop(self):
        kind = "REGISTER"
        while self.running:
            try:
                self.advertise(kind)
                kind = "HEARTBEAT"
            except OSError:
                pass
            time.sleep(self.interval)

    def answer(self, msg):
        text = str(msg.get("payload", ""))
        if self.service == "time":
            return time.strftime("%Y-%m-%d %H:%M:%S")
        if self.service == "upper":
            return text.upper()
        return text

    def run(self):
        signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))
        if self.register:
            threading.Thread(target=self.advert_loop, daemon=True).start()
        self.log("%s serving '%s' on UDP %d (register=%s)" % (self.name, self.service, self.port, self.register))
        try:
            while True:
                data, addr = self.sock.recvfrom(BUFFER_SIZE)
                msg = unpack(data)
                if msg is None or msg["type"] != "REQUEST":
                    continue
                with self.lock:
                    self.recent.append(time.time())
                reply = pack(type="RESPONSE", seq=msg.get("seq"), server=self.name, result=self.answer(msg))
                self.sock.sendto(reply, addr)
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            self.running = False
            if self.register:
                try:
                    self.adv_sock.sendto(pack(type="DEREGISTER", port=self.port), self.registry)
                except OSError:
                    pass
            self.log("%s stopped" % self.name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--service", default="echo")
    parser.add_argument("--registry", default="10.0.0.1")
    parser.add_argument("--registry-port", type=int, default=REGISTRY_PORT)
    parser.add_argument("--port", type=int, default=SERVICE_PORT)
    parser.add_argument("--interval", type=float, default=HEARTBEAT_INTERVAL)
    parser.add_argument("--no-register", action="store_true")
    args = parser.parse_args()
    ServiceServer(args).run()


if __name__ == "__main__":
    main()
