import base64
import copy
from io import BytesIO
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid
from PIL import Image
from commerce import Cart,price_cents,thumbnail,timestamp,MAX_IMAGE_BYTES
from server import Store
import test_lan as lan_tests
from test_lan import until


def product(name='Coca-Cola',price=600,image=None):
    return dict(id=str(uuid.uuid4()),name=name,price_cents=price,description='Chilled drink',image=image,created_at=timestamp())


class CommerceStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name,password='secret');self.store.bootstrap()
    def tearDown(self):self.temp.cleanup()
    def add(self,item):return self.store.command('POST','/items',item,'secret')
    def test_price_and_cart_exact_arithmetic(self):
        self.assertEqual(price_cents('6,00'),600)
        self.assertEqual(price_cents('0.10'),10)
        for invalid in ('','0','-1','NaN','Infinity','1.234','hello'):
            with self.assertRaises(ValueError):price_cents(invalid)
        a,b=Cart(),Cart();item=product(price=10)
        a.add(item);a.add(item)
        self.assertEqual(len(a.rows),1);self.assertEqual(a.total,20);self.assertEqual(b.rows,{})
        a.quantity(item['id'],-1);self.assertEqual(a.total,10)
        a.remove(item['id']);self.assertEqual(a.total,0)
    def test_admin_validation_and_images(self):
        item=product()
        with self.assertRaises(PermissionError):self.store.command('POST','/items',item,'wrong')
        for changes in ({'name':''},{'price_cents':0},{'price_cents':1.5},{'image':'C:\\Users\\image.jpg'}):
            with self.assertRaises(ValueError):self.add(dict(item,**changes))
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'image.png';Image.new('RGB',(1400,700),'red').save(path)
            item['image']=thumbnail(path);self.add(item)
            raw=base64.b64decode(item['image'])
            self.assertLessEqual(len(raw),MAX_IMAGE_BYTES)
            with Image.open(BytesIO(raw)) as image:self.assertEqual(image.size,(512,256))
            with self.store.connection() as db:
                self.assertEqual(db.execute('SELECT typeof(image) FROM items').fetchone()[0],'blob')
        with self.assertRaises(PermissionError):self.store.command('DELETE','/items',{'id':item['id']},'wrong')
    def test_receipt_snapshot_retries_and_deleted_product(self):
        item=product(price=123);self.add(item);cart=Cart();cart.add(item);cart.add(item);cart.customer_name='Ana'
        payload=cart.prepare();self.assertEqual(payload['total_cents'],246)
        self.store.command('POST','/sales',payload)
        self.store.command('DELETE','/items',{'id':item['id']},'secret')
        self.store.command('POST','/sales',payload)  # response-loss retry, even after deletion
        state=self.store.snapshot();self.assertEqual(state['items'],[]);self.assertEqual(len(state['sales']),1)
        sale=state['sales'][0];self.assertEqual(sale['customer_name'],'Ana');self.assertEqual(sale['total_cents'],246)
        self.assertEqual(sale['items'][0]['name'],'Coca-Cola');self.assertEqual(sale['items'][0]['unit_price_cents'],123)
        self.assertTrue(cart.confirm(payload['id']));self.assertFalse(cart.rows);self.assertEqual(cart.customer_name,'')
        self.assertEqual(Store(self.temp.name).snapshot()['sales'],state['sales'])
    def test_unnamed_sale_and_tamper_rejection(self):
        item=product();self.add(item);cart=Cart();cart.add(item);payload=cart.prepare()
        bad=copy.deepcopy(payload);bad['total_cents']=1
        with self.assertRaises(ValueError):self.store.command('POST','/sales',bad)
        bad=copy.deepcopy(payload);bad['items'][0]['name']='Fake name'
        with self.assertRaises(ValueError):self.store.command('POST','/sales',bad)
        self.store.command('POST','/sales',payload)
        self.assertEqual(self.store.snapshot()['sales'][0]['customer_name'],'')
        self.assertEqual(cart.prepare(),payload)
    def test_transaction_rollback_includes_projections(self):
        first=product();self.add(first);old=self.store.events()
        second=product();event=dict(id='item:'+second['id'],clock=0,kind='item_add',item=second)
        conflict=dict(old[0]);conflict['clock']+=1
        with self.assertRaises(ValueError):self.store.merge([event,conflict])
        self.assertEqual(len(self.store.snapshot()['items']),1)
    def test_additive_migration_and_employee_retention(self):
        self.store.command('POST','/employees',{'name':'Jeff'},'secret')
        node_id=self.store.node_id
        reopened=Store(self.temp.name)
        self.assertEqual(reopened.node_id,node_id);self.assertIn('Jeff',reopened.snapshot()['employees'])
        with reopened.connection() as db:
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({'items','sales','sale_items','events','metadata'}<=tables)
    def test_out_of_order_replication_and_no_resurrection(self):
        item=product();self.add(item);cart=Cart();cart.add(item);self.store.command('POST','/sales',cart.prepare())
        self.store.command('DELETE','/items',{'id':item['id']},'secret')
        with tempfile.TemporaryDirectory() as folder:
            other=Store(folder)
            other.merge(list(reversed(self.store.events())))
            self.assertEqual(other.snapshot(),self.store.snapshot())
            self.assertEqual(len(other.snapshot()['sales']),1)
            self.assertEqual(other.snapshot()['items'],[])


class CommerceNetworkTests(unittest.TestCase):
    setUp=lan_tests.NetworkTests.setUp
    tearDown=lan_tests.NetworkTests.tearDown
    start=lan_tests.NetworkTests.start
    ready=lan_tests.NetworkTests.ready
    call=lan_tests.NetworkTests.call
    same=lan_tests.NetworkTests.same
    # Reuse real UDP/HTTP peer harness, not an in-memory substitute.
    def test_products_sales_images_and_failover(self):
        a,b=self.start(0),self.start(1);self.ready(a,b)
        path=Path(self.temp.name)/'product.png';Image.new('RGB',(800,600),'blue').save(path)
        item=product(image=thumbnail(path))
        self.call(a,'/items',item,password='wrong',ok=False)
        self.call(a,'/items',item,password='secret');self.same(a,b)
        remote=b.node.store.snapshot()['items'][0]
        self.assertEqual(remote,item)
        with Image.open(BytesIO(base64.b64decode(remote['image']))) as image:self.assertEqual(image.size,(512,384))
        ca,cb=Cart(),Cart();cb.add(remote);cb.add(remote);cb.customer_name='Jeff'
        self.assertEqual(ca.rows,{})
        self.assertNotIn('cart',a.node.store.snapshot())
        sale=cb.prepare();self.call(b,'/sales',sale);self.same(a,b)
        self.assertEqual(a.node.store.snapshot()['sales'][0]['total_cents'],1200)
        self.assertTrue(cb.confirm(sale['id']))
        cb.add(remote);unnamed=cb.prepare();self.call(b,'/sales',unnamed);self.same(a,b)
        self.assertTrue(any(s['customer_name']=='' for s in a.node.store.snapshot()['sales']))
        self.call(b,'/items',{'id':item['id']},method='DELETE',password='wrong',ok=False)
        self.call(b,'/items',{'id':item['id']},method='DELETE',password='secret');self.same(a,b)
        self.assertEqual(a.node.store.snapshot()['items'],[])
        self.assertEqual(len(a.node.store.snapshot()['sales']),2)
        self.call(b,'/sales',sale);self.same(a,b);self.assertEqual(len(a.node.store.snapshot()['sales']),2)
        leader=next(c for c in [a,b] if c.node.is_coordinator());survivor=b if leader is a else a
        leader.close();leader.thread.join(8)
        until(lambda:survivor.node.is_coordinator() and survivor.connected)
        self.call(survivor,'/sales',sale)
        self.assertEqual(len(survivor.node.store.snapshot()['sales']),2)

if __name__=='__main__':unittest.main()
