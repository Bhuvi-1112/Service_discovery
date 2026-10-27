import argparse
import random
import socket
import time

from common import *


def discover(sock, registry, service, wait):
    qid = random.randint(1, 10 ** 9)
    start = time.perf_counter()
    sock.sendto(pack(type="QUERY", service=service, id=qid), registry)
    end = start + wait
    while True:
        left = end - time.perf_counter()
        if left <= 0:
            return None, []
        sock.settimeout(left)
        try:
            data, _ = sock.recvfrom(BUFFER_SIZE)
        except socket.timeout:
            return None, []
        msg = unpack(data)
        if msg and msg["type"] == "RESULT" and msg.get("id") == qid:
            return (time.perf_counter() - start) * 1000, msg.get("servers", [])


def call_service(sock, target, seq, wait):
    start = time.perf_counter()
    sock.sendto(pack(type="REQUEST", seq=seq, payload="hello"), (target["ip"], target["port"]))
    end = start + wait
    while True:
        left = end - time.perf_counter()
        if left <= 0:
            return None, None
        sock.settimeout(left)
        try:
            data, _ = sock.recvfrom(BUFFER_SIZE)
        except socket.timeout:
            return None, None
        msg = unpack(data)
        if msg and msg["type"] == "RESPONSE" and msg.get("seq") == seq:
            return (time.perf_counter() - start) * 1000, msg


def average(values):
    if not values:
        return "n/a"
    return "%.2f" % (sum(values) / len(values))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", default="10.0.0.1")
    parser.add_argument("--registry-port", type=int, default=REGISTRY_PORT)
    parser.add_argument("--service", default="echo")
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=1.0)
    parser.add_argument("--cooldown", type=float, default=10.0)
    parser.add_argument("--direct", default=None)
    parser.add_argument("--csv", default=None)
    args = parser.parse_args()

    sock = make_socket()
    registry = (args.registry, args.registry_port)
    bad = {}
    ok = 0
    fail = 0
    disc_times = []
    rtts = []
    rows = []

    for i in range(1, args.count + 1):
        disc = None
        if args.direct:
            ip, port = args.direct.split(":")
            target = {"name": args.direct, "ip": ip, "port": int(port)}
        else:
            disc, servers = discover(sock, registry, args.service, args.timeout)
            if disc is None:
                print("round %d | no reply from registry" % i, flush=True)
                fail += 1
                time.sleep(args.interval)
                continue
            disc_times.append(disc)
            names = ",".join(s["name"] for s in servers) or "none"
            now = time.time()
            usable = [s for s in servers
                      if now - bad.get((s["ip"], s["port"]), 0) > args.cooldown]
            if not usable:
                print("round %d | discovery %.2f ms | found %s | no usable server" % (i, disc, names), flush=True)
                fail += 1
                time.sleep(args.interval)
                continue
            target = usable[0]
            print("round %d | discovery %.2f ms | found %s" % (i, disc, names), end=" | ")

        rtt, resp = call_service(sock, target, i, args.timeout)
        if rtt is None:
            bad[(target["ip"], target["port"])] = time.time()
            fail += 1
            print("used %s %s:%d | no response" % (target["name"], target["ip"], target["port"]), flush=True)
        else:
            ok += 1
            rtts.append(rtt)
            print("used %s %s:%d | rtt %.2f ms | result %s" % (target["name"], target["ip"], target["port"], rtt, resp.get("result")), flush=True)
        rows.append((i, target["name"], "" if disc is None else "%.3f" % disc, "" if rtt is None else "%.3f" % rtt))
        time.sleep(args.interval)

    print("SUMMARY ok=%d fail=%d avg_discovery_ms=%s avg_rtt_ms=%s" % (ok, fail, average(disc_times), average(rtts)), flush=True)

    if args.csv:
        with open(args.csv, "a") as f:
            for row in rows:
                f.write(",".join(str(x) for x in row) + "\n")


if __name__ == "__main__":
    main()
