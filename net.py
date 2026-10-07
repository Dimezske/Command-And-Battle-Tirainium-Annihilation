"""
net.py
======
Minimal TCP networking for multiplayer (1 host + up to 7 clients).

Design: simple client-server model, NOT peer-to-peer lockstep.
  * The Host runs the one authoritative game simulation for both players.
  * The Client is a "thin client": it sends the local player's clicks as
    small command messages, and renders whatever state the Host broadcasts.

This avoids desync entirely (only one side ever simulates physics/combat)
at the cost of the client's view lagging the host by a network round trip
(a non-issue on a LAN / localhost).

Wire format: newline-delimited JSON over a plain TCP socket. All socket
I/O happens on background daemon threads that only touch a thread-safe
queue.Queue, so the pygame main loop never blocks.
"""

import socket
import threading
import queue
import json

DEFAULT_PORT = 5555


def get_local_ip():
    """Best-effort guess at this machine's LAN IP, without needing internet
    access (UDP 'connect' just picks a route, it sends nothing)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def parse_address(text, default_port=DEFAULT_PORT):
    text = text.strip()
    if ":" in text:
        ip, port_s = text.rsplit(":", 1)
        try:
            return ip, int(port_s)
        except ValueError:
            return ip, default_port
    return text, default_port


class Connection:
    """Wraps one connected TCP socket with a background reader thread."""

    def __init__(self, sock):
        self.sock = sock
        self.inbox = queue.Queue()
        self.alive = True
        self._buf = b""
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self):
        try:
            while self.alive:
                data = self.sock.recv(65536)
                if not data:
                    break
                self._buf += data
                while b"\n" in self._buf:
                    line, self._buf = self._buf.split(b"\n", 1)
                    if line:
                        try:
                            self.inbox.put(json.loads(line.decode("utf-8")))
                        except Exception:
                            pass
        except Exception:
            pass
        finally:
            self.alive = False

    def send(self, msg):
        if not self.alive:
            return
        try:
            data = (json.dumps(msg) + "\n").encode("utf-8")
            with self._lock:
                self.sock.sendall(data)
        except Exception:
            self.alive = False

    def poll(self):
        msgs = []
        while True:
            try:
                msgs.append(self.inbox.get_nowait())
            except queue.Empty:
                break
        return msgs

    def close(self):
        self.alive = False
        try:
            self.sock.close()
        except Exception:
            pass


class Host:
    """Listens for up to `max_clients` incoming connections (lobby + match).

    Every connection gets a numeric id (cid). poll() returns (cid, message)
    pairs so the game knows which player a command came from, send() is a
    broadcast and send_to() addresses one client."""

    def __init__(self, port=DEFAULT_PORT, max_clients=7):
        self.port = port
        self.max_clients = max_clients
        self.conns = {}               # cid -> Connection
        self._next_cid = 1
        self._new = []                # cids accepted but not yet reported
        self._reported_dead = set()
        self._lock = threading.Lock()
        self.error = None
        self.server_sock = None
        self.accepting = True
        try:
            self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_sock.bind(("0.0.0.0", port))
            self.server_sock.listen(8)
            self.server_sock.settimeout(0.4)
        except Exception as e:
            self.error = str(e)
            self.server_sock = None
            return
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def _accept_loop(self):
        while self.accepting and self.server_sock is not None:
            try:
                client_sock, _addr = self.server_sock.accept()
            except socket.timeout:
                continue
            except Exception:
                break
            with self._lock:
                alive = sum(1 for c in self.conns.values() if c.alive)
                if alive >= self.max_clients or not self.accepting:
                    try:
                        client_sock.close()
                    except Exception:
                        pass
                    continue
                cid = self._next_cid
                self._next_cid += 1
                self.conns[cid] = Connection(client_sock)
                self._new.append(cid)

    # ---- queries --------------------------------------------------------
    @property
    def connected(self):
        return any(c.alive for c in list(self.conns.values()))

    @property
    def client_ids(self):
        return [cid for cid, c in list(self.conns.items()) if c.alive]

    def new_connections(self):
        with self._lock:
            out, self._new = self._new, []
        return out

    def dropped(self):
        """cids whose connection died since the last call."""
        out = []
        for cid, c in list(self.conns.items()):
            if not c.alive and cid not in self._reported_dead:
                self._reported_dead.add(cid)
                out.append(cid)
        return out

    # ---- I/O --------------------------------------------------------------
    def send(self, msg):
        for c in list(self.conns.values()):
            c.send(msg)

    def send_to(self, cid, msg):
        c = self.conns.get(cid)
        if c:
            c.send(msg)

    def poll(self):
        out = []
        for cid, c in list(self.conns.items()):
            for m in c.poll():
                out.append((cid, m))
        return out

    def stop_accepting(self):
        self.accepting = False

    def close(self):
        self.accepting = False
        for c in list(self.conns.values()):
            c.close()
        if self.server_sock:
            try:
                self.server_sock.close()
            except Exception:
                pass
            self.server_sock = None


class Client:
    """Connects to a Host. The connection attempt runs on a background
    thread so the UI stays responsive while waiting."""

    def __init__(self, ip, port=DEFAULT_PORT):
        self.ip = ip
        self.port = port
        self.conn = None
        self.error = None
        self.connecting = True
        self._thread = threading.Thread(target=self._connect, daemon=True)
        self._thread.start()

    def _connect(self):
        try:
            sock = socket.create_connection((self.ip, self.port), timeout=6.0)
            self.conn = Connection(sock)
        except Exception as e:
            self.error = str(e)
        finally:
            self.connecting = False

    @property
    def connected(self):
        return self.conn is not None and self.conn.alive

    def send(self, msg):
        if self.conn:
            self.conn.send(msg)

    def poll(self):
        return self.conn.poll() if self.conn else []

    def close(self):
        if self.conn:
            self.conn.close()
