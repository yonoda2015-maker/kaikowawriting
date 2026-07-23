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
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

from grok_auth import get_access_token, grok_available

DB_PATH = Path(__file__).parent / "kowamoshiro.db"

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


def _grok_chat(prompt: str, days: int = 3) -> str:
    from xai_sdk import Client
    from xai_sdk.chat import user as xai_user
    from xai_sdk.tools import x_search

    client = Client(api_key=get_access_token())
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


# ────────────────────────────────────────────────
# 0. アカウント分析（自アカウントの文体・構文学習）
# ────────────────────────────────────────────────

_ACCOUNT_CACHE_TABLE = """
    CREATE TABLE IF NOT EXISTS account_analysis (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account TEXT NOT NULL,
        analyzed_at TEXT NOT NULL,
        analysis_json TEXT NOT NULL
    )
"""

def analyze_account(account: str = "kaikowa_581", limit: int = 20) -> dict:
    """
    @account の直近投稿をGrok X Searchで取得・分析し、
    「このアカウントに最適な投稿構文」を抽出する。

    Returns:
        {
          "account": str,
          "top_posts": [...],          # いいね上位の投稿
          "style_profile": {
            "opening_pattern": str,    # 冒頭パターン（例: 「体言止め」「疑問形」）
            "sentence_length": str,    # 文の長さの傾向
            "paragraph_structure": str,# 段落構成
            "emoji_usage": str,        # 絵文字の使い方
            "hashtag_style": str,      # ハッシュタグの傾向
            "hook_formula": str,       # バズった投稿に共通するフック公式
            "ending_pattern": str,     # 締め方のパターン
          },
          "best_syntax_template": str, # 最もバズる構文テンプレート
          "do_list": [...],            # やるべきこと
          "dont_list": [...],          # やってはいけないこと
          "analyzed_at": str,
        }
    """
    prompt = f"""@{account} のXアカウントを分析してください。

1. まず直近の投稿を{limit}件検索して取得する
2. その中でいいね数・RT数が多い上位5件を特定する
3. 以下を分析する:

【文体・構文分析】
- 冒頭（最初の一文）のパターン（体言止め・疑問形・数字始まり・「〜した」など）
- 文の長さと改行の使い方
- 段落構成（起承転結 / 列挙 / 一文完結 など）
- 絵文字の使い方・位置・頻度
- ハッシュタグの数・位置・ジャンル
- バズった投稿に共通するフック公式
- 締め方のパターン（余韻・問いかけ・衝撃落ち など）

以下のJSON形式で返してください:
{{
  "account": "{account}",
  "top_posts": [
    {{"text": "投稿本文（冒頭150字）", "likes": 0, "retweets": 0, "why_viral": "理由"}}
  ],
  "style_profile": {{
    "opening_pattern": "...",
    "sentence_length": "...",
    "paragraph_structure": "...",
    "emoji_usage": "...",
    "hashtag_style": "...",
    "hook_formula": "...",
    "ending_pattern": "..."
  }},
  "best_syntax_template": "実際に使える構文テンプレート（穴埋め形式）",
  "do_list": ["やるべきこと1", "やるべきこと2", "やるべきこと3"],
  "dont_list": ["やってはいけないこと1", "やってはいけないこと2"]
}}"""

    raw = _grok_chat(prompt, days=90)

    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        data = json.loads(raw[start:end]) if start >= 0 else {}
    except json.JSONDecodeError:
        data = {}

    data.setdefault("account", account)
    data.setdefault("top_posts", [])
    data.setdefault("style_profile", {})
    data.setdefault("best_syntax_template", raw)
    data.setdefault("do_list", [])
    data.setdefault("dont_list", [])
    data["analyzed_at"] = datetime.now().isoformat()

    _save_account_analysis(account, data)
    return data


def _save_account_analysis(account: str, data: dict):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(_ACCOUNT_CACHE_TABLE)
        conn.execute(
            "INSERT INTO account_analysis (account, analyzed_at, analysis_json) VALUES (?,?,?)",
            (account, data["analyzed_at"], json.dumps(data, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def load_account_analysis(account: str = "kaikowa_581") -> Optional[dict]:
    """最新のアカウント分析をDBから取得"""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(_ACCOUNT_CACHE_TABLE)
        row = conn.execute(
            "SELECT analysis_json FROM account_analysis WHERE account=? ORDER BY id DESC LIMIT 1",
            (account,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return json.loads(row[0])


def build_account_syntax_hint(account: str = "kaikowa_581") -> str:
    """アカウント分析からプロンプト注入テキストを生成"""
    data = load_account_analysis(account)
    if not data:
        return ""
    sp = data.get("style_profile", {})
    tmpl = data.get("best_syntax_template", "")
    do_list = data.get("do_list", [])
    dont_list = data.get("dont_list", [])

    lines = [f"【@{account} に最適な投稿構文（このスタイルで書くこと）】"]
    if tmpl:
        lines.append(f"構文テンプレート: {tmpl}")
    if sp.get("opening_pattern"):
        lines.append(f"冒頭パターン: {sp['opening_pattern']}")
    if sp.get("hook_formula"):
        lines.append(f"フック公式: {sp['hook_formula']}")
    if sp.get("ending_pattern"):
        lines.append(f"締め方: {sp['ending_pattern']}")
    if do_list:
        lines.append("必須: " + " / ".join(do_list[:3]))
    if dont_list:
        lines.append("禁止: " + " / ".join(dont_list[:2]))
    return "\n".join(lines)


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
    if lang == "ja":
        lang_instruction = "日本のXユーザー（日本語投稿）の間で今日バズっているトレンドトピック"
        lang_constraint = "【重要】日本語圏のトレンドのみ。英語圏・海外のトレンド（Taylor Swift・Star Warsなど）は絶対に含めないこと。"
    else:
        lang_instruction = "trending topics on English X today"
        lang_constraint = ""

    prompt = f"""今現在、{lang_instruction}を{limit}件教えてください。

{lang_constraint}

【必須条件 — 以下を含むトピックは絶対に除外してください】
除外カテゴリ: {unsafe_cats}、その他政治・犯罪・暴力・性的・差別に関わる全て

【取得するカテゴリ（これだけ）】
{safe_cats}

各トピックについて以下のJSON形式で返してください:
{{
  "trends": [
    {{
      "topic": "トレンドのキーワード・話題（日本語）",
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
    """DBに保存された最新トレンドを返す（参照用）"""
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
            "SELECT trends_json FROM safe_trends ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return []
    return json.loads(row[0] or "[]")


# ────────────────────────────────────────────────
# 0.5 実話ネタバンクの調達元（Grok X Search経由・APIキー不要）
# 直接スクレイピングはネットワーク制限で不可のため、全てGrokの検索結果を使う。
# ────────────────────────────────────────────────

_REDDIT_HORROR_SUBS = [
    "r/Glitch_in_the_Matrix",
    "r/nosleep",
    "r/creepyencounters",
]

# ネタ元カタログ: ネタバンクUIのタブ名 → (取得先の説明, Grokへの検索指示, 翻案が必要か)
SEED_SOURCES = {
    "reddit": {
        "label": "🌐 Reddit（海外実話）",
        "target": f"Reddit（{'・'.join(_REDDIT_HORROR_SUBS)}等）",
        "instruction": "「日常のちょっとした説明のつかない体験」",
        "localize": True,
    },
    "x_experience": {
        "label": "🐦 X実体験談",
        "target": "X（Twitter）の日本語投稿",
        "instruction": "「実際に体験した説明のつかない出来事」として投稿された日本語のポスト",
        "localize": False,
    },
    "occult_board": {
        "label": "👻 オカルト板（洒落怖系）",
        "target": "5ちゃんねる・したらば等のオカルト板（洒落怖・意味怖系スレ）",
        "instruction": "スレで語られた「日常に潜む違和感」の実話・創作体験談",
        "localize": False,
    },
    "yahoo_chie": {
        "label": "💬 Yahoo!知恵袋",
        "target": "Yahoo!知恵袋",
        "instruction": "「これって普通ですか」「説明がつかないんですが」といった相談形式の不思議な体験質問",
        "localize": False,
    },
}


last_fetch_error: str = ""


def fetch_horror_seeds_from_source(source_key: str, count: int = 5) -> list[dict]:
    """
    指定したネタ元（reddit/x_experience/occult_board/yahoo_chie）から
    実話系「説明のつかない日常体験」をGrok X Search経由で取得する。

    Returns: [{"fact": str, "source": str}, ...]
    失敗時はモジュール変数 last_fetch_error にエラーメッセージを保存して [] を返す。
    """
    global last_fetch_error

    src = SEED_SOURCES.get(source_key)
    if not src:
        last_fetch_error = f"未知のネタ元です: {source_key}"
        return []

    localize_block = (
        "各エピソードを日本の日常に置き換えて、事実だけ2〜3文で要約してください"
        "（人名・地名は日本風に、海外特有の文化・習慣は日本の生活に翻案する）。"
        if src["localize"] else
        "各エピソードを事実だけ2〜3文で要約してください（日本語のまま、脚色を加えない）。"
    )

    prompt = f"""{src['target']}で話題になった{src['instruction']}を{count}個探してください。

条件:
- 超常現象・幽霊だと断定しない。「説明できない事実」レベルのものが理想
- 政治・犯罪・暴力・性的なものは除外

{localize_block}

JSON形式のみ出力:
{{"seeds": [{{"fact": "事実2〜3文", "source": "元ネタの出典（URL不明ならスレ名/投稿の特徴）"}}]}}"""

    try:
        raw = _grok_chat(prompt, days=60)
        s = raw.find("{"); e = raw.rfind("}") + 1
        data = json.loads(raw[s:e]) if s >= 0 else {}
        last_fetch_error = ""
        return data.get("seeds", [])
    except Exception as exc:
        last_fetch_error = f"{type(exc).__name__}: {exc}"
        return []


def fetch_reddit_horror_seeds(count: int = 5) -> list[dict]:
    """後方互換用ラッパー。fetch_horror_seeds_from_source('reddit', count) と同じ。"""
    return fetch_horror_seeds_from_source("reddit", count)


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
