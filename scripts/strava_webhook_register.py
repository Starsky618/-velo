"""
Sprint 8 Fix 1：Strava push subscription 一次性注册脚本——"把 velo 电话号码写到 Strava 通讯录"。

干啥用：跟 Strava 注册一个"通知地址" / 以后 Tim 上传新活动 Strava 会 POST 到这个地址 →
velo api 容器接到 → enqueue worker_strava → 拉详情 → 完整数据进 DB。

操作注意事项（生产 run 前必读）：
- 这是一次性脚本 / 跑成功后 .env 会写入 STRAVA_WEBHOOK_SUBSCRIPTION_ID
- 跑前必须：.env 已配 STRAVA_CLIENT_ID + STRAVA_CLIENT_SECRET + STRAVA_WEBHOOK_VERIFY_TOKEN
- Strava 端最多只能有 1 个 subscription / 重复 POST 会 400 already exists
- 任何 fail 路径**绝对不写 .env**（防误激活 + 留可追溯日志）

输入：.env 里的 client_id + secret + verify_token + callback_url
输出：成功 → .env 写 STRAVA_WEBHOOK_SUBSCRIPTION_ID=<sub_id> + 退出 0
      失败 → 打印错误 + 退出非 0（不写 .env）

类比：去邮局填表 / 告诉邮局"以后给我家寄信请寄到这个地址" / 填好后邮局给你一个挂号编号（subscription_id）/ 记下来。
"""
import os
import sys
import re
import httpx

# Strava webhook API endpoint
STRAVA_PUSH_SUB_URL = "https://www.strava.com/api/v3/push_subscriptions"

# 生产 callback URL（域名备案前用 IP / 备案后切换 / Tim 5-19 真 POST 测试已验证 Strava 接受）
CALLBACK_URL = os.environ.get(
    "STRAVA_WEBHOOK_CALLBACK_URL",
    "http://114.132.190.245/api/strava/webhook",
)

# .env 文件路径（脚本必须在 velo 根目录跑）
ENV_FILE = ".env"


def fail(msg: str) -> None:
    """打印失败信息 + 退出非 0 / 绝对不写 .env。"""
    print(f"❌ FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def get_env(key: str) -> str:
    """读 env：os.environ 优先（容器场景 docker-compose 注入）/ .env 文件兜底（宿主场景）。"""
    if os.environ.get(key):
        return os.environ[key]
    if not os.path.exists(ENV_FILE):
        return ""
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def write_subscription_id_to_env(sub_id: int) -> None:
    """写 sub_id：.env 存在则写文件 / 不存在（容器场景）则醒目 print 让人工拷回。"""
    if not os.path.exists(ENV_FILE):
        print("=" * 70)
        print(f"✅ Strava webhook subscription 注册成功 / sub_id = {sub_id}")
        print("=" * 70)
        print("⚠️ 当前在容器内运行 / .env 不在容器里。")
        print("请在**宿主机**手动写入 .env：")
        print(f"  sed -i 's|^STRAVA_WEBHOOK_SUBSCRIPTION_ID=.*|STRAVA_WEBHOOK_SUBSCRIPTION_ID={sub_id}|' ~/velo/.env")
        print(f"  # 然后 rebuild api 容器让新 env 生效：")
        print(f"  sudo docker compose -f ~/velo/docker-compose.yml up -d --build api")
        print("=" * 70)
        return

    with open(ENV_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = r"^STRAVA_WEBHOOK_SUBSCRIPTION_ID=.*$"
    replacement = f"STRAVA_WEBHOOK_SUBSCRIPTION_ID={sub_id}"

    if re.search(pattern, content, re.MULTILINE):
        new_content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    else:
        new_content = content.rstrip() + f"\n{replacement}\n"

    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"✅ .env 已写入 STRAVA_WEBHOOK_SUBSCRIPTION_ID={sub_id}")
    print("⚠️ 记得 rebuild api 容器让新 env 生效：sudo docker compose up -d --build api")


def main() -> None:
    # ===== 1. 读 .env 凭证 =====
    client_id = get_env("STRAVA_CLIENT_ID")
    client_secret = get_env("STRAVA_CLIENT_SECRET")
    verify_token = get_env("STRAVA_WEBHOOK_VERIFY_TOKEN")

    if not client_id or not client_secret or not verify_token:
        fail("缺少 STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET / STRAVA_WEBHOOK_VERIFY_TOKEN")

    auth = {"client_id": client_id, "client_secret": client_secret}
    print(f"📡 callback_url = {CALLBACK_URL}")

    # ===== Step 1: GET 现有 subscription =====
    print("📋 Step 1: GET 现有 subscription...")
    try:
        r_get = httpx.get(STRAVA_PUSH_SUB_URL, params=auth, timeout=10)
    except Exception as e:
        fail(f"GET 请求异常 / 网络问题？{e}")

    if r_get.status_code != 200:
        fail(f"GET subscriptions 失败 status={r_get.status_code} body={r_get.text[:200]}")

    existing = r_get.json()
    if existing:
        # 已有 sub / 直接复用
        sub_id = existing[0].get("id")
        existing_url = existing[0].get("callback_url", "")
        if sub_id is None:
            fail(f"GET 返回非空但无 id 字段 / Strava 响应异常 / body={existing}")

        if existing_url != CALLBACK_URL:
            print(
                f"⚠️ 现有 subscription callback_url={existing_url} 与目标 {CALLBACK_URL} 不一致 / "
                f"需先 DELETE 旧 sub（id={sub_id}）再重跑本脚本"
            )
            fail("callback_url 不匹配 / 不写 .env")

        print(f"✅ 已有 subscription id={sub_id} url={existing_url} / 复用")
        write_subscription_id_to_env(sub_id)
        return

    # ===== Step 2: POST 新建 =====
    print("📋 Step 2: 现有空 / POST 新建 subscription...")
    try:
        r_post = httpx.post(
            STRAVA_PUSH_SUB_URL,
            data={
                **auth,
                "callback_url": CALLBACK_URL,
                "verify_token": verify_token,
            },
            timeout=15,
        )
    except Exception as e:
        fail(f"POST 请求异常 {e}")

    if r_post.status_code == 201:
        sub = r_post.json()
        sub_id = sub.get("id")
        if sub_id is None:
            fail(f"POST 201 但响应无 id 字段 / 视为失败不写 .env / body={sub}")
        print(f"✅ 新建 subscription id={sub_id}")
        write_subscription_id_to_env(sub_id)
        return

    # ===== Step 3: POST 失败 fallback =====
    if r_post.status_code == 400 and "already exists" in r_post.text.lower():
        # Strava 服务端有但 GET 拿不到（同步延迟 / 边界 case）→ 再 GET 一次
        print("📋 Step 3: 'already exists' fallback / 重 GET...")
        try:
            r_recheck = httpx.get(STRAVA_PUSH_SUB_URL, params=auth, timeout=10)
        except Exception as e:
            fail(f"重 GET 异常 {e}")

        if r_recheck.status_code == 200 and r_recheck.json():
            sub_id = r_recheck.json()[0].get("id")
            if sub_id is not None:
                print(f"✅ 重 GET 拿到 sub id={sub_id} / 复用")
                write_subscription_id_to_env(sub_id)
                return

        fail(
            "POST already exists 但 GET 仍拿不到 / "
            "需在 https://www.strava.com/settings/api 手动清理 subscription"
        )

    fail(f"POST 失败 status={r_post.status_code} body={r_post.text[:200]}")


if __name__ == "__main__":
    main()
