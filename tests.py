import os
import re
import subprocess
import sys
import time

from mininet.log import setLogLevel

import topo


def run_client(host, extra):
    return host.cmd("python3 -u %s/client.py %s" % (topo.BASE, extra))


def parse(out):
    m = re.search(r"SUMMARY ok=(\d+) fail=(\d+) avg_discovery_ms=(\S+)", out)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), m.group(3)


def registry_log():
    with open(os.path.join(topo.LOGS, "registry.log")) as f:
        return f.read()


def kill_server(name, sig="-TERM"):
    subprocess.run(["pkill", sig, "-f", "server.py --name %s " % name])


results = []


def check(name, passed, detail):
    results.append(passed)
    print("[%s] %s - %s" % ("PASS" if passed else "FAIL", name, detail), flush=True)


def run_all(net):
    c1 = net.get("c1")
    c2 = net.get("c2")

    out = run_client(c1, "--count 5 --interval 0.2")
    res = parse(out)
    check("discovery", res is not None and res[0] == 5, "5/5 requests ok, avg discovery %s ms" % (res[2] if res else "n/a"))

    out = run_client(c2, "--service time --count 2 --interval 0.2")
    check("service type lookup", "used sv3" in out and "used sv1" not in out, "time service resolved to sv3")

    out = run_client(c1, "--direct 10.0.0.99:7000 --count 3 --timeout 0.5 --interval 0.1")
    res = parse(out)
    check("unregistered server blocked", res is not None and res[0] == 0, "0/3 packets reached rogue (10.0.0.99)")

    out = run_client(c1, "--direct 10.0.0.21:7000 --count 3 --timeout 0.5 --interval 0.1")
    res = parse(out)
    check("registered server reachable", res is not None and res[0] == 3, "3/3 direct requests to sv1 ok")

    kill_server("rogue")
    topo.start_server(net, "rogue", "echo", register=True)
    time.sleep(3)
    out = run_client(c1, "--direct 10.0.0.99:7000 --count 3 --timeout 0.5 --interval 0.1")
    res = parse(out)
    out2 = run_client(c1, "--count 2 --interval 0.2")
    check("dynamic registration", res is not None and res[0] == 3 and "rogue" in out2,
          "rogue registered at runtime, now reachable and listed")

    t0 = time.time()
    kill_server("sv1", "-KILL")
    detected = None
    while time.time() - t0 < 15:
        if "TIMEOUT sv1" in registry_log():
            detected = time.time() - t0
            break
        time.sleep(0.2)
    time.sleep(1)
    out = run_client(c1, "--count 4 --interval 0.3")
    res = parse(out)
    out2 = run_client(c1, "--direct 10.0.0.21:7000 --count 3 --timeout 0.5 --interval 0.1")
    res2 = parse(out2)
    check("server failure detected", detected is not None and "sv1" not in out and res is not None and res[0] == 4,
          "sv1 timed out after %s s, removed from lookups" % ("%.1f" % detected if detected else "n/a"))
    check("failed server blocked", res2 is not None and res2[0] == 0, "traffic to crashed sv1 dropped by switches")

    topo.start_server(net, "sv1", "echo", register=True)
    time.sleep(3)
    out = run_client(c1, "--count 2 --interval 0.2")
    out2 = run_client(c1, "--direct 10.0.0.21:7000 --count 3 --timeout 0.5 --interval 0.1")
    res2 = parse(out2)
    check("server recovery", "sv1" in out and res2 is not None and res2[0] == 3, "sv1 re-registered and reachable again")


def main():
    setLogLevel("warning")
    topo.check_controller()
    net = topo.build()
    net.start()
    topo.wait_ready(net)
    topo.start_services(net)
    time.sleep(5)
    try:
        run_all(net)
    finally:
        topo.stop_services()
        net.stop()
    print("")
    print("%d of %d tests passed" % (sum(results), len(results)))
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
