"""Minimal systemd readiness notification; no graphics or network imports."""
import os
import socket


def notify_ready():
    address=os.environ.get('NOTIFY_SOCKET')
    if not address:return
    if address.startswith('@'):address='\0'+address[1:]
    with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as channel:
        channel.connect(address)
        channel.sendall(b'READY=1\nSTATUS=HondaLink Bluetooth profiles registered')
