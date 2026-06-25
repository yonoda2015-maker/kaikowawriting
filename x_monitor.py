"""
X投稿監視ボット

対象アカウントの新着投稿を1〜2時間ごとにチェックし、
新しい投稿があったらリプライ文を生成してDiscordに即通知する。

使い方:
  python3 x_monitor.py          # 1回だけ実行
  python3 x_monitor.py --loop   # ループ実行（90分ごと）
"""

import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

DISCORD_WEBHOOK = os.getenv(
    "DISCORD_WEBHOOK_KAIKOWA",
    "https://discord.com/api/webhooks/1519773618823889049/YD0gqeetS6pk32Jv6TxqizYVkoyBFQgxieQ2u5JYu3A4GEerIveICxB3kfMmC4nH8OTb"
)

DB_PATH = Path(__file__).parent / "kowamoshiro.db"

# 監視対象アカウント（親和性の高い怪談・ホラー系）
WATCH_ACCOUNTS = [
    "@zanpnaentou",
    "@obake_Suu",
    "@Lil_Mina_vtuber",
    "@kasumi_mitama",
    "@touro_botan",
    "@KubrickBlogjp",
    "@ishikororin",
    "@harudaily0412",
    "@NihonHorror",
    "@kiwakowa",
]

AUTH_PATH = Path.home() / ".grok" / "auth.json"


def _get_grok_token():
    with open(AUTH_PATH) as f:
        d = json.load(f)
    return list(d.values())[0]["key"]


def _init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS x_monitor_seen (
            post_id TEXT PRIMARY KEY,
            account TEXT,
            seen_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def _is_seen(post_id: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT 1 FROM x_monitor_seen WHERE post_id=?", (post_id,)).fetchone()
    conn.close()
    return row is not None


def _mark_seen(post_id: str, account: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR IGNORE INTO x_monitor_seen (post_id, account, seen_at) VALUES (?,?,?)",
        (post_id, account, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def fetch_new_posts() -> list[dict]:
    """Grok X Searchで対象アカウントの新着投稿を取得"""
    from xai_sdk import Client
    from xai_sdk.chat import user as xai_user
    from xai_sdk.tools import x_search

    client = Client(api_key=_get_grok_token())
    accounts_str = " OR ".join(f"from:{a.lstrip('@')}" for a in WATCH_ACCOUNTS)

    chat = client.chat.create(
        model="grok-3",
        tools=[x_search(
            from_date=datetime.now() - timedelta(hours=3),
            to_date=datetime.now(),
        )],
    )
    chat.append(xai_user(f"""以下のアカウントの直近3時間以内の新着投稿を取得してください。

対象: {", ".join(WATCH_ACCOUNTS)}

条件:
- リプライ・RTは除外（オリジナル投稿のみ）
- 政治・犯罪・差別・自傷系は除外

各投稿についてJSON形式で:
{{
  "posts": [
    {{
      "post_id": "投稿IDの数字部分",
      "account": "@アカウント名",
      "url": "https://x.com/アカウント名/status/投稿ID",
      "text": "本文全文",
      "likes": いいね数
    }}
  ]
}}

投稿が見つからない場合は {{"posts": []}} を返してください。"""))

    raw = ""
    for _, chunk in chat.stream():
        if chunk.content:
            raw += chunk.content

    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        data = json.loads(raw[start:end]) if start >= 0 else {}
        return data.get("posts", [])
    except Exception:
        return []


def generate_reply(post: dict) -> str:
    """Claudeでリプライ文を生成"""
    import anthropic
    client = anthropic.Anthropic()

    prompt = f"""@kaikowa_581（怪談・百物語・心霊ホラー系、フォロワー約4,000人）として以下の投稿にリプライする文章を書いてください。

投稿者: {post['account']}
投稿内容: {post['text'][:300]}

条件:
- 140字以内
- コピペしてそのまま投稿できる完成形
- 押しつけがましくない・自然な会話
- 百物語・怪談の世界観を1〜2語さりげなく入れる（地震など緊急時は入れない）
- 絵文字は0〜1個
- 自アカウントの宣伝は絶対に入れない

リプライ文だけ出力してください。"""

    res = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )
    return res.content[0].text.strip()


def send_to_discord(post: dict, reply: str):
    """Discord Webhookに通知"""
    now = datetime.now().strftime("%H:%M")
    msg = {
        "embeds": [{
            "title": f"🔔 新着投稿！ {post['account']} ｜{now}",
            "color": 0x8B0000,
            "fields": [
                {
                    "name": "投稿内容",
                    "value": post["text"][:300] + ("..." if len(post["text"]) > 300 else ""),
                    "inline": False
                },
                {
                    "name": f"❤️ {post.get('likes', '?')}　[投稿を開く]({post['url']})",
                    "value": "",
                    "inline": False
                },
                {
                    "name": "💬 リプライ（コピペOK）",
                    "value": f"```\n{reply}\n```",
                    "inline": False
                }
            ],
            "footer": {"text": "こわ面白いツール｜X監視ボット"}
        }]
    }
    requests.post(DISCORD_WEBHOOK, json=msg)


def run_once():
    _init_db()
    print(f"[{datetime.now().strftime('%H:%M')}] 監視中... 対象{len(WATCH_ACCOUNTS)}アカウント")

    try:
        posts = fetch_new_posts()
    except Exception as e:
        print(f"  取得エラー: {e}")
        return

    new_posts = [p for p in posts if not _is_seen(p.get("post_id", ""))]
    print(f"  新着: {len(new_posts)}件 / 取得: {len(posts)}件")

    for post in new_posts:
        try:
            reply = generate_reply(post)
            send_to_discord(post, reply)
            _mark_seen(post["post_id"], post["account"])
            print(f"  ✅ 通知送信: {post['account']} → {post['url']}")
            time.sleep(2)
        except Exception as e:
            print(f"  エラー ({post['account']}): {e}")


def run_loop(interval_minutes: int = 90):
    print(f"X監視ボット起動 — {interval_minutes}分ごとにチェック")
    while True:
        run_once()
        next_check = datetime.now() + timedelta(minutes=interval_minutes)
        print(f"  次回チェック: {next_check.strftime('%H:%M')}")
        time.sleep(interval_minutes * 60)


if __name__ == "__main__":
    if "--loop" in sys.argv:
        run_loop()
    else:
        run_once()
