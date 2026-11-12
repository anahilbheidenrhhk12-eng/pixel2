import sys
import threading
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_one_session import (GMS, ONE, PLAY, NativeOneSession, NativeAppError,
                                packages_from, foreground_from, activity_from, command_failed)

class Clock:
    def __init__(self): self.now = 0.0
    def time(self): return self.now
    def wait(self, value): self.now += value

class Device:
    def __init__(self, installed=True):
        self.calls=[]; self.one=installed; self.boot='1'; self.pm=True
        self.play=True; self.gms=True; self.online=True; self.foreground='com.android.launcher3'
        self.launch_target=ONE; self.resolve=True; self.reject=False; self.install_after=None
        self.install_polls=0; self.store_error=False
    def adb(self, *args, **kwargs):
        self.calls.append(args)
        if args == ('get-state',): return 'device' if self.online else 'offline'
        if args[:3] == ('shell','getprop','sys.boot_completed'): return self.boot
        if args[:4] == ('shell','pm','list','packages'):
            if not self.pm: return "Error: Can't find service: package"
            p=['android']
            if self.play: p.append(PLAY)
            if self.gms: p.append(GMS)
            if len(args)==5 and args[4]==ONE:
                self.install_polls += 1
                if self.install_after and self.install_polls >= self.install_after: self.one=True
            if self.one: p.append(ONE)
            if len(args)==5: p=[v for v in p if args[4] in v]
            return '\n'.join('package:'+v for v in p)
        if args[:4] == ('shell','dumpsys','activity','activities'):
            return ('mResumedActivity: ActivityRecord{1a u0 '+self.foreground+'/.Main t1}'
                    if self.foreground else '')
        if args[:4] == ('shell','cmd','package','resolve-activity'):
            return ONE+'/.MainActivity' if self.resolve else 'No activity found'
        if args[:3] == ('shell','am','start'):
            if '-d' in args:
                self.foreground=PLAY
                return 'Error: unable to resolve Intent' if self.store_error else 'Status: ok'
            self.foreground=self.launch_target
            return 'Error: Activity class does not exist.' if self.reject else 'Status: ok'
        if args[:2] == ('shell','monkey'):
            self.foreground=self.launch_target
            return 'No activities found to run' if self.reject else 'Events injected: 1'
        raise AssertionError('Unexpected ADB command: '+str(args))

class SessionTests(unittest.TestCase):
    def make(self, dev=None, cancel=None):
        self.device=dev or Device(); self.clock=Clock(); self.events=[]
        return NativeOneSession(self.device.adb,self.events.append,cancel,
                                self.clock.time,self.clock.wait)
    def test_exact_package_names(self):
        self.assertEqual(packages_from('package:'+ONE+'.other\npackage:android'),{ONE+'.other','android'})
    def test_foreground_not_recent_task(self):
        self.assertIsNone(foreground_from('Hist #1: ActivityRecord{foo u0 '+ONE+'/.Main t1}'))
    def test_top_resumed_priority(self):
        text='mResumedActivity: ActivityRecord{a u0 '+PLAY+'/.Main t1}\n'+'topResumedActivity=ActivityRecord{a u0 '+ONE+'/.Main t2}'
        self.assertEqual(foreground_from(text),ONE)
    def test_component_must_belong_to_google_one(self):
        self.assertIsNone(activity_from('com.other/.Main', ONE))
    def test_error_with_success_exit_is_detected(self):
        self.assertTrue(command_failed('Starting: Intent\nError type 3\nError: Activity missing'))
    def test_boot_property_is_not_enough(self):
        d=Device(); d.pm=False; s=self.make(d)
        self.assertFalse(s.inspect().ready)
    def test_missing_play_services_does_not_mark_ready(self):
        d=Device(); d.gms=False; s=self.make(d)
        self.assertFalse(s.inspect().ready)
        with self.assertRaisesRegex(NativeAppError,'Google Play services'): s.wait_ready(timeout=2)
    def test_offline_has_no_android_commands(self):
        d=Device(); d.online=False; s=self.make(d)
        self.assertFalse(s.inspect().ready); self.assertEqual(len(d.calls),1)
    def test_native_launch_verified(self):
        s=self.make(); result=s.open(0)
        self.assertEqual(result['state'],'native_app_open')
        self.assertEqual(result['verified_foreground'],ONE)
    def test_launch_command_success_not_foreground_success(self):
        d=Device(); d.launch_target='com.android.launcher3'; s=self.make(d)
        self.assertEqual(s.launch_one(timeout=2)['state'],'launch_unconfirmed')
    def test_android_confirmation_is_not_app_success(self):
        d=Device(); d.launch_target=GMS; s=self.make(d)
        self.assertEqual(s.launch_one(timeout=2)['state'],'android_confirmation')
    def test_install_required_is_not_success(self):
        d=Device(False); s=self.make(d)
        self.assertEqual(s.open(0)['state'],'install_required')
        self.assertFalse(any(c[:2]==('shell','monkey') for c in d.calls))
    def test_auto_launch_after_install(self):
        d=Device(False); d.install_after=3; s=self.make(d)
        self.assertEqual(s.open(10)['state'],'native_app_open')
        self.assertTrue(any(e['message']=='Google One installation detected' for e in self.events))
    def test_no_reinstall_on_next_open(self):
        s=self.make(); s.open(0)
        self.assertFalse(any('market://details?id='+ONE in c for c in self.device.calls))
    def test_launch_rejection_is_error(self):
        d=Device(); d.reject=True; s=self.make(d)
        with self.assertRaisesRegex(NativeAppError,'rejected'): s.open(0)
    def test_monkey_fallback_verified(self):
        d=Device(); d.resolve=False; s=self.make(d)
        self.assertEqual(s.open(0)['state'],'native_app_open')
    def test_cancellation_stops_install_watch(self):
        d=Device(False); event=threading.Event()
        def cancel():
            if event.is_set(): raise InterruptedError('stop')
        s=self.make(d,cancel)
        def wait(n): self.clock.wait(n); event.set()
        s.wait=wait
        with self.assertRaises(InterruptedError): s.open(10)
    def test_store_failure_is_not_install_wait(self):
        d=Device(False); d.store_error=True; s=self.make(d)
        with self.assertRaisesRegex(NativeAppError,'could not open'): s.open(10)
    def test_status_has_no_account_information(self):
        s=self.make(); r=s.inspect().report()
        self.assertEqual(set(r),{'online','booted','package_manager','play_store','play_services','google_one','foreground','android_ready'})

if __name__=='__main__': unittest.main()
