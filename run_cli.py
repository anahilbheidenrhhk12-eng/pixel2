import sys
import os
import getpass

# 确保导入路径正确
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import config
from device_simulator import create_device_profile
from google_automation import check_gemini_offer

def main():
    print("🤖 Pixel 10 Pro Google One Gemini Offer CLI 🤖")
    print("==================================================")
    
    # 选项：完全手动登录
    manual_login = input("是否选择完全手动登录 (在弹出的浏览器中手动输账号密码) (y/n, 默认 n): ").strip().lower() == 'y'
    
    email = ""
    password = ""
    totp = None
    
    if manual_login:
        config.HEADLESS = False
        print("💡 已启用【手动登录模式】，系统将自动开启浏览器展示界面。")
    else:
        email = input("请输入 Gmail 邮箱: ").strip()
        if not email:
            print("❌ 邮箱不能为空！")
            return
            
        password = getpass.getpass("请输入密码: ").strip()
        if not password:
            print("❌ 密码不能为空！")
            return
            
        totp = input("请输入 2FA 密钥 (若无 2FA 请直接回车): ").strip()
        if totp:
            totp = totp.upper().replace(" ", "")
        else:
            totp = None
            
        # 允许选择是否开启浏览器界面
        show_browser = input("是否显示浏览器界面进行调试 (y/n, 默认 n): ").strip().lower() == 'y'
        if show_browser:
            config.HEADLESS = False
            print("💡 已设置为【有头模式】(您将能看到浏览器自动操作界面，便于观察和手动干预)")
        else:
            config.HEADLESS = True
            print("💡 已设置为【无头模式】(浏览器在后台静默运行)")
        
    device = create_device_profile()
    
    def progress_callback(msg, screenshot_bytes=None):
        print(f"➜ {msg}")
        if screenshot_bytes:
            try:
                with open("last_step.png", "wb") as f:
                    f.write(screenshot_bytes)
            except Exception:
                pass

    print("\n🚀 开始运行自动化流程...")
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
            print("🎉 成功检测到 12 个月 Gemini Pro 优惠链接！")
            print(f"🔗 链接地址: {offer_link}")
        else:
            print("😔 未在当前账号检测到活动中的优惠链接 (可能是已领过或不满足活动条件)")
    except Exception as e:
        print(f"\n❌ 运行异常出错: {e}")

if __name__ == "__main__":
    main()
