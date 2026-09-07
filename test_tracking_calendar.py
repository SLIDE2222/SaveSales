"""Actual Tk checks for Daily Tracking; no live store or network writes."""
import os
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from PIL import ImageGrab
import customtkinter as ctk
from shop_ui import ShopUI,GREEN,GRAY

class TrackingCalendarTests(unittest.TestCase):
    def setUp(self):
        if sys.platform=='win32':
            for key,folder in [('TCL_LIBRARY','tcl8.6'),('TK_LIBRARY','tk8.6')]:
                path=Path(sys.base_prefix)/'tcl'/folder
                if path.exists():os.environ.setdefault(key,str(path))
        ctk.set_appearance_mode('dark')
        self.app=ctk.CTk();self.app.geometry('1000x600');self.app.configure(fg_color='#111827')
        sidebar=ctk.CTkFrame(self.app,width=220);sidebar.pack(side='left',fill='y');sidebar.pack_propagate(False)
        self.parent=ctk.CTkFrame(self.app,fg_color='#1F2937');self.parent.pack(side='right',fill='both',expand=True,padx=20,pady=20)
        self.page='tracking'
        self.shop=ShopUI(self.app,self.parent,SimpleNamespace(connected=True),lambda:None,lambda p:setattr(self,'page',p),lambda:self.page)
        self.shop.day.set('2026-09-07')
        self.shop.sales=[self.sale('2026-09-07')]
        self.shop.show_tracking();self.app.update()
    def tearDown(self):
        if self.shop.resize_job:self.app.after_cancel(self.shop.resize_job)
        for job in self.app.tk.call('after','info'):
            self.app.after_cancel(job)
        self.app.destroy()
    def sale(self,date):
        return dict(id=date,created_at=date+'T17:04:43',date=date,time='17:04:43',customer_name='',total_cents=1000,
                    items=[dict(item_id='test',name='Test product',quantity=1,unit_price_cents=1000,subtotal_cents=1000)])
    def descendants(self,widget=None):
        for child in (widget or self.app).winfo_children():
            yield child
            yield from self.descendants(child)
    def button(self,text):
        return next(w for w in self.descendants(self.parent) if isinstance(w,ctk.CTkButton) and w.cget('text')==text)
    def labels(self):return [w.cget('text') for w in self.descendants(self.parent) if isinstance(w,ctk.CTkLabel)]
    def test_show_date_inline_and_live_green_days(self):
        self.button('Show date').invoke();self.app.update()
        self.assertTrue(self.shop.tracking_calendar_open)
        self.assertFalse(any(isinstance(w,ctk.CTkToplevel) for w in self.app.winfo_children()))
        self.assertEqual(self.button('7').cget('fg_color'),GREEN)
        self.assertEqual(self.button('7').cget('border_width'),2)
        self.assertEqual(self.button('8').cget('fg_color'),GRAY)
        self.shop.apply_snapshot({'items':[],'sales':[self.sale('2026-09-07'),self.sale('2026-09-08')]})
        self.assertTrue(self.shop.tracking_calendar_open)
        self.assertEqual(self.button('8').cget('fg_color'),GREEN)
    def test_day_selection_total_and_receipt(self):
        self.button('Show date').invoke();self.button('7').invoke();self.app.update()
        self.assertFalse(self.shop.tracking_calendar_open)
        self.assertEqual(self.shop.day.get(),'2026-09-07')
        self.assertIn('1 sale(s) · R$ 10.00',self.labels())
        self.button('View').invoke();self.app.update()
        popup=next(w for w in self.app.winfo_children() if isinstance(w,ctk.CTkToplevel))
        self.assertEqual(popup.title(),'Saved sale');popup.destroy()
        self.button('Show date').invoke();self.button('8').invoke()
        self.assertIn('0 sale(s) · R$ 0.00',self.labels())
    def test_navigation_six_weeks_fit_and_sync_keeps_month(self):
        self.shop.day.set('2026-08-07');self.button('Show date').invoke();self.app.update()
        # August 2026 spans six calendar rows.
        screenshot=Path('work')/'tracking-calendar.png'
        screenshot.parent.mkdir(exist_ok=True)
        self.app.update()
        ImageGrab.grab(window=self.app.winfo_id()).save(screenshot)
        last=self.button('31')
        self.assertLessEqual(last.winfo_rooty()+last.winfo_height(),self.parent.winfo_rooty()+self.parent.winfo_height()-10)
        for text in ('Mon','Tue','Wed','Thu','Fri','Sat','Sun'):self.assertIn(text,self.labels())
        self.button('▶').invoke();self.assertEqual(self.shop.tracking_month,9)
        self.shop.apply_snapshot({'items':[],'sales':[self.sale('2026-09-08')]})
        self.assertEqual(self.shop.tracking_month,9)
        self.button('◀').invoke();self.assertEqual(self.shop.tracking_month,8)
        self.shop.day.set('2026-12-07');self.button('Show date').invoke();self.button('▶').invoke()
        self.assertEqual((self.shop.tracking_year,self.shop.tracking_month),(2027,1))
        self.button('◀').invoke();self.assertEqual((self.shop.tracking_year,self.shop.tracking_month),(2026,12))
    def test_manual_enter_filters(self):
        self.button('Show date').invoke()
        entry=next(w for w in self.descendants(self.parent) if isinstance(w,ctk.CTkEntry))
        entry.delete(0,'end');entry.insert(0,'2026-9-7');entry.focus_set();self.app.update()
        entry._entry.event_generate('<Return>');self.app.update()
        self.assertEqual(self.shop.day.get(),'2026-09-07')
        self.assertFalse(self.shop.tracking_calendar_open)
        self.assertIn('1 sale(s) · R$ 10.00',self.labels())

if __name__=='__main__':unittest.main()
