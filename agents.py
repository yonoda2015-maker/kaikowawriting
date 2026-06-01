import os
import re
import json
import requests
import feedparser
import anthropic
from dotenv import load_dotenv

from logger_config import logger
from validators import (
    sanitize_user_input,
    validate_claude_output,
    validate_rss_entry,
    filter_hashtags,
)
from cache import rss_cache, trend_cache

load_dotenv(override=True)

GENRE_DESCRIPTIONS = {
    "都市伝説・未解決事件": "都市伝説、未解決事件、失踪、陰謀",
    "ホラー体験談・怪談": "心霊体験、怪談、怪奇現象、呪い",
    "不思議・オカルト・陰謀論": "オカルト、陰謀論、超常現象、秘密組織",
    "サイコ・ダークな人間ドラマ": "サイコパス、ストーカー、狂気、ダークな人間関係",
    "心霊スポット（世界）": "世界各地の有名心霊スポット・廃墟・呪われた場所",
    "意味がわかると怖い": "読んだときは普通だが、意味を理解した瞬間に恐怖が来る話",
}

# 意味がわかると怖いジャンル専用ルール
IMI_KOWAI_RULES = """
【意味がわかると怖い話のルール】
- 表面上は普通の日常・会話・出来事として書く
- 読んだだけでは「怖い話」に見えないようにする
- 文章の中に「ひとつだけおかしな点」を隠す
- その「おかしな点」の意味がわかった瞬間に全てが怖くなる構造にする
- 答え・解説は絶対に書かない。読者自身が気づく余白を作る
- タイトルや末尾に「わかった？」「気づいた？」などのヒントを添えてもよい
- 典型的な構造例：
  ・「ある言葉・行動が実は死を示していた」
  ・「語り手自身がすでに死んでいた」
  ・「普通に見えた場面が実は異常だった」
  ・「助けを求めていたのに周囲が気づかなかった」
"""

STYLE_DESCRIPTIONS = {
    "会話風": "セリフのやり取りだけで怖さを表現する。地の文は最小限に。",
    "独り言・日記風": "「今日変なことがあった」系のリアルな体験談。一人称で語る。",
    "スレッド連投風": "「1/5」「2/5」形式で続きが気になる構成にする。",
    "ニュース・報告風": "感情を入れず淡々と事実だけを述べる。",
    "コメント欄風": "第三者目線。「これ本当にあった話なんですが…」",
    "ランキング・リスト風": "「知らない方がよかった都市伝説3選」系。箇条書きで。",
    "問いかけ風": "読者に質問して終わる構成。エンゲージメント狙い。",
    "途中で途切れる風": "文章が突然終わる。読者に想像させる余白を作る。",
    "ブログ記事風": "見出し・本文・まとめの構成で、SEOを意識した読み物として書く。",
}

X_POLICY_RULES = """
【X（Twitter）ポリシー配慮ルール】
- 実在する特定の個人・企業・団体を名指しで誹謗中傷しない
- 自傷・自殺を具体的に描写・推奨しない（暗示はOK）
- 暴力・流血の過激な描写は避け、恐怖は「見えないもの」で表現する
- ヘイトスピーチにつながる表現（差別・民族・宗教への攻撃）は使わない
- 「フィクションです」「創作です」などの免責表現を末尾に1行添える
- 実在する事件・事故と混同されるような断定表現は避ける
"""

ANTI_AI_RULES = """
【絶対ルール】
- 断定口調（〜だ、〜した、〜だった）のみ使う
- 「実は」「なんと」「驚くことに」「まとめると」「つまり」は使わない
- 「〜でしょう」「〜かもしれません」などの曖昧表現は使わない
- 綺麗にまとめない。オチは説明せずに感じさせる
- 実話風の語り口を徹底する
- 起承転結＋最後にゾワッとするオチを必ず入れる
- 文章を美化しない
"""


def _call_claude(prompt: str, max_tokens: int = 2000, retries: int = 2) -> str:
    """
    Claude APIを呼び出す。
    - APIキー未設定は即座にValueError
    - レスポンスのruntime validation
    - 一時的なエラーは retries 回リトライ
    """
    load_dotenv(override=True)
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEYが設定されていません。設定タブで入力してください。")

    client = anthropic.Anthropic(api_key=api_key)
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        try:
            logger.debug(f"Claude API call: max_tokens={max_tokens}, prompt_len={len(prompt)}")
            message = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text
            result = validate_claude_output(raw, min_chars=5)
            if not result.valid:
                raise ValueError(f"Claude出力が無効: {result.errors}")
            for w in result.warnings:
                logger.warning(f"Claude output warning: {w}")
            logger.info(f"Claude API success: {len(raw)}文字")
            return result.value
        except anthropic.RateLimitError as e:
            logger.warning(f"Rate limit hit (attempt {attempt+1}): {e}")
            last_error = e
            if attempt < retries:
                import time; time.sleep(2 ** attempt)
        except anthropic.APIStatusError as e:
            logger.error(f"Claude API error {e.status_code}: {e.message}")
            raise RuntimeError(f"Claude APIエラー ({e.status_code}): {e.message}") from e
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Unexpected Claude error (attempt {attempt+1}): {e}")
            last_error = e
            if attempt < retries:
                import time; time.sleep(1)

    raise RuntimeError(f"Claude API呼び出し失敗（{retries+1}回試行）: {last_error}") from last_error


def _parse_title_and_body(raw: str) -> tuple[str, str]:
    """【タイトル】【本文】フォーマットからタイトルと本文を分離する。"""
    import re
    title_match = re.search(r"【タイトル】\s*\n([^\n【]+)", raw)
    body_match  = re.search(r"【本文】\s*\n([\s\S]+)", raw)
    title = title_match.group(1).strip() if title_match else ""
    body  = body_match.group(1).strip()  if body_match  else raw.strip()
    return body, title


HORROR_LEVEL_INSTRUCTIONS = {
    1: "怖さレベル1（じんわり不気味）: 読後にわずかな違和感が残る程度。直接的な恐怖描写なし。",
    2: "怖さレベル2（ちょっと怖い）: 不気味な雰囲気・奇妙な出来事がある。直接的な恐怖は少ない。",
    3: "怖さレベル3（普通に怖い）: 明確な怖い要素がある。夜に一人で読むと怖いくらい。",
    4: "怖さレベル4（かなり怖い）: 強い恐怖・衝撃・背筋が凍るシーンがある。",
    5: "怖さレベル5（トラウマ級）: 読んだ後しばらく頭から離れない。最大限の恐怖を描け。",
}


def _get_horror_level_instruction(horror_level: int) -> str:
    return HORROR_LEVEL_INSTRUCTIONS.get(horror_level, "")


def generate_post(genre: str, style: str, idea: str, char_count: int = 300,
                  x_safe: bool = False, horror_level: int = 3) -> str:
    # 入力サニタイズ
    san = sanitize_user_input(idea, max_chars=1000)
    if not san.valid:
        logger.warning(f"Input validation failed: {san.errors}")
    idea = san.value
    for w in san.warnings:
        logger.warning(f"Input warning: {w}")

    genre_desc = GENRE_DESCRIPTIONS.get(genre, genre)
    style_desc = STYLE_DESCRIPTIONS.get(style, style)
    policy     = X_POLICY_RULES if x_safe else ""
    level_inst = _get_horror_level_instruction(horror_level)
    # 意味がわかると怖いジャンル専用ルール
    imi_rule   = IMI_KOWAI_RULES if genre == "意味がわかると怖い" else ""

    prompt = f"""以下の条件でSNS投稿文を書け。

ジャンル：{genre}（{genre_desc}）
スタイル：{style}（{style_desc}）
ネタ：{idea}
目標文字数：約{char_count}字
{level_inst}

{ANTI_AI_RULES}
{policy}
{imi_rule}
投稿文だけを出力すること。説明・前置き・タイトルは不要。"""

    return _call_claude(prompt, max_tokens=1000)


def generate_novel(genre: str, idea: str, char_count: int = 3000,
                   x_safe: bool = False, style_hint: str = "",
                   horror_level: int = 3) -> tuple[str, str]:
    """小説本文とタイトルをtupleで返す。"""
    genre_desc = GENRE_DESCRIPTIONS.get(genre, genre)
    max_tokens = min(8000, char_count * 2)
    policy     = X_POLICY_RULES if x_safe else ""
    level_inst = _get_horror_level_instruction(horror_level)
    imi_rule   = IMI_KOWAI_RULES if genre == "意味がわかると怖い" else ""

    prompt = f"""以下の条件でこわ面白い短編小説を書け。

ジャンル：{genre}（{genre_desc}）
ネタ：{idea}
目標文字数：約{char_count}字
{level_inst}

{ANTI_AI_RULES}
{policy}
{style_hint}
{imi_rule}
- 一人称または三人称で、実話風に書く
- ラストは「ゾワッとするオチ」にする

必ず以下のフォーマットで出力すること：

【タイトル】
（ここにタイトルを1行で書く）

【本文】
（ここに小説本文を書く）"""

    raw = _call_claude(prompt, max_tokens=max_tokens)
    return _parse_title_and_body(raw)


def generate_article(genre: str, idea: str, article_type: str, char_count: int = 3000,
                     include_story: bool = False, x_safe: bool = False,
                     horror_level: int = 3) -> tuple[str, str]:
    """記事本文とタイトルをtupleで返す。"""
    genre_desc     = GENRE_DESCRIPTIONS.get(genre, genre)
    max_tokens     = min(8000, char_count * 2)
    policy         = X_POLICY_RULES if x_safe else ""
    level_inst     = _get_horror_level_instruction(horror_level)
    imi_rule       = IMI_KOWAI_RULES if genre == "意味がわかると怖い" else ""
    story_instruction = "記事の中に、関連する短編フィクションを1本（500字程度）埋め込むこと。" if include_story else ""

    article_type_desc = {
        "まとめ記事": "複数のエピソードや事例をまとめた読み物",
        "解説記事": "オカルト・陰謀論などを深掘り解説する読み物",
    }.get(article_type, article_type)

    prompt = f"""以下の条件でWeb記事を書け。

記事種類：{article_type}（{article_type_desc}）
ジャンル：{genre}（{genre_desc}）
ネタ：{idea}
目標文字数：約{char_count}字
{level_inst}
{story_instruction}

{ANTI_AI_RULES}
{policy}
{imi_rule}
- 見出しはMarkdown（##）で書く
- 読者を引き込む書き出しにする

必ず以下のフォーマットで出力すること：

【タイトル】
（ここにタイトルを1行で書く）

【本文】
（ここに記事本文を書く）"""

    raw = _call_claude(prompt, max_tokens=max_tokens)
    return _parse_title_and_body(raw)


def generate_blog_post(
    spot_name: str,
    spot_name_jp: str,
    region: str,
    char_count: int = 2000,
    x_safe: bool = False,
    style_hint: str = "",
) -> tuple[str, str]:
    """
    世界の心霊スポット専用ブログ記事生成。
    spot_name: 英語名, spot_name_jp: 日本語名, region: 国・地域
    Returns: (body, title)
    """
    policy     = X_POLICY_RULES if x_safe else ""
    max_tokens = min(8000, char_count * 2)
    display_name = spot_name_jp if spot_name_jp else spot_name

    prompt = f"""以下の世界の心霊スポットについてブログ記事を書け。

【心霊スポット情報】
英語名：{spot_name}
日本語名（またはカナ読み）：{display_name}
国・地域：{region}

【記事の要件】
- 目標文字数：約{char_count}字
- ブログ記事として読みやすいよう、見出し（##）で構成する
- 構成例：概要 → 歴史・背景 → 目撃情報・怪奇現象 → 現在の状況 → まとめ
- SEOを意識したタイトルにする（「世界最恐」「呪われた」「心霊体験」などのキーワードを含める）
- 事実ベースで書き、誇張しすぎず「怖さを想像させる」トーンにする
- 日本語で読者に伝わるよう、英語固有名詞にはカナ読みを添える

{ANTI_AI_RULES}
{policy}
{style_hint}

必ず以下のフォーマットで出力すること：

【タイトル】
（SEOを意識した魅力的なタイトルを1行で書く）

【本文】
（ブログ記事本文をMarkdown見出し付きで書く）"""

    raw = _call_claude(prompt, max_tokens=max_tokens)
    return _parse_title_and_body(raw)


# ── Phase 2：トレンドリサーチ ───────────────────

# APIキー不要のRSSフィード（媒体ごとに分類）
RSS_FEEDS = {
    "ニュース系": [
        ("NHKニュース", "https://www.nhk.or.jp/rss/news/cat0.xml"),
        ("NHK社会", "https://www.nhk.or.jp/rss/news/cat1.xml"),
        ("朝日新聞", "https://www.asahi.com/rss/asahi/newsheadlines.rdf"),
        ("読売新聞", "https://www.yomiuri.co.jp/feed/"),
        ("毎日新聞", "https://mainichi.jp/rss/etc/mainichi-flash.rss"),
        ("産経新聞", "https://www.sankei.com/rss/news/flash.xml"),
    ],
    "Yahoo!ニュース": [
        ("Yahoo!国内", "https://news.yahoo.co.jp/rss/topics/domestic.xml"),
        ("Yahoo!社会", "https://news.yahoo.co.jp/rss/topics/society.xml"),
        ("Yahoo!エンタメ", "https://news.yahoo.co.jp/rss/topics/entertainment.xml"),
        ("Yahoo!科学", "https://news.yahoo.co.jp/rss/topics/science.xml"),
        ("Yahoo!国際", "https://news.yahoo.co.jp/rss/topics/world.xml"),
    ],
    "ライブドア": [
        ("ライブドア 社会", "https://news.livedoor.com/topics/rss/societal.xml"),
        ("ライブドア 国内", "https://news.livedoor.com/topics/rss/domestic.xml"),
        ("ライブドア 海外", "https://news.livedoor.com/topics/rss/world.xml"),
        ("ライブドア エンタメ", "https://news.livedoor.com/topics/rss/entertainment.xml"),
        ("ライブドア スポーツ", "https://news.livedoor.com/topics/rss/sports.xml"),
    ],
    "テック・IT系": [
        ("ITmedia", "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml"),
        ("Gigazine", "https://gigazine.net/news/rss_2.0/"),
        ("TechCrunch Japan", "https://jp.techcrunch.com/feed/"),
        ("CNET Japan", "https://japan.cnet.com/rss/index.rdf"),
    ],
    "まとめ・バズ系": [
        ("はてなブックマーク 総合", "https://b.hatena.ne.jp/hotentry.rss"),
        ("はてなブックマーク 社会", "https://b.hatena.ne.jp/hotentry/social.rss"),
        ("はてなブックマーク 世の中", "https://b.hatena.ne.jp/hotentry/general.rss"),
        ("Togetter", "https://togetter.com/rss/index"),
    ],
    "オカルト・怪談系": [
        ("オカルトオンライン", "https://occult-online.net/feed/"),
        ("怖い話ブログ", "https://horror-story.jp/feed/"),
    ],
}


def fetch_trends(categories: list[str] = None) -> list[dict]:
    """RSSで今日のニュースを取得。失敗時はSerper API→ダミーの順でフォールバック。"""
    trends = _fetch_rss_trends(categories)
    if trends:
        return trends

    # RSSが全滅した場合はSerper APIを試みる
    load_dotenv(override=True)
    api_key = os.getenv("SERPER_API_KEY")
    if api_key:
        return _fetch_serper_trends(api_key)

    # 最終フォールバック：ダミー
    return [
        {"keyword": "AI技術の急速な進化", "summary": "人工知能が社会のあらゆる場面に浸透しつつある", "source": "ダミー"},
        {"keyword": "地震・自然災害の増加", "summary": "各地で地震や異常気象が頻発", "source": "ダミー"},
        {"keyword": "SNS上の集団行動", "summary": "SNSを通じた見知らぬ人々の繋がりが拡大", "source": "ダミー"},
        {"keyword": "廃墟・立入禁止エリア", "summary": "危険な場所への不法侵入が問題化", "source": "ダミー"},
        {"keyword": "孤立・孤独問題", "summary": "都市部での孤独死・孤立が過去最多水準", "source": "ダミー"},
    ]


def _fetch_rss_trends(categories: list[str] | None = None, per_feed: int = 4, total: int = 30) -> list[dict]:
    """指定カテゴリのRSSを取得。結果はTTLキャッシュに保存（5分）。"""
    target = categories or list(RSS_FEEDS.keys())
    cache_key = "rss:" + ",".join(sorted(target))

    cached = rss_cache.get(cache_key)
    if cached is not None:
        logger.debug(f"RSS cache hit: {cache_key}")
        return cached

    trends: list[dict] = []
    for cat in target:
        feeds = RSS_FEEDS.get(cat, [])
        cat_count = 0
        for name, url in feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:per_feed]:
                    title = str(entry.get("title", "")).strip()
                    if not title or len(title) < 3:
                        continue
                    summary = str(entry.get("summary", entry.get("description", "")))
                    summary = re.sub(r"<[^>]+>", "", summary)[:120]
                    item = {
                        "keyword": title,
                        "summary": summary,
                        "source": f"{cat}／{name}",
                    }
                    if validate_rss_entry(item):
                        trends.append(item)
                        cat_count += 1
                if cat_count >= per_feed * 2:
                    break
            except Exception as e:
                logger.warning(f"RSS fetch error [{name}]: {e}")
                continue
        if len(trends) >= total:
            break

    result = trends[:total]
    if result:
        rss_cache.set(cache_key, result)
        logger.info(f"RSS fetched: {len(result)}件 from {target}")
    return result


def get_rss_categories() -> list[str]:
    return list(RSS_FEEDS.keys())


def _fetch_serper_trends(api_key: str) -> list[dict]:
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    trends = []
    try:
        for q in ["日本 今日 話題 ニュース", "トレンド 最新 SNS"]:
            payload = {"q": q, "gl": "jp", "hl": "ja", "num": 6}
            resp = requests.post("https://google.serper.dev/search", json=payload, headers=headers, timeout=10)
            resp.raise_for_status()
            for item in resp.json().get("organic", [])[:4]:
                trends.append({
                    "keyword": item.get("title", ""),
                    "summary": item.get("snippet", ""),
                    "source": "Serper",
                })
        return trends[:10]
    except Exception:
        return []


def suggest_idea_from_trends(trends: list[dict], genre: str) -> list[dict]:
    """一般トレンドをこわ面白い切り口に変換してネタを提案する。リスト形式で返す。"""
    trend_text = "\n".join([f"- {t['keyword']}：{t['summary']}" for t in trends[:6]])
    prompt = f"""以下は今日の一般的なトレンド・ニュースだ。
これらを「{genre}」ジャンルのこわ面白い視点で読み替えて、SNS投稿ネタを3つ提案せよ。

【今日のトレンド】
{trend_text}

ルール：
- トレンドの話題を「実は怖い話」「都市伝説的に解釈」「裏側がある」風に変換する
- トレンドに直接言及せず、インスパイアされた独自ネタとして提案する
- 必ず以下のJSON形式のみで出力すること。説明文・前置き・コードブロック記号は不要

[
  {{"title": "ネタのタイトル", "description": "ネタの説明（1〜2文）"}},
  {{"title": "ネタのタイトル", "description": "ネタの説明（1〜2文）"}},
  {{"title": "ネタのタイトル", "description": "ネタの説明（1〜2文）"}}
]"""
    raw = _call_claude(prompt, max_tokens=500)
    try:
        # コードブロックが含まれていても除去してパース
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(cleaned)
    except Exception:
        # パース失敗時はテキストをそのままタイトルにして返す
        return [{"title": "提案（要確認）", "description": raw}]


# ── Phase 2：ハッシュタグ生成 ───────────────────

HASHTAG_BASE = {
    "都市伝説・未解決事件": ["#都市伝説", "#未解決事件", "#怖い話", "#ミステリー", "#都市伝説好きと繋がりたい"],
    "ホラー体験談・怪談": ["#怪談", "#ホラー", "#怖い話", "#心霊体験", "#怪談好きと繋がりたい"],
    "不思議・オカルト・陰謀論": ["#オカルト", "#陰謀論", "#不思議な話", "#超常現象", "#オカルト好きと繋がりたい"],
    "サイコ・ダークな人間ドラマ": ["#サイコパス", "#ダーク", "#人間ドラマ", "#怖い話", "#ミステリー"],
}

def generate_hashtags(content: str, genre: str) -> str:
    """コンテンツに合ったハッシュタグを生成する。"""
    base = HASHTAG_BASE.get(genre, ["#怖い話", "#ホラー", "#都市伝説"])
    prompt = f"""以下の投稿文に合うハッシュタグを5〜8個選んで出力せよ。

【投稿文】
{content[:300]}

【使えるベースタグ】
{' '.join(base)}

ルール：
- ハッシュタグだけを1行にスペース区切りで出力する
- コンテンツの内容に合った追加タグを2〜3個加えてよい
- 説明・解説は不要"""

    result = _call_claude(prompt, max_tokens=100)
    tags = [w for w in result.split() if w.startswith("#")]
    if not tags:
        tags = base[:5]
    filtered, removed = filter_hashtags(" ".join(tags))
    if removed:
        logger.info(f"Blacklisted hashtags removed: {removed}")
    return filtered or " ".join(base[:5])


# ── Phase 3：スタイル自動ローテーション ────────────

STYLE_ROTATION = [
    "会話風", "独り言・日記風", "ニュース・報告風", "スレッド連投風",
    "コメント欄風", "ランキング・リスト風", "問いかけ風", "途中で途切れる風",
]

def next_rotation_style(current_style: str) -> str:
    """現在のスタイルの次のスタイルを返す。"""
    try:
        idx = STYLE_ROTATION.index(current_style)
        return STYLE_ROTATION[(idx + 1) % len(STYLE_ROTATION)]
    except ValueError:
        return STYLE_ROTATION[0]


# ── Phase 3：シリーズネタ生成 ───────────────────

def generate_series_idea(template: str, n: int, genre: str, extra: str = "") -> str:
    """シリーズテンプレートから今回のネタ文字列を生成する。"""
    PREFS = [
        "北海道","青森","岩手","宮城","秋田","山形","福島","茨城","栃木","群馬",
        "埼玉","千葉","東京","神奈川","新潟","富山","石川","福井","山梨","長野",
        "岐阜","静岡","愛知","三重","滋賀","京都","大阪","兵庫","奈良","和歌山",
        "鳥取","島根","岡山","広島","山口","徳島","香川","愛媛","高知","福岡",
        "佐賀","長崎","熊本","大分","宮崎","鹿児島","沖縄",
    ]
    pref = PREFS[(n - 1) % 47] if "{pref}" in template else ""
    idea = template.format(n=n, pref=pref)
    return idea + (f"（{extra}）" if extra else "")


# ── Phase 4：伸びパターン学習 ───────────────────

def build_learning_hint(top_patterns: list[dict]) -> str:
    """パフォーマンスデータからプロンプトに追加するヒントを生成する。"""
    if not top_patterns:
        return ""
    lines = ["【過去データから学んだ伸びやすいパターン】"]
    for p in top_patterns[:3]:
        lines.append(f"- ジャンル「{p['genre']}」×スタイル「{p['style']}」：平均エンゲージ {p['avg_engage']:.1f}")
    lines.append("上記パターンを参考に、より引き込む文章を書け。")
    return "\n".join(lines)


def generate_post_with_learning(genre: str, style: str, idea: str, char_count: int,
                                 x_safe: bool, top_patterns: list[dict],
                                 style_hint: str = "", horror_level: int = 3) -> str:
    hint       = build_learning_hint(top_patterns)
    genre_desc = GENRE_DESCRIPTIONS.get(genre, genre)
    style_desc = STYLE_DESCRIPTIONS.get(style, style)
    policy     = X_POLICY_RULES if x_safe else ""
    level_inst = _get_horror_level_instruction(horror_level)
    imi_rule   = IMI_KOWAI_RULES if genre == "意味がわかると怖い" else ""

    prompt = f"""以下の条件でSNS投稿文を書け。

ジャンル：{genre}（{genre_desc}）
スタイル：{style}（{style_desc}）
ネタ：{idea}
目標文字数：約{char_count}字
{level_inst}

{ANTI_AI_RULES}
{policy}
{hint}
{style_hint}
{imi_rule}

投稿文だけを出力すること。説明・前置き・タイトルは不要。"""
    return _call_claude(prompt, max_tokens=1000)


# ── Phase 4：A/Bテスト生成 ──────────────────────

def generate_ab_pair(genre: str, idea: str, style_a: str, style_b: str,
                      char_count: int, x_safe: bool) -> tuple[str, str]:
    content_a = generate_post(genre, style_a, idea, char_count, x_safe)
    content_b = generate_post(genre, style_b, idea, char_count, x_safe)
    return content_a, content_b


# ── Phase 4：ハッシュタグ最適化（パフォーマンスデータ反映）──

def generate_optimized_hashtags(content: str, genre: str, top_tags: list[str]) -> str:
    """過去パフォーマンスの良いタグを優先してハッシュタグを生成。"""
    base = HASHTAG_BASE.get(genre, ["#怖い話", "#ホラー", "#都市伝説"])
    all_tags = list(dict.fromkeys(top_tags + base))  # 重複排除・順序保持
    prompt = f"""以下の投稿文に合うハッシュタグを5〜8個選んで出力せよ。

【投稿文】
{content[:300]}

【優先タグ（過去のパフォーマンスが良いもの）】
{' '.join(all_tags[:15])}

ルール：
- ハッシュタグだけを1行にスペース区切りで出力する
- 優先タグから選びつつ、内容に合ったものを追加してよい
- 説明不要"""
    result = _call_claude(prompt, max_tokens=100)
    tags = [w for w in result.split() if w.startswith("#")]
    return " ".join(tags) if tags else " ".join(base[:5])


# ── Phase 5：日付連動ネタ ─────────────────────────

def generate_date_linked_idea(genre: str) -> str:
    """今日の日付に関連する「○○年前の今日」ネタを生成する。"""
    from datetime import date
    today = date.today()
    prompt = f"""今日は{today.month}月{today.day}日だ。
この日付に実際に起きた出来事・事件・出来事の中から、「{genre}」ジャンルのこわ面白いコンテンツに使えそうなものを1つ選んで提案せよ。

出力形式：
タイトル：○○年前の今日、〇〇が起きた
説明：（1〜2文で内容を説明）

実在する出来事を参考にして、独自のホラー視点で解釈してよい。
タイトルと説明だけ出力すること。"""
    return _call_claude(prompt, max_tokens=200)


# ── Phase 5：リサイクル・リライト ────────────────

def rewrite_content(original: str, style: str, genre: str, x_safe: bool) -> str:
    """過去の人気コンテンツを別スタイルでリライトする。"""
    style_desc = STYLE_DESCRIPTIONS.get(style, style)
    policy = X_POLICY_RULES if x_safe else ""
    prompt = f"""以下の投稿を「{style}」スタイルでリライトせよ。

【元の投稿】
{original}

【リライト後のスタイル】
{style}：{style_desc}

{ANTI_AI_RULES}
{policy}

元の「怖さ・オチ」は維持しつつ、スタイルを完全に変えること。
リライト後の文章だけを出力すること。"""
    return _call_claude(prompt, max_tokens=1000)


# ── Phase 5：収益化 ──────────────────────────────

def add_monetization(content: str, content_type: str, affiliate_url: str = "", note_url: str = "") -> str:
    """コンテンツにアフィリエイトリンク・note誘導文を付与する。"""
    additions = []
    if note_url:
        prompt_note = f"""以下の投稿の末尾に付ける「続きはnoteで」誘導文を1行で書け。
自然に繋がるように。URLは「{note_url}」を使う。
誘導文だけ出力すること。

【投稿】
{content[:200]}"""
        note_text = _call_claude(prompt_note, max_tokens=80)
        additions.append(note_text.strip())

    if affiliate_url:
        prompt_aff = f"""以下の投稿の末尾に付けるアフィリエイト商品への自然な誘導文を1行で書け。
ホラー・オカルト系の本や体験グッズへの誘導として自然に。URLは「{affiliate_url}」を使う。
誘導文だけ出力すること。

【投稿】
{content[:200]}"""
        aff_text = _call_claude(prompt_aff, max_tokens=80)
        additions.append(aff_text.strip())

    if additions:
        return content + "\n\n" + "\n".join(additions)
    return content


# ── Phase 5：DALL-E サムネ生成 ───────────────────

def generate_thumbnail(content: str, genre: str) -> bytes | None:
    """DALL-E 3でサムネイル画像を生成する。OpenAI APIキーが必要。"""
    load_dotenv(override=True)
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    genre_style = {
        "都市伝説・未解決事件": "dark mysterious abandoned place, fog, eerie atmosphere",
        "ホラー体験談・怪談": "Japanese horror, ghost, haunted, dark corridor",
        "不思議・オカルト・陰謀論": "occult symbols, dark conspiracy, ominous shadow",
        "サイコ・ダークな人間ドラマ": "psychological thriller, dark silhouette, noir style",
    }.get(genre, "dark horror atmosphere")

    prompt_img = f"""Dark horror thumbnail image for Japanese SNS post.
Style: {genre_style}
Mood: extremely eerie, unsettling, cinematic
No text, no letters, no words in the image.
High contrast, dark background, single dramatic element."""

    try:
        resp = client.images.generate(
            model="dall-e-3",
            prompt=prompt_img,
            size="1024x1024",
            quality="standard",
            n=1,
        )
        img_url = resp.data[0].url
        img_resp = requests.get(img_url, timeout=30)
        return img_resp.content
    except Exception:
        return None


# ── 感情・緊張感スコア（textblob代替・日本語対応）────

HORROR_KEYWORDS = ["死", "血", "闇", "恐怖", "震え", "消えた", "叫び", "冷たい", "気づいた",
    "振り返ると", "声", "影", "息", "逃げ", "追いかけ", "怖", "鳥肌", "ゾワ", "異常",
    "狂", "幽霊", "呪い", "殺", "行方不明", "失踪", "奇妙", "不気味", "おかしい", "異変"]

TENSION_KEYWORDS = ["突然", "気づいた", "振り返ると", "そのとき", "しかし", "ところが",
    "なのに", "ふと", "気がすると", "いつの間にか", "信じられない", "まさか"]

def calc_horror_score(text: str) -> dict:
    """恐怖・緊張感スコアを算出する。"""
    if not text:
        return {"horror": 0, "tension": 0, "total": 0}
    horror  = min(100, sum(3 for w in HORROR_KEYWORDS  if w in text))
    tension = min(100, sum(5 for w in TENSION_KEYWORDS if w in text))
    total   = min(100, int((horror * 0.6 + tension * 0.4)))
    return {"horror": horror, "tension": tension, "total": total}


# ── バズり予測スコア ──────────────────────────────

def predict_viral_score(content: str, genre: str, style: str, top_patterns: list[dict]) -> int:
    """過去データ＋コンテンツ分析でバズり予測スコア(0-100)を返す。"""
    score = 50

    # 過去パフォーマンスとのパターン一致
    for p in top_patterns:
        if p.get("genre") == genre and p.get("style") == style:
            avg = p.get("avg_engage", 0)
            score += min(20, int(avg / 5))
            break

    # コンテンツ特徴
    horror = calc_horror_score(content)
    score += int(horror["total"] * 0.2)

    # 文字数（短投稿は150-300字がバズりやすい）
    c = len(content)
    if 150 <= c <= 300:
        score += 10
    elif 300 < c <= 500:
        score += 5

    # スレッド連投・問いかけはエンゲージ高い傾向
    if style in ["スレッド連投風", "問いかけ風", "途中で途切れる風"]:
        score += 8

    return min(100, max(0, score))


# ── キャッチコピー生成 ────────────────────────────

def generate_catchcopy(content: str, genre: str) -> list[str]:
    """投稿用キャッチコピー（フック）を3案生成する。"""
    prompt = f"""以下の投稿文に対して、SNSでクリックしたくなるキャッチコピーを3案考えろ。

【投稿文】
{content[:400]}

ジャンル：{genre}

ルール：
- 20字以内
- 「続きが気になる」「怖すぎる」「知らなきゃよかった」系の引き
- 絵文字を1〜2個使ってよい
- 番号付きリストで3案出力すること
- 各案は1行で完結させること"""
    raw = _call_claude(prompt, max_tokens=200)
    lines = [l.strip() for l in raw.splitlines() if l.strip() and any(c.isdigit() for c in l[:3])]
    # 番号を除去
    import re
    copies = [re.sub(r"^\d+[\.\)．\s]+", "", l).strip() for l in lines[:3]]
    return copies if copies else [raw.strip()]


# ── タイトル複数候補 ──────────────────────────────

def generate_title_candidates(content: str, content_type: str) -> list[str]:
    """タイトル候補を5案生成する。"""
    type_hint = {
        "novel":   "ホラー小説・短編のタイトル。文学的でも可。",
        "article": "Webメディアの記事タイトル。SEOを意識してもよい。",
    }.get(content_type, "SNS投稿のタイトル")

    prompt = f"""以下のコンテンツに合うタイトルを5案考えろ。

【コンテンツ冒頭】
{content[:500]}

タイトルの種類：{type_hint}

ルール：
- 各タイトルは1行・30字以内
- 読者が「読みたい」と思う引き
- バリエーションを持たせる（疑問形・断言・数字・感情など）
- 番号付きリストで出力すること"""
    raw = _call_claude(prompt, max_tokens=300)
    import re
    lines = [l.strip() for l in raw.splitlines() if l.strip() and any(c.isdigit() for c in l[:3])]
    titles = [re.sub(r"^\d+[\.\)．\s]+", "", l).strip() for l in lines[:5]]
    return titles if titles else [raw.strip()]


# ── Pillowテキストサムネ生成（APIキー不要）──────────

def generate_text_thumbnail(title: str, genre: str) -> bytes:
    """Pillowでテキストベースのサムネイル画像を生成する（DALL-E不要・クロスプラットフォーム）。"""
    from PIL import Image, ImageDraw, ImageFont
    from pathlib import Path
    import io, textwrap

    GENRE_COLORS = {
        "都市伝説・未解決事件": ("#1a0a0a", "#cc3333"),
        "ホラー体験談・怪談":   ("#0a0a1a", "#6633cc"),
        "不思議・オカルト・陰謀論": ("#0a1a0a", "#336633"),
        "サイコ・ダークな人間ドラマ": ("#1a1a0a", "#666600"),
    }
    bg_color, accent = GENRE_COLORS.get(genre, ("#0d0d0d", "#cc3333"))

    img = Image.new("RGB", (1200, 630), color=bg_color)
    draw = ImageDraw.Draw(img)

    # グリッドライン（不気味な演出）
    for i in range(0, 1200, 80):
        draw.line([(i, 0), (i, 630)], fill=(30, 30, 30), width=1)
    for i in range(0, 630, 80):
        draw.line([(0, i), (1200, i)], fill=(30, 30, 30), width=1)

    # アクセントライン
    draw.rectangle([(0, 0), (1200, 8)], fill=accent)
    draw.rectangle([(0, 622), (1200, 630)], fill=accent)
    draw.rectangle([(0, 0), (8, 630)], fill=accent)
    draw.rectangle([(1192, 0), (1200, 630)], fill=accent)

    # テキスト描画（システムフォント使用）
    # クロスプラットフォーム対応フォント候補
    font_candidates = [
        # macOS
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        # Linux
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        # Windows
        "C:/Windows/Fonts/msgothic.ttc",
        "C:/Windows/Fonts/meiryo.ttc",
    ]
    font_large = None
    font_small = None
    for fp in font_candidates:
        if Path(fp).exists():
            try:
                font_large = ImageFont.truetype(fp, 72)
                font_small = ImageFont.truetype(fp, 36)
                break
            except Exception:
                continue
    if font_large is None:
        font_large = ImageFont.load_default()
        font_small = font_large

    # タイトルを折り返し
    wrapped = textwrap.fill(title, width=16)
    lines = wrapped.split("\n")
    total_h = len(lines) * 90
    y = (630 - total_h) // 2 - 20

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font_large)
        w = bbox[2] - bbox[0]
        draw.text(((1200 - w) // 2 + 2, y + 2), line, fill=(0, 0, 0), font=font_large)  # 影
        draw.text(((1200 - w) // 2, y), line, fill="#ffffff", font=font_large)
        y += 90

    # ジャンルラベル
    draw.text((60, 560), f"#{genre}", fill=accent, font=font_small)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── 一括生成 ─────────────────────────────────────

def batch_generate_posts(genre: str, idea: str, styles: list[str],
                          char_count: int, x_safe: bool) -> list[dict]:
    """複数スタイルで一括生成する。"""
    results = []
    for style in styles:
        try:
            content = generate_post(genre, style, idea, char_count, x_safe)
            results.append({"style": style, "content": content,
                            "score": 0.0})  # スコアはapp側で計算
        except Exception as e:
            results.append({"style": style, "content": f"生成エラー: {e}", "score": 0.0})
    return results
