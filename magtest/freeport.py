"""Pick a port that is free for both TCP and UDP on 127.0.0.1.

libtorrent listens with TCP and with uTP (UDP) on the same port number, and a
session that cannot listen at all makes no outgoing connections either. On
Windows neither a fixed port nor port 0 is safe:

- Windows reserves blocks of ports for Hyper-V, WSL and Docker, separately
  for TCP and UDP, and the blocks move at every restart. List them with
  netsh int ipv4 show excludedportrange protocol=tcp (or protocol=udp).
- Port 0 only finds a free TCP port, and Windows hands those out almost in
  sequence, so retrying after a reserved UDP port tends to walk through the
  rest of the same reserved block.

So: random ports, each kept only if a TCP and a UDP socket can both bind it.
"""
import random
import socket


def free_tcp_udp_port(host='127.0.0.1', tries=200):
    for _ in range(tries):
        port = random.randint(49152, 65535)
        socks = []
        try:
            for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
                s = socket.socket(socket.AF_INET, kind)
                socks.append(s)
                s.bind((host, port))
            return port
        except OSError:
            continue
        finally:
            for s in socks:
                s.close()
    raise RuntimeError('no port free for both TCP and UDP on %s' % host)
