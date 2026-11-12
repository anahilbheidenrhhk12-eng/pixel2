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
def phonebox_api(path, method="GET", payload=None, timeout=90):
 url="https://phonebox.dev/v1/phones/"+PHONEBOX_ID+path
 headers={"Authorization":"Bearer "+PHONEBOX_KEY}
 body=None
 if payload is not None:
  headers["Content-Type"]="application/json"
  body=json.dumps(payload).encode("utf-8")
 req=urllib.request.Request(url,headers=headers,data=body,method=method)
 with urllib.request.urlopen(req,timeout=timeout) as response:
  result=response.read()
 return json.loads(result) if result else {}

GOOGLE_ONE_APP="com.google.android.apps.subscriptions.red"
def google_one_is_installed():
 result=phonebox_api("/apps")
 installed=result.get("data",result.get("apps",[]))
 return any(isinstance(app,dict) and app.get("package")==GOOGLE_ONE_APP for app in installed)
def native_google_one_test():
 """Open the actual Google One Android app, never browser-only; park when done."""
 try:
  status=phonebox_api("").get("status","unknown")
  report("Native Google One test: phone state="+status)
  if status in ("parked","unavailable"):
   status=phonebox_api("/start","POST",{"idle_timeout":60,"max_duration":180,"wait":True},timeout=75).get("status","unknown")
  for i in range(4):
   if status=="ready":break
   if status not in ("creating","starting"):report("Native test interrupted: "+status);return
   status=phonebox_api("?wait=ready&timeout=35",timeout=50).get("status","unknown")
  if status!="ready":report("Native test unable to start: "+status);return
  specs=phonebox_api("/device")
  report("Native Android phone model="+str(specs.get("model","unknown"))+"; Android="+str(specs.get("android_version",specs.get("android","unknown"))))
  present=google_one_is_installed()
  report("Google One Android package installed="+str(present))
  if not present:
   try:
    resp=phonebox_api("/apps","POST",{"package":GOOGLE_ONE_APP},timeout=40)
    report("Google One installation requested, state="+str(resp.get("status","unknown")))
   except urllib.error.HTTPError as e:
    reason=e.read(1500).decode("utf-8","replace")
    report("Google One app install unavailable HTTP "+str(e.code)+"; "+reason[:250])
   for i in range(8):
    if google_one_is_installed():present=True;break
    time.sleep(5)
  if not present:
   report("Google One native app NOT installed. Opening its Google Play listing instead.")
   page=phonebox_api("/actions","POST",{"actions":[{"type":"open_url","url":"market://details?id="+GOOGLE_ONE_APP,"package":"com.android.vending"}],"observe":"ui"},timeout=95)
   result=(page.get("results") or [{}])[0]
   report("Play Store listing opened="+str(result.get("ok",False))+"; foreground="+str((page.get("observation",{}).get("app") or {}).get("package","unknown")))
   return
  action=phonebox_api("/actions","POST",{"actions":[{"type":"open_app","package":GOOGLE_ONE_APP},{"type":"wait","ms":2500}],"observe":"ui"},timeout=95)
  results=action.get("results") or []
  failed=[x.get("error",{}).get("code") for x in results if not x.get("ok")]
  observation=action.get("observation") or {}
  app=(observation.get("app") or {}).get("package","unknown")
  elem=observation.get("elements",[])
  if failed:
   report("Google One native app launch FAILED: "+str(failed)+"; foreground="+str(app))
  else:
   prompt=any("sign in" in str(x.get("text","")).lower() or "add account" in str(x.get("text","")).lower() for x in elem if isinstance(x,dict))
   report("Google One native app opened. foreground="+str(app)+"; elements="+str(len(elem))+"; sign_in_prompt="+str(prompt))
 except urllib.error.HTTPError as e:
  report("Native Google One test HTTP "+str(e.code)+"; "+e.read(900).decode("utf-8","replace")[:300])
 except Exception as e:report("Native Google One test error: "+repr(e))
 finally:
  try:
   phonebox_api("/park","POST",{"wait":False},timeout=40)
   print("[ANDROID-TEST] Native test finished; phone park requested",flush=True)
   STATE["status"]+="; park requested"
  except Exception as e:
   print("[ANDROID-TEST] Native test park ERROR: "+repr(e),flush=True)
   STATE["status"]+="; park failed"

def phonebox_smoke_test():
 """One short paid test of Chrome Google One + Gmail login, then park."""
 phone_status="unknown"
 succeeded=[]
 try:
  phone=phonebox_api("")
  phone_status=phone.get("status","unknown")
  report("Phonebox smoke test started; current phone status="+phone_status)
  if phone_status in ("parked","unavailable"):
   report("Resuming Phonebox for a capped test session (max 180 seconds)")
   phone=phonebox_api("/start","POST",{"idle_timeout":60,"max_duration":180,"wait":True},timeout=90)
   phone_status=phone.get("status","unknown")
  for attempt in range(5):
   if phone_status=="ready":break
   if phone_status not in ("starting","creating"):
    report("Phonebox not ready: "+phone_status);return
   phone=phonebox_api("?wait=ready&timeout=20",timeout=35)
   phone_status=phone.get("status","unknown")
  if phone_status!="ready":
   report("Phonebox did not become ready; state="+phone_status);return
  device=phonebox_api("/device")
  report("Phonebox device: "+str(device.get("brand","?"))+" "+str(device.get("model","?"))+", Android "+str(device.get("android_version",device.get("android","?"))))
  for label,url in (("Google One","https://one.google.com/"),("Google account sign-in","https://accounts.google.com/signin/v2/identifier")):
   result=phonebox_api("/actions","POST",{"actions":[{"type":"open_url","url":url,"package":"com.android.chrome"}],"observe":"ui"},timeout=90)
   actions=result.get("results",[])
   if not actions or not actions[0].get("ok"):
    code=actions[0].get("error",{}).get("code","unknown") if actions else "empty_result"
    report("Test step failed: "+label+"; reason="+str(code));continue
   observed=result.get("observation") or {}
   app=(observed.get("app") or {}).get("package","unknown")
   print("[ANDROID-TEST] Opened "+label+" in phone; foreground app="+str(app)+"; UI elements="+str(len(observed.get("elements",[]))),flush=True)
   succeeded.append(label)
  if len(succeeded)==2:
   report("Phonebox smoke test SUCCESS: Google One and Google sign-in pages opened in Chrome")
  elif succeeded:
   report("Phonebox smoke test PARTIAL: "+", ".join(succeeded))
  else:report("Phonebox smoke test FAILED: neither page opened")
 except urllib.error.HTTPError as e:
  report("Phonebox smoke test HTTP "+str(e.code))
 except Exception as e:
  report("Phonebox smoke test error: "+repr(e))
 finally:
  try:
   phonebox_api("/park","POST",{"wait":False},timeout=35)
   print("[ANDROID-TEST] Phonebox park requested; session charges stopped",flush=True)
   STATE["status"] += "; park requested"
  except Exception as e:
   print("[ANDROID-TEST] ERROR: Phonebox park failed: "+repr(e),flush=True)
   STATE["status"] += "; PARK FAILED - check Phonebox"

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
   if os.environ.get("PHONEBOX_NATIVE_TEST","0")=="1":
    native_google_one_test()
    return
   if os.environ.get("PHONEBOX_SMOKE_TEST","0")=="1":
    phonebox_smoke_test()
    return
   try:
    data,_=phonebox_request("")
    obj=json.loads(data)
    report("Phonebox connected; phone status="+str(obj.get("status","unknown"))+"; phone="+PHONEBOX_ID)
    if obj.get("status")=="ready":
     try:
      info,_=phonebox_request("/device")
      d=json.loads(info)
      print("[ANDROID-TEST] Phonebox device: "+json.dumps(d),flush=True)
     except Exception as err:print("[ANDROID-TEST] Device inspection failed: "+str(err),flush=True)
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
  if self.path.split("?",1)[0]=="/device" and PHONEBOX_KEY and PHONEBOX_ID:
   try:
    data,mime=phonebox_request("/device")
    self.send_response(200);self.send_header("Content-Type","application/json");self.send_header("Cache-Control","no-store");self.end_headers();self.wfile.write(data)
   except Exception as e:self.send_error(503,str(e))
   return
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
