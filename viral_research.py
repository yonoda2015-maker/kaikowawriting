"""
Viral pattern research via Grok Build's X Search.

Uses xai-sdk + Grok CLI OAuth token (~/.grok/auth.json).
No XAI_API_KEY required — just `grok login` once.

Flow:
  1. fetch_safe_trends()      — リアルタイムXトレンド取得（ポリシー安全のみ）
  2. search_viral_posts()     — ジャンル別バズり投稿分析
  3. policy_check_content()   — 生成後のXポリシー違反チェック
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "kowamoshiro.db"
_AUTH_PATH = Path.home() / ".grok" / "auth.json"

# Xポリシーで絶対に避けるべきトピックカテゴリ
_UNSAFE_CATEGORIES = [
    "政治", "選挙", "政党", "政治家", "国会", "首相", "大統領",
    "殺人", "事件", "犯罪", "逮捕", "死亡事故", "テロ", "暴力",
    "戦争", "紛争", "侵攻", "難民",
    "差別", "ヘイト", "人種",
    "自殺", "自傷",
    "性的", "ポルノ",
    "詐欺", "違法",
]

_SAFE_TREND_CATEGORIES = [
    "エンタメ・アニメ・漫画・ゲーム",
    "スポーツ（選手の話題など）",
    "グルメ・料理",
    "旅行・観光スポット",
    "季節のイベント・祭り",
    "不思議体験・都市伝説・怪談",
    "テクノロジー・ガジェット",
    "ペット・動物",
    "芸能・音楽",
]


def _get_token() -> str:
    with open(_AUTH_PATH) as f:
        d = json.load(f)
    return list(d.values())[0]["key"]


def _grok_chat(prompt: str, days: int = 3) -> str:
    from xai_sdk import Client
    from xai_sdk.chat import user as xai_user
    from xai_sdk.tools import x_search

    client = Client(api_key=_get_token())
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
    return raw.strip()


def grok_available() -> bool:
    return _AUTH_PATH.exists()


# ────────────────────────────────────────────────
# 1. リアルタイム安全トレンド取得
# ────────────────────────────────────────────────

def fetch_safe_trends(lang: str = "ja", limit: int = 5) -> list[dict]:
    """
    今Xでバズっている話題のうち、Xポリシーに絶対触れない安全なトレンドを取得。

    Returns: [{"topic": str, "angle": str, "hook": str}, ...]
    """
    safe_cats = "・".join(_SAFE_TREND_CATEGORIES)
    unsafe_cats = "・".join(_UNSAFE_CATEGORIES[:10])
    lang_note = "日本語のXで" if lang == "ja" else "on English X"

    prompt = f"""今{lang_note}バズっているトレンドトピックを{limit}件教えてください。

【必須条件 — 以下を含むトピックは絶対に除外してください】
除外カテゴリ: {unsafe_cats}、その他政治・犯罪・暴力・性的・差別に関わる全て

【取得するカテゴリ（これだけ）】
{safe_cats}

各トピックについて以下のJSON形式で返してください:
{{
  "trends": [
    {{
      "topic": "トレンドのキーワード・話題",
      "category": "カテゴリ名",
      "why_viral": "バズっている理由（30字以内）",
      "horror_angle": "このトレンドと絡めた怖い話のネタ案（50字以内）",
      "safe": true
    }}
  ]
}}

政治・犯罪・暴力・差別・自殺に関係するトピックは safe: false にして含めないでください。"""

    raw = _grok_chat(prompt, days=2)

    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        data = json.loads(raw[start:end]) if start >= 0 else {}
        trends = [t for t in data.get("trends", []) if t.get("safe", True)]
    except (json.JSONDecodeError, ValueError):
        trends = []

    _save_trends(trends)
    return trends


def _save_trends(trends: list[dict]):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS safe_trends (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fetched_at TEXT NOT NULL,
                trends_json TEXT NOT NULL
            )
        """)
        conn.execute(
            "INSERT INTO safe_trends (fetched_at, trends_json) VALUES (?,?)",
            (datetime.now().isoformat(), json.dumps(trends, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def load_latest_trends() -> list[dict]:
    """最新の安全トレンドをDBから読む（3時間以内なら再利用）"""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS safe_trends (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fetched_at TEXT NOT NULL,
                trends_json TEXT NOT NULL
            )
        """)
        row = conn.execute(
            "SELECT fetched_at, trends_json FROM safe_trends ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return []
    fetched_at = datetime.fromisoformat(row[0])
    if datetime.now() - fetched_at > timedelta(hours=3):
        return []  # 3時間超えたら再取得を促す
    return json.loads(row[1] or "[]")


def build_trend_hint(trends: list[dict], genre: str) -> str:
    """トレンドデータをプロンプト注入用テキストに変換"""
    if not trends:
        return ""
    lines = ["【今Xでバズっている安全なトレンド（これと絡めて生成すること）】"]
    for t in trends[:3]:
        lines.append(f"・{t['topic']}（{t.get('why_viral','')}）")
        if t.get("horror_angle"):
            lines.append(f"  → {genre}との絡め方: {t['horror_angle']}")
    lines.append("※ 上記トレンドに自然に絡めた怖い話にすること。無理やり感は出さない。")
    return "\n".join(lines)


# ────────────────────────────────────────────────
# 2. ジャンル別バズり投稿分析（既存機能を強化）
# ────────────────────────────────────────────────

def search_viral_posts(genre: str, lang: str = "ja", days: int = 14, limit: int = 5) -> dict:
    """
    Grok Build の X Search でバズり投稿を検索・分析する。
    """
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

    prompt = f"""X（Twitter）で「{x_query}」を検索して、過去{days}日以内にバズった（いいね多め）{lang_note}を{limit}件見つけてください。

除外（絶対に含めない）: 政治・犯罪ニュース・暴力事件・差別・自殺に関わる投稿

各投稿:
- アカウント名、投稿本文（冒頭100字）、いいね数概算、バズった理由

最後に以下JSON形式で返してください:
{{
  "posts": [{{"account": "...", "text": "...", "likes": 0, "reason": "..."}}],
  "patterns": {{"hook_type": "...", "emotion_trigger": "...", "structure": "..."}},
  "hook_templates": ["...", "...", "..."],
  "summary": "..."
}}"""

    raw = _grok_chat(prompt, days=days)

    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        data = json.loads(raw[start:end]) if start >= 0 else {}
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


# ────────────────────────────────────────────────
# 3. 生成後Xポリシーチェック
# ────────────────────────────────────────────────

# ルールベース即時チェック（Claude API不使用）
_POLICY_NG_PATTERNS = [
    # 暴力・犯罪
    "殺", "死ね", "爆発", "テロ", "爆弾", "銃撃", "刺殺", "絞殺",
    # 差別
    "差別", "ヘイト", "レイシスト",
    # 自傷
    "自殺方法", "死にたい 方法", "首吊り 方法",
    # 性的
    "無修正", "ポルノ", "援交",
    # 詐欺
    "儲かる 簡単", "元本保証", "ネズミ講",
]

_POLICY_WARNING_PATTERNS = [
    # センシティブだが即アウトではない
    "死", "呪い", "怨霊", "血", "遺体", "幽霊", "地獄",
]


def policy_check_content(text: str) -> dict:
    """
    生成されたテキストがXポリシーに違反しないかチェック。

    Returns:
        {
          "safe": bool,
          "level": "ok" | "warning" | "ng",
          "reason": str,
          "fix_hint": str
        }
    """
    text_lower = text.lower()

    # NGパターン（即アウト）
    for pattern in _POLICY_NG_PATTERNS:
        if pattern in text:
            return {
                "safe": False,
                "level": "ng",
                "reason": f"Xポリシー違反の可能性: 「{pattern}」を含む表現",
                "fix_hint": "該当箇所を怪談・ホラー表現に置き換えてください",
            }

    # 政治キーワード
    political = ["政治", "選挙", "政党", "首相", "大統領", "国会", "議員"]
    for kw in political:
        if kw in text:
            return {
                "safe": False,
                "level": "ng",
                "reason": f"政治関連キーワード「{kw}」を含む",
                "fix_hint": "政治に触れる表現を削除してください",
            }

    # Warningパターン（怪談文脈なら許容）
    warnings = [p for p in _POLICY_WARNING_PATTERNS if p in text]
    if len(warnings) >= 4:
        return {
            "safe": True,
            "level": "warning",
            "reason": f"センシティブ語が多め: {', '.join(warnings[:3])}など",
            "fix_hint": "怪談文脈として問題ないですが、投稿前に確認推奨",
        }

    return {"safe": True, "level": "ok", "reason": "ポリシーチェック通過", "fix_hint": ""}


# 後方互換
xai_available = grok_available
