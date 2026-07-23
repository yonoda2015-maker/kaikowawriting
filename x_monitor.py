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
_OIDC_TOKEN_URL = "https://auth.x.ai/oauth2/token"
_OIDC_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"

_cached_token: dict = {"key": "", "expires_at": ""}


def _refresh_access_token(refresh_token: str) -> str:
    """リフレッシュトークンでアクセストークンを更新"""
    res = requests.post(_OIDC_TOKEN_URL, data={
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": _OIDC_CLIENT_ID,
    })
    res.raise_for_status()
    data = res.json()
    return data["access_token"]


def _get_grok_token() -> str:
    global _cached_token

    # まず環境変数のリフレッシュトークンで更新を試みる
    refresh_token = os.getenv("GROK_REFRESH_TOKEN")
    if refresh_token:
        expires_at = _cached_token.get("expires_at", "")
        # 5分前に更新
        if not expires_at or datetime.fromisoformat(expires_at) - datetime.now() < timedelta(minutes=5):
            try:
                new_token = _refresh_access_token(refresh_token)
                _cached_token = {
                    "key": new_token,
                    "expires_at": (datetime.now() + timedelta(hours=6)).isoformat()
                }
                print(f"  [Grok] アクセストークンを更新しました")
            except Exception as e:
                print(f"  [Grok] トークン更新失敗: {e}")
        if _cached_token.get("key"):
            return _cached_token["key"]

    # ローカルのauth.jsonを使う
    if AUTH_PATH.exists():
        with open(AUTH_PATH) as f:
            d = json.load(f)
        return list(d.values())[0]["key"]

    raise RuntimeError("Grokトークンが見つかりません。GROK_REFRESH_TOKEN を設定してください。")


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
            from_date=datetime.now() - timedelta(hours=24),
            to_date=datetime.now(),
        )],
    )
    or_query = " OR ".join(f"from:{a.lstrip('@')}" for a in WATCH_ACCOUNTS)
    chat.append(xai_user(f"""X検索クエリ: {or_query}

上記クエリで直近24時間のオリジナル投稿（RT・リプライ除く）を取得してください。

JSON:
{{
  "posts": [
    {{
      "post_id": "投稿IDの数字部分",
      "account": "@アカウント名",
      "url": "https://x.com/アカウント名/status/投稿ID",
      "text": "本文（200字以内）",
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

    prompt = f"""@kaikowa_581（怪談・心霊ホラー系、フォロワー約4,000人）として以下の投稿にリプライする文章を書いてください。

投稿者: {post['account']}
投稿内容: {post['text'][:300]}

条件:
- 140字以内
- コピペしてそのまま投稿できる完成形
- 押しつけがましくない・自然な会話
- 怪談・心霊の世界観を1〜2語さりげなく入れる（地震など緊急時は入れない）
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


def _init_likes_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS own_post_likes (
            post_id TEXT PRIMARY KEY,
            url TEXT,
            text TEXT,
            likes INTEGER,
            fetched_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def fetch_own_likes(days: int = 7) -> list[dict]:
    """@kaikowa_581の直近投稿といいね数をGrokで取得"""
    from xai_sdk import Client
    from xai_sdk.chat import user as xai_user
    from xai_sdk.tools import x_search

    client = Client(api_key=_get_grok_token())
    chat = client.chat.create(
        model="grok-3",
        tools=[x_search(
            from_date=datetime.now() - timedelta(days=days),
            to_date=datetime.now(),
        )],
    )
    chat.append(xai_user(f"""@kaikowa_581 の直近{days}日以内のオリジナル投稿（RTやリプライ除く）をいいね数とともに取得してください。

JSON形式で返してください:
{{
  "posts": [
    {{
      "post_id": "投稿IDの数字部分",
      "url": "https://x.com/kaikowa_581/status/投稿ID",
      "text": "本文（100字以内）",
      "likes": いいね数（整数）
    }}
  ]
}}

投稿が見つからない場合は {{"posts": []}} を返してください。"""))

    raw = ""
    for _, chunk in chat.stream():
        if chunk.content:
            raw += chunk.content

    try:
        s = raw.find("{"); e = raw.rfind("}") + 1
        return json.loads(raw[s:e]).get("posts", []) if s >= 0 else []
    except Exception:
        return []


def save_and_report_likes():
    """いいね数を取得してDBに保存・Discordに報告"""
    _init_likes_db()
    print(f"[{datetime.now().strftime('%H:%M')}] @kaikowa_581 いいね数取得中...")

    try:
        posts = fetch_own_likes(days=7)
    except Exception as e:
        print(f"  取得エラー: {e}")
        return

    if not posts:
        print("  投稿なし")
        return

    conn = sqlite3.connect(DB_PATH)
    new_count = 0
    for p in posts:
        pid = p.get("post_id", "")
        if not pid:
            continue
        existing = conn.execute("SELECT likes FROM own_post_likes WHERE post_id=?", (pid,)).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO own_post_likes (post_id, url, text, likes, fetched_at) VALUES (?,?,?,?,?)",
                (pid, p.get("url",""), p.get("text","")[:200], p.get("likes",0), datetime.now().isoformat())
            )
            new_count += 1
        else:
            conn.execute("UPDATE own_post_likes SET likes=?, fetched_at=? WHERE post_id=?",
                         (p.get("likes",0), datetime.now().isoformat(), pid))
    conn.commit()
    conn.close()

    posts_sorted = sorted(posts, key=lambda x: x.get("likes", 0), reverse=True)
    now = datetime.now().strftime("%Y/%m/%d %H:%M")

    fields = []
    for i, p in enumerate(posts_sorted[:10], 1):
        fields.append({
            "name": f"{'🥇🥈🥉'[i-1] if i <= 3 else f'{i}位'} ❤️{p.get('likes',0)}",
            "value": f"{p.get('text','')[:80]}…\n[→ 投稿を開く]({p.get('url','')})",
            "inline": False
        })

    msg = {"embeds": [{"title": f"📊 @kaikowa_581 いいね集計｜{now}", "color": 0x1DA1F2, "fields": fields,
                       "footer": {"text": f"直近7日 {len(posts)}件取得 / 新規{new_count}件"}}]}
    requests.post(DISCORD_WEBHOOK, json=msg)
    print(f"  ✅ {len(posts)}件取得 Discord送信完了")


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
    last_likes_date = None
    while True:
        run_once()
        # 1日1回（正午以降の最初のループ）いいね集計
        today = datetime.now().date()
        if datetime.now().hour >= 12 and last_likes_date != today:
            try:
                save_and_report_likes()
                last_likes_date = today
            except Exception as e:
                print(f"  いいね集計エラー: {e}")
        next_check = datetime.now() + timedelta(minutes=interval_minutes)
        print(f"  次回チェック: {next_check.strftime('%H:%M')}")
        time.sleep(interval_minutes * 60)


if __name__ == "__main__":
    if "--loop" in sys.argv:
        run_loop()
    elif "--likes" in sys.argv:
        save_and_report_likes()
    else:
        run_once()
