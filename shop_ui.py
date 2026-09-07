"""Catalog, independent cashier cart and shared receipts for CustomTkinter."""
import base64
import calendar
import html
import webbrowser
from io import BytesIO
from pathlib import Path
import queue
import threading
import uuid
from datetime import datetime
from tkinter import filedialog, messagebox
import customtkinter as ctk
from PIL import Image, ImageOps
from commerce import Cart, CURRENCIES, DEFAULT_CURRENCY, currency_symbol, money, price_cents, thumbnail, timestamp
from branding import logo_pil, logo_data_uri

BG='#111827'; PANEL='#1F2937'; BLUE='#2563EB'; GRAY='#374151'; GREEN='#16A34A'; RED='#DC2626'


class ShopUI:
    def __init__(self,app,parent,client,authorize,set_page,get_page):
        self.app,self.parent,self.client,self.authorize=app,parent,client,authorize
        self.set_page,self.get_page=set_page,get_page
        self.items=[];self.sales=[];self.cart=Cart();self.selected=None;self.currency=DEFAULT_CURRENCY
        self.customer=ctk.StringVar(master=app,value='')
        self.customer.trace_add('write',lambda *_:setattr(self.cart,'customer_name',self.customer.get()))
        self.notice=ctk.StringVar(master=app,value='')
        self.day=ctk.StringVar(master=app,value=datetime.now().strftime('%Y-%m-%d'))
        self.cards={};self.images={};self.columns=3;self.saving=False
        self.tracking_calendar_open=False
        now=datetime.now()
        self.tracking_year,self.tracking_month=now.year,now.month
        self.parent.bind('<Configure>',self.resize,add='+')
        self.resize_job=None
        try:
            _brand = logo_pil()
            self.brand_logo_small = ctk.CTkImage(light_image=_brand, dark_image=_brand, size=(68, 66))
        except Exception:
            self.brand_logo_small = None

    def resize(self,event):
        columns=max(1,min(4,(event.width-30)//225))
        if columns!=self.columns:
            self.columns=columns
            if self.resize_job:self.app.after_cancel(self.resize_job)
            self.resize_job=self.app.after(150,self.reflow)

    def reflow(self):
        self.resize_job=None
        if self.get_page()=='items':self.show_items()

    def clear(self,page):
        self.set_page(page)
        self.cards={}
        for child in self.parent.winfo_children():child.destroy()

    def header(self,title,subtitle):
        header=ctk.CTkFrame(self.parent,fg_color='transparent')
        header.pack(fill='x',padx=22,pady=(18,10))
        labels=ctk.CTkFrame(header,fg_color='transparent');labels.pack(side='left')
        ctk.CTkLabel(labels,text=title,font=('Segoe UI',28,'bold')).pack(anchor='w')
        ctk.CTkLabel(labels,text=subtitle,font=('Segoe UI',12),text_color='#94A3B8').pack(anchor='w')
        ctk.CTkLabel(self.parent,textvariable=self.notice,font=('Segoe UI',12),height=20,text_color='#4ADE80').pack(fill='x',padx=22)
        return header

    def toast(self,text):
        self.notice.set(text)
        self.app.after(5000,lambda:self.notice.set('') if self.notice.get()==text else None)

    def money(self,cents,currency=None):
        return money(cents,currency or self.currency)

    def sale_money(self,sale,cents=None):
        return money(sale['total_cents'] if cents is None else cents,
                     sale.get('currency',DEFAULT_CURRENCY))

    def sales_total_text(self,sales):
        totals={}
        for sale in sales:
            code=sale.get('currency',DEFAULT_CURRENCY)
            totals[code]=totals.get(code,0)+sale['total_cents']
        return ' + '.join(money(total,code) for code,total in sorted(totals.items())) if totals else money(0,self.currency)

    def apply_snapshot(self,data):
        if 'items' not in data:return
        changed=self.items!=data['items'];sales_changed=self.sales!=data.get('sales',[])
        new_currency=data.get('currency',DEFAULT_CURRENCY)
        currency_changed=self.currency!=new_currency
        self.items=data['items'];self.sales=data.get('sales',[]);self.currency=new_currency
        current_ids={item['id'] for item in self.items}
        if self.selected not in current_ids:self.selected=None
        self.images={key:value for key,value in self.images.items() if key in current_ids}
        if self.cart.pending and any(s['id']==self.cart.pending['id'] for s in self.sales):
            self.cart.confirm(self.cart.pending['id']);self.customer.set('');self.saving=False
            self.toast('Sale saved successfully.')
            if self.get_page()=='cart':self.show_cart()
        if (changed or currency_changed) and self.get_page()=='items':self.show_items()
        if currency_changed and self.get_page()=='cart':self.show_cart()
        if (sales_changed or currency_changed) and self.get_page()=='tracking':
            if self.tracking_calendar_open:self.show_tracking_calendar()
            else:self.show_tracking()

    def photo(self,item):
        if not item.get('image'):return None
        if item['id'] not in self.images:
            image=Image.open(BytesIO(base64.b64decode(item['image']))).convert('RGB')
            image=ImageOps.contain(image,(185,105),Image.Resampling.LANCZOS)
            self.images[item['id']]=ctk.CTkImage(light_image=image,dark_image=image,size=image.size)
        return self.images[item['id']]

    def select(self,item_id):
        self.selected=item_id
        for key,card in self.cards.items():card.configure(border_color=BLUE if key==item_id else GRAY,border_width=2 if key==item_id else 1)

    def show_items(self):
        self.clear('items')
        header=self.header('Items','Manage your products and catalog')
        ctk.CTkButton(header,text='Delete Item',width=100,fg_color=RED,command=self.delete_item).pack(side='right',padx=(8,0))
        ctk.CTkButton(header,text='+ Add Item',width=100,fg_color=BLUE,command=self.add_item).pack(side='right')
        panel=ctk.CTkScrollableFrame(self.parent,fg_color=BG)
        panel.pack(fill='both',expand=True,padx=20,pady=(5,18))
        if not self.items:
            ctk.CTkLabel(panel,text='Your catalog is empty.\nUse + Add Item to create your first product.',font=('Segoe UI',17),text_color='#94A3B8').pack(pady=60)
            return
        for col in range(self.columns):panel.grid_columnconfigure(col,weight=1,uniform='products')
        for index,item in enumerate(self.items):
            card=ctk.CTkFrame(panel,width=205,height=285,corner_radius=12,fg_color=PANEL,border_color=BLUE if item['id']==self.selected else GRAY,border_width=2 if item['id']==self.selected else 1)
            card.grid(row=index//self.columns,column=index%self.columns,sticky='nsew',padx=6,pady=7)
            self.cards[item['id']]=card
            select=lambda event=None,key=item['id']:self.select(key)
            card.bind('<Button-1>',select)
            photo=self.photo(item)
            picture=ctk.CTkLabel(card,text='' if photo else '▧',image=photo,height=110,width=185,fg_color='#172033',corner_radius=8,font=('Segoe UI',38),text_color='#64748B')
            picture.pack(padx=10,pady=(12,5),fill='x');picture.bind('<Button-1>',select)
            for text,font,color,height in [(item['name'],('Segoe UI',16,'bold'),'#F8FAFC',40),(self.money(item['price_cents']),('Segoe UI',21,'bold'),'#60A5FA',30),((item['description'][:77]+'…') if len(item['description'])>80 else item['description'],('Segoe UI',12),'#94A3B8',38)]:
                label=ctk.CTkLabel(card,text=text,font=font,text_color=color,wraplength=180,height=height,anchor='w',justify='left')
                label.pack(fill='x',padx=12);label.bind('<Button-1>',select)
            ctk.CTkButton(card,text='Add to Cart',height=32,fg_color=BLUE,command=lambda product=item:self.add_to_cart(product)).pack(fill='x',padx=12,pady=(8,12))

    def add_item(self):
        password=self.authorize()
        if password is None:return
        window=ctk.CTkToplevel(self.app);window.title('Add Item');window.geometry('540x560');window.resizable(False,False);window.transient(self.app);window.grab_set()
        ctk.CTkLabel(window,text='New product',font=('Segoe UI',26,'bold')).pack(anchor='w',padx=25,pady=(20,4))
        ctk.CTkLabel(window,text='Add a product to the shared store catalog',text_color='#94A3B8').pack(anchor='w',padx=25)
        form=ctk.CTkFrame(window,fg_color='transparent');form.pack(fill='both',expand=True,padx=25,pady=10)
        ctk.CTkLabel(form,text='Item name',anchor='w').pack(fill='x')
        name=ctk.CTkEntry(form,height=36,placeholder_text='e.g. Coca-Cola');name.pack(fill='x')
        ctk.CTkLabel(form,text=f'Price ({self.currency} · {currency_symbol(self.currency)})',anchor='w').pack(fill='x',pady=(8,0))
        price=ctk.CTkEntry(form,height=36,placeholder_text='6.00');price.pack(fill='x')
        ctk.CTkLabel(form,text='Description',anchor='w').pack(fill='x',pady=(8,0))
        description=ctk.CTkTextbox(form,height=85);description.pack(fill='x')
        image_row=ctk.CTkFrame(form,fg_color='transparent');image_row.pack(fill='x',pady=10)
        preview=ctk.CTkLabel(image_row,text='No image',height=65,width=100,fg_color=BG,corner_radius=8);preview.pack(side='left')
        status=ctk.CTkLabel(form,text='',text_color='#F87171',wraplength=450,height=35);status.pack(fill='x')
        image_data={'value':None,'busy':False};results=queue.Queue();item_id=str(uuid.uuid4());created=timestamp()
        def select_image():
            path=filedialog.askopenfilename(parent=window,title='Choose product image',filetypes=[('Images','*.jpg *.jpeg *.png *.webp *.bmp'),('All files','*.*')])
            if not path:return
            image_data['busy']=True;save.configure(state='disabled');choose.configure(state='disabled');status.configure(text='Preparing thumbnail…')
            def prepare():
                try:results.put((thumbnail(path),None))
                except Exception as exc:results.put((None,str(exc)))
            threading.Thread(target=prepare,daemon=True).start()
            def poll():
                if not window.winfo_exists():return
                try:value,error=results.get_nowait()
                except queue.Empty:window.after(100,poll);return
                image_data['busy']=False;save.configure(state='normal');choose.configure(state='normal');status.configure(text=error or '')
                if not error:
                    image_data['value']=value
                    image=ImageOps.contain(Image.open(BytesIO(base64.b64decode(value))),(100,65))
                    preview.image=ctk.CTkImage(image,image,size=image.size);preview.configure(image=preview.image,text='')
            poll()
        choose=ctk.CTkButton(image_row,text='Choose image (optional)',command=select_image,width=210,fg_color=GRAY)
        choose.pack(side='left',padx=15)
        def submit():
            try:
                if not name.get().strip():raise ValueError('Item name is required.')
                payload=dict(id=item_id,name=name.get().strip(),price_cents=price_cents(price.get()),description=description.get('1.0','end').strip(),image=image_data['value'],created_at=created)
                if len(payload['name'])>200 or len(payload['description'])>2000:raise ValueError('Use at most 200 characters for name and 2000 for description.')
            except ValueError as exc:status.configure(text=str(exc));return
            save.configure(state='disabled');status.configure(text='Saving to LAN…')
            def done(ok,result):
                if not window.winfo_exists():return
                if ok:window.destroy();self.toast('Item added to the shared catalog.')
                else:save.configure(state='normal');status.configure(text=str(result))
            self.client.submit('POST','/items',payload,password,done)
        buttons=ctk.CTkFrame(window,fg_color='transparent');buttons.pack(fill='x',padx=25,pady=(0,18))
        save=ctk.CTkButton(buttons,text='Save Item',height=36,command=submit);save.pack(side='right')
        ctk.CTkButton(buttons,text='Cancel',fg_color=GRAY,height=36,command=window.destroy).pack(side='left')

    def delete_item(self):
        item=next((i for i in self.items if i['id']==self.selected),None)
        if not item:self.toast('Click a product card to select it first.');return
        password=self.authorize()
        if password is None:return
        if not messagebox.askyesno('Delete catalog item',f"Permanently delete {item['name']} from the catalog?\nPreviously saved sales will remain unchanged.",parent=self.app):return
        def done(ok,result):
            if ok:self.toast('Item deleted from the shared catalog.')
            else:messagebox.showerror('SaveSales',str(result),parent=self.app)
        self.client.submit('DELETE','/items',{'id':item['id']},password,done)

    def add_to_cart(self,item):
        try:self.cart.add(item,self.currency);self.toast(f"{item['name']} added · {sum(r['quantity'] for r in self.cart.rows.values())} item(s) in cart")
        except ValueError as exc:messagebox.showerror('Cart',str(exc),parent=self.app)

    def change_quantity(self,item_id,change):
        try:self.cart.quantity(item_id,change);self.show_cart()
        except ValueError as exc:messagebox.showerror('Cart',str(exc),parent=self.app)

    def remove(self,item_id):
        try:self.cart.remove(item_id);self.show_cart()
        except ValueError as exc:messagebox.showerror('Cart',str(exc),parent=self.app)

    def show_cart(self):
        self.clear('cart');self.header('Cart','Current customer purchase')
        customer_row=ctk.CTkFrame(self.parent,fg_color='transparent');customer_row.pack(fill='x',padx=22,pady=(5,10))
        ctk.CTkLabel(customer_row,text='Customer name (optional)',font=('Segoe UI',13)).pack(side='left',padx=(0,15))
        ctk.CTkEntry(customer_row,textvariable=self.customer,height=34,state='disabled' if self.cart.pending else 'normal').pack(side='left',fill='x',expand=True)
        footer=ctk.CTkFrame(self.parent,fg_color=BG,corner_radius=10);footer.pack(side='bottom',fill='x',padx=20,pady=(5,18))
        totals=ctk.CTkFrame(footer,fg_color='transparent');totals.pack(side='left',padx=18,pady=12)
        ctk.CTkLabel(totals,text='Subtotal  '+self.money(self.cart.total,self.cart.currency or self.currency),font=('Segoe UI',12),text_color='#94A3B8').pack(anchor='w')
        ctk.CTkLabel(totals,text='Total  '+self.money(self.cart.total,self.cart.currency or self.currency),font=('Segoe UI',23,'bold')).pack(anchor='w')
        ctk.CTkButton(footer,text='Saving…' if self.saving else ('Retry Save Sale' if self.cart.pending else 'Save Sale'),width=165,height=44,fg_color=GREEN,state='disabled' if self.saving or not self.cart.rows else 'normal',command=self.save_sale).pack(side='right',padx=18)
        rows=ctk.CTkScrollableFrame(self.parent,fg_color=BG);rows.pack(fill='both',expand=True,padx=20,pady=5)
        if not self.cart.rows:
            ctk.CTkLabel(rows,text='Your cart is empty.\nAdd products from Items to start a purchase.',font=('Segoe UI',17),text_color='#94A3B8').pack(pady=35)
        for row in self.cart.rows.values():
            line=ctk.CTkFrame(rows,fg_color=PANEL,corner_radius=10);line.pack(fill='x',padx=5,pady=5)
            line.grid_columnconfigure(0,weight=1)
            ctk.CTkLabel(line,text=row['name'],font=('Segoe UI',14,'bold'),wraplength=165,anchor='w',justify='left').grid(row=0,column=0,sticky='w',padx=12,pady=6)
            ctk.CTkLabel(line,text='Unit '+self.money(row['unit_price_cents'],self.cart.currency or self.currency),text_color='#94A3B8',font=('Segoe UI',11)).grid(row=1,column=0,sticky='w',padx=12,pady=(0,8))
            controls=ctk.CTkFrame(line,fg_color='transparent');controls.grid(row=0,column=1,rowspan=2,padx=5)
            state='disabled' if self.cart.pending else 'normal'
            ctk.CTkButton(controls,text='−',width=28,state=state,fg_color=GRAY,command=lambda key=row['item_id']:self.change_quantity(key,-1)).pack(side='left')
            ctk.CTkLabel(controls,text=str(row['quantity']),width=40).pack(side='left')
            ctk.CTkButton(controls,text='+',width=28,state=state,fg_color=GRAY,command=lambda key=row['item_id']:self.change_quantity(key,1)).pack(side='left')
            ctk.CTkLabel(line,text=self.money(row['unit_price_cents']*row['quantity'],self.cart.currency or self.currency),width=115,font=('Segoe UI',14,'bold')).grid(row=0,column=2,rowspan=2,padx=5)
            ctk.CTkButton(line,text='Remove',width=72,fg_color=GRAY,state=state,command=lambda key=row['item_id']:self.remove(key)).grid(row=0,column=3,rowspan=2,padx=(0,10))

    def save_sale(self):
        if self.saving:return
        try:payload=self.cart.prepare(self.currency)
        except ValueError as exc:messagebox.showerror('Cart',str(exc),parent=self.app);return
        self.saving=True;self.show_cart()
        def done(ok,result):
            self.saving=False
            if ok:
                self.cart.confirm(payload['id']);self.customer.set('');self.toast('Sale saved successfully.')
            else:
                # A definite business rejection permits editing. A timeout/offline
                # result retains the frozen ID and payload for an idempotent retry.
                if getattr(result,'definitive',False):self.cart.pending=None
                messagebox.showerror('Save Sale',str(result),parent=self.app)
            if self.get_page()=='cart':self.show_cart()
        self.client.submit('POST','/sales',payload,callback=done)

    def _tracking_entry_submit(self, event=None):
        try:
            selected=datetime.strptime(self.day.get().strip(),'%Y-%m-%d')
        except ValueError:
            self.toast('Use date format YYYY-MM-DD.')
            return
        self.day.set(selected.strftime('%Y-%m-%d'))
        self.tracking_year,self.tracking_month=selected.year,selected.month
        self.show_tracking()

    def _tracking_filters(self, calendar_button_command):
        filters=ctk.CTkFrame(self.parent,fg_color='transparent')
        filters.pack(fill='x',padx=22,pady=8)
        date_entry=ctk.CTkEntry(filters,textvariable=self.day,width=145)
        date_entry.pack(side='left')
        date_entry.bind('<Return>',self._tracking_entry_submit)
        ctk.CTkButton(
            filters,text='Show date',width=95,command=calendar_button_command
        ).pack(side='left',padx=8)

        try:
            datetime.strptime(self.day.get().strip(),'%Y-%m-%d')
            sales=[sale for sale in self.sales if sale['date']==self.day.get().strip()]
        except ValueError:
            sales=[]

        actions=ctk.CTkFrame(filters,fg_color='transparent')
        actions.pack(side='right')
        ctk.CTkButton(
            actions,text='Export year',width=95,height=30,fg_color=GRAY,
            command=lambda:self.export_sales_statement('year')
        ).pack(side='right',padx=(6,0))
        ctk.CTkButton(
            actions,text='Export month',width=105,height=30,fg_color=GRAY,
            command=lambda:self.export_sales_statement('month')
        ).pack(side='right',padx=(10,0))
        ctk.CTkLabel(
            actions,
            text=f"{len(sales)} sale(s) · {self.sales_total_text(sales)}",
            font=('Segoe UI',16,'bold')
        ).pack(side='right')
        return sales

    def show_tracking(self):
        self.tracking_calendar_open=False
        self.clear('tracking')
        self.header('Daily Tracking','Completed sales shared across your store')
        sales=self._tracking_filters(self.show_tracking_calendar)

        panel=ctk.CTkScrollableFrame(self.parent,fg_color=BG)
        panel.pack(fill='both',expand=True,padx=20,pady=(5,18))
        if not sales:
            ctk.CTkLabel(
                panel,text='No sales saved for this date.',text_color='#94A3B8'
            ).pack(pady=35)
        for sale in sales:
            row=ctk.CTkFrame(panel,fg_color=PANEL)
            row.pack(fill='x',padx=5,pady=5)
            ctk.CTkLabel(
                row,
                text=sale['time']+'  ·  '+(sale['customer_name'] or 'Walk-in customer'),
                anchor='w',wraplength=330,font=('Segoe UI',14)
            ).pack(side='left',padx=12,pady=14)
            ctk.CTkButton(
                row,text='Delete',width=72,fg_color=RED,hover_color='#B91C1C',
                command=lambda receipt=sale:self.delete_sale(receipt)
            ).pack(side='right',padx=(0,10))
            ctk.CTkButton(
                row,text='View',width=65,
                command=lambda receipt=sale:self.show_receipt(receipt)
            ).pack(side='right',padx=(0,8))
            ctk.CTkLabel(
                row,text=self.sale_money(sale),font=('Segoe UI',16,'bold')
            ).pack(side='right',padx=12)


    def delete_sale(self,sale):
        if not sale or not sale.get('id'):
            return

        # Protected action: ask for the admin password immediately when Delete is clicked.
        password=self.authorize()
        if password is None:
            return

        # Only after admin authorization, ask for the final destructive-action confirmation.
        if not messagebox.askyesno(
            'Delete sale',
            f"Delete this sale permanently from Daily Tracking and exported statements?\n\n"
            f"{sale['date']} {sale['time']}  ·  {self.sale_money(sale)}\n"
            f"{sale['customer_name'] or 'Walk-in customer'}",
            parent=self.app
        ):
            return

        def done(ok,result):
            if ok:
                self.toast('Sale deleted. Daily Tracking and statements were updated.')
            else:
                messagebox.showerror('Delete sale',str(result),parent=self.app)

        self.client.submit('DELETE','/sales',{'id':sale['id']},password,done)

    def show_tracking_calendar(self):
        # Open the calendar on the month currently typed in the date field.
        # If the field is invalid, fall back to today rather than doing nothing.
        if not self.tracking_calendar_open:
            try:
                selected=datetime.strptime(self.day.get().strip(),'%Y-%m-%d')
            except ValueError:
                selected=datetime.now()
                self.day.set(selected.strftime('%Y-%m-%d'))
            self.tracking_year,self.tracking_month=selected.year,selected.month

        self.tracking_calendar_open=True
        self.clear('tracking')
        self.header('Daily Tracking','Completed sales shared across your store')
        self._tracking_filters(self.show_tracking_calendar)

        panel=ctk.CTkFrame(self.parent,fg_color=BG,corner_radius=12)
        panel.pack(fill='both',expand=True,padx=20,pady=(5,18))

        nav=ctk.CTkFrame(panel,fg_color='transparent')
        nav.pack(pady=(12,8))
        ctk.CTkButton(
            nav,text='◀',width=40,height=32,fg_color=GRAY,
            command=lambda:self._change_tracking_month(-1)
        ).pack(side='left',padx=10)
        ctk.CTkLabel(
            nav,
            text=f'{calendar.month_name[self.tracking_month]} {self.tracking_year}',
            width=185,font=('Segoe UI',20,'bold')
        ).pack(side='left')
        ctk.CTkButton(
            nav,text='▶',width=40,height=32,fg_color=GRAY,
            command=lambda:self._change_tracking_month(1)
        ).pack(side='left',padx=10)

        grid=ctk.CTkFrame(panel,fg_color='transparent')
        grid.pack(padx=14,pady=(0,4))
        for column,name in enumerate(('Mon','Tue','Wed','Thu','Fri','Sat','Sun')):
            ctk.CTkLabel(
                grid,text=name,width=56,font=('Segoe UI',11,'bold'),
                text_color='#94A3B8'
            ).grid(row=0,column=column,padx=3,pady=(0,4))

        dates_with_sales={sale['date'] for sale in self.sales}
        for row_index,week in enumerate(
            calendar.monthcalendar(self.tracking_year,self.tracking_month),start=1
        ):
            for column_index,day in enumerate(week):
                if day==0:
                    ctk.CTkLabel(grid,text='',width=52,height=32).grid(
                        row=row_index,column=column_index,padx=3,pady=3
                    )
                    continue

                date_key=f'{self.tracking_year}-{self.tracking_month:02d}-{day:02d}'
                has_sales=date_key in dates_with_sales
                selected=date_key==self.day.get().strip()
                fg=GREEN if has_sales else (BLUE if selected else GRAY)
                hover='#15803D' if has_sales else '#1D4ED8'
                ctk.CTkButton(
                    grid,text=str(day),width=52,height=32,corner_radius=7,
                    fg_color=fg,hover_color=hover,
                    border_width=2 if selected else 0,border_color='#60A5FA',
                    font=('Segoe UI',12,'bold'),
                    command=lambda key=date_key:self._select_tracking_date(key)
                ).grid(row=row_index,column=column_index,padx=3,pady=3)

        legend=ctk.CTkFrame(panel,fg_color='transparent')
        legend.pack(pady=(3,8))
        ctk.CTkLabel(legend,text='●',text_color=GREEN,font=('Segoe UI',14,'bold')).pack(side='left')
        ctk.CTkLabel(legend,text=' Has sales',font=('Segoe UI',11),text_color='#94A3B8').pack(side='left',padx=(0,16))
        ctk.CTkLabel(legend,text='●',text_color=BLUE,font=('Segoe UI',14,'bold')).pack(side='left')
        ctk.CTkLabel(legend,text=' Selected date',font=('Segoe UI',11),text_color='#94A3B8').pack(side='left')

    def _change_tracking_month(self,delta):
        month=self.tracking_month+delta
        year=self.tracking_year
        if month<1:
            month=12
            year-=1
        elif month>12:
            month=1
            year+=1
        self.tracking_year,self.tracking_month=year,month
        self.show_tracking_calendar()

    def _select_tracking_date(self,date_key):
        self.day.set(date_key)
        selected=datetime.strptime(date_key,'%Y-%m-%d')
        self.tracking_year,self.tracking_month=selected.year,selected.month
        self.show_tracking()


    def export_sales_statement(self,period):
        try:
            selected=datetime.strptime(self.day.get().strip(),'%Y-%m-%d')
        except ValueError:
            self.toast('Use date format YYYY-MM-DD before exporting.')
            return

        if period=='month':
            period_sales=[s for s in self.sales if s['date'].startswith(f'{selected.year:04d}-{selected.month:02d}-')]
            period_label=f'{calendar.month_name[selected.month]} {selected.year}'
            default_name=f'SaveSales-{selected.year:04d}-{selected.month:02d}-monthly-statement.html'
        elif period=='year':
            period_sales=[s for s in self.sales if s['date'].startswith(f'{selected.year:04d}-')]
            period_label=str(selected.year)
            default_name=f'SaveSales-{selected.year:04d}-yearly-statement.html'
        else:
            return

        path=filedialog.asksaveasfilename(
            parent=self.app,
            title=f'Export {period} sales statement',
            defaultextension='.html',
            initialfile=default_name,
            filetypes=[('HTML files','*.html'),('All files','*.*')]
        )
        if not path:return

        try:
            statement=self._sales_statement_html(period_sales,period_label,period)
            target=Path(path).expanduser()
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(statement,encoding='utf-8')
        except Exception as exc:
            messagebox.showerror('Export statement',f'Could not save the statement.\n\n{exc}',parent=self.app)
            return

        if messagebox.askyesno('Statement exported',f'Saved successfully:\n{target}\n\nOpen it now?',parent=self.app):
            webbrowser.open(target.resolve().as_uri())

    def _sales_statement_html(self,sales,period_label,period):
        sales=sorted(sales,key=lambda s:(s['date'],s['time'],s['id']))
        items_sold=sum(row['quantity'] for sale in sales for row in sale['items'])

        def esc(value):return html.escape(str(value),quote=True)
        def fmt(cents,code):return money(cents,code)
        def grouped_text(amounts):
            return ' + '.join(fmt(total,code) for code,total in sorted(amounts.items())) if amounts else fmt(0,self.currency)
        def add_amount(bucket,code,cents):
            bucket[code]=bucket.get(code,0)+cents

        totals={}
        counts={}
        daily={}
        monthly={}
        products={}
        for sale in sales:
            code=sale.get('currency',DEFAULT_CURRENCY)
            add_amount(totals,code,sale['total_cents'])
            counts[code]=counts.get(code,0)+1

            day=daily.setdefault(sale['date'],{'count':0,'totals':{}})
            day['count']+=1;add_amount(day['totals'],code,sale['total_cents'])

            month=sale['date'][:7]
            bucket=monthly.setdefault(month,{'count':0,'totals':{}})
            bucket['count']+=1;add_amount(bucket['totals'],code,sale['total_cents'])

            for row in sale['items']:
                key=(row['name'],code)
                product=products.setdefault(key,{'quantity':0,'total':0})
                product['quantity']+=row['quantity'];product['total']+=row['subtotal_cents']

        averages={code:round(total/counts[code]) for code,total in totals.items() if counts.get(code)}
        currencies_used=', '.join(sorted(totals)) if totals else self.currency

        summary_rows=''.join(
            f'<tr><td>{esc(date)}</td><td>{data["count"]}</td><td>{esc(grouped_text(data["totals"]))}</td></tr>'
            for date,data in sorted(daily.items())
        ) or '<tr><td colspan="3" class="empty">No sales in this period.</td></tr>'

        month_rows=''.join(
            f'<tr><td>{esc(calendar.month_name[int(key[5:7])])}</td><td>{data["count"]}</td><td>{esc(grouped_text(data["totals"]))}</td></tr>'
            for key,data in sorted(monthly.items())
        )

        product_rows=''.join(
            f'<tr><td>{esc(name)}</td><td>{esc(code)}</td><td>{data["quantity"]}</td><td>{esc(fmt(data["total"],code))}</td></tr>'
            for (name,code),data in sorted(products.items(),key=lambda pair:(pair[0][0].lower(),pair[0][1]))
        ) or '<tr><td colspan="4" class="empty">No products sold in this period.</td></tr>'

        sale_cards=[]
        for sale in sales:
            code=sale.get('currency',DEFAULT_CURRENCY)
            lines=''.join(
                '<tr>'
                f'<td>{esc(row["name"])}</td>'
                f'<td>{row["quantity"]}</td>'
                f'<td>{esc(fmt(row["unit_price_cents"],code))}</td>'
                f'<td>{esc(fmt(row["subtotal_cents"],code))}</td>'
                '</tr>'
                for row in sale['items']
            )
            sale_cards.append(f'''<section class="sale-card">
                <div class="sale-head">
                    <div><strong>{esc(sale['date'])} · {esc(sale['time'])}</strong><span>{esc(sale['customer_name'] or 'Walk-in customer')} · {esc(code)}</span></div>
                    <strong>{esc(fmt(sale['total_cents'],code))}</strong>
                </div>
                <table class="compact"><thead><tr><th>Item</th><th>Qty</th><th>Unit</th><th>Subtotal</th></tr></thead><tbody>{lines}</tbody></table>
                <div class="sale-id">Sale ID: {esc(sale['id'])}</div>
            </section>''')
        sales_html=''.join(sale_cards) or '<div class="empty-panel">No completed sales in this period.</div>'
        monthly_section=''
        if period=='year':
            monthly_section=f'''<section class="panel"><h2>Monthly summary</h2><table><thead><tr><th>Month</th><th>Sales</th><th>Total</th></tr></thead><tbody>{month_rows}</tbody></table></section>'''

        generated=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        brand_logo_uri=logo_data_uri()
        return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SaveSales · {esc(period_label)} statement</title>
<style>
:root{{--bg:#0b1220;--panel:#111827;--panel2:#1f2937;--line:#334155;--blue:#2563eb;--green:#16a34a;--text:#f8fafc;--muted:#94a3b8}}
*{{box-sizing:border-box}} body{{margin:0;background:linear-gradient(135deg,#07101e,#111827);color:var(--text);font-family:Segoe UI,Arial,sans-serif}}
.wrap{{max-width:1180px;margin:auto;padding:42px 24px 64px}} .brand{{display:flex;align-items:center;gap:12px;margin-bottom:28px}}
.brand-logo{{width:92px;height:90px;object-fit:contain;border-radius:18px;box-shadow:0 12px 30px rgba(0,0,0,.28)}} h1{{margin:0;font-size:34px}} .subtitle{{color:var(--muted);margin-top:6px}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:26px 0}} .metric,.panel,.sale-card,.empty-panel{{background:rgba(17,24,39,.94);border:1px solid var(--line);border-radius:16px;box-shadow:0 16px 45px rgba(0,0,0,.18)}}
.metric{{padding:18px}} .metric span{{display:block;color:var(--muted);font-size:13px}} .metric strong{{display:block;font-size:20px;margin-top:6px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}} .panel{{padding:20px;margin-bottom:16px}} h2{{font-size:18px;margin:0 0 14px}}
table{{width:100%;border-collapse:collapse}} th,td{{padding:11px 10px;border-bottom:1px solid #263449;text-align:left}} th{{color:#cbd5e1;font-size:12px;text-transform:uppercase;letter-spacing:.05em}} td:last-child,th:last-child{{text-align:right}}
.sale-card{{padding:18px;margin:12px 0}} .sale-head{{display:flex;justify-content:space-between;gap:20px;align-items:center;margin-bottom:12px}} .sale-head span{{display:block;color:var(--muted);font-size:13px;margin-top:4px}} .compact th,.compact td{{padding:8px}} .sale-id{{color:#64748b;font-size:11px;margin-top:10px}}
.empty,.empty-panel{{color:var(--muted);text-align:center}} .empty-panel{{padding:28px}} .footer{{margin-top:28px;color:#64748b;font-size:12px;line-height:1.6}}
.badge{{display:inline-block;background:#123d2a;color:#86efac;border:1px solid #166534;border-radius:999px;padding:5px 10px;font-size:12px;margin-top:10px}}
@media(max-width:760px){{.cards,.grid{{grid-template-columns:1fr 1fr}}}} @media(max-width:520px){{.cards,.grid{{grid-template-columns:1fr}}.wrap{{padding:24px 14px}}}}
@media print{{body{{background:white;color:#111827}} .metric,.panel,.sale-card{{box-shadow:none;background:white;border-color:#cbd5e1}} .subtitle,.sale-head span,.footer,.sale-id{{color:#475569}} .brand-logo{{box-shadow:none}}}}
</style></head>
<body><main class="wrap">
<div class="brand"><img class="brand-logo" src="{brand_logo_uri}" alt="SaveSales logo"><div><h1>SaveSales</h1><div class="subtitle">Sales statement · {esc(period_label)}</div><div class="badge">Currencies: {esc(currencies_used)}</div></div></div>
<div class="cards">
<div class="metric"><span>Total sales</span><strong>{len(sales)}</strong></div>
<div class="metric"><span>Gross sales</span><strong>{esc(grouped_text(totals))}</strong></div>
<div class="metric"><span>Average sale</span><strong>{esc(grouped_text(averages))}</strong></div>
<div class="metric"><span>Items sold</span><strong>{items_sold}</strong></div>
</div>
{monthly_section}
<div class="grid">
<section class="panel"><h2>Daily summary</h2><table><thead><tr><th>Date</th><th>Sales</th><th>Total</th></tr></thead><tbody>{summary_rows}</tbody></table></section>
<section class="panel"><h2>Product summary</h2><table><thead><tr><th>Product</th><th>Currency</th><th>Qty</th><th>Revenue</th></tr></thead><tbody>{product_rows}</tbody></table></section>
</div>
<section class="panel"><h2>Sale details</h2>{sales_html}</section>
<div class="footer">Generated by SaveSales on {esc(generated)}.<br>Amounts in different currencies are shown separately and are never added together. Changing the store currency does not perform exchange-rate conversion. This file is a sales record/export from SaveSales and is not, by itself, an official tax document or payroll record.</div>
</main></body></html>'''

    def show_receipt(self,sale):
        window=ctk.CTkToplevel(self.app);window.title('Saved sale');window.geometry('540x470');window.transient(self.app)
        receipt_header=ctk.CTkFrame(window,fg_color='transparent');receipt_header.pack(fill='x',padx=20,pady=(16,5))
        if self.brand_logo_small is not None:
            ctk.CTkLabel(receipt_header,text='',image=self.brand_logo_small).pack(side='left',padx=(0,12))
        ctk.CTkLabel(receipt_header,text='Sale receipt',font=('Segoe UI',24,'bold')).pack(side='left')
        sale_currency=sale.get('currency',DEFAULT_CURRENCY)
        ctk.CTkLabel(window,text=f"{sale['date']}  {sale['time']}\n{sale['customer_name'] or 'Walk-in customer'} · {sale_currency}",wraplength=480).pack()
        rows=ctk.CTkScrollableFrame(window,fg_color=BG);rows.pack(fill='both',expand=True,padx=20,pady=15)
        for row in sale['items']:
            ctk.CTkLabel(rows,text=f"{row['name']}\n{row['quantity']} × {money(row['unit_price_cents'],sale_currency)}  =  {money(row['subtotal_cents'],sale_currency)}",anchor='w',justify='left',wraplength=450).pack(fill='x',padx=10,pady=6)
        ctk.CTkLabel(window,text='Total  '+money(sale['total_cents'],sale_currency),font=('Segoe UI',22,'bold')).pack(pady=5)
        ctk.CTkLabel(window,text='Sale ID: '+sale['id'],font=('Segoe UI',10),text_color='#94A3B8').pack(pady=(0,12))
