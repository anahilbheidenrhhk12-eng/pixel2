import os,subprocess,threading,time,base64,html,json,urllib.request,urllib.error
from http.server import HTTPServer,BaseHTTPRequestHandler
TOKEN=os.environ.get("VIEWER_TOKEN","")
REMOTE_ADB=os.environ.get("ANDROID_ADB_ENDPOINT","").strip()
PHONEBOX_KEY=os.environ.get("PHONEBOX_API_KEY","").strip()
PHONEBOX_ID=os.environ.get("PHONEBOX_PHONE_ID","").strip()
def phonebox_request(path):
 req=urllib.request.Request("https://phonebox.dev/v1/phones/"+PHONEBOX_ID+path,headers={"Authorization":"Bearer "+PHONEBOX_KEY})
 with urllib.request.urlopen(req,timeout=25) as response:
  return response.read(),response.headers.get("Content-Type","application/octet-stream")
def adb_args(*args):
 return ["adb"]+(["-s",REMOTE_ADB] if REMOTE_ADB else [])+list(args)
STATE={"status":"starting"}
def report(message):
 print("[ANDROID-TEST] "+str(message),flush=True)
 STATE["status"]=str(message)
def emulator_diagnostics():
 try:
  with open("/tmp/emulator.log","r",errors="replace") as f:
   tail=f.read()[-5000:]
  lines=[line for line in tail.splitlines() if any(term in line.lower() for term in ("error","fatal","warning","failed","kvm","accel","qemu","memory","panic"))]
  print("[ANDROID-TEST] emulator diagnostics: "+(" | ".join(lines[-12:])[-2400:] if lines else tail[-1200:] or "(log empty)"),flush=True)
 except Exception as e:print("[ANDROID-TEST] diagnostics error: "+repr(e),flush=True)
def boot():
 try:
  if PHONEBOX_KEY:
   if not PHONEBOX_ID:report("PHONEBOX_PHONE_ID is missing");return
   try:
    data,_=phonebox_request("")
    obj=json.loads(data)
    report("Phonebox connected; phone status="+str(obj.get("status","unknown"))+"; phone="+PHONEBOX_ID)
   except urllib.error.HTTPError as e:
    if e.code==404:
     try:
      req=urllib.request.Request("https://phonebox.dev/v1/phones",headers={"Authorization":"Bearer "+PHONEBOX_KEY})
      with urllib.request.urlopen(req,timeout=25) as response: phones=json.load(response).get("data",[])
      report("Configured Phonebox ID not found. Available phones: "+", ".join(str(x.get("id"))+" ("+str(x.get("status"))+")" for x in phones[:10]))
     except Exception as err:report("Phonebox phone-list lookup failed: "+str(err))
    else:report("Phonebox HTTP error: "+str(e.code))
    return
   except Exception as e:report("Phonebox connection failed: "+str(e));return
   return
  if REMOTE_ADB:
   report("Connecting to remote Android via ADB")
   for i in range(180):
    subprocess.run(["adb","connect",REMOTE_ADB],capture_output=True,text=True,timeout=15)
    x=subprocess.run(adb_args("shell","getprop","sys.boot_completed"),capture_output=True,text=True,timeout=15)
    if x.stdout.strip()=="1":report("Remote Android booted and connected");return
    if i%10==0:report("Waiting for remote Android; elapsed="+str(i*3)+"s; adb="+(x.stdout.strip() or x.stderr.strip()[:120]))
    time.sleep(3)
   report("Remote Android connection timeout");return
  if not os.path.exists("/dev/kvm"):
   report("KVM unavailable on this host. Set ANDROID_ADB_ENDPOINT to a private VPN Android ADB address (host:port). Local emulator disabled.");return
  report("Launching emulator")
  p=subprocess.Popen(["emulator","-avd","androidtest","-no-window","-no-audio","-no-boot-anim","-no-snapshot","-accel","off","-gpu","swiftshader_indirect","-memory","2048","-cores","2"],stdout=open("/tmp/emulator.log","w"),stderr=subprocess.STDOUT)
  report("emulator started pid="+str(p.pid))
  for i in range(180):
   x=subprocess.run(adb_args("shell","getprop","sys.boot_completed"),capture_output=True,text=True,timeout=15)
   if x.stdout.strip()=="1":report("Android booted");return
   if p.poll() is not None:
    report("emulator exited "+str(p.returncode))
    try:report(open("/tmp/emulator.log").read()[-4000:])
    except Exception:pass
    return
   if i%10==0:
    emulator_diagnostics()
    report("waiting for Android boot; elapsed="+str(i*3)+"s; adb="+(x.stdout.strip() or x.stderr.strip()[:120]))
   time.sleep(3)
  emulator_diagnostics()
  report("boot timeout")
 except Exception as e:report(repr(e))
class H(BaseHTTPRequestHandler):
 def auth(self):
  if not TOKEN or self.headers.get("Authorization")!="Bearer "+TOKEN:
   self.send_response(401);self.end_headers();self.wfile.write(b"Set VIEWER_TOKEN and send Authorization: Bearer <token>");return False
  return True
 def do_GET(self):
  if self.path.split("?",1)[0]=="/health":
   self.send_response(200);self.end_headers();self.wfile.write(STATE["status"].encode());return
  if not self.auth():return
  if self.path.split("?",1)[0]=="/screen":
   if PHONEBOX_KEY and PHONEBOX_ID:
    try:
     data,mime=phonebox_request("/screenshot?format=png&max_width=720")
     self.send_response(200);self.send_header("Content-Type",mime);self.send_header("Cache-Control","no-store");self.end_headers();self.wfile.write(data)
    except Exception as e:self.send_error(503,str(e))
    return
   try:
    p=subprocess.run(adb_args("exec-out","screencap","-p"),capture_output=True,timeout=30)
    self.send_response(200 if p.returncode==0 else 503);self.send_header("Content-Type","image/png");self.end_headers();self.wfile.write(p.stdout)
   except Exception as e:self.send_error(503,str(e))
  else:
   self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8");self.end_headers();self.wfile.write(("<h2>Android test: "+html.escape(STATE["status"])+"</h2><p>Use Authorization Bearer token for /screen; ADB control API will be added after successful boot.</p>").encode())
threading.Thread(target=boot,daemon=True).start()
HTTPServer(("0.0.0.0",int(os.environ.get("PORT","8080"))),H).serve_forever()
