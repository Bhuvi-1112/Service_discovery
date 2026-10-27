import os
import socket
import subprocess
import sys
import time

from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import OVSKernelSwitch, RemoteController

BASE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(BASE, "logs")
CONTROLLER_IP = "127.0.0.1"
CONTROLLER_PORT = 6653
REGISTRY_IP = "10.0.0.1"
NOTIFY_IP = "10.0.0.255"

SERVERS = [
    ("sv1", "10.0.0.21", "echo"),
    ("sv2", "10.0.0.22", "echo"),
    ("sv3", "10.0.0.23", "time"),
]
ROGUE = ("rogue", "10.0.0.99", "echo")


def check_controller():
    s = socket.socket()
    s.settimeout(2)
    try:
        s.connect((CONTROLLER_IP, CONTROLLER_PORT))
    except OSError:
        print("Controller is not running on port %d. Start it first with ./run_controller.sh" % CONTROLLER_PORT)
        sys.exit(1)
    finally:
        s.close()


def build():
    net = Mininet(controller=None, switch=OVSKernelSwitch, link=TCLink, autoSetMacs=True)
    net.addController("c0", controller=RemoteController, ip=CONTROLLER_IP, port=CONTROLLER_PORT)
    s1 = net.addSwitch("s1", protocols="OpenFlow13")
    s2 = net.addSwitch("s2", protocols="OpenFlow13")
    s3 = net.addSwitch("s3", protocols="OpenFlow13")
    net.addLink(s2, s1, delay="2ms")
    net.addLink(s3, s1, delay="2ms")
    reg = net.addHost("reg", ip=REGISTRY_IP + "/24")
    c1 = net.addHost("c1", ip="10.0.0.11/24")
    c2 = net.addHost("c2", ip="10.0.0.12/24")
    for h in (reg, c1, c2):
        net.addLink(h, s2)
    for name, ip, service in SERVERS + [ROGUE]:
        net.addLink(net.addHost(name, ip=ip + "/24"), s3)
    return net


def wait_ready(net):
    if hasattr(net, "waitConnected"):
        net.waitConnected(timeout=15)
    else:
        time.sleep(3)
    time.sleep(1)


def start_registry(net):
    cmd = "python3 -u %s/registry.py --notify %s > %s/registry.log 2>&1 &" % (BASE, NOTIFY_IP, LOGS)
    net.get("reg").cmd(cmd)


def start_server(net, name, service, register=True):
    flag = "" if register else " --no-register"
    cmd = "python3 -u %s/server.py --name %s --service %s --registry %s%s > %s/%s.log 2>&1 &" % (
        BASE, name, service, REGISTRY_IP, flag, LOGS, name)
    net.get(name).cmd(cmd)


def start_services(net):
    os.makedirs(LOGS, exist_ok=True)
    start_registry(net)
    time.sleep(1)
    for name, ip, service in SERVERS:
        start_server(net, name, service)
    start_server(net, ROGUE[0], ROGUE[2], register=False)


def stop_services():
    subprocess.run(["pkill", "-f", "python3 -u %s/" % BASE])


def main():
    setLogLevel("info")
    check_controller()
    net = build()
    net.start()
    wait_ready(net)
    start_services(net)
    print("")
    print("Registry on reg (10.0.0.1), servers sv1 sv2 sv3 registered, rogue (10.0.0.99) is NOT registered")
    print("Clients: c1, c2.  Example:  c1 python3 client.py --count 5")
    print("Logs are in the logs/ folder")
    print("")
    CLI(net)
    stop_services()
    net.stop()


if __name__ == "__main__":
    main()
