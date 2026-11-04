"""Acceptance-only guard: deny Python socket connections outside loopback.

Loaded only when explicitly placed on PYTHONPATH by the offline acceptance runner.
This is not an OS firewall and is not part of the shipping application.
"""

import ipaddress
import socket

_connect = socket.socket.connect
_connect_ex = socket.socket.connect_ex


def _allowed(address):
    if not isinstance(address, tuple):
        return True
    try:
        return ipaddress.ip_address(address[0]).is_loopback
    except ValueError:
        return address[0] == "localhost"


def _guarded_connect(self, address):
    if not _allowed(address):
        raise OSError("M1 offline acceptance: non-loopback connection denied")
    return _connect(self, address)


def _guarded_connect_ex(self, address):
    if not _allowed(address):
        return 10013
    return _connect_ex(self, address)


socket.socket.connect = _guarded_connect
socket.socket.connect_ex = _guarded_connect_ex
