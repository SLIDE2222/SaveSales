"""Durability and real-socket multi-PC simulation. Uses temporary SQLite replicas."""
import concurrent.futures
import json
import logging
import queue
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from datetime import datetime
from unittest.mock import patch

from server import Store, PeerNode, SERVICE, discovery_targets
from lan_client import LanClient

logging.getLogger('werkzeug').setLevel(logging.ERROR)


def until(predicate, timeout=15):
    end = time.monotonic()+timeout
    while time.monotonic()<end:
        if predicate():
            return
        time.sleep(.05)
    raise AssertionError('Timed out waiting for LAN convergence')


def port():
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name,password='secret')
        self.store.bootstrap()

    def tearDown(self):
        self.temp.cleanup()

    def add(self,name='Jeff'):
        return self.store.command('POST','/employees',{'name':name},'secret')

    def test_concurrent_writes_and_restart(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            list(pool.map(lambda i:self.add(f'Employee {i}'),range(40)))
        self.assertEqual(len(Store(self.temp.name).snapshot()['employees']),40)

    def test_migration_is_non_destructive(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)
            before='{"employees":["Legacy"],"employee_times":{"Legacy":{"2025-01-01":{"clock_in":"08:00:00","clock_out":"17:00:00"}}}}'
            (p/'savesales_shared.json').write_text(before)
            store=Store(p);store.bootstrap()
            self.assertEqual(store.snapshot()['employee_times']['Legacy']['2025-01-01']['clock_in'],'08:00:00')
            self.assertEqual((p/'savesales_shared.json').read_text(),before)
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'employees.json').write_text('["Legacy"]');(p/'employee_times.json').write_text('{}')
            store=Store(p);store.bootstrap()
            self.assertEqual(store.snapshot()['employees'],['Legacy'])
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'employees.json').write_text('{invalid')
            store=Store(p)
            with self.assertRaises(json.JSONDecodeError):store.bootstrap()
            self.assertEqual(store.events(),[])

    def test_password_and_invalid_transitions(self):
        with self.assertRaises(PermissionError):self.store.command('POST','/employees',{'name':'Jeff'},'bad')
        state=self.add();ids=state['employee_ids']['Jeff'];date=datetime.now().strftime('%Y-%m-%d')
        def event(action):return self.store.command('POST','/time-events',{'employee':'Jeff','employee_ids':ids,'date':date,'action':action})
        with self.assertRaises(ValueError):event('break_in')
        event('clock_in')
        with self.assertRaises(ValueError):event('break_out')
        event('break_in'); before=self.store.snapshot();event('break_in')
        self.assertEqual(before,self.store.snapshot())
        with self.assertRaises(ValueError):event('clock_out')
        event('break_out');event('clock_out')
        with self.assertRaises(PermissionError):self.store.command('DELETE','/employees',{'name':'Jeff','employee_ids':ids},'wrong')

    def test_delete_tombstone_and_recreation(self):
        before=self.add();ids=before['employee_ids']['Jeff'];old=self.store.events()
        self.store.command('DELETE','/employees',{'name':'Jeff','employee_ids':ids},'secret')
        self.store.merge(old)
        self.assertEqual(self.store.snapshot()['employees'],[])
        self.add()
        with self.assertRaises(ValueError):self.store.command('DELETE','/employees',{'name':'Jeff','employee_ids':ids},'secret')

    def test_transaction_conflict_rolls_back(self):
        self.add();before=self.store.events()
        changed=dict(before[0]);changed['clock']+=1
        with self.assertRaises(ValueError):
            self.store.merge([dict(id='new',clock=100,kind='add',name='Should roll back'),changed])
        self.assertEqual(before,self.store.events())

    def test_partition_merge_converges_without_resurrection(self):
        self.add()
        with tempfile.TemporaryDirectory() as folder:
            other=Store(folder);other.merge(self.store.events())
            ids=self.store.snapshot()['employee_ids']['Jeff']
            other.command('POST','/time-events',dict(employee='Jeff',employee_ids=ids,action='clock_in',date=datetime.now().strftime('%Y-%m-%d')))
            self.store.command('DELETE','/employees',dict(name='Jeff',employee_ids=ids),'secret')
            self.store.command('POST','/employees',{'name':'Alice'},'secret')
            other.command('POST','/employees',{'name':'Bob'},'secret')
            self.store.merge(other.events());other.merge(self.store.events())
            self.assertEqual(self.store.snapshot(),other.snapshot())
            self.assertEqual(set(other.snapshot()['employees']),{'Alice','Bob'})


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.ports=[port(),port(),port()]
        self.clients=[]

    def tearDown(self):
        for client in self.clients:client.close()
        for client in self.clients:client.thread.join(8)
        self.temp.cleanup()

    def start(self,index,password='secret'):
        folder=Path(self.temp.name)/str(index)
        client=LanClient(directory=folder,legacy_directory=folder,password=password,
                         bind_host='127.0.0.1',discovery_port=self.ports[index],
                         targets=[('127.0.0.1',p) for p in self.ports],heartbeat=.2,expiry=1.5,settle=.5)
        self.clients.append(client)
        return client

    def ready(self,*clients):
        until(lambda:all(c.node and c.connected and c.node.coordinator_url() for c in clients))
        until(lambda:len({c.node.candidate for c in clients})==1)

    def call(self,client,path,payload,method='POST',password=None,ok=True):
        payload=dict(payload)
        if path=='/time-events':
            payload['employee_ids']=client.node.store.snapshot()['employee_ids'].get(payload['employee'],[])
            payload['date']=datetime.now().strftime('%Y-%m-%d')
        if method=='DELETE' and path=='/employees':payload['employee_ids']=client.node.store.snapshot()['employee_ids'].get(payload['name'],[])
        done=threading.Event();answer=[]
        client.submit(method,path,payload,password,lambda success,value:(answer.extend([success,value]),done.set()))
        deadline=time.monotonic()+12
        while not done.is_set() and time.monotonic()<deadline:
            try:kind,value,callback=client.results.get(timeout=.2)
            except queue.Empty:continue
            if callback:callback(kind=='ok',value)
        self.assertTrue(done.is_set(),'No command result')
        self.assertEqual(answer[0],ok,answer)
        return answer[1]

    def same(self,*clients):
        until(lambda:len({c.node.store.snapshot()['digest'] for c in clients})==1)

    def test_full_two_peer_workflow_and_failover(self):
        a=self.start(0);self.ready(a)
        b=self.start(1,password='different-local-password');self.ready(a,b)
        self.call(a,'/employees',{'name':'Jeff'},password='secret');self.same(a,b)
        self.assertIn('Jeff',b.node.store.snapshot()['employees'])
        for client,action in [(b,'clock_in'),(a,'break_in'),(b,'break_out'),(a,'clock_out')]:
            self.call(client,'/time-events',{'employee':'Jeff','action':action});self.same(a,b)
            date=datetime.now().strftime('%Y-%m-%d')
            self.assertIn(action,a.node.store.snapshot()['employee_times']['Jeff'][date])
        self.assertEqual(a.node.store.snapshot()['employee_times'],b.node.store.snapshot()['employee_times'])
        self.call(b,'/employees',{'name':'Jeff'},method='DELETE',password='wrong',ok=False)
        leader=next(c for c in [a,b] if c.node.is_coordinator())
        survivor=b if leader is a else a
        leader_index=0 if leader is a else 1
        leader.close();leader.thread.join(8)
        until(lambda:survivor.node.is_coordinator() and survivor.connected)
        self.call(survivor,'/employees',{'name':'After takeover'},password='secret')
        self.call(survivor,'/employees',{'name':'Jeff'},method='DELETE',password='secret')
        restarted=self.start(leader_index);self.ready(survivor,restarted);self.same(survivor,restarted)
        self.assertNotIn('Jeff',restarted.node.store.snapshot()['employees'])
        self.assertIn('After takeover',restarted.node.store.snapshot()['employees'])

    def test_simultaneous_startup_and_all_clients_write(self):
        a,b,c=self.start(0),self.start(1),self.start(2)
        self.ready(a,b,c);self.same(a,b,c)
        self.assertEqual(sum(client.node.is_coordinator() for client in [a,b,c]),1)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures=[pool.submit(self.call,client,'/employees',{'name':f'Employee {i}'},password='secret') for i,client in enumerate([a,b,c])]
            for future in futures:future.result()
        self.same(a,b,c)
        self.assertEqual(len(a.node.store.snapshot()['employees']),3)

    def test_partition_takeover_and_reconciliation(self):
        a,b=self.start(0),self.start(1);self.ready(a,b)
        self.call(a,'/employees',{'name':'Jeff'},password='secret');self.same(a,b)
        targets_a,targets_b=a.node.targets,b.node.targets
        a.node.targets=[];b.node.targets=[]
        # Simulate a broken network link for both heartbeats AND HTTP replication.
        with patch.object(a.node,'synchronize',side_effect=OSError('partition')), patch.object(b.node,'synchronize',side_effect=OSError('partition')):
            until(lambda:a.node.is_coordinator() and b.node.is_coordinator() and a.connected and b.connected)
            self.call(a,'/employees',{'name':'Alice'},password='secret')
            self.call(b,'/employees',{'name':'Bob'},password='secret')
            self.call(a,'/employees',{'name':'Jeff'},method='DELETE',password='secret')
            self.call(b,'/time-events',{'employee':'Jeff','action':'clock_in'})
        a.node.targets=targets_a;b.node.targets=targets_b
        self.ready(a,b);self.same(a,b)
        self.assertEqual(sum(c.node.is_coordinator() for c in [a,b]),1)
        self.assertEqual(set(a.node.store.snapshot()['employees']),{'Alice','Bob'})
        self.assertNotIn('Jeff',b.node.store.snapshot()['employee_times'])

    def test_actual_udp_broadcast(self):
        folder=Path(self.temp.name)/'broadcast'
        node=PeerNode(directory=folder,legacy_directory=folder,discovery_port=port(),heartbeat=.2,settle=.4)
        try:
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1)
                sock.settimeout(3)
                query=dict(service=SERVICE,node_id='broadcast-probe',port=1,token='test',kind='hello')
                for target in discovery_targets(node.sock.getsockname()[1]):
                    if target[0] != '127.0.0.1':
                        sock.sendto(json.dumps(query).encode(),target)
                try:
                    reply,peer=sock.recvfrom(4096)
                except TimeoutError:
                    self.skipTest('Windows/network does not loop back LAN broadcasts on this host; physical two-PC broadcast test required')
                self.assertEqual(json.loads(reply)['node_id'],node.node_id)
        finally:node.close()

    def test_stale_coordinator_is_fenced(self):
        a,b=self.start(0),self.start(1);self.ready(a,b)
        follower=next(c for c in [a,b] if not c.node.is_coordinator())
        with follower.node.create_app().test_client() as http:
            self.assertEqual(http.post('/employees',json={'name':'Bypass'},headers={'X-Admin-Password':'secret'}).status_code,503)
            self.assertEqual(http.post('/replica',json={'events':[]}).status_code,403)

    def test_udp_discovery_response(self):
        a=self.start(0);self.ready(a)
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
            sock.settimeout(2)
            query=dict(service=SERVICE,node_id='discovery-test',port=1,token='test',kind='hello')
            sock.sendto(json.dumps(query).encode(),('127.0.0.1',self.ports[0]))
            reply,peer=sock.recvfrom(4096)
            info=json.loads(reply)
            self.assertEqual(info['service'],SERVICE)
            self.assertEqual(info['node_id'],a.node.node_id)
            self.assertEqual(info['port'],a.node.http.server_port)


if __name__=='__main__':unittest.main()
