"""
Viral pattern research via Grok Build's X Search.

Uses xAI API (OpenAI-compatible) to search X for real viral posts,
extract writing patterns, and store them for content generation.
"""

import os
import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional

_XAI_BASE = "https://api.x.ai/v1"
_GROK_MODEL = "grok-3"  # has live X Search tool

DB_PATH = Path(__file__).parent / "kowamoshiro.db"


def _get_client():
    from openai import OpenAI
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        raise ValueError("XAI_API_KEY が設定されていません。.env に追加してください。")
    return OpenAI(api_key=api_key, base_url=_XAI_BASE)


def search_viral_posts(genre: str, lang: str = "ja", limit: int = 5) -> dict:
    """
    X Search で指定ジャンルのバズり投稿を検索し、パターンを分析する。

    Returns:
        {
          "posts": [...],          # 実際の投稿リスト
          "patterns": {...},       # 抽出したバズりパターン
          "hook_templates": [...], # 使えるフック文例
          "raw_analysis": str      # Grokの生分析テキスト
        }
    """
    client = _get_client()

    query_map = {
        "ホラー体験談・怪談": "怖い体験談 OR 実話怪談 OR 心霊体験",
        "都市伝説・未解決事件": "都市伝説 OR 未解決事件 OR 心霊スポット",
        "不思議・オカルト・陰謀論": "不思議な話 OR オカルト OR 都市伝説",
        "意味がわかると怖い": "意味がわかると怖い OR 意味怖",
        "面白くて怖い（おも怖い）": "おも怖い OR 怖面白い OR ホラーコメディ",
        "王道ホラー（心霊）": "心霊写真 OR 幽霊 OR 霊的体験",
        "胸糞・ヒトコワ": "胸糞話 OR 人間怖い OR ヒトコワ",
        "サイコ・ダークな人間ドラマ": "サイコ OR ダーク OR 人間ドラマ 怖い",
        "心霊スポット（世界）": "海外心霊スポット OR 世界の怖い場所",
    }

    x_query = query_map.get(genre, f"{genre} 怖い 体験")
    lang_note = "日本語の投稿" if lang == "ja" else "English posts"

    prompt = f"""X（Twitter）で以下のクエリを使って、過去2週間以内に**バズった（いいね100以上）**{lang_note}を{limit}件検索してください。

検索クエリ: {x_query}
条件:
- 宣伝・公式アカウントの投稿は除外
- 実際の体験談・一般ユーザーの生の声を優先
- エンゲージメント（いいね・RT）が多い順

各投稿について以下を返してください:
1. アカウント名
2. 投稿本文（冒頭100字）
3. いいね数（概算）
4. バズった理由（フック・構成・感情訴求など）

その後、これらの投稿から**共通するバズりパターン**を分析して:
- フック（冒頭の掴み）のパターン
- 感情訴求のポイント
- 構成の特徴
- 実際に使えるフック文例を3つ（{genre}ジャンル向け）

JSON形式で返答してください:
{{
  "posts": [
    {{"account": "...", "text": "...", "likes": 0, "reason": "..."}}
  ],
  "patterns": {{
    "hook_type": "...",
    "emotion_trigger": "...",
    "structure": "..."
  }},
  "hook_templates": ["...", "...", "..."],
  "summary": "..."
}}"""

    response = client.chat.completions.create(
        model=_GROK_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )

    raw = response.choices[0].message.content

    # JSON部分を抽出
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(raw[start:end])
        else:
            data = {"posts": [], "patterns": {}, "hook_templates": [], "summary": raw}
    except json.JSONDecodeError:
        data = {"posts": [], "patterns": {}, "hook_templates": [], "summary": raw}

    data["raw_analysis"] = raw
    data["genre"] = genre
    data["searched_at"] = datetime.now().isoformat()

    _save_viral_research(genre, data)
    return data


def _save_viral_research(genre: str, data: dict):
    """検索結果をDBに保存"""
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
                data.get("searched_at", ""),
                json.dumps(data.get("posts", []), ensure_ascii=False),
                json.dumps(data.get("patterns", {}), ensure_ascii=False),
                json.dumps(data.get("hook_templates", []), ensure_ascii=False),
                data.get("summary", ""),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_latest_research(genre: str) -> Optional[dict]:
    """最新の検索結果をDBから読む"""
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
    """最新の検索結果からプロンプト用のヒント文を生成"""
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


def xai_available() -> bool:
    return bool(os.getenv("XAI_API_KEY"))
