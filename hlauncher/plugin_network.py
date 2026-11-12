"""Compatibility helper for the SDK’s configured TCP connection."""

from array import array
import ipaddress
import re
import socket
import threading
import time


def parse_endpoint(value):
    host, separator, port = value.rpartition(':')
    if not separator or not re.fullmatch(r'[0-9]{1,5}', port) or not 1 <= int(port) <= 65535:
        raise ValueError('Enter a numeric IP address and TCP port')
    try:
        address = ipaddress.ip_address(host.strip('[]'))
    except ValueError as exc:
        raise ValueError('Enter a numeric IP address and TCP port') from exc
    if address.is_unspecified or address.is_multicast:
        raise ValueError('Choose a specific unicast IP address')
    return str(address), int(port)


class Network:
    def __init__(self, endpoint):
        self.endpoint = parse_endpoint(endpoint)
        try:
            self.host, self.child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        except OSError:
            self.host, self.child = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.host.settimeout(.5)
        self.closed = threading.Event()

    def start(self):
        self.child.close()
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        last_attempt = 0
        with self.host:
            while not self.closed.is_set():
                try:
                    request = self.host.recv(16)
                except TimeoutError:
                    continue
                except OSError:
                    return
                if not request:
                    return
                if request != b'connect' or time.monotonic() - last_attempt < 1:
                    return
                last_attempt = time.monotonic()
                try:
                    with socket.create_connection(self.endpoint, timeout=2) as connection:
                        if self.closed.is_set():
                            return
                        connection.setblocking(True)
                        rights = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array('i', [connection.fileno()]))]
                        self.host.sendmsg([b'+'], rights)
                except OSError:
                    try:
                        self.host.send(b'-')
                    except OSError:
                        return

    def close(self):
        self.closed.set()
        self.child.close()
        self.host.close()
