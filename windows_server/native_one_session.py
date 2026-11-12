"""Verified native Google One lifecycle. No passwords, purchases or device spoofing.

The ADB transport is injected so the same controller can be tested on Windows
and on a Linux CI Android emulator without changing the running device.
"""
from __future__ import annotations
import re
import threading
import time
from dataclasses import asdict, dataclass
from typing import Callable

ONE = 'com.google.android.apps.subscriptions.red'
PLAY = 'com.android.vending'
GMS = 'com.google.android.gms'


class NativeAppError(RuntimeError):
    pass


def packages_from(text: str) -> set[str]:
    return {line.strip()[8:] for line in text.splitlines()
            if re.fullmatch(r'package:[A-Za-z0-9_.]+', line.strip())}


def foreground_from(text: str) -> str | None:
    # Do not mistake a task in recents for the foreground application.
    for marker in ('topResumedActivity', 'mResumedActivity', 'ResumedActivity'):
        for line in text.splitlines():
            if marker in line:
                match = re.search(r'\bu\d+\s+([A-Za-z0-9_.]+)/[A-Za-z0-9_.$]+', line)
                if match:
                    return match[1]
    return None


def activity_from(text: str, package: str) -> str | None:
    for line in reversed(text.splitlines()):
        value = line.strip()
        if re.fullmatch(re.escape(package) + r'/[A-Za-z0-9_.$]+', value):
            return value
    return None


def command_failed(text: str) -> bool:
    return bool(re.search(r'(?im)^\s*(?:error\b|exception\b|securityexception\b)|'
                          r'permission denial|unable to resolve intent|no activities found', text))


@dataclass(frozen=True)
class Readiness:
    online: bool = False
    booted: bool = False
    package_manager: bool = False
    play_store: bool = False
    play_services: bool = False
    google_one: bool = False
    foreground: str | None = None

    @property
    def ready(self) -> bool:
        return self.online and self.booted and self.package_manager and self.play_store and self.play_services

    def report(self) -> dict:
        # No account names, cookies, access tokens or screen text.
        return {**asdict(self), 'android_ready': self.ready}


class NativeOneSession:
    def __init__(self, adb: Callable, notify: Callable | None = None,
                 check_cancel: Callable | None = None, clock: Callable = time.monotonic,
                 wait: Callable | None = None):
        self.adb = adb
        self.notify = notify or (lambda event: None)
        self.check_cancel = check_cancel or (lambda: None)
        self.clock = clock
        self.wait = wait or threading.Event().wait

    def emit(self, message: str, detail: str = '', phase: str = 'app'):
        self.notify({'type': 'progress', 'phase': phase, 'message': message,
                     'detail': detail, 'percent': None})

    def pause(self, seconds: float):
        self.check_cancel()
        self.wait(max(0, seconds))
        self.check_cancel()

    def foreground(self) -> str | None:
        return foreground_from(self.adb('shell', 'dumpsys', 'activity', 'activities', timeout=10))

    def inspect(self) -> Readiness:
        self.check_cancel()
        online = self.adb('get-state', timeout=6).strip() == 'device'
        if not online:
            return Readiness()
        booted = self.adb('shell', 'getprop', 'sys.boot_completed', timeout=6).strip() == '1'
        if not booted:
            return Readiness(online=True)
        output = self.adb('shell', 'pm', 'list', 'packages', timeout=15)
        packages = packages_from(output)
        pm_ready = 'android' in packages and not command_failed(output)
        return Readiness(True, True, pm_ready, PLAY in packages, GMS in packages,
                         ONE in packages, self.foreground() if pm_ready else None)

    def wait_ready(self, timeout: float = 60) -> Readiness:
        deadline = self.clock() + max(0, timeout)
        last = Readiness()
        while True:
            self.check_cancel()
            try:
                last = self.inspect()
            except (RuntimeError, OSError):
                self.check_cancel()
            if last.ready:
                return last
            if self.clock() >= deadline:
                missing = [label for label, ok in (
                    ('ADB connection', last.online), ('Android boot', last.booted),
                    ('Android package manager', last.package_manager),
                    ('Google Play Store', last.play_store), ('Google Play services', last.play_services)) if not ok]
                raise NativeAppError('Android not ready: ' + ', '.join(missing))
            self.emit('Checking Android services', 'Waiting for Package Manager, Google Play and Play services.', 'boot')
            self.pause(min(2, deadline - self.clock()))

    def installed(self, package: str) -> bool:
        self.check_cancel()
        output = self.adb('shell', 'pm', 'list', 'packages', package, timeout=12)
        if command_failed(output):
            raise NativeAppError('Android package manager is not responding correctly.')
        return package in packages_from(output)

    def open_store(self):
        self.check_cancel()
        output = self.adb('shell', 'am', 'start', '-W', '-a', 'android.intent.action.VIEW',
                          '-d', 'market://details?id=' + ONE, '-p', PLAY, timeout=20)
        if command_failed(output):
            raise NativeAppError('Google Play could not open the Google One installation page.')
        self.emit('Install Google One inside Android',
                  'Sign in to Play Store if asked, then tap Install. The app will open automatically when installed.')

    def launch_one(self, timeout: float = 20) -> dict:
        self.check_cancel()
        resolved = self.adb('shell', 'cmd', 'package', 'resolve-activity', '--brief',
                            '-a', 'android.intent.action.MAIN', '-c',
                            'android.intent.category.LAUNCHER', ONE, timeout=12)
        activity = activity_from(resolved, ONE)
        if activity:
            output = self.adb('shell', 'am', 'start', '-W', '-n', activity, timeout=25)
            accepted = not command_failed(output)
        else:
            output = self.adb('shell', 'monkey', '-p', ONE, '-c',
                              'android.intent.category.LAUNCHER', '1', timeout=20)
            accepted = not command_failed(output) and 'Events injected: 1' in output
        if not accepted:
            raise NativeAppError('Android rejected the Google One launch command. The app was not reported as opened.')
        self.emit('Opening the Google One Android app', 'Verifying the foreground app, not just the launch command.')
        deadline = self.clock() + max(0, timeout)
        foreground = None
        while True:
            self.check_cancel()
            foreground = self.foreground()
            if foreground == ONE:
                return {'state': 'native_app_open', 'verified_foreground': ONE,
                        'message': 'Google One native app is open inside Android.'}
            if self.clock() >= deadline:
                break
            self.pause(min(1, deadline - self.clock()))
        if foreground in (GMS, 'com.android.settings', 'com.google.android.permissioncontroller',
                          'com.android.permissioncontroller'):
            return {'state': 'android_confirmation', 'verified_foreground': foreground,
                    'message': 'Android requires account confirmation or a permission. Complete it on the emulator screen.'}
        return {'state': 'launch_unconfirmed', 'verified_foreground': foreground,
                'message': 'Google One is installed, but its foreground screen was not confirmed. Inspect the emulator.'}

    def open(self, install_wait: float = 600) -> dict:
        snapshot = self.wait_ready()
        if not snapshot.google_one:
            self.open_store()
            deadline = self.clock() + max(0, install_wait)
            while not self.installed(ONE):
                self.check_cancel()
                if self.clock() >= deadline:
                    return {'state': 'install_required', 'verified_foreground': None,
                            'message': 'Google One is not installed yet. Complete Install in Play Store, then press Open Google One.'}
                self.pause(min(2, deadline - self.clock()))
            self.emit('Google One installation detected', 'Launching the native Android app automatically.')
        return self.launch_one()
