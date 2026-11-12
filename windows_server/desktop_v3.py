"""Digi Pixel Server v3 desktop. Reuses the existing account/app/browser actions.
No changes to the saved browser profile, native app identity or Railway broker.
"""
from __future__ import annotations
import argparse
import ctypes
import json
import os
import queue
import secrets
import sys
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from agent import PixelServer, CONNECTION, ACTIONS
from desktop_runtime import Runtime, SetupCancelled
from winpixel_sdk import home, ONE_APP, adb_command

BG = '#101721'
PANEL = '#192331'
CARD = '#202e3e'
BORDER = '#304155'
TEXT = '#f2f6fa'
MUTED = '#a1b1c3'
ACCENT = '#45dcc1'
WARN = '#f0c674'
ERROR = '#ff9797'
VERSION = '3.0.0'


class DesktopServer(PixelServer):
    def __init__(self, testing=False):
        self.testing = testing
        self.sdk = self.serial = self.driver = None
        self.ready = self.busy = self.relay_ok = False
        self.current_action = ''
        self.status = 'Ready to prepare Android'
        self.shutdown = threading.Event()
        self.cancel_event = threading.Event()
        self.work = queue.Queue()
        self.notifications = queue.Queue()
        self.job_lock = threading.Lock()
        self.scheduled = False
        self.closing = False
        self.app_installed = None
        self.phase = 'check'
        self.last_percent = None
        self.last_line = ''
        self.last_heartbeat = time.monotonic()
        self.pairing = ''.join(str(secrets.randbelow(10)) for _ in range(8))
        self.log_path = home()/'logs'/'server.log'
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.config = {}
        if CONNECTION.is_file():
            try:
                conf = json.loads(CONNECTION.read_text(encoding='utf-8-sig'))
                if conf.get('railway_url', '').startswith('https://') and len(conf.get('bridge_token', '')) >= 32:
                    self.config = conf
            except (OSError, ValueError, TypeError):
                pass
        self.runtime = Runtime(self.publish, self.cancel_event)
        self.root = tk.Tk()
        self.root.title('Digi Pixel Server  |  Desktop ' + VERSION)
        self.root.configure(bg=BG)
        w = min(1000, self.root.winfo_screenwidth()-70)
        h = min(720, self.root.winfo_screenheight()-85)
        self.root.geometry(f'{w}x{h}')
        self.root.minsize(min(800, w), min(570, h))
        self.build_ui()
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.after(120, self.refresh)
        if not testing:
            threading.Thread(target=self.worker, daemon=True).start()
            threading.Thread(target=self.relay_loop, daemon=True).start()
            self.root.after(350, lambda: self.schedule('start', None))

    def label(self, parent, text, size=14, color=TEXT, bold=False, **kwargs):
        # Pixel-sized fonts avoid multiplying fixed layouts under Windows DPI scaling.
        return tk.Label(parent, text=text, font=('Segoe UI', -size, 'bold' if bold else 'normal'),
                        bg=parent.cget('bg'), fg=color, anchor='w', justify='left', **kwargs)

    def button(self, parent, text, command, primary=False):
        return tk.Button(parent, text=text, command=command, relief='flat', borderwidth=0,
            bg=ACCENT if primary else CARD, fg=BG if primary else TEXT,
            activebackground='#65ead2', activeforeground=BG, disabledforeground='#67798c',
            font=('Segoe UI', -14, 'bold'), padx=12, pady=10, cursor='hand2')

    def build_ui(self):
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)
        header = tk.Frame(self.root, bg=BG, padx=24, pady=18)
        header.grid(row=0, column=0, sticky='ew')
        header.grid_columnconfigure(0, weight=1)
        self.label(header, 'DIGI / PIXEL SERVER', 13, ACCENT, True).grid(row=0,column=0,sticky='w')
        self.label(header, 'Android workspace', 27, TEXT, True).grid(row=1,column=0,sticky='w',pady=(4,0))
        self.relay_label = self.label(header, 'RAILWAY  /  CHECKING', 12, MUTED, True)
        self.relay_label.grid(row=0,column=1,sticky='e')
        self.label(header, 'DESKTOP ' + VERSION, 12, MUTED).grid(row=1,column=1,sticky='e')
        body = tk.Frame(self.root, bg=BG)
        body.grid(row=1,column=0,sticky='nsew',padx=20,pady=(0,12))
        body.grid_columnconfigure(0, weight=0, minsize=218)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)
        side = tk.Frame(body,bg=PANEL,padx=14,pady=16)
        side.grid(row=0,column=0,sticky='nsew',padx=(0,12))
        self.label(side, 'CONTROLS', 11, MUTED, True).pack(anchor='w',pady=(0,12))
        self.controls = {}
        for action, title in [('start','Start Android'),('one','Open Google One'),
                              ('account','Google accounts'),('offers','Check offers'),
                              ('pixel','Saved Pixel browser'),('screenshot','Screenshot')]:
            btn = self.button(side,title,lambda a=action:self.schedule(a,None),action=='start')
            btn.pack(fill='x',pady=4)
            self.controls[action] = btn
        self.stop_button = self.button(side,'Stop current operation',self.stop_current)
        self.stop_button.pack(fill='x',pady=(14,6))
        self.stop_button.configure(state='disabled')
        self.label(side,'Saved browser profile',11,MUTED).pack(anchor='w',pady=(12,3))
        self.label(side,'Pixel 11 Pro XL',15,TEXT,True).pack(anchor='w')
        self.label(side,'Android runtime and browser\nprofile are separate layers.',11,MUTED).pack(anchor='w',pady=(6,0))
        right = tk.Frame(body,bg=BG)
        right.grid(row=0,column=1,sticky='nsew')
        right.grid_columnconfigure(0,weight=1)
        right.grid_rowconfigure(2,weight=1,minsize=130)
        self.progress_card = tk.Frame(right,bg=PANEL,padx=20,pady=16)
        self.progress_card.grid(row=0,column=0,sticky='ew')
        self.progress_card.grid_columnconfigure(0,weight=1)
        self.label(self.progress_card,'CURRENT OPERATION',11,MUTED,True).grid(row=0,column=0,sticky='w')
        self.status_label = self.label(self.progress_card,'Preparing your workspace',20,TEXT,True,wraplength=490)
        self.status_label.grid(row=1,column=0,sticky='ew',pady=(8,6))
        self.detail_label = self.label(self.progress_card,'Existing accounts and downloaded components will be kept.',12,MUTED,wraplength=490)
        self.detail_label.grid(row=2,column=0,sticky='ew')
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('Digi.Horizontal.TProgressbar', troughcolor=CARD, background=ACCENT,
                        bordercolor=CARD, lightcolor=ACCENT, darkcolor=ACCENT, thickness=7)
        self.progressbar = ttk.Progressbar(self.progress_card,style='Digi.Horizontal.TProgressbar',mode='indeterminate')
        self.progressbar.grid(row=3,column=0,sticky='ew',pady=(14,7))
        self.percent_label = self.label(self.progress_card,'Awaiting installer output',11,MUTED)
        self.percent_label.grid(row=4,column=0,sticky='w')
        stages = tk.Frame(self.progress_card,bg=PANEL)
        stages.grid(row=5,column=0,sticky='ew',pady=(15,0))
        self.stage_labels = {}
        for col,(key,name) in enumerate([('check','01 CHECK'),('download','02 DOWNLOAD'),('install','03 INSTALL'),('boot','04 START')]):
            stages.grid_columnconfigure(col,weight=1)
            lab = self.label(stages,name,11,MUTED,True)
            lab.grid(row=0,column=col,sticky='w')
            self.stage_labels[key] = lab
        pair = tk.Frame(right,bg=PANEL,padx=20,pady=12)
        pair.grid(row=1,column=0,sticky='ew',pady=10)
        pair.grid_columnconfigure(0,weight=1)
        self.label(pair,'TELEGRAM LINK',11,MUTED,True).grid(row=0,column=0,sticky='w')
        self.pair_label = self.label(pair,self.pairing,19,ACCENT,True)
        self.pair_label.grid(row=1,column=0,sticky='w',pady=(3,0))
        self.label(pair,'One-time pairing; no activation code.',11,MUTED).grid(row=2,column=0,sticky='w')
        self.button(pair,'Copy pairing command',self.copy_pair).grid(row=0,column=1,rowspan=3,padx=(10,0))
        activity = tk.Frame(right,bg=PANEL,padx=14,pady=10)
        activity.grid(row=2,column=0,sticky='nsew')
        activity.grid_columnconfigure(0,weight=1)
        activity.grid_rowconfigure(1,weight=1,minsize=70)
        self.label(activity,'ACTIVITY',11,MUTED,True).grid(row=0,column=0,sticky='w',pady=(0,7))
        tools = tk.Frame(activity,bg=PANEL)
        tools.grid(row=0,column=1,sticky='e')
        for text,cmd in [('Open logs',self.open_log),('Copy',self.copy_log)]:
            tk.Button(tools,text=text,command=cmd,bg=PANEL,fg=ACCENT,relief='flat',
                      font=('Segoe UI',-11),cursor='hand2').pack(side='left',padx=3)
        self.log = scrolledtext.ScrolledText(activity,height=6,bg='#131d29',fg='#c6d4e4',
            relief='flat',font=('Consolas',-12),wrap='word',borderwidth=0,padx=9,pady=8,state='disabled')
        self.log.grid(row=1,column=0,columnspan=2,sticky='nsew')
        footer = tk.Frame(self.root,bg=BG,padx=24,pady=9)
        footer.grid(row=2,column=0,sticky='ew')
        self.footer_label = self.label(footer,'LOCAL DATA PRESERVED  /  Windows host',11,MUTED)
        self.footer_label.pack(side='left')
        self.label(footer,'HTTPS relay  |  No public ADB port',11,MUTED).pack(side='right')
        def resize(event):
            if event.width > 90:
                for lab in (self.status_label,self.detail_label):
                    lab.configure(wraplength=max(200,event.width-40))
        self.progress_card.bind('<Configure>',resize)
        self.update_controls()

    def copy_pair(self):
        self.root.clipboard_clear()
        self.root.clipboard_append('/winpixel pair ' + self.pairing)

    def publish(self, event):
        if event.get('type') == 'progress':
            self.status = str(event.get('message',''))[:240]
        self.notifications.put(event)

    def set_status(self, message):
        self.status = str(message)[:240]
        self.publish({'type':'progress','message':self.status,'phase':self.phase,'percent':None,'detail':''})

    def log_event(self, message):
        self.publish({'type':'log','message':str(message)[:2200]})

    def append_log(self, message):
        line = time.strftime('%H:%M:%S') + '  ' + str(message)
        if line[10:] == self.last_line:
            return
        self.last_line = line[10:]
        self.log.configure(state='normal')
        self.log.insert('end',line+'\n')
        if int(self.log.index('end-1c').split('.')[0]) > 450:
            self.log.delete('1.0','80.0')
        self.log.see('end')
        self.log.configure(state='disabled')
        try:
            with self.log_path.open('a',encoding='utf-8') as output:
                output.write(line+'\n')
        except OSError:
            pass

    def update_controls(self):
        occupied = self.busy or self.scheduled
        for action,button in self.controls.items():
            enabled = not occupied and (self.ready or action == 'start')
            button.configure(state='normal' if enabled else 'disabled')
        self.stop_button.configure(state='normal' if occupied else 'disabled')

    def refresh(self):
        for _ in range(120):
            try:
                event = self.notifications.get_nowait()
            except queue.Empty:
                break
            if isinstance(event,str):
                event = {'type':'log','message':event}
            message = event.get('message','')
            if event.get('type') == 'progress':
                self.phase = event.get('phase',self.phase)
                detail = event.get('detail','')
                self.status_label.configure(text=message,fg=ERROR if self.phase=='error' else TEXT)
                self.detail_label.configure(text=detail)
                percent = event.get('percent')
                self.progressbar.stop()
                if percent is not None:
                    p = max(0,min(100,float(percent)))
                    self.progressbar.configure(mode='determinate',value=p)
                    self.percent_label.configure(text=f'{p:.0f}% of this operation (reported by the installer)')
                elif self.busy:
                    self.progressbar.configure(mode='indeterminate')
                    self.progressbar.start(35)
                    self.percent_label.configure(text='Waiting for tool output - no percentage reported')
                else:
                    self.progressbar.configure(mode='determinate',value=100 if self.ready else 0)
                    self.percent_label.configure(text='Android ready' if self.ready else 'Ready to retry')
                for key,lab in self.stage_labels.items():
                    lab.configure(fg=ACCENT if key==self.phase or self.phase=='ready' else MUTED)
                self.append_log(message + (' | '+detail if detail else ''))
            else:
                self.append_log(message)
        self.relay_label.configure(text='RAILWAY  /  '+('CONNECTED' if self.relay_ok else ('CONNECTING' if self.config else 'LOCAL MODE')),
                                   fg=ACCENT if self.relay_ok else MUTED)
        self.update_controls()
        if self.closing and not self.busy:
            self.root.destroy()
            return
        self.root.after(140,self.refresh)

    def schedule(self, action, job_id, remote=False):
        if action not in ACTIONS:
            return
        with self.job_lock:
            occupied = self.busy or self.scheduled
            if not occupied:
                self.scheduled = True
                self.cancel_event.clear()
                self.work.put((action,job_id))
        if occupied:
            text = 'Another operation is running. No duplicate command was added.'
            self.log_event(text)
            if job_id:
                threading.Thread(target=self.post_result,args=(job_id,text,None),daemon=True).start()
        else:
            self.log_event('Requested: '+action)
        if not remote:
            self.update_controls()

    def stop_current(self):
        self.cancel_event.set()
        self.log_event('Stop requested. Installed components and accounts will be retained.')
        self.status_label.configure(text='Stopping current operation...')

    def ensure(self):
        if self.sdk and self.serial:
            try:
                if adb_command(self.sdk,'get-state',serial=self.serial,timeout=6) == 'device':
                    return self.sdk,self.serial
            except Exception:
                self.sdk = self.serial = None
                self.ready = False
        self.sdk,self.serial = self.runtime.start()
        self.ready = True
        return self.sdk,self.serial

    def installed(self, package):
        if not self.sdk or not self.serial:
            return False
        result = self.adb('shell','pm','list','packages',package)
        return 'package:'+package in result.splitlines()

    def worker(self):
        while not self.shutdown.is_set():
            try:
                action,job_id = self.work.get(timeout=0.3)
            except queue.Empty:
                continue
            with self.job_lock:
                self.busy,self.scheduled = True,False
            self.current_action = action
            image = None
            try:
                self.runtime.check_cancelled()
                message = self.execute(action)
                if action == 'screenshot':
                    image = self.shot()
                self.app_installed = self.installed(ONE_APP) if self.ready else None
                self.publish({'type':'progress','phase':'ready','message':'Android is ready',
                    'percent':100,'detail':('Google One is installed.' if self.app_installed else
                    'Google One needs one-time installation from Play Store inside Android.')})
                self.log_event(message)
            except SetupCancelled as exc:
                message = str(exc)
                self.publish({'type':'progress','phase':'check','message':'Operation stopped',
                              'percent':None,'detail':message})
            except Exception as exc:
                message = str(exc)
                self.publish({'type':'progress','phase':'error','message':'This step needs attention',
                              'percent':None,'detail':message[:600]})
                self.log_event(message)
            finally:
                self.busy = False
                self.current_action = ''
                self.work.task_done()
            if job_id:
                self.post_result(job_id,message[:1400],image)

    def close(self):
        if self.busy and not self.testing:
            if not messagebox.askyesno('Close desktop','Stop the current operation and close? Saved Android data will be kept.'):
                return
        self.shutdown.set()
        self.cancel_event.set()
        self.closing = True
        if not self.busy:
            self.root.destroy()


def single_instance():
    if os.name != 'nt':
        return True
    kernel = ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CreateMutexW(None,False,'Local\\DigiPixelServerDesktopV3')
    return ctypes.get_last_error() != 183


def ui_smoke(output=None):
    app = DesktopServer(testing=True)
    app.root.update()
    app.busy = True
    app.publish({'type':'progress','phase':'install','message':'Installing Google Play system image',
                 'percent':42,'detail':'42% Unzipping system.img - actual SDK output'})
    app.refresh()
    app.root.update()
    assert app.log.winfo_height() >= 65, 'Activity log is too small'
    assert app.controls['one'].cget('state') == 'disabled', 'App actions must be disabled during setup'
    assert app.status_label.cget('text') == 'Installing Google Play system image'
    assert app.log.cget('state') == 'disabled', 'Activity log should be read-only'
    assert app.progressbar.cget('mode') == 'determinate'
    for w,h in [(960,680),(820,600)]:
        app.root.geometry(f'{w}x{h}')
        app.root.update()
        for widget in (app.stop_button, app.log, app.footer_label):
            bottom = widget.winfo_rooty()+widget.winfo_height()
            assert bottom <= app.root.winfo_rooty()+app.root.winfo_height()+2, 'A control is clipped'
    app.root.geometry('1000x720')
    app.root.update()
    if output:
        try:
            from PIL import ImageGrab
            x,y = app.root.winfo_rootx(),app.root.winfo_rooty()
            ImageGrab.grab((x,y,x+app.root.winfo_width(),y+app.root.winfo_height())).save(output)
        except Exception as exc:
            print('Screenshot unavailable:',type(exc).__name__)
    app.busy = False
    app.close()
    print('GUI_SMOKE_OK: responsive layout, busy controls, reported progress, readable logs')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--ui-smoke',action='store_true')
    parser.add_argument('--screenshot')
    args = parser.parse_args()
    if args.ui_smoke:
        ui_smoke(args.screenshot)
    elif single_instance():
        DesktopServer().run()
    else:
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo('Digi Pixel Server','Digi Pixel Server v3 is already running. Open its existing window.')
        root.destroy()
