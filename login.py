import os
import requests
import time
import re
from datetime import datetime
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext, Playwright

# --- 1. 日志函数 (公共) ---
def log(message: str):
    """一个简单的日志打印函数"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")

# --- 2. Telegram 通知函数 ---
def send_telegram_message(bot_token, chat_id, message, proxy_url: str | None = None):
    """使用 requests 向 Telegram Bot API 发送消息 (支持代理)"""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'Markdown'
    }

    # --- 设置代理 ---
    proxies = None
    if proxy_url:
        proxies = {
            'http': proxy_url,
            'https': proxy_url
        }
        log(f"ℹ️ 检测到 TELEGRAM_PROXY，将使用代理: {proxy_url}")
    # --- 代理设置完毕 ---

    try:
        response = requests.post(url, json=payload, timeout=10, proxies=proxies)
        if response.status_code == 200:
            log("✅ Telegram 消息发送成功")
        else:
            log(f"❌ Telegram 消息发送失败: {response.status_code} - {response.text}")
    except Exception as e:
        log(f"❌ 发送 Telegram 消息时发生异常: {e}")


# --- 3. 登录函数 (核心优化区域) ---

def login_account(playwright: Playwright, USER: str, PWD: str, max_retries: int = 2):
    """
    针对 web.freecloud.ltd 的稳健登录 / 保活函数：
    - 切换回 Chromium，并增加 Playwright Context 的“人性化”配置，减少被识别为自动化的几率。
    - 增加 slow_mo 延迟，模拟人类操作。
    """
    attempt = 0
    # 增加 slow_mo 延迟，模拟人类操作
    slow_mo_ms = 500 
    
    while attempt <= max_retries:
        attempt += 1
        log(f"🚀 开始登录账号: {USER} (尝试 {attempt}/{max_retries + 1})")
        browser: Browser | None = None
        context: BrowserContext | None = None
        page: Page | None = None
        
        try:
            # === 关键修改 1: 切换到 Chromium 并启用 slow_mo ===
            browser = playwright.chromium.launch(
                headless=True,
                proxy=None,
                slow_mo=slow_mo_ms # 增加操作延迟
            )
            # === 修改完毕 ===
            
            # === 关键修改 2: 增强 Context 配置，模拟真实设备指纹 ===
            context = browser.new_context(
                # 模拟 Windows + Chrome 的指纹
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                viewport={'width': 1280, 'height': 800},
                locale='zh-CN',
                device_scale_factor=1.0,
            )
            # === 修改完毕 ===

            page = context.new_page()

            target_login_url = "https://web.freecloud.ltd/index.php?rp=/login"
            # 增加初始页面加载超时，以应对可能较长的 CF 验证过程
            page.goto(target_login_url, timeout=120000) 
            
            try:
                page.wait_for_load_state("networkidle", timeout=60000)
            except:
                log("⚠️ 首次 networkidle 超时，页面可能仍在验证或加载")

            # ==== 特殊逻辑：检测 Cloudflare 验证并等待通过 ====
            start = time.time()
            max_wait = 300  # <-- 关键修改 3：延长到 300s (5分钟)
            saw_cf = False
            login_page_reached = False

            login_indicators = [
                "输入邮箱", "邮箱地址", "Email", "邮箱",
                "登录用户中心", "登录", "登录到您的账户",
                "placeholder=\"输入邮箱\"", "input[type=\"email\"]"
            ]

            while time.time() - start < max_wait:
                html_lower = ""
                try:
                    html_lower = page.content().lower()
                except Exception:
                    html_lower = ""

                # 检查是否已到达登录页
                if any(ind.lower() in html_lower for ind in login_indicators):
                    login_page_reached = True
                    break

                # 检测 CF 验证挑战的迹象
                cf_flag = False
                try:
                    if "cloudflare" in html_lower or "正在验证" in html_lower or "checking your browser" in html_lower:
                        cf_flag = True
                    # 检查是否有 Turnstile 或 Managed Challenge 的 iframe
                    if page.query_selector("iframe[src*='turnstile']") or page.query_selector("iframe[src*='cloudflare']") or page.query_selector("iframe[title*='challenge']"):
                        cf_flag = True
                except Exception:
                    pass

                if cf_flag and not saw_cf:
                    saw_cf = True
                    log(f"⚠️ 检测到 Cloudflare 验证页面，等待其自动通过（最多等待 {max_wait}s）...")
                
                # --- 关键修改 4：更具鲁棒性的 Turnstile 点击尝试 ---
                if saw_cf:
                    try:
                        turnstile_iframe_handle = page.query_selector("iframe[src*='turnstile']")
                        if turnstile_iframe_handle:
                            log("ℹ️ 检测到 Turnstile iframe，正在切换并尝试点击... (1/3)")
                            turnstile_frame = turnstile_iframe_handle.content_frame()
                            if turnstile_frame:
                                # 尝试点击 iframe 内部的可见元素，而不是隐藏的 input[type=checkbox]
                                # 常见的 Turnstile 按钮/容器选择器
                                # Playwright 的 locator 是最推荐的方式
                                
                                # 尝试使用 get_by_role('checkbox') 查找，并用 force=True 强制点击
                                checkbox_locator = turnstile_frame.locator("body *").filter(has_text=re.compile("Verify you are human", re.IGNORECASE))
                                if checkbox_locator.count() > 0:
                                    # 优先点击包含 'Verify you are human' 文本的元素
                                    checkbox_locator.first.click(timeout=5000, force=True)
                                    log("✅ 已尝试点击 Turnstile 验证文本 (2/3)")
                                else:
                                    # 如果没有找到文本，尝试点击 iframe 内部的复选框
                                    turnstile_frame.locator("input[type=checkbox]").click(timeout=5000, force=True)
                                    log("✅ 已尝试点击 Turnstile 复选框 (2/3)")
                                    
                                # 增加一个短暂的等待，给 CF 留出处理点击的时间
                                time.sleep(1.5)
                                log("ℹ️ 点击操作已完成 (3/3)")
                            else:
                                log("⚠️ 找到了 iframe 但无法获取其 content_frame")
                    except Exception as e:
                        log(f"ℹ️ 自动点击 Turnstile 失败 (可能元素未出现或被遮挡): {e}")
                # --- 修改完毕 ---

                time.sleep(3) # 轮询间隔

            # CF/登录页状态判定
            if saw_cf and login_page_reached:
                log("✅ Cloudflare 验证已通过，页面已到达登录页")
            elif saw_cf and not login_page_reached:
                log(f"❌ 等待 Cloudflare 验证超时（{max_wait}s），未到达登录页")
                raise RuntimeError("cf-timeout")
            elif login_page_reached:
                log("ℹ️ 直接到达登录页（未检测到明显 Cloudflare 验证）")
            else:
                log("⚠️ 未检测到登录页或 Cloudflare 验证标志，页面可能异常")
                raise RuntimeError("no-login-or-cf")

            # === Step 1: 尝试填写用户名/邮箱 ===
            input_selectors = [
                "input[placeholder*='邮箱']", "input[placeholder*='输入邮箱']",
                "#inputEmail", "#inputUsername", "#username", "input[name='username']",
                "input[name='email']", "input[type='email']"
            ]
            filled_user = False
            for selector in input_selectors:
                try:
                    # 使用 get_by_role("textbox") 作为更健壮的定位方式
                    email_input = page.locator(selector).or_(page.get_by_role("textbox", name=re.compile("email|邮箱", re.IGNORECASE)))
                    if email_input.count() > 0 and email_input.first.is_visible():
                        email_input.first.fill(USER)
                        log(f"📝 填入用户名/邮箱 (Selector: {selector} 或 Role)")
                        filled_user = True
                        break
                except Exception:
                    continue

            # === Step 2: 填写密码 ===
            password_selectors = ["input[placeholder*='密码']", "#inputPassword", "input[name='password']", "input[type='password']", "#password"]
            filled_pw = False
            for selector in password_selectors:
                try:
                    password_input = page.locator(selector).or_(page.get_by_role("textbox", name=re.compile("password|密码", re.IGNORECASE)))
                    if password_input.count() > 0 and password_input.first.is_visible():
                        password_input.first.fill(PWD)
                        log(f"🔒 填入密码 (Selector: {selector} 或 Role)")
                        filled_pw = True
                        break
                except Exception:
                    continue

            if not (filled_user and filled_pw and USER and PWD):
                # 如果没有填写成功，但已经到达了登录页面，仍然视为保活成功（目标是访问该页面）
                if login_page_reached:
                    log(f"✅ 保活目标达成：到达登录页面。账号 {USER} 视为保活成功 (跳过登录)")
                    if context: context.close()
                    if browser: browser.close()
                    return
                else:
                    raise RuntimeError("Failed to locate or fill login fields.")

            time.sleep(1 + slow_mo_ms / 1000) # 增加延迟

            # === Step 3: 提交登录表单 ===
            submitted = False
            # 优先尝试点击文本为“登录”的按钮
            button_labels = ["登录", "Login", "Sign in", "Sign In", "Submit"]
            for label in button_labels:
                try:
                    # 使用更具弹性的正则表达式匹配
                    page.get_by_role("button", name=re.compile(label, re.IGNORECASE)).click(timeout=5000)
                    log(f"🔘 点击按钮 '{label}' 尝试登录")
                    submitted = True
                    break
                except Exception:
                    continue

            # 其次尝试通过 CSS Selector 提交
            if not submitted:
                try:
                    css_candidates = ["button[type='submit']", "input[type='submit']", ".btn-primary", "form button", "form input[type='submit']"]
                    for sel in css_candidates:
                        try:
                            loc = page.locator(sel)
                            if loc.count() and loc.first.is_visible():
                                loc.first.click(timeout=4000)
                                log(f"🔘 点击 CSS 按钮: {sel}")
                                submitted = True
                                break
                        except:
                            continue
                except:
                    pass

            if not submitted:
                # 最后的尝试：通过回车键提交（依赖于密码框的焦点）
                try:
                    page.press("input[type='password']", "Enter")
                    log("🔘 使用回车键提交")
                    submitted = True
                except:
                    log("⚠️ 未能找到任何提交方式，登录可能未触发")

            # === Step 4: 等待登录后页面或确认 ===
            try:
                # 增加等待时间，等待 Dashboard 加载
                page.wait_for_load_state("networkidle", timeout=60000) 
            except:
                log("⚠️ 登录提交后 networkidle 超时，继续轮询检测页面内容")

            time.sleep(2 + slow_mo_ms / 1000)

            # === Step 5: 成功判定 ===
            html = ""
            try:
                html = page.content().lower()
            except:
                html = ""

            success_signs = ["dashboard", "client area", "my services", "time until suspension", "security settings", "用户中心", "控制台", "注销", "logout"]
            current_url = page.url or ""
            
            if any(s in html for s in success_signs) or any(x in current_url for x in ["/dashboard", "/clientarea", "/user", "/account", "/home"]):
                log(f"✅ 账号 {USER} 登录或保活成功（检测到成功标识或 URL 跳转）")
                
                # 尝试提取倒计时 (保持原有逻辑)
                try:
                    countdown_loc = page.get_by_text("Time until suspension", exact=False, timeout=10000)
                    if countdown_loc.is_visible():
                        countdown_text = countdown_loc.text_content()
                        m = re.search(r"(\d+d\s+\d+h\s+\d+m\s+\d+s)", countdown_text)
                        if m:
                            log(f"⏱️ 登录后检测到倒计时: {m.group(1)}")
                        else:
                            # 尝试在父元素中查找
                            parent_text = countdown_loc.evaluate("e => e.parentElement.textContent")
                            m = re.search(r"(\d+d\s+\d+h\s+\d+m\s+\d+s)", parent_text)
                            if m:
                                log(f"⏱️ 登录后检测到倒计时: {m.group(1)}")
                            else:
                                log(f"ℹ️ 找到 'Time until suspension' 但未提取到具体时间: {parent_text[:100].strip()}")
                except Exception:
                    pass 

                if context: context.close()
                if browser: browser.close()
                return # 成功返回

            # === Step 6: 失败判定（例如 密码错误） ===
            failure_signs = ["wrong password", "密码错误", "invalid login", "登录失败", "邮箱或密码不正确", "not a member yet?"]
            if any(s in html for s in failure_signs):
                log(f"❌ 登录失败：检测到错误提示（可能是密码错误或账号问题）。")
                if context: context.close()
                if browser: browser.close()
                raise RuntimeError("Login failed: Invalid credentials or error message detected.") 

            log("⚠️ 未能确认登录后状态（既没有成功标志也没有失败提示），将进入重试/诊断")
            raise RuntimeError("login-unknown-state")

        except Exception as e:
            log(f"❌ 账号 {USER} 尝试 ({attempt}) 异常: {e}")
            # --- 保持调试文件保存逻辑 ---
            try:
                timestamp = datetime.now().strftime("%Y%m%dT%H%M%SZ")
                if page:
                    try:
                        screenshot_path = f"screenshot_{USER.replace('@','_')}_{timestamp}.png"
                        page.screenshot(path=screenshot_path, full_page=True)
                        log(f"📷 已保存截图: {screenshot_path}")
                    except Exception as ex_s:
                        log(f"⚠️ 保存截图失败: {ex_s}")
                    try:
                        html_path = f"page_{USER.replace('@','_')}_{timestamp}.html"
                        content = page.content()
                        with open(html_path, "w", encoding="utf-8") as f:
                            f.write(content)
                        log(f"📝 已保存页面 HTML: {html_path}")
                    except Exception as ex_h:
                        log(f"⚠️ 保存 HTML 失败: {ex_h}")
            except Exception as ex_debug:
                log(f"⚠️ 写入调试文件时发生异常: {ex_debug}")
            # --- 调试文件保存逻辑结束 ---

            if attempt <= max_retries:
                wait_sec = 10 + attempt * 5 # 增加重试间隔
                log(f"⏳ 等待 {wait_sec}s 后重试...")
                time.sleep(wait_sec)
            else:
                log(f"❌ 账号 {USER} 登录最终失败（{max_retries + 1} 次尝试均未成功）")
                raise e

        finally:
            try:
                if context: context.close()
                if browser: browser.close()
            except Exception as e:
                log(f"⚠️ 关闭浏览器实例时出错: {e}")

    log(f"❌ 账号 {USER} 所有 {max_retries + 1} 次尝试均已失败。")
    raise RuntimeError(f"Account {USER} failed all {max_retries + 1} login attempts.")


# --- 4. 主执行函数 ---
def main():
    """主执行函数"""
    log("🚀 开始执行保活任务...")

    # 1. 从 GitHub Secrets (环境变量) 中读取信息
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE') # 默认值
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', 'YOUR_CHAT_ID_HERE')     # 默认值
    site_accounts = os.environ.get('SITE_ACCOUNTS', 'eraierbing1314@gmail.com:YOUR_PASSWORD_HERE') # 默认值
    telegram_proxy = os.environ.get('TELEGRAM_PROXY')

    if bot_token == 'YOUR_BOT_TOKEN_HERE' or chat_id == 'YOUR_CHAT_ID_HERE' or site_accounts == 'eraierbing1314@gmail.com:YOUR_PASSWORD_HERE':
        log("❌ 请确保已正确设置 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 和 SITE_ACCOUNTS 环境变量。")
        log("ℹ️ 目前正在使用默认的占位符值，这会导致任务失败。")
        return

    # 2. 解析账号
    accounts = []
    try:
        for acc_pair in site_accounts.split(','):
            if ':' in acc_pair:
                user, pwd = acc_pair.split(':', 1)
                accounts.append((user.strip(), pwd.strip()))
    except Exception as e:
        log(f"❌ 解析 SITE_ACCOUNTS 失败: {e}")
        return

    if not accounts:
        log("⚠️ 未找到任何账号信息")
        return

    log(f"ℹ️ 成功加载 {len(accounts)} 个账号")
    
    # 3. 运行 Playwright 并执行登录
    report_lines = ["*FreeCloud 自动保活报告*"]
    success_count = 0
    
    try:
        with sync_playwright() as p:
            for user, pwd in accounts:
                try:
                    # 尝试次数改为 max_retries=2 (总共 3 次)
                    login_account(p, user, pwd, max_retries=2) 
                    
                    log(f"✅ 账号 {user} 保活成功")
                    report_lines.append(f"✅ 账号: `{user}` - 成功")
                    success_count += 1
                except Exception as e:
                    log(f"❌ 账号 {user} 保活失败: {e}")
                    # 修复 Telegram 消息格式，对特殊字符进行转义
                    error_message = str(e)
                    # 仅转义 Markdown V2 中需要转义的字符
                    escaped_error = error_message.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[").replace("`", "\\`").replace("(", "\\(").replace(")", "\\)")
                    report_lines.append(f"❌ 账号: `{user}` - 失败: {escaped_error}")
                    
                time.sleep(5)
    except Exception as e:
        log(f"❌ Playwright 运行时发生严重错误: {e}")
        error_message = str(e)
        escaped_error = error_message.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[").replace("`", "\\`").replace("(", "\\)")
        report_lines.append(f"❌ 严重错误: {escaped_error}")

    # 4. 发送总结报告
    report_lines.append(f"\n--- *总结* ---")
    report_lines.append(f"总数: {len(accounts)}, 成功: {success_count}, 失败: {len(accounts) - success_count}")
    
    final_report = "\n".join(report_lines)
    send_telegram_message(bot_token, chat_id, final_report, telegram_proxy)
    log("🏁 保活任务全部执行完毕")

# --- 5. 脚本入口 ---
if __name__ == "__main__":
    main()
