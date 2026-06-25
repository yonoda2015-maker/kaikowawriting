"""
Viral pattern research via Grok Build's X Search.

Uses xai-sdk + Grok CLI OAuth token (~/.grok/auth.json).
No XAI_API_KEY required — just `grok login` once.
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "kowamoshiro.db"
_AUTH_PATH = Path.home() / ".grok" / "auth.json"


def _get_token() -> str:
    with open(_AUTH_PATH) as f:
        d = json.load(f)
    return list(d.values())[0]["key"]


def grok_available() -> bool:
    return _AUTH_PATH.exists()


def search_viral_posts(genre: str, lang: str = "ja", days: int = 14, limit: int = 5) -> dict:
    """
    Grok Build の X Search でバズり投稿を検索・分析する。

    Returns:
        {
          "posts": [...],
          "patterns": {...},
          "hook_templates": [...],
          "summary": str
        }
    """
    from xai_sdk import Client
    from xai_sdk.chat import user as xai_user
    from xai_sdk.tools import x_search

    token = _get_token()
    client = Client(api_key=token)

    query_map = {
        "ホラー体験談・怪談": "怖い体験談 OR 実話怪談 OR 心霊体験",
        "都市伝説・未解決事件": "都市伝説 OR 未解決事件 OR 心霊スポット",
        "不思議・オカルト・陰謀論": "不思議な話 OR オカルト OR 陰謀論",
        "意味がわかると怖い": "意味がわかると怖い OR 意味怖",
        "面白くて怖い（おも怖い）": "おも怖い OR 怖面白い",
        "王道ホラー（心霊）": "心霊写真 OR 幽霊 OR 霊的体験",
        "胸糞・ヒトコワ": "胸糞話 OR 人間怖い OR ヒトコワ",
        "サイコ・ダークな人間ドラマ": "サイコ OR ダーク 怖い",
        "心霊スポット（世界）": "海外心霊スポット OR 世界の怖い場所",
    }
    x_query = query_map.get(genre, f"{genre} 怖い 体験")
    lang_note = "日本語の投稿" if lang == "ja" else "English posts"

    prompt = f"""X（Twitter）で「{x_query}」を検索して、過去{days}日以内に**バズった（いいね多め）**{lang_note}を{limit}件見つけてください。

条件:
- 宣伝・公式アカウントは除外
- 一般ユーザーの実体験・生の声を優先
- エンゲージメントが高い順

各投稿について:
- アカウント名
- 投稿本文（冒頭100字）
- いいね数（概算）
- バズった理由（フック・構成・感情訴求）

最後に共通パターンを分析して以下のJSON形式で返してください:
{{
  "posts": [{{"account": "...", "text": "...", "likes": 0, "reason": "..."}}],
  "patterns": {{"hook_type": "...", "emotion_trigger": "...", "structure": "..."}},
  "hook_templates": ["...", "...", "..."],
  "summary": "..."
}}"""

    chat = client.chat.create(
        model="grok-3",
        tools=[x_search(
            from_date=datetime.now() - timedelta(days=days),
            to_date=datetime.now(),
        )],
    )
    chat.append(xai_user(prompt))

    raw = ""
    for _, chunk in chat.stream():
        if chunk.content:
            raw += chunk.content

    # JSON抽出
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        data = json.loads(raw[start:end]) if start >= 0 and end > start else {}
    except json.JSONDecodeError:
        data = {}

    data.setdefault("posts", [])
    data.setdefault("patterns", {})
    data.setdefault("hook_templates", [])
    data.setdefault("summary", raw)
    data["genre"] = genre
    data["searched_at"] = datetime.now().isoformat()

    _save_viral_research(genre, data)
    return data


def _save_viral_research(genre: str, data: dict):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS viral_research (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                genre TEXT NOT NULL,
                searched_at TEXT NOT NULL,
                posts_json TEXT,
                patterns_json TEXT,
                hook_templates_json TEXT,
                summary TEXT
            )
        """)
        conn.execute(
            "INSERT INTO viral_research (genre, searched_at, posts_json, patterns_json, hook_templates_json, summary) VALUES (?,?,?,?,?,?)",
            (
                genre,
                data["searched_at"],
                json.dumps(data["posts"], ensure_ascii=False),
                json.dumps(data["patterns"], ensure_ascii=False),
                json.dumps(data["hook_templates"], ensure_ascii=False),
                data["summary"],
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_latest_research(genre: str) -> Optional[dict]:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS viral_research (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                genre TEXT NOT NULL,
                searched_at TEXT NOT NULL,
                posts_json TEXT,
                patterns_json TEXT,
                hook_templates_json TEXT,
                summary TEXT
            )
        """)
        row = conn.execute(
            "SELECT searched_at, posts_json, patterns_json, hook_templates_json, summary FROM viral_research WHERE genre=? ORDER BY id DESC LIMIT 1",
            (genre,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return None
    return {
        "searched_at": row[0],
        "posts": json.loads(row[1] or "[]"),
        "patterns": json.loads(row[2] or "{}"),
        "hook_templates": json.loads(row[3] or "[]"),
        "summary": row[4] or "",
        "genre": genre,
    }


def build_viral_hint(genre: str) -> str:
    data = load_latest_research(genre)
    if not data:
        return ""
    hooks = data.get("hook_templates", [])
    patterns = data.get("patterns", {})
    lines = [f"【X バズりパターン（{genre}）】"]
    if patterns.get("hook_type"):
        lines.append(f"フック型: {patterns['hook_type']}")
    if patterns.get("emotion_trigger"):
        lines.append(f"感情訴求: {patterns['emotion_trigger']}")
    if hooks:
        lines.append("フック文例:")
        for h in hooks[:3]:
            lines.append(f"  ・{h}")
    return "\n".join(lines)


# 後方互換（旧: xai_available → grok_available に統一）
xai_available = grok_available
