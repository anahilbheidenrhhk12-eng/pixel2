"""Desktop v3 runtime: actual tool output, cached setup and cancellable work.
No account credentials or device-identity modifications are performed here.
"""
from __future__ import annotations
import codecs
import hashlib
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import winpixel_sdk as sdk


class SetupCancelled(RuntimeError):
    pass


def sdk_progress(text):
    """Return the SDK tool's reported operation percent, never elapsed/estimated."""
    values = re.findall(r'(?<![\d.])(\d{1,3})(?:\.\d+)?\s*%', text)
    return min(100, int(values[-1])) if values else None


def clean_output(text):
    return re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text).strip()


class Runtime:
    def __init__(self, notify, cancel=None):
        self.notify = notify
        self.cancel = cancel or threading.Event()
        self.phase = 'check'
        self.process = None
        self.log_dir = sdk.home() / 'logs'
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._base_fetch = sdk.fetch

    def emit(self, message, percent=None, detail=''):
        self.notify({'type': 'progress', 'phase': self.phase,
                     'message': str(message), 'percent': percent, 'detail': detail})

    def check_cancelled(self):
        if self.cancel.is_set():
            raise SetupCancelled('Operation stopped. Installed files have been kept.')

    def kill_tree(self, process):
        if process.poll() is not None:
            return
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           stdin=subprocess.DEVNULL, timeout=10,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        else:
            process.kill()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()

    def run(self, command, env=None, input_data=None, timeout=300,
            progress=None, label='Android SDK'):
        """Read CR-delimited sdkmanager output while the process is running."""
        self.check_cancelled()
        output_queue = queue.Queue()
        proc = subprocess.Popen([str(x) for x in command], env=env,
            stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.process = proc
        def read_output():
            try:
                while True:
                    chunk = proc.stdout.read1(4096)
                    if not chunk:
                        break
                    output_queue.put(chunk)
            finally:
                output_queue.put(None)
        threading.Thread(target=read_output, daemon=True).start()
        if input_data is not None:
            def write_input():
                try:
                    proc.stdin.write(input_data.encode('utf-8'))
                    proc.stdin.close()
                except (OSError, BrokenPipeError):
                    pass
            threading.Thread(target=write_input, daemon=True).start()
        started = last_update = time.monotonic()
        decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        fragments, pending, ended, last_line = [], '', False, ''
        self.emit(label, detail='Reading installer output')
        try:
            with (self.log_dir / 'installer.log').open('a', encoding='utf-8') as logfile:
                while not ended or proc.poll() is None:
                    self.check_cancelled()
                    if time.monotonic() - started > timeout:
                        raise TimeoutError(label + ' timed out. See installer.log.')
                    try:
                        chunk = output_queue.get(timeout=0.15)
                    except queue.Empty:
                        chunk = b''
                    if chunk is None:
                        ended = True
                    elif chunk:
                        text = decoder.decode(chunk)
                        fragments.append(text)
                        logfile.write(text)
                        logfile.flush()
                        pending += text
                        parts = re.split(r'[\r\n]', pending)
                        pending = parts.pop()
                        for item in parts:
                            line = clean_output(item)
                            if line and line != last_line:
                                last_line = line
                                self.emit(label, sdk_progress(line), line[-350:])
                                last_update = time.monotonic()
                    if time.monotonic() - last_update >= 10:
                        self.emit(label, detail='Tool is running; no new progress reported. ' + last_line[-160:])
                        last_update = time.monotonic()
                output = ''.join(fragments)
                if proc.returncode:
                    tail = clean_output(output)[-1500:]
                    raise RuntimeError(label + ' failed (exit ' + str(proc.returncode) + '):\n' + tail)
                return output
        except BaseException:
            self.kill_tree(proc)
            raise
        finally:
            self.process = None
            if proc.stdout:
                proc.stdout.close()

    def fetch(self, url, destination, expected_sha=None, progress=None):
        """Resume our direct downloads when the server supports byte ranges."""
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        part = destination.with_name(destination.name + '.part')
        def digest(path):
            h = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    self.check_cancelled()
                    h.update(block)
            return h.hexdigest()
        if destination.is_file() and expected_sha and digest(destination) == expected_sha:
            self.emit('Using cached ' + destination.name, 100)
            return destination
        for attempt in range(3):
            self.check_cancelled()
            offset = part.stat().st_size if part.exists() else 0
            headers = {'User-Agent': 'DigiPixelServer/3.0', 'Accept-Encoding': 'identity'}
            if offset:
                headers['Range'] = 'bytes=' + str(offset) + '-'
            try:
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=30) as response:
                    code = response.status
                    cr = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
                    if code == 206 and (not cr or int(cr[1]) != offset):
                        raise RuntimeError('Download server returned an invalid byte range.')
                    if code != 206:
                        offset = 0
                    size = int(response.headers.get('Content-Length') or 0)
                    total = int(cr[3]) if cr and code == 206 else size
                    received, session_bytes = offset, 0
                    started = last_update = time.monotonic()
                    with part.open('ab' if offset else 'wb') as output:
                        while True:
                            self.check_cancelled()
                            block = response.read(256 * 1024)
                            if not block:
                                break
                            output.write(block)
                            received += len(block)
                            session_bytes += len(block)
                            now = time.monotonic()
                            if now - last_update >= 0.4:
                                rate = session_bytes / max(0.001, now-started) / 1048576
                                detail = '%.1f MB' % (received/1048576)
                                if total:
                                    detail += ' / %.1f MB' % (total/1048576)
                                detail += '  |  %.2f MB/s' % rate
                                self.emit('Downloading ' + destination.name,
                                          100*received/total if total else None, detail)
                                last_update = now
                    if total and received != total:
                        raise OSError('Incomplete download; retrying from saved bytes.')
                if expected_sha and digest(part).lower() != expected_sha.lower():
                    part.unlink(missing_ok=True)
                    raise RuntimeError('Download checksum mismatch: ' + destination.name)
                part.replace(destination)
                self.emit('Downloaded ' + destination.name, 100)
                return destination
            except SetupCancelled:
                raise
            except urllib.error.HTTPError as exc:
                if exc.code == 416:
                    part.unlink(missing_ok=True)
                if attempt == 2:
                    raise
            except (OSError, TimeoutError):
                if attempt == 2:
                    raise
            self.emit('Retrying download', detail='Saved partial file is kept when the server supports resume.')
            if self.cancel.wait(1 + attempt):
                self.check_cancelled()
        raise RuntimeError('Download failed')

    def install_io(self):
        # Compatibility layer for existing SDK provisioning; identity code is untouched.
        sdk.run = self.run
        sdk.fetch = self.fetch

    def installed_play_image(self, root):
        images = []
        for props in (root / 'system-images').glob('android-*/google_apis_playstore*/x86_64/source.properties'):
            folder = props.parent
            if not (folder / 'system.img').is_file() or not (folder / 'package.xml').is_file():
                continue
            match = re.search(r'android-(\d+)', str(folder))
            if match:
                images.append((int(match[1]), ';'.join(folder.relative_to(root).parts)))
        return max(images)[1] if images else None

    def select_image(self, root, manager, env):
        installed = self.installed_play_image(root)
        if installed:
            self.emit('Reusing installed Google Play image', 100, installed)
            return installed
        listing = self.run([manager, '--sdk_root=' + str(root), '--list'], env,
                           timeout=180, label='Finding a Google Play system image')
        candidates = set(re.findall(r'system-images;android-\d+(?:\.\d+)?;google_apis_playstore(?:_ps16k)?;x86_64', listing))
        if not candidates:
            raise RuntimeError('No Google Play x86_64 image is listed by the official SDK.')
        return max(candidates, key=lambda item: tuple(int(n) for n in re.findall(r'android-(\d+)(?:\.(\d+))?', item)[0] if n))

    def acceleration_check(self, root, env):
        self.phase = 'check'
        self.emit('Checking hardware acceleration')
        try:
            self.run([root/'emulator'/'emulator.exe', '-accel-check'], env,
                     timeout=25, label='Hardware acceleration check')
        except RuntimeError as exc:
            raise RuntimeError('Hardware acceleration is not ready. Enable virtualization in BIOS and Windows Hypervisor Platform, then restart Windows.\n' + str(exc)) from exc

    def prepare(self):
        self.install_io()
        self.phase = 'check'
        self.emit('Checking installed components')
        if os.name != 'nt':
            raise RuntimeError('This launcher requires Windows 10/11, 64-bit.')
        root = sdk.find_sdk()
        root.mkdir(parents=True, exist_ok=True)
        env = sdk.sdk_env(root)
        avd_ini = Path.home()/'.android'/'avd'/(sdk.AVD_NAME+'.ini')
        tools_ok = all((root/path).is_file() for path in ['platform-tools/adb.exe', 'emulator/emulator.exe'])
        if tools_ok and avd_ini.exists():
            self.emit('Existing Android installation found; download skipped', 100)
            self.acceleration_check(root, env)
            os.environ.update({k: env[k] for k in ('ANDROID_HOME','ANDROID_SDK_ROOT','PATH')})
            return root, env
        free = shutil.disk_usage(root).free
        if free < 10*1024**3:
            raise RuntimeError('Less than 10 GB disk space is free in the SDK folder. Free space before continuing.')
        self.phase = 'download'
        env = sdk.ensure_java(env, self.emit)
        manager = sdk.ensure_cmdline(root, self.emit)
        env['PATH'] = str(manager.parent) + os.pathsep + env.get('PATH', '')
        self.phase = 'install'
        self.run([manager, '--sdk_root='+str(root), '--licenses'], env,
                 input_data='y\n'*150, timeout=180, label='Checking SDK licenses')
        missing = []
        if not (root/'platform-tools'/'adb.exe').is_file():
            missing.append('platform-tools')
        if not (root/'emulator'/'emulator.exe').is_file():
            missing.append('emulator')
        if missing:
            self.run([manager, '--sdk_root='+str(root), *missing], env,
                     input_data='y\n'*150, timeout=1800, label='Installing emulator tools')
        self.acceleration_check(root, env)
        self.phase = 'install'
        package = self.select_image(root, manager, env)
        if not self.installed_play_image(root):
            self.run([manager, '--sdk_root='+str(root), package], env,
                     input_data='y\n'*150, timeout=3600, label='Installing Google Play system image')
        if not avd_ini.exists():
            avdm = manager.with_name('avdmanager.bat')
            self.emit('Creating persistent Android device')
            devices = self.run([avdm, 'list', 'device'], env, timeout=45, label='Reading device profiles')
            profile = 'pixel_9_pro_xl' if '"pixel_9_pro_xl"' in devices else 'pixel'
            self.run([avdm, 'create', 'avd', '-n', sdk.AVD_NAME, '-k', package,
                      '--device', profile], env, input_data='no\n', timeout=180,
                     label='Creating Android virtual device')
        os.environ.update({k: env[k] for k in ('ANDROID_HOME','ANDROID_SDK_ROOT','PATH','JAVA_HOME') if k in env})
        return root, env

    def start(self):
        root, env = self.prepare()
        self.phase = 'boot'
        self.emit('Starting Android')
        existing = sdk.ready_emulator(root)
        process = None
        bootlog = self.log_dir/'emulator.log'
        if not existing:
            with bootlog.open('ab') as output:
                process = subprocess.Popen([str(root/'emulator'/'emulator.exe'),
                    '-avd', sdk.AVD_NAME, '-no-boot-anim', '-gpu', 'auto'],
                    env=env, cwd=str(root/'emulator'), stdin=subprocess.DEVNULL,
                    stdout=output, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        deadline = time.monotonic()+300
        while time.monotonic() < deadline:
            self.check_cancelled()
            if process and process.poll() is not None:
                tail = bootlog.read_text(encoding='utf-8', errors='replace')[-1600:]
                raise RuntimeError('Android exited before boot completed.\n'+tail)
            for serial in sdk.ready_emulator(root):
                try:
                    boot = sdk.adb_command(root, 'shell','getprop','sys.boot_completed', serial=serial, timeout=8)
                    if boot == '1':
                        os.environ['ANDROID_SERIAL'] = serial
                        self.phase = 'ready'
                        self.emit('Android is ready', 100, serial)
                        return root, serial
                except RuntimeError:
                    continue
            self.emit('Android is booting', detail='Waiting for Android boot completion; Railway status is independent.')
            if self.cancel.wait(3):
                self.check_cancelled()
        raise RuntimeError('Android boot timed out. Open emulator.log for the device error.')
