import json
import socket

REGISTRY_PORT = 5000
CONTROL_PORT = 5001
SERVICE_PORT = 7000
HEARTBEAT_INTERVAL = 2
SERVICE_TIMEOUT = 6
BUFFER_SIZE = 4096


def pack(**fields):
    return json.dumps(fields).encode()


def unpack(data):
    try:
        msg = json.loads(data.decode())
    except (ValueError, UnicodeDecodeError):
        return None
    if isinstance(msg, dict) and "type" in msg:
        return msg
    return None


def make_socket(ip="0.0.0.0", port=0, broadcast=False):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if broadcast:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind((ip, port))
    return sock
