# pixel-gemini

**Pixel 10 Pro Google One Gemini 优惠领取助手（支持 Telegram 机器人 & 本地命令行 CLI）**

本项目是一个基于 Python 的自动化脚本与 Telegram 机器人，用于**模拟 Google Pixel 10 Pro (Android 16) 设备**登录用户的 Gmail 账号，并自动从 Google One 中检测并提取 **12 个月免费 Gemini Advanced (Gemini Pro) 试用** 的激活链接。

---

## 项目结构

```
pixel-gemini/
├── main.py               # Telegram 机器人启动入口
├── run_cli.py            # 本地命令行 (CLI) 运行入口（无需配置 Bot Token）
├── device_simulator.py   # Android Pixel 10 Pro 设备模拟逻辑
├── google_automation.py  # 谷歌登录与 Google One 优惠探测核心逻辑
├── config.py             # 全局配置及常量
├── requirements.txt      # Python 依赖包列表
└── README.md             # 说明文档（本文件）
```

---

## 核心功能

| 功能 | 详情介绍 |
|---|---|
| 📱 **设备模拟** | 每次会话模拟真实的 Pixel 10 Pro (Android 16) 设备，拥有独立的 IMEI、Android ID，并注入对应硬件参数与 navigator 信息。 |
| 💻 **本地 CLI 模式** | 直接通过终端运行（`run_cli.py`），**无需搭建 Telegram 机器人或配置 Bot Token**，简单易用。 |
| 🔐 **手动/自动登录** | 支持在弹出的浏览器中**手动登录**（完全避开谷歌风控防爬虫机制，最推荐）或在命令行**自动登录**。 |
| 🤖 **Telegram 机器人** | 支持 `/start`, `/login`, `/check_offer`, `/get_link`, `/status` 等指令，便于远程操作。 |
| 🌐 **自动 ChromeDriver** | 自动识别本地 Chrome 浏览器版本并下载对应驱动，同时修复了 Windows 平台下 webdriver-manager 的解析 Bug。 |
| 🛡️ **防闪退保护** | 有头模式下流程执行完毕后，窗口会保留并提示“按回车关闭”，避免提取出链接后浏览器瞬间关闭的问题。 |

---

## 本地命令行 (CLI) 运行指南（推荐）

对于个人使用或测试，使用本地 CLI 模式最方便且成功率最高。

### 1. 准备工作
* 电脑中需安装 **Python 3.10+**（已完美兼容 Python 3.13）。
* 确保安装了 **Google Chrome** 浏览器。

### 2. 搭建虚拟环境与安装依赖
在项目根目录 `E:\app\pixel_gemini` 打开 PowerShell 或 CMD，执行以下命令：
```bash
# 创建虚拟环境
python -m venv venv

# 安装项目依赖
.\venv\Scripts\pip.exe install -r requirements.txt
```

### 3. 启动 CLI 脚本
```bash
.\venv\Scripts\python.exe run_cli.py
```

### 4. 选择登录模式
启动后，会提示您进行以下选择：
1. **完全手动登录 [强烈推荐]**：
   * 输入 **`y`** 并回车。
   * 系统会自动弹出 Chrome 浏览器窗口。请在网页中手动输入您的 Gmail 邮箱、密码并完成 2FA 验证。
   * 登录成功并看到您的 Google 账户首页后，回到命令行终端**按下【回车键】**。脚本将自动接管，进入 Google One 并提取 Gemini 优惠链接。
   * *优势：100% 绕过谷歌的自动化程序检测，安全稳定。*
2. **全自动登录**：
   * 直接按回车（默认 **`n`**）。
   * 按照终端提示依次输入您的 Gmail 邮箱、密码和 2FA 密钥，脚本将尝试为您进行全自动登录。

---

## Telegram 机器人配置指南（服务器/Replit）

### 1. 创建 Telegram 机器人
1. 打开 Telegram，搜索并关注官方机器人 **@BotFather**。
2. 发送 `/newbot`，按提示起名并创建。
3. 保存 BotFather 发给您的 **HTTP API Token**（形如 `123456:ABC-DEF…`）。

### 2. 配置 Token
您可以将 Token 设置为环境变量 `TELEGRAM_BOT_TOKEN`，或者直接修改项目中的 `config.py` 文件第 8 行：
```python
TELEGRAM_BOT_TOKEN = "您的_TELEGRAM_BOT_TOKEN"
```

### 3. 运行机器人
```bash
.\venv\Scripts\python.exe main.py
```
终端输出 `Bot is running. Press Ctrl-C to stop.` 后，机器人开始工作。

### 机器人常用指令
| 命令 | 描述 |
|---|---|
| `/start` | 欢迎语及指令介绍 |
| `/login` | 输入 Gmail 邮箱、密码与 2FA（信息仅保存在运行内存中，用完即毁） |
| `/check_offer` | 启动 Pixel 10 Pro 模拟并进入 Google One 探测优惠链接 |
| `/get_link` | 再次获取当前会话最后一次提取成功的 Gemini 优惠链接 |
| `/status` | 查看当前会话状态及模拟的 Pixel 设备指纹参数 |

---

## 技术细节

* **有头与无头模式自动兼容**：为了在 Telegram 机器人（服务器环境）上正常运行，Bot 默认以无头模式运行。CLI 模式下支持开启有头模式以方便手动验证与阻断闪退。
* **反指纹检测（指纹伪装）**：通过注入 CDP 指令与重写 JS 的 navigator 属性（WebGL、电池、多点触控、屏幕尺寸、Sec-CH-UA-Model 客户端提示），完美伪装 Pixel 10 Pro 硬件参数。
* **隐私安全**：输入的所有密码和 2FA 密钥仅存在于瞬时内存中，绝不保存到本地文件或硬盘。在 Telegram 对话中输入的密码会在读取后自动删除对应的气泡消息。

---

## 免责声明

本项目仅供学习交流及个人研究使用。利用自动化脚本访问谷歌账户可能违反《Google 服务条款》，请在遵守当地法律法规的前提下使用，并仅对您个人拥有的账户进行操作。
