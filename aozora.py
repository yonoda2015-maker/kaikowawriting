import re
import io
import zipfile
import urllib.request
from anthropic import Anthropic
import os
from dotenv import load_dotenv

load_dotenv(override=True)

# ホラー・怪談・怪奇系の名作家と代表作
HORROR_AUTHORS = {
    "江戸川乱歩": [
        ("人間椅子",       "001779", "56641_ruby_59384.zip"),
        ("押絵と旅する男", "001779", "56782_ruby_59743.zip"),
        ("赤い部屋",       "001779", "56818_ruby_59755.zip"),
    ],
    "夢野久作": [
        ("瓶詰の地獄",          "000096", "2381_ruby_25784.zip"),
        ("ドグラ・マグラ（冒頭）", "000096", "2013_ruby_26188.zip"),
    ],
    "芥川龍之介": [
        ("羅生門",  "000879", "127_ruby_150.zip"),
        ("藪の中",  "000879", "35_ruby_113.zip"),
        ("地獄変",  "000879", "1241_ruby_49622.zip"),
    ],
    "小泉八雲": [
        ("怪談・耳なし芳一", "000258", "42289_ruby_16851.zip"),
        ("怪談・雪女",       "000258", "42290_ruby_16852.zip"),
    ],
    "泉鏡花": [
        ("高野聖",   "000050", "50935_ruby_50774.zip"),
        ("夜叉ヶ池", "000050", "45630_ruby_23610.zip"),
    ],
    "太宰治": [
        ("人間失格", "000035", "301_ruby_5915.zip"),
        ("斜陽",     "000035", "1565_ruby_8220.zip"),
    ],
    "谷崎潤一郎": [
        ("刺青",   "001383", "56641_ruby_59456.zip"),
        ("春琴抄", "001383", "56866_ruby_58168.zip"),
    ],
    "坂口安吾": [
        ("桜の森の満開の下", "001095", "42618_ruby_21052.zip"),
        ("続堕落論",         "001095", "42619_ruby_21408.zip"),
    ],
    "中島敦": [
        ("山月記", "000119", "623_ruby_18352.zip"),
    ],
    "幸田露伴": [
        ("五重塔", "000051", "50351_ruby_36038.zip"),
    ],
}

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; KowamoshiroBot/1.0)"}


def _fetch_zip_text(author_id: str, zip_name: str) -> str | None:
    """青空文庫のZIPをダウンロードしてテキストを返す。"""
    url = f"https://www.aozora.gr.jp/cards/{author_id}/files/{zip_name}"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for name in zf.namelist():
                if name.endswith(".txt"):
                    raw = zf.read(name)
                    try:
                        return raw.decode("shift_jis")
                    except Exception:
                        return raw.decode("utf-8", errors="replace")
    except Exception:
        return None


def _clean_aozora_text(text: str, max_chars: int = 3000) -> str:
    """青空文庫テキストのルビ・注釈・ヘッダーを除去してプレーンテキストにする。"""
    # 区切り線（ハイフン・全角ハイフン10文字以上）以降の本文を取得
    parts = re.split(r"[-－ー]{10,}", text)
    # 区切り線が複数ある場合、最後の区切り以降が本文
    if len(parts) >= 2:
        text = parts[-1]
    # ルビ記号を除去: 《》
    text = re.sub(r"《[^》]*》", "", text)
    # ルビ開始記号を除去: ｜
    text = re.sub(r"｜", "", text)
    # 入力者注を除去: ［＃...］
    text = re.sub(r"［＃[^］]*］", "", text)
    # ※記号を除去
    text = re.sub(r"※[^\n]*", "", text)
    # 空白行の連続を整理
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    return text[:max_chars]


def fetch_author_samples(author_name: str) -> list[dict]:
    """指定作家の作品テキストサンプルを取得する。"""
    works = HORROR_AUTHORS.get(author_name, [])
    samples = []
    for title, author_id, zip_name in works:
        raw = _fetch_zip_text(author_id, zip_name)
        if raw:
            cleaned = _clean_aozora_text(raw, max_chars=2000)
            samples.append({"title": title, "text": cleaned})
    return samples


# 現代作家（著作権あり・Claude知識ベースで文体学習）
MODERN_AUTHORS = {
    "乙一": "ホラー・ミステリ作家。白乙一（純文学寄り）と黒乙一（残酷描写）の両面を持つ。短文を積み重ねる独特のリズム、感情を排した淡々とした語り口で恐怖を演出。日常の違和感を丁寧に描写して読者を追い詰める手法が特徴。代表作：ZOO、GOTH、夏と花火と私の死体",
    "貴志祐介": "ホラー・サスペンス作家。科学的・論理的な説明で超自然現象をリアルに描く。緻密な伏線と圧倒的な恐怖描写。読者を徐々に追い詰めるペース配分が巧み。代表作：黒い家、天使の囀り、新世界より",
    "綾辻行人": "本格ミステリ・ホラー作家。館シリーズで有名。論理的なトリックと不気味な雰囲気の融合。叙述トリックを得意とし、読者の先入観を逆手に取る。代表作：十角館の殺人、Another",
    "道尾秀介": "ミステリ・ホラー作家。日常の中に潜む闇を描く。視点の巧みな操作と予測不能なラストが特徴。読後感に強い余韻を残す。代表作：向日葵の咲かない夏、カラスの親指",
    "住野よる": "現代文学。日常系の文体で非日常を描く。読みやすい口語体と独特のセリフ回し。感情の揺れを丁寧に描写。代表作：君の膵臓をたべたい、また同じ夢を見ていた",
    "湊かなえ": "イヤミス女王。複数の視点から同じ事件を描く多視点構成。登場人物の歪んだ内面を赤裸々に描写。読後に強い後味の悪さを残す。代表作：告白、往復書簡、少女",
    "辻村深月": "ミステリ・ホラー。子どもの視点で描く恐怖と成長。繊細な心理描写と意外な真相。伏線の張り方が精巧。代表作：かがみの孤城、ツナグ、スロウハイツの神様",
    "恩田陸": "ホラー・ファンタジー・ミステリの融合。幻想的な雰囲気と緻密な構成。日常と非日常の境界を曖昧にする描写が特徴。代表作：夜のピクニック、蜂蜜と遠雷、ユージニア",
}


def get_available_authors() -> list[str]:
    return list(HORROR_AUTHORS.keys())


def get_modern_authors() -> list[str]:
    return list(MODERN_AUTHORS.keys())


def analyze_modern_style(author_name: str) -> str:
    """現代作家の文体をClaudeの知識ベースで分析する（著作権フリー）。"""
    load_dotenv(override=True)
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return ""

    author_info = MODERN_AUTHORS.get(author_name, "")
    prompt = f"""現代日本の作家「{author_name}」の文体・スタイルを分析せよ。

【作家情報】
{author_info}

この作家の文体をSNS投稿・ホラー小説の生成に活用できる形で詳細に分析し、以下を箇条書きで出力せよ：

1. 文の長さ・リズム（短文多用か、長文か、テンポの特徴）
2. 語り口・視点（一人称・三人称・多視点など）
3. 感情表現の方法（直接的か間接的か、どう読者に伝えるか）
4. 恐怖・不気味さ・緊張感の演出技法（具体的な手法）
5. 特徴的な語彙・表現パターン・口癖
6. 【重要】このスタイルで文章を書くための具体的な指示文（プロンプトとして使える形で、5〜8項目）

分析結果と指示文だけを出力すること。著作権のある文章は引用しないこと。"""

    client = Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def analyze_style(author_name: str, samples: list[dict]) -> str:
    """Claudeにサンプルテキストを渡して文体特徴を分析させる。"""
    load_dotenv(override=True)
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key or not samples:
        return ""

    combined = "\n\n---\n\n".join([f"【{s['title']}】\n{s['text']}" for s in samples[:2]])

    prompt = f"""以下は{author_name}の小説の冒頭部分だ。
この作家の文体の特徴を、SNS投稿・ホラー小説の生成に活用できる形で分析せよ。

【テキスト】
{combined[:3000]}

以下の観点で分析し、箇条書きで出力せよ：
1. 文の長さ・リズム（短文多用か、長文か）
2. 語り口（一人称・三人称・神の視点など）
3. 感情表現の方法（直接的か間接的か）
4. 恐怖・不気味さの演出技法
5. 特徴的な語彙・表現パターン
6. このスタイルを真似るための具体的な指示（プロンプトに使える形で）

分析結果と「このスタイルで書くための指示文」だけを出力すること。"""

    client = Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def build_style_prompt(style_analysis: str) -> str:
    """分析結果をプロンプトに組み込める形に整形する。"""
    if not style_analysis:
        return ""
    return f"""【文体参考（青空文庫より学習）】
{style_analysis}

上記の文体特徴を参考にしながら、現代語で読みやすく書くこと。
古語・文語体は使わず、リズムや演出技法だけを取り入れること。
"""
