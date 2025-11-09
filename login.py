import time
import re
from datetime import datetime
from playwright.sync_api import sync_playwright, Page, Browser, Context

# 你的代码依赖一个 log 函数，这里补充一个简单的实现
def log(message: str):
    """一个简单的日志打印函数"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")

def login_account(playwright, USER, PWD, max_retries: int = 2):
    """
    针对 web.freecloud.ltd 的稳健登录 / 保活函数：
    - (已修改) 强制使用直连网络，绕过 v2rayN 等系统代理
    - 处理 Cloudflare 验证（检测到 CF challenge 时等待其通过）
    - 页面加载很慢时做长时间轮询（最多等待约 120s）以判断是否到达登录页
    - 到达登录页（能找到邮箱/密码输入框或登录按钮）则判定为成功（保活达成）
    - 若确实是登录操作（你同时传了账号密码），则会在登录页尝试登录并获取后续倒计时（如有）
    """
    attempt = 0
    while attempt <= max_retries:
        attempt += 1
        log(f"🚀 开始登录账号: {USER} (尝试 {attempt}/{max_retries + 1})")
        browser: Browser | None = None
        context: Context | None = None
        page: Page | None = None
        try:
            # === 关键修改点 ===
            # 当 v2rayN 等软件开启时，会设置系统代理。
            # Playwright 默认会使用系统代理，这可能是导致连接失败的原因。
            # 我们在这里通过 'proxy={"server": "direct://"}' 强制指定 Playwright
            # 绕过所有系统代理，使用直接连接（直连网络）。
            proxy_settings = {"server": "direct://"}
            
            browser = playwright.chromium.launch(
                headless=True, 
                proxy=proxy_settings  # <--- 应用直连设置
            )
            # === 修改完毕 ===
            
            context = browser.new_context()
            page = context.new_page()

            target_login_url = "https://web.freecloud.ltd/index.php?rp=/login"
            page.goto(target_login_url, timeout=90000)  # 页面可能慢，延长超时
            # 立即给一次 networkidle 的等待（也许 CF 会自动跳转）
            try:
                page.wait_for_load_state("networkidle", timeout=45000)
            except:
                log("⚠️ 首次 networkidle 超时（页面可能仍在验证或加载），进入轮询检测")

            # ==== 特殊逻辑：检测 Cloudflare 验证并等待通过 ====
            # ... (后续逻辑保持不变)
            start = time.time()
            max_wait = 120  # 最多等待 120s
            saw_cf = False
            login_page_reached = False

            # 预定义一些能识别“已到登录页”的标志（中文/英文都考虑）
            login_indicators = [
                "输入邮箱", "邮箱地址", "Email", "邮箱",    # 输入提示
                "登录用户中心", "登录", "登录到您的账户",      # 页面标题/按钮
                "placeholder=\"输入邮箱\"", "input[type=\"email\"]" # html 片段
            ]

            while time.time() - start < max_wait:
                html_lower = ""
                try:
                    html_lower = page.content().lower()
                except Exception:
                    html_lower = ""

                # 若 html 中命中任意登录页标识 -> 认为 CF 已放行并到达登录页
                if any(ind.lower() in html_lower for ind in login_indicators):
                    login_page_reached = True
                    break

                # 检测 CF 验证挑战的迹象
                cf_flag = False
                try:
                    if "cloudflare" in html_lower or "正在验证" in html_lower or "checking your browser" in html_lower:
                        cf_flag = True
                    if page.query_selector("iframe[src*='turnstile']") or page.query_selector("iframe[src*='cloudflare']"):
                        cf_flag = True
                except Exception:
                    pass

                if cf_flag and not saw_cf: # 只在第一次检测到时打印
                    saw_cf = True
                    log(f"⚠️ 检测到 Cloudflare 验证页面，等待其自动通过（最多等待 {max_wait}s）...")
                
                time.sleep(3) # 轮询间隔

            if saw_cf and login_page_reached:
                log("✅ Cloudflare 验证已通过，页面已到达登录页")
            elif saw_cf and not login_page_reached:
                log("❌ 等待 Cloudflare 验证超时，未到达登录页")
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
                    page.wait_for_selector(selector, timeout=3000)
                    page.fill(selector, USER)
                    log(f"📝 使用字段 {selector} 填入用户名/邮箱")
                    filled_user = True
                    break
                except Exception:
                    continue

            # === Step 2: 填写密码 ===
            password_selectors = ["input[placeholder*='密码']", "#inputPassword", "input[name='password']", "input[type='password']", "#password"]
            filled_pw = False
            for selector in password_selectors:
                try:
                    page.wait_for_selector(selector, timeout=3000)
                    page.fill(selector, PWD)
                    log(f"🔒 使用字段 {selector} 填入密码")
                    filled_pw = True
                    break
                except Exception:
                    continue

            # 如果都没找到表单控件（例如，如果USER或PWD为空，我们只做保活检查）
            # 或者如果只传了USER/PWD中的一个，我们也不应该尝试登录
            if not (filled_user and filled_pw and USER and PWD):
                log(f"✅ 保活目标达成：到达登录页面。账号 {USER} 视为保活成功")
                if context: context.close()
                if browser: browser.close()
                return

            time.sleep(0.8)

            # === Step 3: 提交登录表单（支持中文'登录'按钮） ===
            submitted = False
            button_labels = ["登录", "Login", "Sign in", "Sign In", "Submit", "登录按钮"]
            for label in button_labels:
                try:
                    page.get_by_role("button", name=re.compile(label, re.IGNORECASE)).click(timeout=3000)
                    log(f"🔘 点击按钮 '{label}' 尝试登录")
                    submitted = True
                    break
                except Exception:
                    continue

            if not submitted:
                # 兜底：尝试常见 css submit
                try:
                    css_candidates = ["button[type='submit']", "input[type='submit']", "button.btn", ".btn-primary", ".login-btn", "form button"]
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
                try:
                    # 兜底：回车键
                    page.press("input[type='password']", "Enter")
                    log("🔘 使用回车键提交")
                    submitted = True
                except:
                    log("⚠️ 未能找到任何提交方式，登录可能未触发")

            # === Step 4: 等待登录后页面或确认（延长等待） ===
            try:
                page.wait_for_load_state("networkidle", timeout=45000)
            except:
                log("⚠️ 登录提交后 networkidle 超时，继续轮询检测页面内容")

            time.sleep(2)

            # === Step 5: 成功判定 ===
            html = ""
            try:
                html = page.content().lower()
            except:
                html = ""

            success_signs = ["dashboard", "client area", "my services", "time until suspension", "security settings", "用户中心", "控制台"]
            current_url = page.url or ""
            
            # 检查登录后的关键字或URL变化
            if any(s in html for s in success_signs) or any(x in current_url for x in ["/dashboard", "/clientarea", "/user", "/account", "/home"]):
                log(f"✅ 账号 {USER} 登录或保活成功（检测到成功标识或 URL 跳转）")
                # 尝试提取倒计时
                try:
                    page.wait_for_selector("text=Time until suspension", timeout=10000)
                    countdown_elem = page.query_selector("text=Time until suspension")
                    if countdown_elem:
                        # 尝试找到兄弟元素或父元素中的倒计时
                        parent = countdown_elem.evaluate_handle("element => element.parentElement")
                        countdown_text = parent.text_content().strip()
                        m = re.search(r"(\d+d\s+\d+h\s+\d+m\s+\d+s)", countdown_text)
                        if m:
                            log(f"⏱️ 登录后检测到倒计时: {m.group(1)}")
                        else:
                            log(f"ℹ️ 找到 'Time until suspension' 但未提取到具体时间: {countdown_text[:100]}")
                except Exception:
                    pass # 没有倒计时也正常

                if context: context.close()
                if browser: browser.close()
                return # 成功返回

            # === Step 6: 失败判定（例如 密码错误） ===
            failure_signs = ["wrong password", "密码错误", "invalid login", "登录失败", "邮箱或密码不正确"]
            if any(s in html for s in failure_signs):
                log(f"❌ 登录失败：检测到错误提示（可能是密码错误或账号问题）。")
                # 账号密码错误是确定性失败，不应该重试
                if context: context.close()
                if browser: browser.close()
                return # 确定性失败，直接返回，不再重试

            log("⚠️ 未能确认登录后状态（既没有成功标志也没有失败提示），将进入重试/诊断")
            raise RuntimeError("login-unknown-state")

        except Exception as e:
            log(f"❌ 账号 {USER} 尝试 ({attempt}) 异常: {e}")
            # 失败时保存截图和 HTML 摘要
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
                        # 限制摘要长度，避免写入过大文件
                        with open(html_path, "w", encoding="utf-8") as f:
                            f.write(content)
                        log(f"📝 已保存页面 HTML: {html_path}")
                    except Exception as ex_h:
                        log(f"⚠️ 保存 HTML 失败: {ex_h}")
            except Exception as ex_debug:
                log(f"⚠️ 写入调试文件时发生异常: {ex_debug}")

            # 重试逻辑
            if attempt <= max_retries:
                wait_sec = 5 + attempt * 5
                log(f"⏳ 等待 {wait_sec}s 后重试...")
                time.sleep(wait_sec)
                # continue (循环会自动继续)
            else:
                log(f"❌ 账号 {USER} 登录最终失败（{max_retries + 1} 次尝试均未成功）")
                # return (循环会自然结束)

        finally:
            # 确保每次尝试后都关闭浏览器
            try:
                if context: context.close()
                if browser: browser.close()
            except Exception as e:
                log(f"⚠️ 关闭浏览器实例时出错: {e}")

    # 如果循环结束仍未成功（即所有重试都失败了）
    log(f"❌ 账号 {USER} 所有 {max_retries + 1} 次尝试均已失败。")
    return # 显式返回

# --- 如何使用 (示例) ---
# if __name__ == "__main__":
#     USER_EMAIL = "your_email@example.com"
#     USER_PASSWORD = "your_password"
    
#     with sync_playwright() as p:
#         # 注意：现在 login_account 接受 playwright 实例作为第一个参数
#         login_account(p, USER_EMAIL, USER_PASSWORD, max_retries=1)
