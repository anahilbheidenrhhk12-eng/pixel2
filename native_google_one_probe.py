#!/usr/bin/env python3
"""Google One native Android smoke test on an attached device or GitHub Actions AVD.
No credentials, purchase, device attestation changes, or entitlement claims.
"""
import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

APP = "com.google.android.apps.subscriptions.red"
OUT = Path("native_test_results")
OUT.mkdir(exist_ok=True)

def adb(*args, timeout=35, binary=False):
    proc = subprocess.run(["adb", *args], capture_output=True, timeout=timeout)
    if binary:
        return proc.returncode, proc.stdout, proc.stderr
    return proc.returncode, proc.stdout.decode("utf-8","replace").strip(), proc.stderr.decode("utf-8","replace").strip()

def getprop(name):
    return adb("shell","getprop",name)[1]

def capture(name):
    code, data, error = adb("exec-out","screencap","-p",binary=True)
    if code==0 and data.startswith(b"\x89PNG"):
        (OUT/name).write_bytes(data)
        return True
    return False

def nodes():
    code, text, err = adb("shell","uiautomator","dump","/sdcard/googleone_probe.xml",timeout=45)
    if code:
        return [], err
    code, xml, err = adb("exec-out","cat","/sdcard/googleone_probe.xml")
    if code:
        return [], err
    try:
        tree=ET.fromstring(xml)
    except ET.ParseError as exc:
        return [], str(exc)
    return [n.attrib for n in tree.iter("node")], None

def tap_label(phrases):
    items, err=nodes()
    if err:
        return False, "UI dump failed: "+err
    for phrase in phrases:
        for item in items:
            if phrase.casefold() in (item.get("text","")+" "+item.get("content-desc","")).casefold():
                m=re.findall(r"\d+",item.get("bounds",""))
                if len(m)==4:
                    a,b,c,d=map(int,m)
                    code,_,_=adb("shell","input","tap",str((a+c)//2),str((b+d)//2))
                    return code==0, phrase
    return False,"Not visible"

def main():
    report={"at":datetime.now(timezone.utc).isoformat(),"outcome":"started"}
    try:
        code,text,err=adb("devices")
        online=[x.split()[0] for x in text.splitlines()[1:] if x.split()[1:]==["device"]]
        if not online:
            raise RuntimeError("No ADB online devices: "+err+" "+text)
        report["serial"]=online[0]
        for key,prop in (
            ("model","ro.product.model"),("brand","ro.product.brand"),
            ("android","ro.build.version.release"),("api","ro.build.version.sdk"),
            ("fingerprint","ro.build.fingerprint")
        ):
            report[key]=getprop(prop)
        report["google_play_installed"]=bool(adb("shell","pm","path","com.android.vending")[1])
        report["google_play_services_installed"]=bool(adb("shell","pm","path","com.google.android.gms")[1])
        report["google_one_installed"]=bool(adb("shell","pm","path",APP)[1])
        print("Android:",report["android"],"API:",report["api"],"Model:",report["model"],flush=True)
        if not report["google_one_installed"]:
            report["outcome"]="blocked_google_one_not_installed"
            adb("shell","am","start","-a","android.intent.action.VIEW",
                "-d","market://details?id="+APP)
            time.sleep(3)
            capture("google_one_play_store.png")
            print("Google One native app is absent. Play Store page opened; no account is signed in.",flush=True)
            return
        code,out,err=adb("shell","monkey","-p",APP,"-c","android.intent.category.LAUNCHER","1")
        report["launch_ok"]=code==0 and "Events injected: 1" in out
        report["launch_error"]=err
        time.sleep(4)
        capture("google_one_native.png")
        items,error=nodes()
        report["ui_error"]=error
        report["ui_text"]=[(x.get("text") or x.get("content-desc") or "")[:100] for x in items
                            if x.get("text") or x.get("content-desc")][:30]
        if not report["launch_ok"]:
            report["outcome"]="failed_to_open_google_one"
            return
        report["outcome"]="google_one_app_opened"
        success,detail=tap_label(["Settings","الإعدادات","Paramètres"])
        report["settings"]={"found":success,"detail":detail}
        if success:
            time.sleep(2)
            capture("google_one_settings.png")
            success,detail=tap_label(["Check for offers","البحث عن عروض","Vérifier les offres"])
            report["check_for_offers"]={"found":success,"detail":detail}
            if success:
                time.sleep(3)
                capture("google_one_offers.png")
                report["outcome"]="offer_check_screen_opened"
    except Exception as exc:
        report["outcome"]="error"
        report["error"]=str(exc)
        print("Native probe failed:",str(exc),file=sys.stderr)
        raise
    finally:
        (OUT/"report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
        print("RESULT:",json.dumps({k:v for k,v in report.items() if k!="ui_text"},ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
