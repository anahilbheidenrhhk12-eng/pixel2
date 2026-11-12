import hashlib
import http.server
import os
from pathlib import Path
import socketserver
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop_runtime import Runtime, SetupCancelled, clean_output, sdk_progress

DATA = bytes(range(256))*8192
REQUESTS = []


class DownloadHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def do_GET(self):
        offset = int(self.headers.get('Range','bytes=0-').split('=')[1].split('-')[0])
        REQUESTS.append((self.path,offset))
        if self.path == '/ignore-range':
            offset = 0
        if offset:
            self.send_response(206)
            self.send_header('Content-Range',f'bytes {offset}-{len(DATA)-1}/{len(DATA)}')
        else:
            self.send_response(200)
        self.send_header('Content-Length',str(len(DATA)-offset))
        self.end_headers()
        self.wfile.write(DATA[offset:])


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = socketserver.TCPServer(('127.0.0.1',0),DownloadHandler)
        threading.Thread(target=cls.http.serve_forever,daemon=True).start()
        cls.url = 'http://127.0.0.1:'+str(cls.http.server_address[1])
    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        self.patcher = patch('desktop_runtime.sdk.home',return_value=self.path)
        self.patcher.start()
        self.events = []
        self.rt = Runtime(self.events.append)
        REQUESTS.clear()
    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()
    def test_percent_is_reported_not_invented(self):
        self.assertIsNone(sdk_progress('Installing ... 132 sec'))
        self.assertEqual(sdk_progress('[=======] 42% Unzipping system.img'),42)
        self.assertEqual(sdk_progress('100% done'),100)
    def test_ansi_cleanup(self):
        self.assertEqual(clean_output('\x1b[32mREADY\x1b[0m'),'READY')
    def test_streaming_carriage_return_progress(self):
        cmd = [sys.executable,'-u','-c',"import sys,time; sys.stdout.write('10% Downloading\\r'); sys.stdout.flush(); time.sleep(.15); print('55% Unzipping')"]
        text = self.rt.run(cmd,timeout=5,label='Fixture install')
        self.assertIn('55%',text)
        percentages = [e['percent'] for e in self.events]
        self.assertIn(10,percentages)
        self.assertIn(55,percentages)
    def test_tool_failure_retains_error(self):
        with self.assertRaisesRegex(RuntimeError,'disk fixture failure'):
            self.rt.run([sys.executable,'-c',"import sys; print('disk fixture failure',file=sys.stderr); sys.exit(7)"],timeout=5)
    def test_cancel_before_launch(self):
        self.rt.cancel.set()
        with self.assertRaises(SetupCancelled):
            self.rt.run([sys.executable,'-c','pass'])
    def test_cancel_running_process(self):
        timer = threading.Timer(.3,self.rt.cancel.set)
        timer.start()
        started = time.monotonic()
        with self.assertRaises(SetupCancelled):
            self.rt.run([sys.executable,'-u','-c','import time; print("started"); time.sleep(20)'],timeout=10)
        timer.cancel()
        self.assertLess(time.monotonic()-started,12)
        self.assertIsNone(self.rt.process)
    def test_timeout_stops_child(self):
        with self.assertRaises(TimeoutError):
            self.rt.run([sys.executable,'-c','import time; time.sleep(20)'],timeout=.2)
    def test_download_and_checksum(self):
        target = self.path/'download.zip'
        self.rt.fetch(self.url+'/file',target,hashlib.sha256(DATA).hexdigest())
        self.assertEqual(target.read_bytes(),DATA)
        self.assertFalse(target.with_name(target.name+'.part').exists())
    def test_download_resume(self):
        target = self.path/'resume.zip'
        part = target.with_name(target.name+'.part')
        part.write_bytes(DATA[:20000])
        self.rt.fetch(self.url+'/file',target,hashlib.sha256(DATA).hexdigest())
        self.assertIn(('/file',20000),REQUESTS)
        self.assertEqual(target.read_bytes(),DATA)
    def test_server_without_range_restarts_cleanly(self):
        target = self.path/'restart.zip'
        target.with_name(target.name+'.part').write_bytes(DATA[:20000])
        self.rt.fetch(self.url+'/ignore-range',target,hashlib.sha256(DATA).hexdigest())
        self.assertEqual(target.read_bytes(),DATA)
    def test_checksum_failure_never_publishes_file(self):
        target = self.path/'corrupt.zip'
        with self.assertRaisesRegex(RuntimeError,'checksum'):
            self.rt.fetch(self.url+'/file',target,'0'*64)
        self.assertFalse(target.exists())
    def test_verified_cache_skips_network(self):
        target = self.path/'cache.zip'
        target.write_bytes(DATA)
        self.rt.fetch('http://127.0.0.1:1/not-called',target,hashlib.sha256(DATA).hexdigest())
        self.assertEqual(REQUESTS,[])
    def test_cached_image_reused_without_sdk_query(self):
        directory = self.path/'system-images/android-36/google_apis_playstore/x86_64'
        directory.mkdir(parents=True)
        for name in ['source.properties','package.xml','system.img']:
            (directory/name).write_text('fixture',encoding='utf-8')
        with patch.object(self.rt,'run',side_effect=AssertionError('SDK query must not run')):
            selected = self.rt.select_image(self.path,Path('unused'),{})
        self.assertEqual(selected,'system-images;android-36;google_apis_playstore;x86_64')
    def test_incomplete_image_is_not_ready(self):
        directory = self.path/'system-images/android-36/google_apis_playstore/x86_64'
        directory.mkdir(parents=True)
        (directory/'source.properties').write_text('fixture',encoding='utf-8')
        self.assertIsNone(self.rt.installed_play_image(self.path))


if __name__ == '__main__':
    unittest.main(verbosity=2)
