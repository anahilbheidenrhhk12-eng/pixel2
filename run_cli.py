import sys
import os
import getpass

# 确保导入路径正确
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import config
from device_simulator import create_device_profile
from google_automation import check_gemini_offer

def main():
    print(f"🤖 {config.DEVICE_MODEL} Google One Gemini Offer CLI 🤖")
    print("==================================================")
    
    # 选项：完全手动登录
    manual_login = input("Use manual sign-in in the browser? (y/n, default n): ").strip().lower() == 'y'
    
    email = ""
    password = ""
    totp = None
    
    if manual_login:
        config.HEADLESS = False
        print("💡 Manual sign-in mode enabled. A browser window will open.")
    else:
        email = input("Enter Gmail email: ").strip()
        if not email:
            print("❌ Gmail email is required.")
            return
            
        password = getpass.getpass("Enter your password: ").strip()
        if not password:
            print("❌ Password is required.")
            return
            
        totp = input("Enter your 2FA authenticator secret (or leave blank): ").strip()
        if totp:
            totp = totp.upper().replace(" ", "")
        else:
            totp = None
            
        # 允许选择是否开启浏览器界面
        show_browser = input("Show the browser for debugging? (y/n, default n): ").strip().lower() == 'y'
        if show_browser:
            config.HEADLESS = False
            print("💡 Visible browser mode enabled.")
        else:
            config.HEADLESS = True
            print("💡 Headless browser mode enabled.")
        
    device = create_device_profile()
    
    def progress_callback(msg, screenshot_bytes=None):
        print(f"➜ {msg}")
        if screenshot_bytes:
            try:
                with open("last_step.png", "wb") as f:
                    f.write(screenshot_bytes)
            except Exception:
                pass

    print("\n🚀 Starting automation…")
    try:
        offer_link = check_gemini_offer(
            email=email,
            password=password,
            device=device,
            totp_secret=totp,
            progress_callback=progress_callback,
            manual_login=manual_login
        )
        print("\n==================================================")
        if offer_link:
            print("✅ Google AI Pro Annual checkout link captured. No payment confirmed.")
            print(f"🔗 Link: {offer_link}")
        else:
            print("ℹ️ No standalone checkout link was captured. Check the final screenshot. No payment confirmed.")
    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    main()
