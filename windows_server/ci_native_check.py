"""Real ADB integration check on a fresh CI emulator; no Google credentials."""
import json
import subprocess
import sys
import time
from pathlib import Path
from native_one_session import NativeOneSession, ONE, PLAY

out = Path('qa/native')
out.mkdir(parents=True, exist_ok=True)
def adb(*args, timeout=30):
    r = subprocess.run(['adb', '-s', 'emulator-5554', *args], capture_output=True,
                       text=True, errors='replace', timeout=timeout)
    if r.returncode: raise RuntimeError(r.stderr[-300:])
    return r.stdout.strip()

report = {'test_type': 'real_android_emulator', 'google_login_tested': False}
try:
    controller = NativeOneSession(adb)
    ready = controller.wait_ready(timeout=90)
    report.update(ready.report())
    report['android_version'] = adb('shell','getprop','ro.build.version.release')
    report['android_api'] = adb('shell','getprop','ro.build.version.sdk')
    result = controller.open(install_wait=0)
    report['app_result'] = result
    if not ready.google_one:
        assert result['state'] == 'install_required', 'Missing app must not pass as opened'
        deadline = time.monotonic() + 20
        foreground = None
        while time.monotonic() < deadline:
            foreground = controller.foreground()
            if foreground == PLAY: break
            time.sleep(1)
        report['verified_store_foreground'] = foreground
        assert foreground == PLAY, 'Native Play Store did not reach the foreground'
    else:
        assert result['state'] in ('native_app_open', 'android_confirmation'), result
    image = subprocess.run(['adb','-s','emulator-5554','exec-out','screencap','-p'],
                           capture_output=True, timeout=15)
    if image.returncode == 0 and image.stdout.startswith(b'\x89PNG'):
        (out/'android-screen.png').write_bytes(image.stdout)
    report['integration_passed'] = True
except Exception as exc:
    report['integration_passed'] = False
    report['error'] = str(exc)
    raise
finally:
    (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('NATIVE_INTEGRATION_RESULT:',json.dumps(report))
