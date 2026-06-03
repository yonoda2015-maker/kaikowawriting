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
    # ── ホラー・ミステリ系 ──────────────────────────
    "乙一": "【ホラー】淡々とした短文で日常の違和感を積み重ね、気づいたら怖い状況を作る。感情を排した冷静な語り口。代表作：ZOO、GOTH",
    "貴志祐介": "【ホラー】科学・医学的な説明で超自然をリアルに描く。論理的に追い詰められる恐怖。代表作：黒い家、天使の囀り",
    "綾辻行人": "【ミステリ】叙述トリックの名手。「実は全部嘘だった」系の逆転構造。閉鎖空間の恐怖。代表作：十角館の殺人、Another",
    "道尾秀介": "【ミステリ】複数視点の操作で読者を騙す。予測不能なラストで価値観を覆す。代表作：向日葵の咲かない夏",
    "湊かなえ": "【イヤミス】複数の語り手が「自分は正しい」と主張する多視点構成。読後の後味の悪さが特徴。代表作：告白",
    "辻村深月": "【ミステリ】子ども・若者の視点で描く孤独と恐怖。精巧な伏線回収。代表作：かがみの孤城",
    "恩田陸": "【幻想】日常が突然異界に変わる感覚。音楽・光・色彩で恐怖と美を同時に表現。代表作：夜のピクニック",
    "住野よる": "【青春】口語体・テンポのよい会話。等身大の若者の喪失と後悔を描く。代表作：君の膵臓をたべたい",

    # ── コメディ・おも怖い・笑える系 ──────────────────
    "星新一": "【SF・ショートショート】超短編の名手。オチが完璧に決まるサプライズエンド。ブラックユーモアと皮肉。最後の一行で世界が変わる構造。代表作：ボッコちゃん、悪魔のいる天国",
    "筒井康隆": "【SF・ブラックコメディ】ぶっ飛んだ設定と毒舌ユーモア。社会の不条理を笑い飛ばしながら描く。笑いと狂気が同居。代表作：時をかける少女、旅のラゴス",
    "伊坂幸太郎": "【エンタメ・ウィット】軽妙な会話と伏線の美しい回収。ユーモラスなキャラが深刻な状況に巻き込まれる。テンポよく読める。代表作：重力ピエロ、ゴールデンスランバー",
    "東野圭吾": "【ミステリ・エンタメ】誰でも読みやすい明快な文体。感情移入できるキャラクターで重いテーマを扱う。読後に温かさと恐怖が残る。代表作：容疑者Xの献身、ナミヤ雑貨店の奇蹟",
    "朝井リョウ": "【青春・リアル】若者の本音をえぐる直球表現。痛いほどリアルな自意識と承認欲求の描写。SNS時代の闇。代表作：何者、桐島、部活やめるってよ",
    "又吉直樹": "【純文学・自虐】お笑い芸人出身の純文学。自虐的なユーモアと文学的な美しさの融合。孤独と滑稽の同居。代表作：火花、劇場",
    "西加奈子": "【ユーモア・人間愛】温かみのあるユーモアと人間の愛おしさ。笑いながら泣ける文体。関西弁を混ぜたリズム感。代表作：サラバ、きいろいゾウ",
    "羽田圭介": "【現代・毒】毒のあるユーモアで現代社会の矛盾を描く。直球でえぐい表現。読後に笑えない笑いが残る。代表作：スクラップ・アンド・ビルド、黒冷水",
    "村上春樹": "【文学・幻想】独特のリズムと比喩の天才。日常に幻想が溶け込む不思議な感覚。クールでユーモラスな語り口。代表作：ノルウェイの森、1Q84",
    "池井戸潤": "【企業・痛快】組織の不条理に一人が立ち向かう爽快感。テンポのよい展開とどんでん返し。正義が勝つカタルシス。代表作：半沢直樹、下町ロケット",
    "百田尚樹": "【エンタメ・強烈】強烈なキャラクターと引力のある文体。賛否両論を巻き起こす過激な表現と熱量。代表作：永遠の0、海賊とよばれた男",
    "有川浩（有川ひろ）": "【恋愛・ミリタリー】恋愛と非日常の融合。ライトで読みやすいのに感情が揺さぶられる。男女のリアルなやり取り。代表作：図書館戦争、三匹のおっさん",
    "村田沙耶香": "【ホラー・不条理】「普通」の定義を問い直す不気味な設定。日常が狂気に変わる過程。読後に世界の見え方が変わる。代表作：コンビニ人間、消滅世界",
    "川上未映子": "【文学・ユーモア】関西弁の独特リズムと詩的な表現。コメカルで文学的な奇妙な感覚。代表作：乳と卵、ヘヴン",
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
