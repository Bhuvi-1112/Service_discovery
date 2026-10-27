# Service Discovery System (UDP + SDN)

Computer Networks mini project (SDN - Socket Programming), project 21.

Servers advertise themselves to a registry over UDP. Clients ask the registry for a service and get back the servers that are alive. A Ryu SDN controller only lets service traffic reach servers that are registered, and the registry tells the controller whenever a server joins or disappears.

## Team and contributions

| Name | SRN | Contribution |
|------|-----|--------------|
| Aditya Jain | PES1UG25CS035 | client.py (discovery and latency measurement), common.py, README, .gitignore |
| Bhuvana H | PES1UG26CS811 | registry.py (service registry, timeouts, controller notifications), server.py (advertisements and service handling) |
| Akash Balaram Lamani | PES1UG25CS043 | controller.py (Ryu SDN controller), topo.py (Mininet topology), tests.py (automatic tests) |

## Files

| File | What it does |
|------|--------------|
| registry.py | UDP registry. Takes adverts, answers client queries, removes servers that stop sending heartbeats, tells the controller to ALLOW/BLOCK |
| server.py | Service server. Sends REGISTER and HEARTBEAT adverts, answers requests on UDP 7000 |
| client.py | Client. Asks the registry (measures discovery latency), then calls the server it got |
| controller.py | Ryu OpenFlow 1.3 controller (learning switch + service filter) |
| topo.py | Mininet topology, starts the registry and servers, opens the Mininet CLI |
| tests.py | Automatic test run (8 checks) |
| common.py | Ports and message helpers |
| setup.sh, run_controller.sh | Original helper scripts (not used, see Setup) |

## Requirements

Ubuntu 20.04 or 22.04 VM with sudo and internet (setup installs Python 3.9 for Ryu in a virtual environment).

## Setup (one time)

Ryu does not work with the default Python 3.10 on Ubuntu 22.04 (eventlet crashes), so it is installed in a Python 3.9 virtual environment. Mininet and the rest use the normal system Python.

    sudo apt update
    sudo apt install -y mininet openvswitch-switch python3-pip software-properties-common
    sudo add-apt-repository -y ppa:deadsnakes/ppa
    sudo apt update
    sudo apt install -y python3.9 python3.9-venv
    python3.9 -m venv ~/ryu-env
    ~/ryu-env/bin/pip install "setuptools==67.6.1" wheel
    ~/ryu-env/bin/pip install "eventlet==0.30.2" ryu
    ~/ryu-env/bin/pip install --force-reinstall "eventlet==0.30.2"

(Do not use `./setup.sh` or `./run_controller.sh`, they install and start Ryu with the system Python.)

## Run

Open two terminals in the project folder (the one that contains controller.py).

Important: run `sudo mn -c` BEFORE starting the controller. It kills every ryu-manager process, so running it while the controller is up stops the controller.

Terminal 1 (cleanup, then controller):

    sudo mn -c
    ~/ryu-env/bin/ryu-manager --ofp-tcp-listen-port 6653 controller.py

Terminal 2 (network, start it after the controller is running):

    sudo python3 topo.py

This starts the registry and servers sv1, sv2, sv3. Wait about 5 seconds and you get the `mininet>` prompt. The controller terminal prints "switch s1 connected" for each switch.

To run again after exiting Mininet, stop the controller with Ctrl+C, run `sudo mn -c`, and start the controller again.

## Automatic tests

Type `exit` first if a Mininet session from `topo.py` is still open, because `tests.py` builds its own network.

Run `sudo mn -c` first, then start the controller in terminal 1 as above, then in terminal 2:

    sudo python3 tests.py

Do not run `sudo mn -c` while the controller is running. It prints PASS or FAIL for discovery, service lookup, blocking of an unregistered server, dynamic registration, failure detection, blocking of a failed server and recovery (8 checks, about a minute).

## Topology

    reg, c1, c2 --- s2 --- s1 --- s3 --- sv1, sv2, sv3, rogue
                           |
                       controller (127.0.0.1:6653)

Links between switches have 2 ms delay.

## Troubleshooting

- `Controller is not running`: start the controller in terminal 1 first.
- `TypeError: cannot set 'is_timeout' attribute`: ryu-manager from the system Python was used. Use `~/ryu-env/bin/ryu-manager` as shown above.
- `Controller is not running` right after you started it: `sudo mn -c` was run after the controller started and killed it. Run `sudo mn -c` first, then start the controller.
- Old Mininet state: run `sudo mn -c` before starting the controller.
- Nothing is discovered right after start: wait 5 seconds, servers need one heartbeat.
