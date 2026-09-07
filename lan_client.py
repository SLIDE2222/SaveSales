"""Background UI adapter. Opening the desktop also starts its embedded LAN peer."""
import json
import logging
import queue
import threading
import time
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
from server import PeerNode


class RequestFailure(str):
    """Keep rejection certainty with the queued result, not mutable link status."""
    def __new__(cls, message, definitive=False):
        value = super().__new__(cls, message)
        value.definitive = definitive
        return value


class LanClient:
    def __init__(self, **node_options):
        self.commands = queue.Queue()
        self.results = queue.Queue()
        self.stopped = threading.Event()
        self.node = None
        self.node_options = node_options
        self.url = None
        self.state_digest = None
        self.connected = False
        self.http = build_opener(ProxyHandler({}))
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def submit(self, method, path, data=None, password=None, callback=None):
        # Do not silently queue offline clock events for later execution.
        if not self.connected:
            self.results.put(('offline', RequestFailure('No SaveSales LAN connection. Wait for LAN synced, then try again.'), callback))
            return
        self.commands.put((method, path, data, password, callback))

    def request(self, method, path, data=None, password=None):
        headers = {'Content-Type': 'application/json'}
        if password is not None:
            headers['X-Admin-Password'] = password
        req = Request(self.url + path, method=method, headers=headers,
                      data=json.dumps(data).encode() if data is not None else None)
        with self.http.open(req, timeout=8) as response:
            return json.load(response)

    def run(self):
        try:
            # Initialization, SQLite migration, service and elections never run on Tk.
            self.node = PeerNode(**self.node_options)
            next_poll = 0
            while not self.stopped.is_set():
                try:
                    command = self.commands.get(timeout=.15)
                except queue.Empty:
                    command = None
                if command is None and time.monotonic() < next_poll:
                    continue
                method, path, data, password, callback = command or ('GET','/state',None,None,None)
                try:
                    self.url = self.node.coordinator_url()
                    if not self.url:
                        raise OSError(self.node.error or 'LAN discovery, election or synchronization in progress')
                    request_path = path + '?digest=' + self.state_digest if path == '/state' and self.state_digest else path
                    result = self.request(method, request_path, data, password)
                    if 'employees' in result:
                        self.state_digest = result.get('digest')
                    self.connected = True
                    self.results.put(('ok',result,callback))
                    next_poll = time.monotonic() + (0 if command else 2)
                except HTTPError as exc:
                    try:
                        error = json.load(exc).get('error',str(exc))
                    except (ValueError, AttributeError):
                        error = str(exc)
                    self.connected = exc.code < 500
                    self.results.put(('error' if self.connected else 'offline', RequestFailure(error, definitive=400 <= exc.code < 500),callback))
                    next_poll = time.monotonic()+1
                except (OSError, ValueError, TypeError) as exc:
                    self.connected = False
                    message = str(exc)
                    if command:
                        message += '. If a write was sent, its result may be unknown; check the shared state after reconnection before retrying.'
                    self.results.put(('offline',RequestFailure(message),callback))
                    next_poll = time.monotonic()+1
        except Exception as exc:
            logging.getLogger('savesales').exception('Unable to start SaveSales LAN service')
            self.results.put(('startup_error',f'Unable to start SaveSales LAN service: {exc}. Check that SaveSales is not already open on this PC.',None))
        finally:
            self.connected = False
            if self.node:
                self.node.close()

    def close(self):
        self.stopped.set()
