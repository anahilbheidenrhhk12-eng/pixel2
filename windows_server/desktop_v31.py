"""Desktop 3.1: verified Android readiness and native Google One lifecycle.
Retains the existing browser profile, local AVD data and Railway connection.
"""
from __future__ import annotations
import argparse
import json
import os
import queue
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

import desktop_v3 as base
from desktop_runtime import Runtime, SetupCancelled
from native_one_session import NativeOneSession, ONE, NativeAppError
import winpixel_sdk as sdk

base.VERSION = '3.1.0'


class Runtime31(Runtime):
    def start(self):
        root, env = self.prepare()
        self.phase = 'boot'
        self.emit('Starting Android')
        process = None
        owned = False
        bootlog = self.log_dir / 'emulator.log'
        try:
            if not sdk.ready_emulator(root):
                self.check_cancelled()
                with bootlog.open('ab') as output:
                    process = subprocess.Popen(
                        [str(root/'emulator'/'emulator.exe'), '-avd', sdk.AVD_NAME,
                         '-no-boot-anim', '-gpu', 'auto'], env=env,
                        cwd=str(root/'emulator'), stdin=subprocess.DEVNULL,
                        stdout=output, stderr=subprocess.STDOUT,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                owned = True
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                self.check_cancelled()
                if process and process.poll() is not None:
                    tail = bootlog.read_text(encoding='utf-8', errors='replace')[-1600:]
                    raise RuntimeError('Android exited before boot completed.\n'+tail)
                for serial in sdk.ready_emulator(root):
                    try:
                        boot = sdk.adb_command(root, 'shell', 'getprop', 'sys.boot_completed',
                                               serial=serial, timeout=8)
                    except (RuntimeError, subprocess.TimeoutExpired):
                        continue
                    if boot == '1':
                        os.environ['ANDROID_SERIAL'] = serial
                        probe = NativeOneSession(
                            lambda *a, **kw: sdk.adb_command(root, *a, serial=serial, **kw),
                            self.notify, self.check_cancelled, wait=self.cancel.wait)
                        probe.wait_ready(timeout=60)
                        self.phase = 'ready'
                        self.emit('Android services verified', 100,
                                  'Package Manager responds; Google Play Store and Play services are installed.')
                        return root, serial
                self.emit('Android is booting', detail='Waiting for boot completion and Google Play services.')
                if self.cancel.wait(2): self.check_cancelled()
            raise RuntimeError('Android boot timed out. Open emulator.log for details.')
        except BaseException:
            # Only stop a newly launched child. Never kill an emulator that was
            # already running when this desktop attached to it.
            if owned and process is not None:
                self.kill_tree(process)
            raise


class DesktopServer(base.DesktopServer):
    def __init__(self, testing=False):
        self.app_result = None
        super().__init__(testing=testing)
        self.runtime = Runtime31(self.publish, self.cancel_event)

    def native(self):
        if not self.sdk or not self.serial:
            raise NativeAppError('Start Android first.')
        return NativeOneSession(
            lambda *a, **kw: sdk.adb_command(self.sdk, *a, serial=self.serial, **kw),
            self.publish, self.runtime.check_cancelled, wait=self.cancel_event.wait)

    def save_readiness(self, snapshot):
        # No account identifiers, passwords, tokens or UI dumps in this file.
        report = {'at': datetime.now(timezone.utc).isoformat(),
                  'application_version': base.VERSION, **snapshot.report()}
        target = sdk.home()/'logs'/'android_readiness.json'
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            part = target.with_suffix('.tmp')
            part.write_text(json.dumps(report, indent=2), encoding='utf-8')
            part.replace(target)
        except OSError:
            pass

    def ensure(self):
        if self.sdk and self.serial:
            try:
                snapshot = self.native().wait_ready(timeout=8)
                self.ready = True
                self.save_readiness(snapshot)
                return self.sdk, self.serial
            except SetupCancelled:
                raise
            except (NativeAppError, RuntimeError, OSError):
                self.sdk = self.serial = None
                self.ready = False
        self.sdk, self.serial = self.runtime.start()
        self.save_readiness(self.native().inspect())
        self.ready = True
        return self.sdk, self.serial

    def open_one(self):
        self.ensure()
        self.app_result = self.native().open(install_wait=600)
        return self.app_result['message']

    def worker(self):
        while not self.shutdown.is_set():
            try:
                action, job_id = self.work.get(timeout=0.3)
            except queue.Empty:
                continue
            with self.job_lock:
                self.busy, self.scheduled = True, False
            self.current_action = action
            self.app_result = None
            image = None
            try:
                self.runtime.check_cancelled()
                message = self.execute(action)
                if action == 'screenshot': image = self.shot()
                self.app_installed = self.installed(ONE) if self.ready else None
                state = (self.app_result or {}).get('state')
                titles = {
                    'native_app_open': 'Google One app verified on screen',
                    'install_required': 'Google One installation is still required',
                    'android_confirmation': 'Complete the Android confirmation',
                    'launch_unconfirmed': 'App launch was not confirmed',
                }
                self.publish({'type': 'progress',
                              'phase': 'ready' if state in (None, 'native_app_open') else 'app',
                              'message': titles.get(state, 'Operation completed'),
                              'percent': 100 if state == 'native_app_open' else None,
                              'detail': (self.app_result or {}).get('message', message)[:600]})
                self.log_event(message)
                if self.ready:
                    try:
                        self.save_readiness(self.native().inspect())
                    except (RuntimeError, OSError):
                        self.log_event('Readiness report refresh unavailable; action result is unchanged.')
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
                with self.job_lock:
                    self.busy = False
                self.current_action = ''
                self.work.task_done()
            if job_id:
                self.post_result(job_id, message[:1400], image)


def ui_smoke(output=None):
    # Exercise the real 3.1 subclass with the established layout assertions.
    previous = base.DesktopServer
    base.DesktopServer = DesktopServer
    try:
        base.ui_smoke(output)
    finally:
        base.DesktopServer = previous


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--ui-smoke', action='store_true')
    parser.add_argument('--screenshot')
    args = parser.parse_args()
    if args.ui_smoke:
        ui_smoke(args.screenshot)
    elif base.single_instance():
        DesktopServer().run()
    else:
        root = tk.Tk(); root.withdraw()
        messagebox.showinfo('Digi Pixel Server', 'The desktop is already running. Use its existing window.')
        root.destroy()
