import customtkinter as ctk
import queue
from tkinter import filedialog, messagebox
from lan_client import LanClient
from shop_ui import ShopUI
from commerce import CURRENCIES, DEFAULT_CURRENCY
from branding import logo_pil, logo_data_uri
from PIL import ImageTk
import calendar
import html
import os
import sys
import webbrowser

from pathlib import Path
from datetime import datetime, timedelta


# Some Windows virtual environments do not locate the bundled Tcl/Tk scripts.
if sys.platform == 'win32':
    for variable, folder in (('TCL_LIBRARY', 'tcl8.6'), ('TK_LIBRARY', 'tk8.6')):
        library = Path(sys.base_prefix) / 'tcl' / folder
        if library.is_dir():
            os.environ.setdefault(variable, str(library))

ctk.set_appearance_mode("dark")

app = ctk.CTk()
app.geometry("1000x600")
app.title("SaveSales")

# Brand the native window too. Keep a reference so Tk does not garbage-collect it.
try:
    _window_icon = logo_pil().resize((64, 64))
    app._savesales_icon = ImageTk.PhotoImage(_window_icon)
    app.iconphoto(True, app._savesales_icon)
except Exception:
    app._savesales_icon = None


# =========================================================
# COLORS
# =========================================================

background = "#111827"
sidebar_color = "#0F172A"
panel_color = "#1F2937"

blue = "#2563EB"
blue_hover = "#1D4ED8"

green = "#16A34A"
green_hover = "#15803D"

red = "#DC2626"
red_hover = "#B91C1C"

gray = "#374151"
gray_hover = "#4B5563"

yellow = "#CA8A04"

app.configure(fg_color=background)


# =========================================================
# FILES / DATA
# =========================================================

# UI snapshots; the embedded peer service maintains the durable SQLite replica.
employees = []
employee_times = {}
employee_attendance = {}
employee_ids = {}
sync_conflicts = []
store_currency = DEFAULT_CURRENCY
selected_employee = None
current_page = ('items',)
connected = False
last_ui_date = datetime.now().date()
client = LanClient()


def apply_snapshot(data):
    global employees, employee_times, employee_attendance, employee_ids, selected_employee, sync_conflicts, store_currency
    if 'employees' not in data or 'employee_times' not in data:
        return
    shop.apply_snapshot(data)
    incoming_currency = data.get('currency', DEFAULT_CURRENCY)
    store_currency = incoming_currency
    if 'currency_var' in globals():
        currency_var.set(currency_choice_label(incoming_currency))
    incoming_attendance = data.get('employee_attendance', {})
    changed = (employees != data['employees'] or employee_times != data['employee_times'] or
               employee_attendance != incoming_attendance)
    employees, employee_times = data['employees'], data['employee_times']
    employee_attendance = incoming_attendance
    employee_ids = data.get('employee_ids', {})
    sync_conflicts = data.get('conflicts', [])
    conflict_button.configure(text=f'Review time conflicts ({len(sync_conflicts)})')
    if sync_conflicts:
        conflict_button.pack(side='bottom', padx=10, pady=5)
    else:
        conflict_button.pack_forget()
    if selected_employee not in employees:
        selected_employee = None
    if changed:
        if current_page[0] == 'employees':
            open_employees()
        elif current_page[0] == 'employee':
            if current_page[1] in employees:
                open_employee_page(*current_page[1:])
            else:
                open_employees()


def process_network():
    global connected, last_ui_date
    today = datetime.now().date()
    if today != last_ui_date:
        last_ui_date = today
        if current_page[0] == 'employee':
            open_employee_page(*current_page[1:])
    try:
        while True:
            kind, result, callback = client.results.get_nowait()
            connected = kind not in ('offline', 'startup_error')
            connection_label.configure(
                text='● Connected / LAN synced' if connected else '● No SaveSales LAN connection',
                text_color=green if connected else red)
            if kind == 'startup_error':
                messagebox.showerror('SaveSales LAN', result, parent=app)
            if kind == 'ok':
                apply_snapshot(result)
            if callback:
                callback(kind == 'ok', result)
    except queue.Empty:
        pass
    app.after(100, process_network)


def mutation_done(ok, result):
    if not ok:
        messagebox.showerror('SaveSales', result, parent=app)


# =========================================================
# SIDEBAR
# =========================================================

sidebar = ctk.CTkFrame(
    app,
    width=220,
    corner_radius=0,
    fg_color=sidebar_color
)

sidebar.pack(
    side="left",
    fill="y"
)

sidebar.pack_propagate(False)


brand_frame = ctk.CTkFrame(
    sidebar,
    fg_color="transparent"
)

brand_frame.pack(
    fill="x",
    padx=14,
    pady=(14, 18)
)

# Use the real SaveSales mascot/logo instead of the old placeholder S tile.
try:
    _sidebar_logo_source = logo_pil()
    brand_logo = ctk.CTkImage(
        light_image=_sidebar_logo_source,
        dark_image=_sidebar_logo_source,
        size=(174, 170)
    )
    brand_logo_label = ctk.CTkLabel(
        brand_frame,
        text="",
        image=brand_logo,
        fg_color="transparent"
    )
    brand_logo_label.pack(anchor="center")
except Exception:
    # If branding somehow fails, the app remains usable instead of dying at startup.
    ctk.CTkLabel(
        brand_frame,
        text="SaveSales",
        font=("Segoe UI", 25, "bold"),
        text_color="#F8FAFC"
    ).pack(anchor="center", pady=8)


# =========================================================
# MAIN AREA
# =========================================================

main_area = ctk.CTkFrame(
    app,
    corner_radius=15,
    fg_color=panel_color
)

main_area.pack(
    side="right",
    fill="both",
    expand=True,
    padx=20,
    pady=20
)


# =========================================================
# HELPERS
# =========================================================

def clear_page():

    for widget in main_area.winfo_children():

        widget.destroy()


# =========================================================
# ITEMS
# =========================================================

def set_shop_page(page):
    global current_page
    current_page = (page,)


def open_items():
    shop.show_items()


def open_cart():
    shop.show_cart()


def open_tracking():
    shop.show_tracking()


# =========================================================
# ADMIN PASSWORD
# =========================================================

def check_admin_password():

    result = {
        "authorized": None
    }

    password_window = ctk.CTkToplevel(app)

    password_window.title(
        "Admin Access"
    )

    password_window.geometry(
        "400x250"
    )

    password_window.resizable(
        False,
        False
    )

    password_window.transient(app)

    password_window.grab_set()


    title = ctk.CTkLabel(
        password_window,
        text="🔒 Admin Access",
        font=("Arial", 22, "bold")
    )

    title.pack(
        pady=(25, 15)
    )


    # PASSWORD AREA

    password_frame = ctk.CTkFrame(
        password_window,
        fg_color="transparent"
    )

    password_frame.pack(
        padx=30,
        fill="x"
    )


    password_entry = ctk.CTkEntry(
        password_frame,
        placeholder_text="Enter admin password",
        show="●",
        height=42,
        font=("Arial", 15)
    )

    password_entry.pack(
        side="left",
        fill="x",
        expand=True
    )


    password_visible = {
        "value": False
    }


    def toggle_password():

        password_visible["value"] = (
            not password_visible["value"]
        )

        if password_visible["value"]:

            password_entry.configure(
                show=""
            )

            eye_button.configure(
                text="🙈"
            )

        else:

            password_entry.configure(
                show="●"
            )

            eye_button.configure(
                text="👁"
            )


    eye_button = ctk.CTkButton(
        password_frame,
        text="👁",
        width=45,
        height=42,
        command=toggle_password
    )

    eye_button.pack(
        side="right",
        padx=(8, 0)
    )


    # ERROR MESSAGE

    error_label = ctk.CTkLabel(
        password_window,
        text="",
        text_color="#EF4444",
        font=("Arial", 14, "bold")
    )

    error_label.pack(
        pady=(8, 0)
    )


    def verify_password(event=None):

        password = password_entry.get()

        login_button.configure(state="disabled")
        def verified(ok, value):
            if not password_window.winfo_exists():
                return
            login_button.configure(state="normal")
            if ok:
                result["authorized"] = password
                password_window.destroy()
            else:
                error_label.configure(text=str(value), wraplength=340)
                password_entry.focus()
        client.submit('POST', '/admin/verify', {}, password, verified)


    button_frame = ctk.CTkFrame(
        password_window,
        fg_color="transparent"
    )

    button_frame.pack(
        pady=15
    )


    login_button = ctk.CTkButton(
        button_frame,
        text="Confirm",
        width=130,
        command=verify_password
    )

    login_button.pack(
        side="left",
        padx=5
    )


    cancel_button = ctk.CTkButton(
        button_frame,
        text="Cancel",
        width=130,
        fg_color=gray,
        hover_color=gray_hover,
        command=password_window.destroy
    )

    cancel_button.pack(
        side="left",
        padx=5
    )


    password_entry.bind(
        "<Return>",
        verify_password
    )

    password_entry.focus()

    app.wait_window(
        password_window
    )

    return result["authorized"]


# =========================================================
# EMPLOYEE MANAGEMENT
# =========================================================

def add_employee():
    password = check_admin_password()
    if password is None:
        return
    dialog = ctk.CTkInputDialog(text="Employee name:", title="Add Employee")
    name = dialog.get_input()
    if name and name.strip():
        client.submit('POST', '/employees', {'name': name.strip()}, password, mutation_done)


def delete_employee():
    name = selected_employee
    target_ids = employee_ids.get(name, [])
    if not name:
        return
    password = check_admin_password()
    if password is not None:
        client.submit('DELETE', '/employees', {'name': name, 'employee_ids': target_ids}, password, mutation_done)


def select_employee(name):

    global selected_employee

    selected_employee = name

    open_employee_page(
        name
    )


# =========================================================
# CLOCK SYSTEM
# =========================================================

def send_time(employee, action):
    client.submit('POST', '/time-events', {
        'employee': employee, 'action': action, 'employee_ids': employee_ids.get(employee, []),
        'date': datetime.now().strftime('%Y-%m-%d')
    }, callback=mutation_done)


def clock_in(employee):
    send_time(employee, 'clock_in')


def lunch_break(employee):
    today = employee_times.get(employee, {}).get(datetime.now().strftime('%Y-%m-%d'), {})
    send_time(employee, 'break_out' if 'break_in' in today else 'break_in')


def clock_out(employee):
    send_time(employee, 'clock_out')


def edit_day_times(employee, date_key, parent_window=None):
    """Admin-only correction of an employee's saved punches for one date."""
    if parent_window is not None and parent_window.winfo_exists():
        try:
            parent_window.grab_release()
        except Exception:
            pass

    password = check_admin_password()

    if parent_window is not None and parent_window.winfo_exists():
        try:
            parent_window.grab_set()
        except Exception:
            pass

    if password is None:
        return

    current = employee_times.get(employee, {}).get(date_key, {})

    window = ctk.CTkToplevel(app)
    window.title("Edit Employee Punches")
    window.geometry("470x500")
    window.resizable(False, False)
    window.transient(parent_window if parent_window is not None and parent_window.winfo_exists() else app)
    window.grab_set()

    formatted_date = datetime.strptime(date_key, "%Y-%m-%d").strftime("%B %d, %Y")

    ctk.CTkLabel(
        window,
        text="Edit employee punches",
        font=("Arial", 24, "bold")
    ).pack(anchor="w", padx=28, pady=(24, 3))

    ctk.CTkLabel(
        window,
        text=f"{employee}  ·  {formatted_date}",
        font=("Arial", 14),
        text_color="#9CA3AF"
    ).pack(anchor="w", padx=28, pady=(0, 16))

    ctk.CTkLabel(
        window,
        text="Use HH:MM or HH:MM:SS. Leave a field blank to remove that punch.",
        font=("Arial", 12),
        text_color="#9CA3AF",
        wraplength=410,
        justify="left"
    ).pack(anchor="w", padx=28, pady=(0, 12))

    form = ctk.CTkFrame(window, fg_color="#111827", corner_radius=10)
    form.pack(fill="x", padx=28, pady=(0, 10))

    fields = {}
    definitions = [
        ("clock_in", "Clock In"),
        ("break_in", "Lunch Break In"),
        ("break_out", "Lunch Break Out"),
        ("clock_out", "Clock Out"),
    ]

    for key, label_text in definitions:
        row = ctk.CTkFrame(form, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=8)
        ctk.CTkLabel(row, text=label_text, width=145, anchor="w", font=("Arial", 14, "bold")).pack(side="left")
        entry = ctk.CTkEntry(row, width=190, height=36, placeholder_text="HH:MM")
        entry.pack(side="right")
        if current.get(key):
            entry.insert(0, current[key])
        fields[key] = entry

    error_label = ctk.CTkLabel(
        window,
        text="",
        text_color="#F87171",
        font=("Arial", 12, "bold"),
        wraplength=410
    )
    error_label.pack(fill="x", padx=28, pady=(4, 2))

    def normalize_time(value):
        value = value.strip()
        if not value:
            return None
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                parsed = datetime.strptime(value, fmt)
                return parsed.strftime("%H:%M:%S")
            except ValueError:
                pass
        raise ValueError("Use HH:MM or HH:MM:SS, for example 08:30 or 08:30:15.")

    def save_changes():
        try:
            values = {key: normalize_time(entry.get()) for key, entry in fields.items()}
            present = {key: value for key, value in values.items() if value is not None}
            if present and 'clock_in' not in present:
                raise ValueError("Clock In is required when another punch is filled.")
            if 'break_out' in present and 'break_in' not in present:
                raise ValueError("Lunch Break In is required before Lunch Break Out.")
            if 'break_in' in present and 'clock_out' in present and 'break_out' not in present:
                raise ValueError("Lunch Break Out is required before Clock Out.")
            ordered = [present[key] for key in ('clock_in','break_in','break_out','clock_out') if key in present]
            if any(a > b for a, b in zip(ordered, ordered[1:])):
                raise ValueError("Punch times must be in chronological order.")
        except ValueError as exc:
            error_label.configure(text=str(exc))
            return

        attendance_status = employee_attendance.get(employee, {}).get(date_key)
        request_password = password
        clear_attendance = bool(present) and attendance_status in ('no_show', 'sick_leave')

        if clear_attendance:
            label = 'No show' if attendance_status == 'no_show' else 'Sick leave'
            if not messagebox.askyesno(
                "Override attendance status",
                f"This date is currently marked as {label}.\n\n"
                "If the employee actually came to work, SaveSales can clear that status and save these punches.\n\n"
                "Continue?",
                parent=window
            ):
                return

            # Require admin approval AGAIN for changing an absence into a worked day.
            try:
                window.grab_release()
            except Exception:
                pass
            request_password = check_admin_password()
            if window.winfo_exists():
                try:
                    window.grab_set()
                except Exception:
                    pass
            if request_password is None:
                return

        save_button.configure(state="disabled", text="Saving…")
        error_label.configure(text="")

        payload = {
            'employee': employee,
            'employee_ids': employee_ids.get(employee, []),
            'date': date_key,
            'values': values,
            'clear_attendance': clear_attendance,
        }

        def done(ok, result):
            if not window.winfo_exists():
                return
            if ok:
                window.destroy()
                message = f"Punches for {employee} on {date_key} were updated."
                if clear_attendance:
                    message += "\nThe No show/Sick leave status was cleared."
                messagebox.showinfo(
                    "Employee punches updated",
                    message,
                    parent=parent_window if parent_window is not None and parent_window.winfo_exists() else app
                )
            else:
                save_button.configure(state="normal", text="Save changes")
                error_label.configure(text=str(result))

        client.submit('POST', '/time-events/edit', payload, request_password, done)

    buttons = ctk.CTkFrame(window, fg_color="transparent")
    buttons.pack(fill="x", padx=28, pady=(8, 20))

    ctk.CTkButton(
        buttons,
        text="Cancel",
        width=130,
        fg_color=gray,
        hover_color=gray_hover,
        command=window.destroy
    ).pack(side="left")

    save_button = ctk.CTkButton(
        buttons,
        text="Save changes",
        width=145,
        fg_color=blue,
        hover_color=blue_hover,
        command=save_changes
    )
    save_button.pack(side="right")


def set_day_attendance_status(employee, date_key, status, parent_window=None):
    """Admin-only attendance marker for dates without punches."""
    if parent_window is not None and parent_window.winfo_exists():
        try:
            parent_window.grab_release()
        except Exception:
            pass

    password = check_admin_password()

    if parent_window is not None and parent_window.winfo_exists():
        try:
            parent_window.grab_set()
        except Exception:
            pass

    if password is None:
        return

    labels = {
        'no_show': 'No show',
        'sick_leave': 'Sick leave',
        'clear': 'Clear attendance status',
    }
    label = labels[status]
    if status == 'clear':
        prompt = f"Clear the attendance status for {employee} on {date_key}?"
    else:
        prompt = f"Mark {employee} as {label} on {date_key}?"

    if not messagebox.askyesno(
        "Attendance status",
        prompt,
        parent=parent_window if parent_window is not None and parent_window.winfo_exists() else app
    ):
        return

    payload = {
        'employee': employee,
        'employee_ids': employee_ids.get(employee, []),
        'date': date_key,
        'status': status,
    }

    def done(ok, result):
        if ok:
            messagebox.showinfo(
                "Attendance updated",
                f"{employee} · {date_key}\n{labels[status]}",
                parent=parent_window if parent_window is not None and parent_window.winfo_exists() else app
            )
        else:
            messagebox.showerror(
                "Attendance status",
                str(result),
                parent=parent_window if parent_window is not None and parent_window.winfo_exists() else app
            )

    client.submit('POST', '/attendance-status', payload, password, done)


def show_day_details(employee, date_key):
    day_data = employee_times.get(employee, {}).get(date_key, {})
    attendance_status = employee_attendance.get(employee, {}).get(date_key)

    details_window = ctk.CTkToplevel(app)
    details_window.title("Shift Details")
    details_window.geometry("500x585")
    details_window.resizable(False, False)
    details_window.transient(app)
    details_window.grab_set()

    formatted_date = datetime.strptime(date_key, "%Y-%m-%d").strftime("%B %d, %Y")

    title = ctk.CTkLabel(details_window, text=employee, font=("Arial", 24, "bold"))
    title.pack(pady=(22, 4))

    date_label = ctk.CTkLabel(details_window, text=formatted_date, font=("Arial", 16), text_color="#9CA3AF")
    date_label.pack(pady=(0, 12))

    status_names = {'no_show': 'No show', 'sick_leave': 'Sick leave'}
    status_colors = {'no_show': red, 'sick_leave': yellow}
    status_label = ctk.CTkLabel(
        details_window,
        text=status_names.get(attendance_status, 'No attendance status'),
        font=("Arial", 14, "bold"),
        text_color=status_colors.get(attendance_status, '#9CA3AF')
    )
    status_label.pack(pady=(0, 10))

    details = ctk.CTkFrame(details_window, fg_color="#111827", corner_radius=10)
    details.pack(fill="x", padx=30, pady=8)

    times = [
        ("🟢 Clock In", day_data.get("clock_in", "--:--")),
        ("🍴 Lunch Break In", day_data.get("break_in", "--:--")),
        ("🍴 Lunch Break Out", day_data.get("break_out", "--:--")),
        ("🔴 Clock Out", day_data.get("clock_out", "--:--"))
    ]

    detail_labels = []
    for label_text, time_text in times:
        row = ctk.CTkFrame(details, fg_color="transparent")
        row.pack(fill="x", padx=15, pady=8)
        ctk.CTkLabel(row, text=label_text, font=("Arial", 14, "bold")).pack(side="left")
        time_label = ctk.CTkLabel(row, text=time_text, font=("Arial", 14))
        time_label.pack(side="right")
        detail_labels.append(time_label)

    ctk.CTkLabel(
        details_window,
        text="Attendance override",
        font=("Arial", 13, "bold"),
        text_color="#CBD5E1"
    ).pack(pady=(12, 5))

    attendance_buttons = ctk.CTkFrame(details_window, fg_color="transparent")
    attendance_buttons.pack(pady=(0, 8))
    ctk.CTkButton(
        attendance_buttons, text="No show", width=115, fg_color=red, hover_color=red_hover,
        command=lambda: set_day_attendance_status(employee, date_key, 'no_show', details_window)
    ).pack(side="left", padx=4)
    ctk.CTkButton(
        attendance_buttons, text="Sick leave", width=115, fg_color=yellow, hover_color="#A16207",
        command=lambda: set_day_attendance_status(employee, date_key, 'sick_leave', details_window)
    ).pack(side="left", padx=4)
    ctk.CTkButton(
        attendance_buttons, text="Clear status", width=115, fg_color=gray, hover_color=gray_hover,
        command=lambda: set_day_attendance_status(employee, date_key, 'clear', details_window)
    ).pack(side="left", padx=4)

    def refresh_details():
        if not details_window.winfo_exists():
            return
        data = employee_times.get(employee, {}).get(date_key, {})
        for widget, key in zip(detail_labels, ('clock_in', 'break_in', 'break_out', 'clock_out')):
            widget.configure(text=data.get(key, '--:--'))
        current_status = employee_attendance.get(employee, {}).get(date_key)
        status_label.configure(
            text=status_names.get(current_status, 'No attendance status'),
            text_color=status_colors.get(current_status, '#9CA3AF')
        )
        title.configure(text=employee if employee in employees else employee + ' (deleted)')
        details_window.after(500, refresh_details)
    refresh_details()

    buttons = ctk.CTkFrame(details_window, fg_color="transparent")
    buttons.pack(pady=12)

    ctk.CTkButton(
        buttons, text="✎ Edit punches", width=140, fg_color=blue, hover_color=blue_hover,
        command=lambda: edit_day_times(employee, date_key, details_window)
    ).pack(side="left", padx=5)

    ctk.CTkButton(
        buttons, text="Close", width=120, fg_color=gray, hover_color=gray_hover,
        command=details_window.destroy
    ).pack(side="left", padx=5)


# =========================================================
# EMPLOYEE WORK-TIME EXPORT
# =========================================================

def _duration_text(total_seconds):
    total_seconds = max(0, int(total_seconds or 0))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _shift_totals(day, attendance_status=None):
    """Return auditable worked/break seconds without guessing incomplete punches."""
    values = {key: day.get(key) for key in ('clock_in', 'break_in', 'break_out', 'clock_out')}
    if attendance_status in ('no_show', 'sick_leave') and not any(values.values()):
        return {
            **values,
            'status': 'No show' if attendance_status == 'no_show' else 'Sick leave',
            'gross_seconds': None,
            'break_seconds': None,
            'worked_seconds': None,
        }
    if not any(values.values()):
        return None

    status = 'Complete'
    worked_seconds = None
    break_seconds = None
    gross_seconds = None

    if not values['clock_in'] or not values['clock_out']:
        status = 'Incomplete punches'
    elif bool(values['break_in']) != bool(values['break_out']):
        status = 'Incomplete lunch'
    else:
        try:
            start = datetime.strptime(values['clock_in'], '%H:%M:%S')
            end = datetime.strptime(values['clock_out'], '%H:%M:%S')
            gross_seconds = int((end - start).total_seconds())
            if gross_seconds < 0:
                raise ValueError

            break_seconds = 0
            if values['break_in'] and values['break_out']:
                lunch_start = datetime.strptime(values['break_in'], '%H:%M:%S')
                lunch_end = datetime.strptime(values['break_out'], '%H:%M:%S')
                break_seconds = int((lunch_end - lunch_start).total_seconds())
                if break_seconds < 0:
                    raise ValueError

            worked_seconds = gross_seconds - break_seconds
            if worked_seconds < 0:
                raise ValueError
        except (ValueError, TypeError):
            status = 'Invalid time order'
            worked_seconds = break_seconds = gross_seconds = None

    return {
        **values,
        'status': status,
        'gross_seconds': gross_seconds,
        'break_seconds': break_seconds,
        'worked_seconds': worked_seconds,
    }


def _period_bounds(period, reference):
    if period == 'week':
        start = reference - timedelta(days=reference.weekday())
        end = start + timedelta(days=6)
        label = f"Week · {start.strftime('%B %d, %Y')} to {end.strftime('%B %d, %Y')}"
    elif period == 'month':
        start = reference.replace(day=1)
        end = reference.replace(day=calendar.monthrange(reference.year, reference.month)[1])
        label = reference.strftime('%B %Y')
    elif period == 'year':
        start = reference.replace(month=1, day=1)
        end = reference.replace(month=12, day=31)
        label = str(reference.year)
    else:
        raise ValueError('Unknown export period.')
    return start, end, label


def _build_employee_time_statement(employee, period, reference):
    start, end, period_label = _period_bounds(period, reference)
    history = employee_times.get(employee, {})
    attendance = employee_attendance.get(employee, {})
    rows = []

    cursor = start
    while cursor <= end:
        key = cursor.strftime('%Y-%m-%d')
        day = history.get(key, {})
        summary = _shift_totals(day, attendance.get(key))
        if summary:
            rows.append((cursor, key, summary))
        cursor += timedelta(days=1)

    completed = [row for row in rows if row[2]['status'] == 'Complete']
    no_shows = [row for row in rows if row[2]['status'] == 'No show']
    sick_leave = [row for row in rows if row[2]['status'] == 'Sick leave']
    incomplete = [row for row in rows if row[2]['status'] not in ('Complete', 'No show', 'Sick leave')]
    total_worked = sum(row[2]['worked_seconds'] or 0 for row in completed)
    total_break = sum(row[2]['break_seconds'] or 0 for row in completed)
    total_gross = sum(row[2]['gross_seconds'] or 0 for row in completed)
    average = total_worked // len(completed) if completed else 0

    esc = html.escape
    employee_html = esc(employee)
    generated = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    brand_logo_uri = logo_data_uri()

    table_rows = []
    for date_value, _, row in rows:
        status_class = ('ok' if row['status'] == 'Complete' else
                        'noshow' if row['status'] == 'No show' else
                        'sick' if row['status'] == 'Sick leave' else 'warn')
        table_rows.append(
            '<tr>'
            f'<td><strong>{date_value.strftime("%a, %b %d, %Y")}</strong></td>'
            f'<td>{esc(row["clock_in"] or "—")}</td>'
            f'<td>{esc(row["break_in"] or "—")}</td>'
            f'<td>{esc(row["break_out"] or "—")}</td>'
            f'<td>{esc(row["clock_out"] or "—")}</td>'
            f'<td>{_duration_text(row["break_seconds"]) if row["break_seconds"] is not None else "—"}</td>'
            f'<td><strong>{_duration_text(row["worked_seconds"]) if row["worked_seconds"] is not None else "—"}</strong></td>'
            f'<td><span class="status {status_class}">{esc(row["status"])}</span></td>'
            '</tr>'
        )

    if not table_rows:
        table_rows.append('<tr><td colspan="8" class="empty">No punches or attendance statuses recorded in this period.</td></tr>')

    breakdown_html = ''
    if period == 'month':
        groups = {}
        for date_value, _, row in completed:
            monday = date_value - timedelta(days=date_value.weekday())
            groups.setdefault(monday, 0)
            groups[monday] += row['worked_seconds'] or 0
        cards = ''.join(
            f'<div class="mini"><span>{monday.strftime("%b %d")} – {(monday + timedelta(days=6)).strftime("%b %d")}</span><strong>{_duration_text(seconds)}</strong></div>'
            for monday, seconds in sorted(groups.items())
        ) or '<div class="empty small">No completed shifts.</div>'
        breakdown_html = f'<section><h2>Weekly breakdown</h2><div class="mini-grid">{cards}</div></section>'
    elif period == 'year':
        groups = {}
        for date_value, _, row in completed:
            month_key = date_value.replace(day=1)
            groups.setdefault(month_key, 0)
            groups[month_key] += row['worked_seconds'] or 0
        cards = ''.join(
            f'<div class="mini"><span>{month_key.strftime("%B")}</span><strong>{_duration_text(seconds)}</strong></div>'
            for month_key, seconds in sorted(groups.items())
        ) or '<div class="empty small">No completed shifts.</div>'
        breakdown_html = f'<section><h2>Monthly breakdown</h2><div class="mini-grid">{cards}</div></section>'

    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SaveSales · {employee_html} · {esc(period_label)}</title>
<style>
:root{{--ink:#0f172a;--muted:#64748b;--line:#e2e8f0;--blue:#2563eb;--navy:#0f172a;--green:#16a34a;--amber:#d97706;--paper:#fff;}}
*{{box-sizing:border-box}} body{{margin:0;background:#eef2f7;color:var(--ink);font:14px/1.45 "Segoe UI",Arial,sans-serif}}
.page{{max-width:1180px;margin:32px auto;background:var(--paper);border-radius:20px;overflow:hidden;box-shadow:0 20px 55px rgba(15,23,42,.12)}}
.hero{{background:linear-gradient(135deg,#0f172a,#1e3a8a);color:white;padding:34px 40px}}
.brand{{display:flex;align-items:center;gap:14px;font-size:15px;font-weight:700;letter-spacing:.02em}} .brand-logo{{width:88px;height:86px;object-fit:contain;border-radius:16px;box-shadow:0 10px 25px rgba(0,0,0,.22)}}
h1{{margin:22px 0 5px;font-size:31px}} .hero p{{margin:0;color:#cbd5e1;font-size:15px}}
.content{{padding:30px 40px 42px}} .summary{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:12px;margin-bottom:28px}}
.card{{border:1px solid var(--line);border-radius:14px;padding:16px;background:#f8fafc}} .card span{{display:block;color:var(--muted);font-size:12px;margin-bottom:6px}} .card strong{{font-size:21px}}
h2{{font-size:18px;margin:27px 0 12px}} .table-wrap{{overflow:auto;border:1px solid var(--line);border-radius:14px}}
table{{width:100%;border-collapse:collapse;min-width:900px}} th{{background:#f1f5f9;text-align:left;color:#475569;font-size:12px;text-transform:uppercase;letter-spacing:.04em}} th,td{{padding:12px 13px;border-bottom:1px solid var(--line);white-space:nowrap}} tr:last-child td{{border-bottom:0}}
.status{{display:inline-block;border-radius:999px;padding:4px 9px;font-size:12px;font-weight:700}} .status.ok{{background:#dcfce7;color:#166534}} .status.warn{{background:#ffedd5;color:#9a3412}} .status.noshow{{background:#fee2e2;color:#991b1b}} .status.sick{{background:#fef3c7;color:#92400e}}
.mini-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:10px}} .mini{{border:1px solid var(--line);border-radius:12px;padding:12px 14px;display:flex;justify-content:space-between;gap:15px;background:#f8fafc}} .mini span{{color:var(--muted)}}
.empty{{text-align:center;color:var(--muted);padding:26px!important}} .empty.small{{text-align:left;padding:0!important}}
.note{{margin-top:28px;padding:14px 16px;border-left:4px solid var(--blue);background:#eff6ff;color:#334155;border-radius:8px}} footer{{margin-top:28px;color:#94a3b8;font-size:12px}}
@media(max-width:800px){{.page{{margin:0;border-radius:0}}.content,.hero{{padding:24px}}.summary{{grid-template-columns:1fr 1fr}}}}
@media print{{body{{background:white}}.page{{margin:0;max-width:none;box-shadow:none;border-radius:0}}.hero{{background:white!important;color:#0f172a;border-bottom:2px solid #0f172a}}.hero p{{color:#475569}}.brand-logo{{box-shadow:none}}}}
</style>
</head>
<body><main class="page">
<header class="hero"><div class="brand"><img class="brand-logo" src="{brand_logo_uri}" alt="SaveSales logo"><span>SaveSales</span></div><h1>Employee work-time statement</h1><p>{employee_html} · {esc(period_label)} · {start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}</p></header>
<div class="content">
<div class="summary">
<div class="card"><span>Completed shifts</span><strong>{len(completed)}</strong></div>
<div class="card"><span>No shows</span><strong>{len(no_shows)}</strong></div>
<div class="card"><span>Sick leave</span><strong>{len(sick_leave)}</strong></div>
<div class="card"><span>Total worked</span><strong>{_duration_text(total_worked)}</strong></div>
<div class="card"><span>Total lunch / breaks</span><strong>{_duration_text(total_break)}</strong></div>
<div class="card"><span>Gross clocked span</span><strong>{_duration_text(total_gross)}</strong></div>
<div class="card"><span>Average completed shift</span><strong>{_duration_text(average)}</strong></div>
</div>
<section><h2>Recorded shifts</h2><div class="table-wrap"><table><thead><tr><th>Date</th><th>Clock in</th><th>Lunch in</th><th>Lunch out</th><th>Clock out</th><th>Break</th><th>Worked</th><th>Status</th></tr></thead><tbody>{''.join(table_rows)}</tbody></table></div></section>
{breakdown_html}
<div class="note"><strong>Payroll review:</strong> {len(incomplete)} incomplete or invalid record(s), {len(no_shows)} no show(s), and {len(sick_leave)} sick-leave day(s). Attendance-status days are included in the statement with zero worked time; incomplete records are not included in worked-time totals.</div>
<footer>Generated by SaveSales on {generated}. This statement reflects the punches stored in SaveSales at generation time.</footer>
</div></main></body></html>'''


def export_employee_time_statement(employee, default_year=None, default_month=None):
    """Require admin access, then let the admin export week/month/year HTML."""
    password = check_admin_password()
    if password is None:
        return

    now = datetime.now()
    year = default_year or now.year
    month = default_month or now.month
    day = min(now.day, calendar.monthrange(year, month)[1])

    window = ctk.CTkToplevel(app)
    window.title("Export Employee Time")
    window.geometry("500x360")
    window.resizable(False, False)
    window.transient(app)
    window.grab_set()

    ctk.CTkLabel(window, text="Export worked-time statement", font=("Arial", 24, "bold")).pack(anchor="w", padx=28, pady=(24, 4))
    ctk.CTkLabel(window, text=employee, font=("Arial", 15), text_color="#9CA3AF").pack(anchor="w", padx=28, pady=(0, 18))
    ctk.CTkLabel(window, text="Reference date", font=("Arial", 13, "bold")).pack(anchor="w", padx=28)

    date_entry = ctk.CTkEntry(window, height=38)
    date_entry.pack(fill="x", padx=28, pady=(6, 4))
    date_entry.insert(0, f"{year:04d}-{month:02d}-{day:02d}")

    ctk.CTkLabel(
        window,
        text="Choose Week, Month, or Year. The selected period is calculated from this date.",
        text_color="#9CA3AF",
        font=("Arial", 12),
        wraplength=440,
        justify="left"
    ).pack(anchor="w", padx=28, pady=(3, 14))

    error_label = ctk.CTkLabel(window, text="", text_color="#F87171", font=("Arial", 12, "bold"))
    error_label.pack(fill="x", padx=28, pady=(0, 5))

    def do_export(period):
        try:
            reference = datetime.strptime(date_entry.get().strip(), "%Y-%m-%d").date()
        except ValueError:
            error_label.configure(text="Use a valid date in YYYY-MM-DD format.")
            return
        try:
            statement = _build_employee_time_statement(employee, period, reference)
            start, end, _ = _period_bounds(period, reference)
        except Exception as exc:
            error_label.configure(text=f"Could not build statement: {exc}")
            return

        safe_employee = ''.join(ch if ch.isalnum() or ch in ('-', '_') else '_' for ch in employee).strip('_') or 'employee'
        if period == 'week':
            period_name = f"week_{start.strftime('%Y-%m-%d')}_to_{end.strftime('%Y-%m-%d')}"
        elif period == 'month':
            period_name = reference.strftime('%Y-%m')
        else:
            period_name = reference.strftime('%Y')

        # Release the CustomTkinter modal grab while Windows owns the native Save dialog.
        # Without this, the file picker can end up blocked/hidden on some Windows setups.
        try:
            window.grab_release()
        except Exception:
            pass
        try:
            path = filedialog.asksaveasfilename(
                parent=window,
                title="Save employee time statement",
                initialfile=f"SaveSales_{safe_employee}_{period_name}.html",
                defaultextension=".html",
                filetypes=[("HTML statement", "*.html"), ("All files", "*.*")]
            )
        finally:
            if window.winfo_exists():
                try:
                    window.grab_set()
                except Exception:
                    pass
        if not path:
            return

        try:
            target = Path(path).expanduser()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(statement, encoding="utf-8")
        except Exception as exc:
            error_label.configure(text=f"Could not save file: {exc}")
            return

        window.destroy()
        messagebox.showinfo("Statement exported", f"Employee time statement saved to:\n{target}", parent=app)
        try:
            if sys.platform == 'win32':
                os.startfile(str(target))
            else:
                webbrowser.open(target.resolve().as_uri())
        except OSError:
            pass

    period_buttons = ctk.CTkFrame(window, fg_color="transparent")
    period_buttons.pack(fill="x", padx=28, pady=8)

    ctk.CTkButton(period_buttons, text="Export week", width=130, height=40, fg_color=blue, hover_color=blue_hover, command=lambda: do_export('week')).pack(side="left")
    ctk.CTkButton(period_buttons, text="Export month", width=130, height=40, fg_color=blue, hover_color=blue_hover, command=lambda: do_export('month')).pack(side="left", padx=8)
    ctk.CTkButton(period_buttons, text="Export year", width=130, height=40, fg_color=blue, hover_color=blue_hover, command=lambda: do_export('year')).pack(side="left")

    ctk.CTkButton(window, text="Cancel", width=120, fg_color=gray, hover_color=gray_hover, command=window.destroy).pack(pady=(12, 20))


# =========================================================
# EMPLOYEE CLOCK PAGE
# =========================================================

def open_employee_page(employee, year=None, month=None):
    global current_page
    current_page = ('employee', employee, year, month)
    clear_page()

    now = datetime.now()

    if year is None:
        year = now.year

    if month is None:
        month = now.month

    # -----------------------------------------------------
    # TOP
    # -----------------------------------------------------
    top_bar = ctk.CTkFrame(main_area, fg_color="transparent")
    top_bar.pack(fill="x", padx=30, pady=(20, 10))

    back_button = ctk.CTkButton(
        top_bar,
        text="← Back",
        width=90,
        fg_color=gray,
        hover_color=gray_hover,
        command=open_employees
    )
    back_button.pack(side="left")

    employee_name = ctk.CTkLabel(
        top_bar,
        text="👤  " + employee,
        font=("Arial", 28, "bold")
    )
    employee_name.pack(side="left", padx=20)

    export_time_button = ctk.CTkButton(
        top_bar,
        text="⇩ Export time",
        width=120,
        fg_color=gray,
        hover_color=gray_hover,
        command=lambda: export_employee_time_statement(employee, year, month)
    )
    export_time_button.pack(side="right")

    edit_today_button = ctk.CTkButton(
        top_bar,
        text="✎ Edit today's punches",
        width=155,
        fg_color=gray,
        hover_color=gray_hover,
        command=lambda: edit_day_times(employee, datetime.now().strftime("%Y-%m-%d"))
    )
    edit_today_button.pack(side="right", padx=(0, 8))

    # -----------------------------------------------------
    # TODAY'S DATA
    # -----------------------------------------------------
    today_key = now.strftime("%Y-%m-%d")
    today_data = employee_times.get(employee, {}).get(today_key, {})
    today_attendance = employee_attendance.get(employee, {}).get(today_key)

    clock_in_time = today_data.get("clock_in", "--:--")
    break_in_time = today_data.get("break_in", "--:--")
    break_out_time = today_data.get("break_out", "--:--")
    clock_out_time = today_data.get("clock_out", "--:--")

    # -----------------------------------------------------
    # CLOCK BUTTONS
    # -----------------------------------------------------
    clock_frame = ctk.CTkFrame(main_area, fg_color="transparent")
    clock_frame.pack(pady=(5, 15))

    clock_in_button = ctk.CTkButton(
        clock_frame,
        text="🟢 Clock In",
        width=165,
        height=48,
        font=("Arial", 16, "bold"),
        fg_color=green,
        hover_color=green_hover,
        command=lambda: clock_in(employee)
    )
    clock_in_button.pack(side="left", padx=6)

    lunch_button = ctk.CTkButton(
        clock_frame,
        text="🍴 Lunch Break",
        width=165,
        height=48,
        font=("Arial", 16, "bold"),
        fg_color="#D97706",
        hover_color="#B45309",
        command=lambda: lunch_break(employee)
    )
    lunch_button.pack(side="left", padx=6)

    clock_out_button = ctk.CTkButton(
        clock_frame,
        text="🔴 Clock Out",
        width=165,
        height=48,
        font=("Arial", 16, "bold"),
        fg_color=red,
        hover_color=red_hover,
        command=lambda: clock_out(employee)
    )
    clock_out_button.pack(side="left", padx=6)

    # Button states.
    if clock_in_time != "--:--":
        clock_in_button.configure(state="disabled", text="✓ Clocked In")
    else:
        lunch_button.configure(state="disabled")
        clock_out_button.configure(state="disabled")

    if break_in_time != "--:--" and break_out_time == "--:--":
        lunch_button.configure(text="🍴 End Lunch Break")
        clock_out_button.configure(state="disabled")
    elif break_in_time != "--:--" and break_out_time != "--:--":
        lunch_button.configure(state="disabled", text="✓ Lunch Completed")

    if clock_out_time != "--:--":
        clock_out_button.configure(state="disabled", text="✓ Clocked Out")
        lunch_button.configure(state="disabled")

    if today_attendance in ('no_show', 'sick_leave'):
        clock_in_button.configure(state="disabled")
        lunch_button.configure(state="disabled")
        clock_out_button.configure(state="disabled")

    # -----------------------------------------------------
    # TODAY STATUS
    # -----------------------------------------------------
    status_frame = ctk.CTkFrame(
        main_area,
        fg_color="#111827",
        corner_radius=10
    )
    status_frame.pack(padx=30, pady=(0, 15), fill="x")

    today_title = ctk.CTkLabel(
        status_frame,
        text="Today",
        font=("Arial", 16, "bold")
    )
    today_title.pack(side="left", padx=(20, 10), pady=12)

    today_date = now.strftime("%A, %B %d, %Y").replace(" 0", " ")
    today_date_label = ctk.CTkLabel(
        status_frame,
        text=today_date,
        font=("Arial", 14),
        text_color="#94A3B8"
    )
    today_date_label.pack(side="left", padx=(0, 20), pady=12)

    if today_attendance in ('no_show', 'sick_leave'):
        attendance_text = 'No show' if today_attendance == 'no_show' else 'Sick leave'
        attendance_color = red if today_attendance == 'no_show' else yellow
        ctk.CTkLabel(
            status_frame,
            text=attendance_text,
            font=("Arial", 13, "bold"),
            text_color=attendance_color
        ).pack(side="left", padx=(0, 12), pady=12)

    times_label = ctk.CTkLabel(
        status_frame,
        text=(
            f"In: {clock_in_time}     "
            f"Lunch: {break_in_time} → {break_out_time}     "
            f"Out: {clock_out_time}"
        ),
        font=("Arial", 14)
    )
    times_label.pack(side="right", padx=20)

    # -----------------------------------------------------
    # CALENDAR
    # -----------------------------------------------------
    calendar_panel = ctk.CTkFrame(
        main_area,
        fg_color="#111827",
        corner_radius=12
    )
    calendar_panel.pack(
        fill="both",
        expand=True,
        padx=30,
        pady=(0, 25)
    )

    # -----------------------------------------------------
    # MONTH NAVIGATION
    # -----------------------------------------------------
    calendar_header = ctk.CTkFrame(calendar_panel, fg_color="transparent")
    calendar_header.pack(pady=(15, 8))

    def previous_month():
        new_month = month - 1
        new_year = year

        if new_month == 0:
            new_month = 12
            new_year -= 1

        open_employee_page(employee, new_year, new_month)

    def next_month():
        new_month = month + 1
        new_year = year

        if new_month == 13:
            new_month = 1
            new_year += 1

        open_employee_page(employee, new_year, new_month)

    previous_button = ctk.CTkButton(
        calendar_header,
        text="◀",
        width=38,
        height=32,
        fg_color=gray,
        hover_color=gray_hover,
        command=previous_month
    )
    previous_button.pack(side="left", padx=10)

    month_name = calendar.month_name[month]

    month_label = ctk.CTkLabel(
        calendar_header,
        text=f"{month_name}  {year}",
        font=("Arial", 20, "bold"),
        width=170
    )
    month_label.pack(side="left")

    next_button = ctk.CTkButton(
        calendar_header,
        text="▶",
        width=38,
        height=32,
        fg_color=gray,
        hover_color=gray_hover,
        command=next_month
    )
    next_button.pack(side="left", padx=10)

    # -----------------------------------------------------
    # CALENDAR GRID
    # -----------------------------------------------------
    calendar_grid = ctk.CTkFrame(calendar_panel, fg_color="transparent")
    calendar_grid.pack(padx=20, pady=5)

    weekday_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    for column, weekday in enumerate(weekday_names):
        label = ctk.CTkLabel(
            calendar_grid,
            text=weekday,
            width=65,
            font=("Arial", 12, "bold"),
            text_color="#9CA3AF"
        )
        label.grid(row=0, column=column, padx=3, pady=(0, 6))

    month_calendar = calendar.monthcalendar(year, month)

    for row_index, week in enumerate(month_calendar, start=1):
        for column_index, day in enumerate(week):
            if day == 0:
                empty = ctk.CTkLabel(
                    calendar_grid,
                    text="",
                    width=55,
                    height=38
                )
                empty.grid(
                    row=row_index,
                    column=column_index,
                    padx=4,
                    pady=4
                )
                continue

            date_key = f"{year}-{month:02d}-{day:02d}"
            day_data = employee_times.get(employee, {}).get(date_key, {})

            has_in = "clock_in" in day_data
            has_out = "clock_out" in day_data
            attendance_status = employee_attendance.get(employee, {}).get(date_key)

            if attendance_status == 'no_show':
                day_color = red
            elif attendance_status == 'sick_leave':
                day_color = yellow
            elif has_in and has_out:
                day_color = green
            elif has_in:
                day_color = "#D97706"
            else:
                day_color = gray

            day_box = ctk.CTkButton(
                calendar_grid,
                text=str(day),
                width=55,
                height=38,
                fg_color=day_color,
                hover_color=blue_hover,
                corner_radius=6,
                font=("Arial", 13, "bold"),
                command=lambda selected_date=date_key: show_day_details(
                    employee,
                    selected_date
                )
            )
            day_box.grid(
                row=row_index,
                column=column_index,
                padx=4,
                pady=4
            )

    # -----------------------------------------------------
    # LEGEND
    # -----------------------------------------------------
    legend = ctk.CTkLabel(
        calendar_panel,
        text=(
            "🟢 Completed shift      "
            "🟠 Shift in progress      "
            "🔴 No show      "
            "🟡 Sick leave      "
            "⬛ No record      "
            "Click a date to view, edit, or mark attendance"
        ),
        font=("Arial", 12),
        text_color="#9CA3AF"
    )
    legend.pack(pady=(5, 10))


# =========================================================
# EMPLOYEES PAGE
# =========================================================

def open_employees():
    global current_page
    current_page = ('employees',)

    clear_page()


    # -----------------------------------------------------
    # TOP BAR
    # -----------------------------------------------------

    top_bar = ctk.CTkFrame(
        main_area,
        fg_color="transparent"
    )

    top_bar.pack(
        fill="x",
        padx=30,
        pady=25
    )


    title_area = ctk.CTkFrame(
        top_bar,
        fg_color="transparent"
    )

    title_area.pack(side="left")

    title = ctk.CTkLabel(
        title_area,
        text="Employees",
        font=("Segoe UI", 30, "bold"),
        text_color="#F8FAFC"
    )

    title.pack(anchor="w")

    subtitle = ctk.CTkLabel(
        title_area,
        text="Manage your team and employee activity",
        font=("Segoe UI", 13),
        text_color="#94A3B8"
    )

    subtitle.pack(
        anchor="w",
        pady=(2, 0)
    )


    delete_button = ctk.CTkButton(
        top_bar,
        text="Delete Employee",
        width=140,
        height=40,
        fg_color=red,
        hover_color=red_hover,
        command=delete_employee
    )

    delete_button.pack(
        side="right",
        padx=5
    )


    add_button = ctk.CTkButton(
        top_bar,
        text="+ Add Employee",
        width=140,
        height=40,
        fg_color=blue,
        hover_color=blue_hover,
        command=add_employee
    )

    add_button.pack(
        side="right",
        padx=5
    )


    # -----------------------------------------------------
    # EMPLOYEE SEARCH + LIST
    # -----------------------------------------------------

    search_row = ctk.CTkFrame(
        main_area,
        fg_color="transparent"
    )

    search_row.pack(
        fill="x",
        padx=30,
        pady=(0, 12)
    )

    search_var = ctk.StringVar(value="")

    search_entry = ctk.CTkEntry(
        search_row,
        textvariable=search_var,
        placeholder_text="Search employee by name...",
        height=40,
        font=("Segoe UI", 14)
    )

    search_entry.pack(
        side="left",
        fill="x",
        expand=True
    )

    employee_list = ctk.CTkScrollableFrame(
        main_area,
        fg_color="#111827"
    )

    employee_list.pack(
        fill="both",
        expand=True,
        padx=30,
        pady=(0, 30)
    )

    def render_employee_list(*_):
        for widget in employee_list.winfo_children():
            widget.destroy()

        query = search_var.get().strip().casefold()
        matches = [
            employee for employee in employees
            if query in employee.casefold()
        ]

        if not employees:
            ctk.CTkLabel(
                employee_list,
                text="No employees added yet.",
                font=("Arial", 16),
                text_color="#9CA3AF"
            ).pack(pady=30)
            return

        if not matches:
            ctk.CTkLabel(
                employee_list,
                text="No employee found.",
                font=("Arial", 16),
                text_color="#9CA3AF"
            ).pack(pady=30)
            return

        for employee in matches:
            employee_button = ctk.CTkButton(
                employee_list,
                text="👤  " + employee,
                height=50,
                anchor="w",
                font=("Arial", 16),
                fg_color=gray,
                hover_color=blue_hover,
                command=lambda name=employee: select_employee(name)
            )

            employee_button.pack(
                fill="x",
                padx=10,
                pady=5
            )

    def clear_employee_search():
        search_var.set("")
        search_entry.focus()

    search_button = ctk.CTkButton(
        search_row,
        text="Search",
        width=95,
        height=40,
        fg_color=blue,
        hover_color=blue_hover,
        command=render_employee_list
    )

    search_button.pack(
        side="left",
        padx=(10, 0)
    )

    clear_button = ctk.CTkButton(
        search_row,
        text="Clear",
        width=75,
        height=40,
        fg_color=gray,
        hover_color=gray_hover,
        command=clear_employee_search
    )

    clear_button.pack(
        side="left",
        padx=(8, 0)
    )

    search_var.trace_add("write", render_employee_list)
    search_entry.bind("<Return>", lambda _event: render_employee_list())
    render_employee_list()


# =========================================================
# STORE CURRENCY
# =========================================================

def currency_choice_label(code):
    info=CURRENCIES.get(code,CURRENCIES[DEFAULT_CURRENCY])
    return f"{code} · {info['symbol']}"


def change_store_currency(choice):
    global store_currency
    code=next((code for code in CURRENCIES if currency_choice_label(code)==choice),None)
    if not code or code==store_currency:
        currency_var.set(currency_choice_label(store_currency))
        return

    # Revert the visible dropdown until the protected change is actually accepted.
    currency_var.set(currency_choice_label(store_currency))
    password=check_admin_password()
    if password is None:
        return

    current_info=CURRENCIES[store_currency]
    new_info=CURRENCIES[code]
    if not messagebox.askyesno(
        'Change store currency',
        f"Change the SaveSales store currency from {store_currency} ({current_info['symbol']}) "
        f"to {code} ({new_info['symbol']})?\n\n"
        "This changes the currency used for new prices and sales. It does NOT convert numeric prices "
        "using an exchange rate. Historical sales keep the currency they were recorded in.",
        parent=app
    ):
        return

    def done(ok,result):
        if not ok:
            messagebox.showerror('Store currency',str(result),parent=app)
            currency_var.set(currency_choice_label(store_currency))
            return
        apply_snapshot(result)
        messagebox.showinfo(
            'Store currency',
            f"Store currency changed to {code} · {new_info['name']}.",
            parent=app
        )

    client.submit('POST','/settings/currency',{'currency':code},password,done)


# =========================================================
# SIDEBAR BUTTONS
# =========================================================

items_button = ctk.CTkButton(
    sidebar,
    text="📦  Items",
    height=55,
    font=("Arial", 18, "bold"),
    fg_color=blue,
    hover_color=blue_hover,
    corner_radius=10,
    command=open_items
)

items_button.pack(
    padx=20,
    pady=10,
    fill="x"
)


cart_button = ctk.CTkButton(
    sidebar, text='🛒  Cart', height=55, font=('Arial',18,'bold'),
    fg_color=blue, hover_color=blue_hover, corner_radius=10, command=open_cart)
cart_button.pack(padx=20,pady=10,fill='x')


tracking_button = ctk.CTkButton(
    sidebar,
    text="📊  Daily Tracking",
    height=55,
    font=("Arial", 18, "bold"),
    fg_color=blue,
    hover_color=blue_hover,
    corner_radius=10,
    command=open_tracking
)

tracking_button.pack(
    padx=20,
    pady=10,
    fill="x"
)


employees_button = ctk.CTkButton(
    sidebar,
    text="👥  Employees",
    height=55,
    font=("Arial", 18, "bold"),
    fg_color=blue,
    hover_color=blue_hover,
    corner_radius=10,
    command=open_employees
)

employees_button.pack(
    padx=20,
    pady=10,
    fill="x"
)


currency_frame=ctk.CTkFrame(sidebar,fg_color='transparent')
currency_frame.pack(fill='x',padx=20,pady=(10,4))
ctk.CTkLabel(
    currency_frame,text='Store currency',font=('Segoe UI',12,'bold'),
    text_color='#CBD5E1',anchor='w'
).pack(fill='x',pady=(0,5))

currency_var=ctk.StringVar(master=app,value=currency_choice_label(store_currency))
currency_menu=ctk.CTkOptionMenu(
    currency_frame,
    variable=currency_var,
    values=[currency_choice_label(code) for code in CURRENCIES],
    command=change_store_currency,
    height=34,
    fg_color=gray,
    button_color=blue,
    button_hover_color=blue_hover,
    dropdown_fg_color=panel_color,
)
currency_menu.pack(fill='x')
ctk.CTkLabel(
    currency_frame,text='Admin protected · LAN synced',font=('Segoe UI',10),
    text_color='#64748B'
).pack(anchor='w',pady=(4,0))


# =========================================================
# START
# =========================================================

def show_sync_conflicts():
    window = ctk.CTkToplevel(app)
    window.title('SaveSales synchronization review')
    window.geometry('650x430')
    window.transient(app)
    text = ctk.CTkTextbox(window, wrap='word')
    text.pack(fill='both', expand=True, padx=15, pady=15)
    text.insert('end', 'Conflicting records remain in the local SQLite journal. The calendar uses the same deterministic result on every PC.\n\n')
    for event in sync_conflicts:
        text.insert('end', f"{event['name']} | {event['date']} | {event['action']}\n"
                    f"Recorded: {event['time']} | Calendar: {event.get('selected_time') or '--'}\n"
                    f"{event['reason']}\nRecord ID: {event['id']}\n\n")
    text.configure(state='disabled')


conflict_button = ctk.CTkButton(sidebar, text='Review time conflicts',
                               fg_color=yellow, command=show_sync_conflicts)
connection_label = ctk.CTkLabel(
    sidebar, text='● No SaveSales LAN connection', text_color=red,
    font=('Segoe UI', 12), wraplength=190)
connection_label.pack(side='bottom', padx=10, pady=20)


def close_app():
    if getattr(app, '_closing', False):
        return
    app._closing = True
    client.close()
    app.withdraw()
    def finish_close():
        if client.thread.is_alive():
            app.after(100, finish_close)
        else:
            app.destroy()
    finish_close()


shop = ShopUI(app, main_area, client, check_admin_password, set_shop_page, lambda: current_page[0])
app.protocol('WM_DELETE_WINDOW', close_app)
open_items()
process_network()
app.mainloop()