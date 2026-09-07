"""Embedded SaveSales peer service, SQLite journal, discovery and reconciliation.

This is availability-oriented LAN coordination, not quorum consensus. A partition
can temporarily elect two coordinators; immutable operations merge deterministically
on reunion. Never replace a replica with an older whole-state snapshot.
"""
import copy
import commerce
from contextlib import contextmanager
import hashlib
import ipaddress
import psutil
import json
import logging
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import sys
import threading
import time
import uuid
from datetime import datetime
from urllib.request import Request, build_opener, ProxyHandler

from flask import Flask, jsonify, request
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.serving import make_server

SERVICE = 'SaveSales-peer-v3'
DISCOVERY_PORT = 54545
log = logging.getLogger('savesales')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def data_directory():
    # Writable and outside OneDrive; also works in a one-file PyInstaller build.
    return Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local' / 'share')) / 'SaveSales'


def source_directory():
    return Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent


def discovery_targets(port):
    """Broadcast on every active IPv4 interface, not just the VPN/default route."""
    result = {('255.255.255.255', port), ('127.0.0.1', port)}
    stats = psutil.net_if_stats()
    for name, addresses in psutil.net_if_addrs().items():
        if name not in stats or not stats[name].isup:
            continue
        for address in addresses:
            if address.family != socket.AF_INET or not address.netmask:
                continue
            try:
                interface = ipaddress.IPv4Interface(address.address + '/' + address.netmask)
                if not interface.ip.is_loopback and interface.network.prefixlen < 31:
                    result.add((str(interface.network.broadcast_address), port))
            except ValueError:
                continue
    return sorted(result)


class Store:
    """One local SQLite database per PC, durable union of immutable operations."""
    def __init__(self, directory, legacy_directory=None, password=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'savesales.sqlite3'
        self.legacy_directory = Path(legacy_directory or directory)
        self.password = password if password is not None else os.environ.get('SAVESALES_ADMIN_PASSWORD', 'admin')
        self.lock = threading.RLock()
        self._cache = None
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
            db.execute('INSERT OR IGNORE INTO metadata VALUES (?, ?)', ('node_id', str(uuid.uuid4())))
            self.node_id = db.execute("SELECT value FROM metadata WHERE key='node_id'").fetchone()[0]
            commerce.initialize(db)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db:
                yield db
        finally:
            db.close()

    def events(self):
        with self.lock, self.connection() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT body FROM events ORDER BY id')]

    @staticmethod
    def validate(event):
        if not isinstance(event, dict) or not isinstance(event.get('id'), str) or not 1 <= len(event['id']) <= 100:
            raise ValueError('Invalid journal ID')
        if type(event.get('clock')) is not int or not 0 <= event['clock'] < 2**53:
            raise ValueError('Invalid journal clock')
        if event.get('kind') in ('item_add','item_delete','sale_save','sale_delete'):
            commerce.validate_event(event)
            return
        if event.get('kind') == 'config':
            if not isinstance(event.get('password_hash'), str) or len(event['password_hash']) > 500:
                raise ValueError('Invalid admin configuration')
            return
        if event.get('kind') == 'currency':
            if event.get('currency') not in commerce.CURRENCIES:
                raise ValueError('Invalid store currency')
            return
        if event.get('kind') not in ('add', 'delete', 'time', 'time_edit', 'attendance_status'):
            raise ValueError('Invalid journal action')
        if not isinstance(event.get('name'), str) or not 1 <= len(event['name']) <= 200:
            raise ValueError('Invalid employee name')
        if event['kind'] == 'delete':
            if not isinstance(event.get('generations'), list) or not all(isinstance(g, str) for g in event['generations']):
                raise ValueError('Invalid deletion')
        if event['kind'] == 'time':
            if not isinstance(event.get('generation'), str) or event.get('action') not in ('clock_in','break_in','break_out','clock_out'):
                raise ValueError('Invalid time event')
            datetime.strptime(event['date'], '%Y-%m-%d')
            datetime.strptime(event['time'], '%H:%M:%S')
        if event['kind'] == 'time_edit':
            if not isinstance(event.get('generation'), str):
                raise ValueError('Invalid time correction')
            datetime.strptime(event['date'], '%Y-%m-%d')
            values = event.get('values')
            keys = ('clock_in','break_in','break_out','clock_out')
            if not isinstance(values, dict) or set(values) != set(keys):
                raise ValueError('Invalid corrected punch data')
            parsed = {}
            for key in keys:
                value = values[key]
                if value is None:
                    continue
                if not isinstance(value, str):
                    raise ValueError('Invalid corrected punch time')
                parsed[key] = datetime.strptime(value, '%H:%M:%S').time()
            if 'clock_in' not in parsed and parsed:
                raise ValueError('Clock In is required when other punches are present')
            if 'break_out' in parsed and 'break_in' not in parsed:
                raise ValueError('Lunch Break In is required before Lunch Break Out')
            if 'break_in' in parsed and 'clock_out' in parsed and 'break_out' not in parsed:
                raise ValueError('Lunch Break Out is required before Clock Out')
            sequence = [parsed[k] for k in keys if k in parsed]
            if any(a > b for a, b in zip(sequence, sequence[1:])):
                raise ValueError('Punch times must be in chronological order')
        if event['kind'] == 'attendance_status':
            if not isinstance(event.get('generation'), str):
                raise ValueError('Invalid attendance status')
            datetime.strptime(event['date'], '%Y-%m-%d')
            if event.get('status') not in ('no_show', 'sick_leave', 'clear'):
                raise ValueError('Invalid attendance status')

    def merge(self, incoming):
        if not isinstance(incoming, list):
            raise ValueError('Invalid replica journal')
        for event in incoming:
            self.validate(event)
        with self.lock, self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = False
            for event in incoming:
                body = canonical(event)
                old = db.execute('SELECT body FROM events WHERE id=?', (event['id'],)).fetchone()
                if old and old[0] != body:
                    raise ValueError('Conflicting journal ID; original data retained')
                if not old:
                    db.execute('INSERT INTO events VALUES (?, ?)', (event['id'], body))
                    commerce.project(db,event)
                    changed = True
            db.commit()
            if changed:
                self._cache = None

    def bootstrap(self):
        """Import only if discovery/synchronization did not find an existing journal."""
        with self.lock:
            if self.events():
                return
            folder = self.legacy_directory
            shared = folder / 'savesales_shared.json'
            def read(name, default):
                path = folder / name
                return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else default
            if shared.exists():
                data = read('savesales_shared.json', {})
            else:
                data = {'employees': read('employees.json', []), 'employee_times': read('employee_times.json', {})}
            names, history = data.get('employees'), data.get('employee_times')
            if not isinstance(names, list) or not isinstance(history, dict) or not all(isinstance(n,str) and n.strip() for n in names):
                raise ValueError('Invalid legacy JSON. Original files were not modified.')
            operations = [
                {'id': str(uuid.uuid4()), 'clock': 0, 'kind': 'config',
                 'password_hash': generate_password_hash(self.password)},
                {'id': str(uuid.uuid4()), 'clock': 0, 'kind': 'currency',
                 'currency': commerce.DEFAULT_CURRENCY},
            ]
            for name in dict.fromkeys(names + list(history)):
                generation = 'legacy-' + hashlib.sha256(name.encode()).hexdigest()
                operations.append(dict(id=generation, clock=1, kind='add', name=name))
                days = history.get(name, {})
                if not isinstance(days, dict):
                    raise ValueError('Invalid legacy history')
                for date, values in days.items():
                    if not isinstance(values, dict):
                        raise ValueError('Invalid legacy time record')
                    for index, action in enumerate(('clock_in','break_in','break_out','clock_out'), 2):
                        if action in values:
                            event = dict(clock=index, kind='time', name=name, generation=generation,
                                         date=date, action=action, time=values[action])
                            event['id'] = hashlib.sha256(canonical(event).encode()).hexdigest()
                            operations.append(event)
            self.merge(operations)

    def snapshot(self):
        with self.lock:
            if self._cache is not None:
                return copy.deepcopy(self._cache)
            events = self.events()
            ordered = sorted(events, key=lambda e: (e['clock'], e['id']))
            adds = {e['id']: e for e in ordered if e['kind'] == 'add'}
            removed = {g for e in ordered if e['kind'] == 'delete' for g in e['generations']}
            names = {}
            for generation, event in adds.items():
                if generation not in removed:
                    names.setdefault(event['name'], []).append(generation)
            history, attendance, conflicts = {}, {}, []
            for event in ordered:
                if event['kind'] not in ('time', 'time_edit', 'attendance_status'):
                    continue
                generation = event['generation']
                if generation in removed:
                    continue  # A deleted employee's records can never resurrect it.
                if generation not in adds or adds[generation]['name'] != event['name']:
                    conflicts.append(dict(event, reason='Employee identity is unavailable'))
                    continue
                if event['kind'] == 'attendance_status':
                    employee_days = attendance.setdefault(event['name'], {})
                    if event['status'] == 'clear':
                        employee_days.pop(event['date'], None)
                    else:
                        employee_days[event['date']] = event['status']
                    continue
                if event['kind'] == 'time_edit':
                    corrected = {key: value for key, value in event['values'].items() if value is not None}
                    history.setdefault(event['name'], {})[event['date']] = corrected
                    continue
                day = history.setdefault(event['name'], {}).setdefault(event['date'], {})
                action = event['action']
                reason = self.transition_error(day, action)
                if action in day or reason:
                    if day.get(action) != event['time']:
                        conflicts.append(dict(event, reason='Conflicting time event'))
                    continue
                day[action] = event['time']
            currency_events=[e for e in ordered if e.get('kind')=='currency']
            currency=currency_events[-1]['currency'] if currency_events else commerce.DEFAULT_CURRENCY
            digest = hashlib.sha256(canonical(events).encode()).hexdigest()
            with self.connection() as db:
                shop = commerce.snapshot(db)
            self._cache = dict(**shop, employees=list(names), employee_times=history,
                               employee_attendance=attendance, employee_ids=names, currency=currency,
                               revision=len(events), digest=digest, conflicts=conflicts)
            return copy.deepcopy(self._cache)

    @staticmethod
    def transition_error(day, action):
        if action in day:
            return None
        if action != 'clock_in' and 'clock_in' not in day:
            return 'Clock in first'
        if 'clock_out' in day:
            return 'Shift already completed'
        if action == 'break_out' and 'break_in' not in day:
            return 'Start lunch first'
        if action == 'clock_out' and 'break_in' in day and 'break_out' not in day:
            return 'End lunch before clocking out'
        return None

    def authorized(self, password):
        configs = sorted((e for e in self.events() if e['kind'] == 'config'), key=lambda e: e['id'])
        return bool(configs) and check_password_hash(configs[0]['password_hash'], password or '')

    def command(self, method, path, payload, password=None):
        with self.lock:
            if path in ('/items','/sales'):
                return commerce.command(self,method,path,payload,password)
            if path == '/settings/currency':
                if not self.authorized(password):
                    raise PermissionError('Incorrect admin password')
                if method != 'POST' or not isinstance(payload, dict):
                    raise ValueError('Invalid currency request')
                code=payload.get('currency')
                if code not in commerce.CURRENCIES:
                    raise ValueError('Unsupported currency')
                state=self.snapshot()
                if state.get('currency', commerce.DEFAULT_CURRENCY)==code:
                    return state
                event=dict(id=str(uuid.uuid4()),
                           clock=max((e['clock'] for e in self.events()), default=0)+1,
                           kind='currency', currency=code)
                self.merge([event])
                return self.snapshot()
            if path in ('/employees', '/admin/verify', '/time-events/edit', '/attendance-status') and not self.authorized(password):
                raise PermissionError('Incorrect admin password')
            if path == '/admin/verify':
                return {'ok': True}
            if not isinstance(payload, dict):
                raise ValueError('Invalid request')
            state = self.snapshot()
            name = payload.get('name') if path == '/employees' else payload.get('employee')
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 200:
                raise ValueError('Enter an employee name (1–200 characters)')
            name = name.strip()
            event = dict(id=str(uuid.uuid4()), clock=max((e['clock'] for e in self.events()), default=0)+1, name=name)
            ids = state['employee_ids'].get(name, [])
            if path == '/employees' and method == 'POST':
                if ids:
                    return state
                event['kind'] = 'add'
            else:
                expected = payload.get('employee_ids')
                if not ids or expected != ids:
                    raise ValueError('Employee changed or was deleted. Refresh and try again.')
                if path == '/employees' and method == 'DELETE':
                    event.update(kind='delete', generations=ids)
                elif path == '/time-events':
                    action = payload.get('action')
                    if action not in ('clock_in','break_in','break_out','clock_out'):
                        raise ValueError('Invalid time action')
                    now = datetime.now()
                    date = now.strftime('%Y-%m-%d')
                    if payload.get('date') != date:
                        raise ValueError('The date changed. Refresh and try again.')
                    day = state['employee_times'].get(name, {}).get(date, {})
                    attendance_status = state.get('employee_attendance', {}).get(name, {}).get(date)
                    if attendance_status in ('no_show', 'sick_leave'):
                        raise ValueError('This date is marked as No show or Sick leave. Ask an admin to clear the attendance status first.')
                    error = self.transition_error(day, action)
                    if error:
                        raise ValueError(error)
                    if action in day:
                        return state
                    event.update(kind='time', generation=ids[0], action=action, date=date, time=now.strftime('%H:%M:%S'))
                elif path == '/time-events/edit' and method == 'POST':
                    date = payload.get('date')
                    values = payload.get('values')
                    clear_attendance = payload.get('clear_attendance') is True
                    datetime.strptime(date, '%Y-%m-%d')
                    attendance_status = state.get('employee_attendance', {}).get(name, {}).get(date)
                    has_punches = isinstance(values, dict) and any(values.values())
                    if attendance_status in ('no_show', 'sick_leave') and has_punches and not clear_attendance:
                        raise ValueError('This date is marked as No show or Sick leave. Admin approval is required to override the absence.')

                    event.update(kind='time_edit', generation=ids[0], date=date, values=values)
                    self.validate(event)

                    if attendance_status in ('no_show', 'sick_leave') and has_punches and clear_attendance:
                        # One authorized command records both immutable events.  The
                        # absence is cleared and the corrected punches are saved atomically.
                        clear_event = dict(
                            id=str(uuid.uuid4()),
                            clock=event['clock'],
                            kind='attendance_status',
                            name=name,
                            generation=ids[0],
                            date=date,
                            status='clear',
                        )
                        event['clock'] += 1
                        self.validate(clear_event)
                        self.merge([clear_event, event])
                        return self.snapshot()
                elif path == '/attendance-status' and method == 'POST':
                    date = payload.get('date')
                    status = payload.get('status')
                    datetime.strptime(date, '%Y-%m-%d')
                    if status in ('no_show', 'sick_leave'):
                        day = state['employee_times'].get(name, {}).get(date, {})
                        if any(day.values()):
                            raise ValueError('This date already has punches. Remove the punches first, then mark No show or Sick leave.')
                    event.update(kind='attendance_status', generation=ids[0], date=date, status=status)
                    self.validate(event)
                else:
                    raise ValueError('Unknown command')
            self.merge([event])
            return self.snapshot()


class PeerNode:
    """All PCs run this identical embedded service; only the elected one orders writes."""
    def __init__(self, directory=None, legacy_directory=None, password=None,
                 bind_host='', discovery_port=DISCOVERY_PORT, targets=None,
                 heartbeat=1.0, expiry=6.0, settle=2.5):
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self.write_lock = threading.RLock()
        self.peers = {}
        self.heartbeat, self.expiry, self.settle = heartbeat, expiry, settle
        self.started = time.monotonic()
        self.candidate = None
        self.candidate_since = self.started
        self.ready = False
        self.error = None
        self.token = secrets.token_urlsafe(32)
        self.targets = targets
        self.discovery_port = discovery_port
        self.http_client = build_opener(ProxyHandler({}))
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            self.sock.bind((bind_host, discovery_port))
            self.sock.settimeout(.3)
            self.store = Store(directory or data_directory(), legacy_directory or source_directory(), password)
            self.node_id = self.store.node_id
            self.http = make_server(bind_host or '0.0.0.0', 0, self.create_app(), threaded=True)
        except BaseException:
            self.sock.close()
            raise
        self.url = f'http://{bind_host or "127.0.0.1"}:{self.http.server_port}'
        self.threads = [threading.Thread(target=self.http.serve_forever, daemon=True),
                        threading.Thread(target=self.receive, daemon=True),
                        threading.Thread(target=self.maintain, daemon=True)]
        for thread in self.threads:
            thread.start()

    def live_peers(self):
        with self.lock:
            now = time.monotonic()
            return {key: dict(value) for key,value in self.peers.items() if now-value['seen'] < self.expiry}

    def info(self):
        with self.lock:
            return dict(service=SERVICE, node_id=self.node_id, port=self.http.server_port,
                        leader=self.candidate, ready=self.ready, token=self.token,
                        digest=self.store.snapshot()['digest'])

    def send_hello(self):
        packet = canonical(dict(self.info(), kind='hello')).encode()
        for target in (self.targets if self.targets is not None else discovery_targets(self.discovery_port)):
            try:
                self.sock.sendto(packet, target)
            except OSError:
                pass

    def receive(self):
        while not self.stop_event.is_set():
            try:
                raw, address = self.sock.recvfrom(4096)
                data = json.loads(raw)
                if data.get('service') != SERVICE or data.get('node_id') == self.node_id:
                    continue
                if not isinstance(data.get('node_id'), str) or not isinstance(data.get('token'), str):
                    continue
                if type(data.get('port')) is not int or not 1 <= data['port'] <= 65535:
                    continue
                with self.lock:
                    self.peers[data['node_id']] = dict(data, url=f"http://{address[0]}:{data['port']}", seen=time.monotonic())
                    # Fence a former leader as soon as a higher-priority peer reappears.
                    if data['node_id'] < self.node_id:
                        self.ready = False
                if data.get('kind') == 'hello':
                    self.sock.sendto(canonical(dict(self.info(), kind='reply')).encode(), address)
            except (OSError, ValueError, AttributeError, TypeError):
                continue

    def request(self, peer, method, path, body=None):
        req = Request(peer['url']+path, method=method,
                      headers={'Content-Type':'application/json', 'X-Peer-Token':peer['token']},
                      data=canonical(body).encode() if body is not None else None)
        with self.http_client.open(req, timeout=1.2) as response:
            return json.load(response)

    def synchronize(self, peer):
        # Exchange IDs first so a new sale does not resend every product image.
        local = self.store.events()
        reply = self.request(peer, 'POST', '/replica', {
            'node_id': self.node_id, 'events': [], 'known_ids': [e['id'] for e in local]})
        self.store.merge(reply['events'])
        remote_ids = set(reply['known_ids'])
        local = self.store.events()
        missing = [event for event in local if event['id'] not in remote_ids]
        if missing:
            reply = self.request(peer, 'POST', '/replica', {
                'node_id': self.node_id, 'events': missing, 'known_ids': [e['id'] for e in local]})
            self.store.merge(reply['events'])
        return True

    def maintain(self):
        while not self.stop_event.is_set():
            try:
                self.send_hello()
                live = self.live_peers()
                synchronized = True
                for peer in live.values():
                    try:
                        if peer.get('digest') != self.store.snapshot()['digest']:
                            self.synchronize(peer)
                    except (OSError, ValueError, KeyError):
                        synchronized = False
                now = time.monotonic()
                with self.lock:
                    winner = min([self.node_id] + list(live))
                    if winner != self.candidate:
                        self.candidate, self.candidate_since = winner, now
                        self.ready = False
                    settled = now-self.candidate_since >= self.settle and now-self.started >= self.settle
                    agreement = all(p.get('leader') == winner for p in live.values())
                    self.ready = False
                    if settled and synchronized and agreement and winner == self.node_id:
                        self.store.bootstrap()
                        self.ready = True
                    self.error = None
            except Exception as exc:
                self.ready = False
                self.error = str(exc)
                log.exception('SaveSales synchronization failed')
            self.stop_event.wait(self.heartbeat)

    def coordinator_url(self):
        with self.lock:
            if self.candidate == self.node_id:
                return self.url if self.ready else None
            peer = self.live_peers().get(self.candidate)
            if peer and peer.get('ready') and peer.get('leader') == self.candidate:
                return peer['url']
            return None

    def is_coordinator(self):
        with self.lock:
            live = self.live_peers()
            return self.ready and self.candidate == self.node_id and min([self.node_id]+list(live)) == self.node_id

    def create_app(self):
        app = Flask(__name__)
        app.config['MAX_CONTENT_LENGTH'] = 32*1024*1024

        @app.get('/health')
        def health():
            return jsonify(service=SERVICE, node_id=self.node_id, leader=self.candidate, ready=self.is_coordinator())

        @app.post('/replica')
        def replica():
            if not secrets.compare_digest(request.headers.get('X-Peer-Token',''),self.token):
                return jsonify(error='Peer handshake required'),403
            payload = request.get_json(silent=True)
            try:
                if not isinstance(payload,dict) or payload.get('node_id') not in self.live_peers():
                    return jsonify(error='Peer discovery required'),403
                self.store.merge(payload['events'])
                events = self.store.events()
                known = payload.get('known_ids', [])
                if not isinstance(known, list) or not all(isinstance(key, str) for key in known):
                    raise ValueError('Invalid replica manifest')
                known = set(known)
                return jsonify(events=[e for e in events if e['id'] not in known], known_ids=[e['id'] for e in events])
            except (ValueError, KeyError, TypeError) as exc:
                return jsonify(error=str(exc)),400
            except sqlite3.Error:
                log.exception('Replica write failed')
                return jsonify(error='Unable to save local replica'),503

        @app.get('/state')
        def state():
            if not self.is_coordinator():
                return jsonify(error='LAN election or synchronization in progress'),503
            snapshot = self.store.snapshot()
            if request.args.get('digest') == snapshot['digest']:
                return jsonify(unchanged=True, digest=snapshot['digest'])
            return jsonify(snapshot)

        @app.route('/items',methods=['POST','DELETE'])
        @app.route('/sales',methods=['POST','DELETE'])
        @app.route('/employees',methods=['POST','DELETE'])
        @app.post('/admin/verify')
        @app.post('/time-events')
        @app.post('/time-events/edit')
        @app.post('/attendance-status')
        @app.post('/settings/currency')
        def command():
            with self.write_lock:
                if not self.is_coordinator():
                    return jsonify(error='LAN election or synchronization in progress; retry after connection is green'),503
                try:
                    result = self.store.command(request.method, request.path,
                                                request.get_json(silent=True), request.headers.get('X-Admin-Password'))
                    # Push before replying when peers are reachable. Failover still has
                    # an unavoidable loss window if the only holder dies during a write.
                    for peer in self.live_peers().values():
                        try:
                            self.synchronize(peer)
                        except (OSError, ValueError, KeyError):
                            log.warning('Write saved locally; replica delivery will retry')
                    if 'employees' in result:
                        result = self.store.snapshot()
                    return jsonify(result)
                except PermissionError as exc:
                    return jsonify(error=str(exc)),403
                except (ValueError, TypeError, KeyError) as exc:
                    return jsonify(error=str(exc)),409
                except sqlite3.Error:
                    log.exception('Save failed')
                    return jsonify(error='Unable to save data on this PC'),503
        return app

    def close(self):
        self.stop_event.set()
        self.ready = False
        self.sock.close()
        self.http.shutdown()
        self.http.server_close()
        for thread in self.threads:
            if thread is not threading.current_thread():
                thread.join(timeout=3)


if __name__ == '__main__':
    # Retain the old filename as a launcher, never as a required second process.
    import runpy
    runpy.run_path(str(source_directory() / 'main.py'), run_name='__main__')
