"""Typed catalog/sale projections, image preparation, and a strictly PC-local cart."""
import base64
import copy
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
import uuid
from datetime import datetime
from PIL import Image, ImageOps

MAX_CENTS = 999_999_999
MAX_IMAGE_BYTES = 160_000

CURRENCIES = {
    'BRL': {'symbol': 'R$', 'name': 'Brazilian Real'},
    'USD': {'symbol': '$', 'name': 'US Dollar'},
    'CAD': {'symbol': 'C$', 'name': 'Canadian Dollar'},
    'GBP': {'symbol': '£', 'name': 'British Pound'},
    'AUD': {'symbol': 'A$', 'name': 'Australian Dollar'},
    'NZD': {'symbol': 'NZ$', 'name': 'New Zealand Dollar'},
    'EUR': {'symbol': '€', 'name': 'Euro'},
    'CHF': {'symbol': 'CHF', 'name': 'Swiss Franc'},
    'SEK': {'symbol': 'kr', 'name': 'Swedish Krona'},
    'NOK': {'symbol': 'kr', 'name': 'Norwegian Krone'},
    'DKK': {'symbol': 'kr', 'name': 'Danish Krone'},
    'PLN': {'symbol': 'zł', 'name': 'Polish Zloty'},
    'SGD': {'symbol': 'S$', 'name': 'Singapore Dollar'},
    'ZAR': {'symbol': 'R', 'name': 'South African Rand'},
    'INR': {'symbol': '₹', 'name': 'Indian Rupee'},
}
DEFAULT_CURRENCY = 'BRL'


def currency_display(code):
    info = CURRENCIES.get(code, CURRENCIES[DEFAULT_CURRENCY])
    return f"{code} · {info['symbol']} · {info['name']}"


def currency_symbol(code):
    return CURRENCIES.get(code, CURRENCIES[DEFAULT_CURRENCY])['symbol']


def price_cents(text):
    value = str(text).strip().replace(',', '.')
    try:
        amount = Decimal(value)
        if not amount.is_finite() or amount <= 0 or amount > Decimal(MAX_CENTS)/100 or amount.as_tuple().exponent < -2:
            raise ValueError('Enter a positive price with at most two decimal places.')
        return int(amount*100)
    except (InvalidOperation, OverflowError) as exc:
        raise ValueError('Enter a valid price, for example 6.00 or 6,00.') from exc


def money(cents, currency=DEFAULT_CURRENCY):
    if currency not in CURRENCIES:
        currency = DEFAULT_CURRENCY
    symbol = CURRENCIES[currency]['symbol']
    return f'{symbol} {cents//100:,}.{cents%100:02d}'


def timestamp():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def thumbnail(path):
    path=Path(path)
    if path.stat().st_size > 20*1024*1024:
        raise ValueError('Choose an image smaller than 20 MB.')
    with Image.open(path) as source:
        if source.width*source.height > 20_000_000:
            raise ValueError('Choose an image smaller than 20 megapixels.')
        image=ImageOps.exif_transpose(source)
        image.thumbnail((512,384),Image.Resampling.LANCZOS)
        rgba=image.convert('RGBA')
        background=Image.new('RGB',rgba.size,'#172033')
        background.paste(rgba,mask=rgba.getchannel('A'))
        for quality in (82,65,45):
            output=BytesIO();background.save(output,format='JPEG',quality=quality,optimize=True)
            raw=output.getvalue()
            if len(raw)<=MAX_IMAGE_BYTES:
                return base64.b64encode(raw).decode('ascii')
    raise ValueError('Image is too complex; choose a smaller image.')


def image_bytes(encoded):
    if encoded in ('',None):return None
    if not isinstance(encoded,str) or len(encoded)>((MAX_IMAGE_BYTES+2)//3)*4:
        raise ValueError('Product image is too large.')
    try:
        raw=base64.b64decode(encoded,validate=True)
        if len(raw)>MAX_IMAGE_BYTES:raise ValueError('Product image is too large.')
        with Image.open(BytesIO(raw)) as image:
            if image.format!='JPEG' or image.width>512 or image.height>384:
                raise ValueError('Product images must be resized JPEG thumbnails.')
            image.verify()
        return raw
    except (OSError,ValueError) as exc:
        raise ValueError('Invalid product thumbnail.') from exc


def identifier(value):
    if not isinstance(value,str) or str(uuid.UUID(value))!=value:
        raise ValueError('Invalid ID.')
    return value


def positive_int(value,maximum):
    if type(value) is not int or not 1<=value<=maximum:
        raise ValueError('Invalid price or quantity.')


def validate_event(event):
    kind=event['kind']
    if event['clock']!=0:raise ValueError('Invalid commerce journal clock.')
    if kind=='item_add':
        item=event['item'];identifier(item['id'])
        if event['id']!='item:'+item['id']:raise ValueError('Invalid item event ID.')
        if not isinstance(item['name'],str) or not 1<=len(item['name'].strip())<=200:raise ValueError('Item name is required (up to 200 characters).')
        positive_int(item['price_cents'],MAX_CENTS)
        if not isinstance(item['description'],str) or len(item['description'])>2000:raise ValueError('Description is too long.')
        datetime.fromisoformat(item['created_at'])
        image_bytes(item.get('image'))
    elif kind=='item_delete':
        identifier(event['item_id'])
        if event['id']!='delete-item:'+event['item_id']:raise ValueError('Invalid item deletion ID.')
    elif kind=='sale_delete':
        identifier(event['sale_id'])
        if event['id']!='delete-sale:'+event['sale_id']:raise ValueError('Invalid sale deletion ID.')
    elif kind=='sale_save':
        sale=event['sale'];identifier(sale['id'])
        if event['id']!='sale:'+sale['id']:raise ValueError('Invalid sale event ID.')
        if sale.get('currency',DEFAULT_CURRENCY) not in CURRENCIES:raise ValueError('Invalid sale currency.')
        datetime.fromisoformat(sale['created_at'])
        if not isinstance(sale['customer_name'],str) or len(sale['customer_name'])>200:raise ValueError('Customer name is too long.')
        if not isinstance(sale['items'],list) or not 1<=len(sale['items'])<=200:raise ValueError('Cart must contain 1–200 products.')
        seen=set();total=0
        for row in sale['items']:
            identifier(row['item_id'])
            if row['item_id'] in seen:raise ValueError('Duplicate sale line.')
            seen.add(row['item_id'])
            if not isinstance(row['name'],str) or not 1<=len(row['name'])<=200:raise ValueError('Invalid sale item name.')
            positive_int(row['quantity'],9999);positive_int(row['unit_price_cents'],MAX_CENTS)
            subtotal=row['quantity']*row['unit_price_cents']
            if type(row['subtotal_cents']) is not int or row['subtotal_cents']!=subtotal:raise ValueError('Incorrect line subtotal.')
            total+=subtotal
        if type(sale['total_cents']) is not int or sale['total_cents']!=total:raise ValueError('Incorrect sale total.')
    else:raise ValueError('Unknown commerce operation.')


def initialize(db):
    # Additive migration. Employee events/metadata and stable node IDs stay intact.
    db.execute('CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, name TEXT NOT NULL, price_cents INTEGER NOT NULL CHECK(price_cents>0), description TEXT NOT NULL, image BLOB, created_at TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0)')
    db.execute('CREATE TABLE IF NOT EXISTS item_tombstones (item_id TEXT PRIMARY KEY)')
    db.execute('CREATE TABLE IF NOT EXISTS sales (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, sale_date TEXT NOT NULL, sale_time TEXT NOT NULL, customer_name TEXT NOT NULL, total_cents INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT "BRL")')
    sale_columns={row[1] for row in db.execute('PRAGMA table_info(sales)')}
    if 'currency' not in sale_columns:
        db.execute('ALTER TABLE sales ADD COLUMN currency TEXT NOT NULL DEFAULT "BRL"')
    # Deletions are durable tombstones so an incorrect sale stays removed after LAN reconciliation.
    db.execute('CREATE TABLE IF NOT EXISTS sale_tombstones (sale_id TEXT PRIMARY KEY)')
    # No FK to items: a historical receipt never depends on a live catalog entry.
    db.execute('CREATE TABLE IF NOT EXISTS sale_items (sale_id TEXT NOT NULL, item_id TEXT NOT NULL, name TEXT NOT NULL, quantity INTEGER NOT NULL, unit_price_cents INTEGER NOT NULL, subtotal_cents INTEGER NOT NULL, PRIMARY KEY(sale_id,item_id), FOREIGN KEY(sale_id) REFERENCES sales(id))')
    db.execute('CREATE INDEX IF NOT EXISTS sales_date_idx ON sales(sale_date,created_at)')
    db.execute("INSERT OR IGNORE INTO metadata VALUES ('commerce_schema','1')")


def project(db,event):
    kind=event['kind']
    if kind=='item_add':
        item=event['item']
        removed=db.execute('SELECT 1 FROM item_tombstones WHERE item_id=?',(item['id'],)).fetchone()
        db.execute('INSERT INTO items VALUES (?,?,?,?,?,?,?)',(item['id'],item['name'],item['price_cents'],item['description'],image_bytes(item.get('image')),item['created_at'],int(bool(removed))))
    elif kind=='item_delete':
        db.execute('INSERT OR IGNORE INTO item_tombstones VALUES (?)',(event['item_id'],))
        db.execute('UPDATE items SET deleted=1 WHERE id=?',(event['item_id'],))
    elif kind=='sale_delete':
        db.execute('INSERT OR IGNORE INTO sale_tombstones VALUES (?)',(event['sale_id'],))
    elif kind=='sale_save':
        sale=event['sale'];when=datetime.fromisoformat(sale['created_at'])
        db.execute('INSERT INTO sales (id,created_at,sale_date,sale_time,customer_name,total_cents,currency) VALUES (?,?,?,?,?,?,?)',
                   (sale['id'],sale['created_at'],when.strftime('%Y-%m-%d'),when.strftime('%H:%M:%S'),sale['customer_name'],sale['total_cents'],sale.get('currency',DEFAULT_CURRENCY)))
        for row in sale['items']:
            db.execute('INSERT INTO sale_items VALUES (?,?,?,?,?,?)',(sale['id'],row['item_id'],row['name'],row['quantity'],row['unit_price_cents'],row['subtotal_cents']))


def snapshot(db):
    items=[]
    for row in db.execute('SELECT id,name,price_cents,description,image,created_at FROM items WHERE deleted=0 ORDER BY created_at,id'):
        items.append(dict(id=row[0],name=row[1],price_cents=row[2],description=row[3],image=base64.b64encode(row[4]).decode('ascii') if row[4] else None,created_at=row[5]))
    sales=[]
    lines={}
    for row in db.execute('SELECT sale_id,item_id,name,quantity,unit_price_cents,subtotal_cents FROM sale_items ORDER BY item_id'):
        lines.setdefault(row[0],[]).append(dict(item_id=row[1],name=row[2],quantity=row[3],unit_price_cents=row[4],subtotal_cents=row[5]))
    for row in db.execute('SELECT s.id,s.created_at,s.sale_date,s.sale_time,s.customer_name,s.total_cents,s.currency FROM sales s LEFT JOIN sale_tombstones t ON t.sale_id=s.id WHERE t.sale_id IS NULL ORDER BY s.created_at DESC,s.id'):
        sales.append(dict(id=row[0],created_at=row[1],date=row[2],time=row[3],customer_name=row[4],total_cents=row[5],currency=row[6] or DEFAULT_CURRENCY,items=lines.get(row[0],[])))
    return dict(items=items,sales=sales)


def command(store,method,path,payload,password):
    protected = path=='/items' or (path=='/sales' and method=='DELETE')
    if protected and not store.authorized(password):raise PermissionError('Incorrect admin password')
    if not isinstance(payload,dict):raise ValueError('Invalid request.')
    if path=='/items':
        if method=='POST':
            item=dict(id=payload['id'],name=payload['name'].strip(),price_cents=payload['price_cents'],description=payload.get('description','').strip(),image=payload.get('image'),created_at=payload['created_at'])
            event=dict(id='item:'+item['id'],clock=0,kind='item_add',item=item)
        elif method=='DELETE':
            event=dict(id='delete-item:'+payload['id'],clock=0,kind='item_delete',item_id=payload['id'])
        else:raise ValueError('Unknown item action.')
    elif path=='/sales' and method=='POST':
        # Timestamp and ID are captured ONCE by the cashier. The immutable event
        # is identical on a retry, including across coordinator changes.
        sale=copy.deepcopy(payload)
        sale.setdefault('currency', store.snapshot().get('currency', DEFAULT_CURRENCY))
        sale['items']=sorted(sale.get('items',[]),key=lambda row:row['item_id'])
        event=dict(id='sale:'+sale['id'],clock=0,kind='sale_save',sale=sale)
    elif path=='/sales' and method=='DELETE':
        sale_id=payload.get('id')
        identifier(sale_id)
        if not any(s['id']==sale_id for s in store.snapshot()['sales']):
            raise ValueError('Sale was already deleted or does not exist.')
        event=dict(id='delete-sale:'+sale_id,clock=0,kind='sale_delete',sale_id=sale_id)
    else:raise ValueError('Unknown commerce request.')
    validate_event(event)
    existing=next((e for e in store.events() if e['id']==event['id']),None)
    if existing:
        if existing!=event:raise ValueError('This request ID was already used with different details.')
        return store.snapshot()
    if path=='/sales' and method=='POST':
        catalog={item['id']:item for item in store.snapshot()['items']}
        for row in sale['items']:
            item=catalog.get(row['item_id'])
            if not item:raise ValueError(f"{row['name']} is no longer in the catalog. Remove it from the cart.")
            if row['unit_price_cents']!=item['price_cents'] or row['name']!=item['name']:
                raise ValueError('The catalog changed. Remove and re-add the affected item.')
    store.merge([event])
    return store.snapshot()


class Cart:
    """No network or database references: unfinished purchases never replicate."""
    def __init__(self):
        self.rows={};self.customer_name='';self.pending=None;self.currency=None

    def editable(self):
        if self.pending:raise ValueError('This sale is awaiting confirmation. Retry the same sale first.')

    def add(self,item,currency=DEFAULT_CURRENCY):
        self.editable()
        if currency not in CURRENCIES:raise ValueError('Invalid store currency.')
        if self.rows and self.currency and self.currency!=currency:
            raise ValueError('The store currency changed while this cart was open. Finish or empty this cart before adding more items.')
        if not self.rows:self.currency=currency
        row=self.rows.setdefault(item['id'],dict(item_id=item['id'],name=item['name'],unit_price_cents=item['price_cents'],quantity=0))
        if row['quantity']>=9999:raise ValueError('Maximum quantity is 9999.')
        row['quantity']+=1

    def quantity(self,item_id,change):
        self.editable();row=self.rows[item_id]
        if row['quantity']+change>9999:raise ValueError('Maximum quantity is 9999.')
        row['quantity']+=change
        if row['quantity']<=0:self.rows.pop(item_id)

    def remove(self,item_id):
        self.editable();self.rows.pop(item_id,None)
        if not self.rows:self.currency=None

    @property
    def total(self):return sum(r['quantity']*r['unit_price_cents'] for r in self.rows.values())

    def prepare(self,currency=DEFAULT_CURRENCY):
        if self.pending:return copy.deepcopy(self.pending)
        if not self.rows:raise ValueError('Add at least one product to the cart.')
        if self.currency and self.currency!=currency:
            raise ValueError('The store currency changed while this cart was open. Empty the cart and add the products again.')
        customer=self.customer_name.strip()
        if len(customer)>200:raise ValueError('Customer name must be at most 200 characters.')
        self.pending=dict(id=str(uuid.uuid4()),created_at=timestamp(),customer_name=customer,currency=self.currency or currency,
                          items=[dict(r,subtotal_cents=r['quantity']*r['unit_price_cents']) for r in self.rows.values()],total_cents=self.total)
        return copy.deepcopy(self.pending)

    def confirm(self,sale_id):
        if self.pending and self.pending['id']==sale_id:
            self.rows.clear();self.customer_name='';self.pending=None;self.currency=None
            return True
        return False
