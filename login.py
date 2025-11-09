[Immersive content redacted for brevity.]
    # --- 新增：读取代理 ---
    telegram_proxy = os.environ.get('TELEGRAM_PROXY')

    # --- 如何在代码中指定代理 ---
    # 如果你不想使用 GitHub Secrets，可以在这里取消下面两行的注释
    # 并填入你的代理地址 (例如 "http://127.0.0.1:7890")
    # (但注意：这会把你的代理暴露在代码中，不推荐用于公开项目)
    # if not telegram_proxy:
    #     telegram_proxy = "http://YOUR_PROXY_ADDRESS:PORT" # <--- 在这里填入你的代理
    # --- ---
    
    # --- 新增完毕 ---

    if not all([bot_token, chat_id, site_accounts]):
[Immersive content redacted for brevity.]
