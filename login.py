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

        # === Step 1: 寻找用户名/邮箱输入框 ===
        input_filled = False
        for selector in ["#inputEmail", "#inputUsername", "input[name='username']", "input[name='email']"]:
            try:
                page.wait_for_selector(selector, timeout=5000)
                page.fill(selector, USER)
                log(f"📝 使用字段 {selector} 填入用户名/邮箱")
                input_filled = True
                break
            except:
                continue

        if not input_filled:
            log("❌ 未找到可用的用户名/邮箱输入框，终止登录")
            context.close()
            browser.close()
            return

        # === Step 2: 填写密码 ===
        try:
            page.wait_for_selector("#inputPassword", timeout=10000)
            page.fill("#inputPassword", PWD)
        except:
            log("❌ 未找到密码输入框，终止登录")
            context.close()
            browser.close()
            return

        time.sleep(1)

        # === Step 3: 提交表单 ===
        # 按钮名兼容多种英文写法
        button_labels = ["Login", "Sign in", "Validate", "Submit", "Email"]
        clicked = False
        for label in button_labels:
            try:
                page.get_by_role("button", name=label).click(timeout=3000)
                log(f"🔘 点击按钮 '{label}' 尝试登录")
                clicked = True
                break
            except:
                continue

        if not clicked:
            # 没有找到按钮则尝试直接提交表单或用 Enter 触发
            log("⚠️ 未找到登录按钮，改用 form 提交或回车键提交")
            try:
                page.evaluate("document.querySelector('form').submit()")
            except:
                try:
                    page.press("#inputPassword", "Enter")
                except:
                    log("⚠️ 回车提交失败，可能页面结构特殊")

        # === Step 4: 等待页面加载与判断结果 ===
        page.wait_for_load_state("networkidle")
        time.sleep(5)

        # 登录成功标识
        success_signs = [
            "exclusive owner of the following domains",
            "My Services",
            "Client Area",
            "Dashboard"
        ]
        if any(page.query_selector(f"text={sign}") for sign in success_signs):
            log(f"✅ 账号 {USER} 登录成功")
        else:
            # 登录失败标识
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

        # === Step 5: 清理资源 ===
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
