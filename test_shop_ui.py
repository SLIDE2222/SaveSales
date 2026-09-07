"""Real Tk smoke test; temp data, no changes to the live store."""
import inspect
import logging
from pathlib import Path
import runpy
import tempfile
import time
import uuid
from unittest.mock import patch
import customtkinter as ctk
from PIL import Image,ImageDraw,ImageGrab
import lan_client
from commerce import timestamp,thumbnail

def run():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    original_client=lan_client.LanClient;original_loop=ctk.CTk.mainloop
    errors=[]
    output=Path(__file__).parent/'ui_test_output'
    output.mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory() as folder:
        image_path=Path(folder)/'drink.png'
        image=Image.new('RGB',(640,400),'#164E63');draw=ImageDraw.Draw(image);draw.rounded_rectangle((235,35,405,365),radius=25,fill='#F8FAFC');draw.rectangle((235,135,405,265),fill='#DC2626');draw.text((280,185),'COLA',fill='white');image.save(image_path)
        picture=thumbnail(image_path)
        lan_client.LanClient=lambda:original_client(directory=folder,legacy_directory=folder,bind_host='127.0.0.1',discovery_port=0,targets=[],heartbeat=.2,settle=.4)
        def smoke(app):
            ns=inspect.currentframe().f_back.f_globals;shop=ns['shop'];deadline=time.monotonic()+35
            def fail(exc):errors.append(str(exc));ns['close_app']()
            def wait_for(predicate,callback):
                try:
                    if predicate():callback();return
                    if time.monotonic()>deadline:raise AssertionError('UI test timed out')
                    app.after(80,lambda:wait_for(predicate,callback))
                except Exception as exc:fail(exc)
            def capture(name):
                app.update();app.lift();time.sleep(.2);app.update()
                x,y=app.winfo_rootx(),app.winfo_rooty()
                ImageGrab.grab(window=app.winfo_id()).save(output/name)
            fixtures=[('Coca-Cola',600,'Refreshing chilled cola',picture),('Mineral Water',250,'Still water, 500 ml',None),('Sandwich',1290,'Freshly prepared every morning',None)]
            def seed(index=0):
                if index==len(fixtures):test_form();return
                name,price,desc,img=fixtures[index]
                payload=dict(id=str(uuid.uuid4()),name=name,price_cents=price,description=desc,image=img,created_at=timestamp())
                def done(ok,result):
                    if not ok:fail(result)
                    else:seed(index+1)
                ns['client'].submit('POST','/items',payload,'admin',done)
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            def test_form():
                try:
                    # Server-side authentication is exercised by the network suite;
                    # this tests actual form widgets, async image import and submission.
                    shop.authorize=lambda:'admin';shop.add_item()
                    form=next(w for w in app.winfo_children() if isinstance(w,ctk.CTkToplevel) and w.title()=='Add Item')
                    widgets=list(descendants(form));entries=[w for w in widgets if isinstance(w,ctk.CTkEntry)]
                    entries[0].insert(0,'Orange Juice');entries[1].insert(0,'9.90')
                    box=next(w for w in widgets if isinstance(w,ctk.CTkTextbox));box.insert('1.0','Fresh orange juice')
                    choose=next(w for w in widgets if isinstance(w,ctk.CTkButton) and w.cget('text')=='Choose image (optional)')
                    save=next(w for w in widgets if isinstance(w,ctk.CTkButton) and w.cget('text')=='Save Item')
                    with patch('shop_ui.filedialog.askopenfilename',return_value=str(image_path)):choose.invoke()
                    wait_for(lambda:save.cget('state')=='normal',save.invoke)
                    wait_for(lambda:len(shop.items)==4,test_cart)
                except Exception as exc:fail(exc)
            def test_cart():
                try:
                    shop.show_items();capture('items.png')
                    item=next(i for i in shop.items if i['name']=='Coca-Cola')
                    shop.add_to_cart(item);shop.add_to_cart(item)
                    assert shop.cart.rows[item['id']]['quantity']==2
                    shop.authorize=lambda:(_ for _ in ()).throw(AssertionError('Cart removal asked for admin'))
                    shop.remove(item['id']);assert not shop.cart.rows
                    shop.add_to_cart(item);shop.add_to_cart(item)
                    shop.customer.set('Jeff');shop.show_cart();capture('cart.png')
                    assert shop.cart.total==1200
                    shop.save_sale()
                    wait_for(lambda:len(shop.sales)==1 and not shop.cart.rows,test_receipt)
                except Exception as exc:fail(exc)
            def test_receipt():
                try:
                    assert shop.customer.get()==''
                    assert shop.sales[0]['customer_name']=='Jeff'
                    shop.show_tracking();capture('tracking.png')
                    shop.show_receipt(shop.sales[0])
                    receipt=next(w for w in app.winfo_children() if isinstance(w,ctk.CTkToplevel) and w.title()=='Saved sale');receipt.destroy()
                    item=next(i for i in shop.items if i['name']=='Coca-Cola')
                    shop.selected=item['id'];shop.authorize=lambda:'admin'
                    with patch('shop_ui.messagebox.askyesno',return_value=False):shop.delete_item()
                    assert any(i['id']==item['id'] for i in shop.items)
                    with patch('shop_ui.messagebox.askyesno',return_value=True):shop.delete_item()
                    wait_for(lambda:not any(i['id']==item['id'] for i in shop.items),finish)
                except Exception as exc:fail(exc)
            def finish():
                try:
                    assert shop.sales[0]['items'][0]['name']=='Coca-Cola'
                    ns['open_employees']();ns['open_items']()
                    print('PASS: actual item form, image import, cards, cart quantity/removal, customer, save/clear, receipt, delete confirmation and employee navigation')
                except Exception as exc:errors.append(str(exc))
                ns['close_app']()
            app.report_callback_exception=lambda kind,value,tb:fail(value)
            app.after(100,lambda:wait_for(lambda:ns['connected'],seed))
            original_loop(app)
        ctk.CTk.mainloop=smoke
        runpy.run_path(str(Path(__file__).with_name('main.py')),run_name='__main__')
    if errors:raise AssertionError(errors)


if __name__ == '__main__':
    run()
