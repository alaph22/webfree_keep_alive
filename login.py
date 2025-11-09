import os
import time
import requests
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

# -------------------------------
log_buffer = []

def log(msg):
    print(msg)
    log_buffer.append(msg)
# -------------------------------

# Telegram 推送函数
def send_tg_log():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("⚠️ Telegram 未配置，跳过推送")
        return

    utc_now = datetime.utcnow()
    beijing_now = utc_now + timedelta(hours=8)
    now_str = beijing_now.strftime("%Y-%m-%d %H:%M:%S") + " UTC+8"

    final_msg = f"📌 webhostmost 保活执行日志\n🕒 {now_str}\n\n" + "\n".join(log_buffer)

    for i in range(0, len(final_msg), 3900):
        chunk = final_msg[i:i+3900]
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{token}/sendMessage",
                params={"chat_id": chat_id, "text": chunk},
                timeout=10
            )
            if resp.status_code == 200:
                print(f"✅ Telegram 推送成功 [{i//3900 + 1}]")
            else:
                print(f"⚠️ Telegram 推送失败 [{i//3900 + 1}]: HTTP {resp.status_code}, 响应: {resp.text}")
        except Exception as e:
            print(f"⚠️ Telegram 推送异常 [{i//3900 + 1}]: {e}")

# 从环境变量解析多个账号
accounts_env = os.environ.get("SITE_ACCOUNTS", "")
accounts = []

for item in accounts_env.split(";"):
    if item.strip():
        try:
            username, password = item.split(",", 1)
            accounts.append({"username": username.strip(), "password": password.strip()})
        except ValueError:
            log(f"⚠️ 忽略格式错误的账号项: {item}")

fail_msgs = [
    "Invalid credentials.",
    "Not connected to server.",
    "Error with the login: login size should be between 2 and 50 (currently: 1)"
]

def login_account(playwright, USER, PWD):
    log(f"🚀 开始登录账号: {USER}")
    try:
        # 启动浏览器
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # 打开登录页面
        page.goto("https://client.webhostmost.com/login", timeout=60000)
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        # 等待邮箱和密码输入框加载
        page.wait_for_selector("#inputEmail", timeout=30000)
        page.wait_for_selector("#inputPassword", timeout=30000)

        # 填入登录凭据
        page.fill("#inputEmail", USER)
        page.fill("#inputPassword", PWD)
        time.sleep(1)

        # 提交登录表单
        # 按钮可能是 "Login"、"Sign in"、"Validate" 等
        try:
            page.get_by_role("button", name="Login").click(timeout=5000)
        except:
            # 兜底：用常见按钮名尝试
            for label in ["Sign in", "Validate", "Submit"]:
                try:
                    page.get_by_role("button", name=label).click(timeout=3000)
                    break
                except:
                    continue
            else:
                log("⚠️ 未找到登录按钮，改用 form 提交")
                page.press("#inputPassword", "Enter")

        # 等待跳转或加载
        page.wait_for_load_state("networkidle")
        time.sleep(5)

        # 登录成功验证（常见几种情况）
        success_signs = [
            "exclusive owner of the following domains",
            "My Services",
            "Client Area",
            "Dashboard"
        ]
        if any(page.query_selector(f"text={sign}") for sign in success_signs):
            log(f"✅ 账号 {USER} 登录成功")
        else:
            # 检测错误信息
            fail_msgs = [
                "Invalid login details",
                "Incorrect username or password",
                "Login failed",
                "Your credentials are incorrect"
            ]
            failed_msg = next(
                (msg for msg in fail_msgs if page.query_selector(f"text={msg}")),
                None
            )
            if failed_msg:
                log(f"❌ 账号 {USER} 登录失败: {failed_msg}")
            else:
                log(f"❌ 账号 {USER} 登录失败: 未检测到成功标识")

        # 清理
        context.close()
        browser.close()

    except Exception as e:
        log(f"❌ 账号 {USER} 登录异常: {e}")


def run():
    with sync_playwright() as playwright:
        for acc in accounts:
            login_account(playwright, acc["username"], acc["password"])
            time.sleep(2)

if __name__ == "__main__":
    run()
    send_tg_log()  # 发送日志
