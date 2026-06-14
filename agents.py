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
    "面白くて怖い（おも怖い）": "笑えるのに怖い・怖いのに笑える。コメディとホラーの融合",
    "王道ホラー（心霊）": "五感の異常・日常の侵食。怪異の姿を見せず恐怖を醸成する王道心霊",
    "胸糞・ヒトコワ": "幽霊なし。人間の執着・狂気・善意を装う悪意。救いのない後味の悪さ",
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

# おも怖いジャンル専用ルール
OMO_KOWAI_RULES = """
【面白くて怖い（おも怖い）話のルール】
- 最初は完全にコメディ・ギャグ・笑える展開として書く
- 読者が「面白い話だな」と思って読み進める
- 途中か最後に「ゾワッとする恐怖」を一発ぶち込む
- 笑いと恐怖が同時に来る「おも怖い」を目指す
- コメディのテンポ・ボケとツッコミ・日常系の軽さを維持する
- 恐怖の部分は説明せず、一文でズドンと落とす
- 典型的な構造例：
  ・「ギャグっぽい状況が実は恐ろしい現実だった」
  ・「笑えるやり取りの相手が存在しない何かだった」
  ・「おかしな日常の「おかしさ」の正体が判明して背筋が凍る」
  ・「面白い体験談かと思ったら最後の一文で全てが変わる」
- 文体は軽く・テンポよく・口語的に書く
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
- 「実は」「なんと」「驚くことに」「まとめると」「つまり」「でしょう」「かもしれません」は一切使わない（品質スコアで大幅減点される）
- 綺麗にまとめない。オチは説明せずに感じさせる
- 実話風の語り口を徹底する
- 起承転結＋最後にゾワッとするオチを必ず入れる
- 文章を美化しない
"""

# 品質スコア（app.pyのcalc_quality_score）で高得点を取るための執筆ガイド。
# スコアは「1文の平均長15〜50字」「不気味な語彙の密度」「AIっぽい言い回しの不在」を見ているため、
# 生成段階でこれを満たす文章にしておくと再生成の手戻りが減る。
QUALITY_BOOST_RULES = """
【高品質スコアを取るための文章作法】
- 1文を15〜50字程度に保つ。だらだら長い一文や、極端に短い一文の連続を避ける
- 句点（。）でこまめに文を区切り、リズムを作る
- 文章全体に「死」「消えた」「気づいた」「振り返ると」「声」「影」「血」「冷たい」「震」「息」のような
  感覚や気配を表す語を自然に複数回散りばめる（無理に詰め込まず、情景描写の中で使う）
- 説明的な「〜だと思う」ではなく「〜だった」と言い切ることでリズムと不気味さを両立させる
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


def _parse_article_with_candidates(raw: str) -> tuple[str, str, list[str]]:
    """記事専用パーサー。【タイトル案】【タイトル】【本文】を分離する。
    Returns: (body, title, title_candidates)
    """
    import re
    # タイトル案を抽出（案1: / 案2: / 案3: 形式）
    candidates_block = re.search(r"【タイトル案】\s*\n([\s\S]+?)(?=【タイトル】)", raw)
    candidates: list[str] = []
    if candidates_block:
        for line in candidates_block.group(1).splitlines():
            m = re.match(r"案\d+[：:]\s*(.+)", line.strip())
            if m:
                candidates.append(m.group(1).strip())
    body, title = _parse_title_and_body(raw)
    return body, title, candidates


HORROR_LEVEL_INSTRUCTIONS = {
    1: "怖さレベル1（じんわり不気味）: 読後にわずかな違和感が残る程度。直接的な恐怖描写なし。",
    2: "怖さレベル2（ちょっと怖い）: 不気味な雰囲気・奇妙な出来事がある。直接的な恐怖は少ない。",
    3: "怖さレベル3（普通に怖い）: 明確な怖い要素がある。夜に一人で読むと怖いくらい。",
    4: "怖さレベル4（かなり怖い）: 強い恐怖・衝撃・背筋が凍るシーンがある。",
    5: "怖さレベル5（トラウマ級）: 読んだ後しばらく頭から離れない。最大限の恐怖を描け。",
}


def _get_horror_level_instruction(horror_level: int) -> str:
    return HORROR_LEVEL_INSTRUCTIONS.get(horror_level, "")


def _research_idea(idea: str, genre: str, content_type: str = "投稿") -> str:
    """
    書き出す前の下調べ。登場人物・場所・時系列など、文章全体で
    一貫させるべき設定をメモとして整理する。これを執筆プロンプトに
    渡すことで、後段の整合性チェックの基準にもなる。
    """
    prompt = f"""これから「{content_type}」を書く。本文を書く前の下調べとして、
次のネタについて整理せよ。

ネタ：{idea}
ジャンル：{genre}

以下の項目を簡潔に箇条書きで整理せよ（本文は書かないこと）：
- 登場人物・場所・組織名など、文章に出てくる固有名詞とその設定
- 時系列（いつ、どんな順番で何が起きるか）
- ジャンル的に外せない要素、矛盾が起きやすいポイント
- 実話風に見せるために抑えておくべきリアリティのディテール（年代・地名・状況など）

下調べメモだけを出力すること。説明や前置きは不要。"""
    try:
        return _call_claude(prompt, max_tokens=600)
    except Exception as e:
        logger.warning(f"下調べ生成に失敗（スキップして続行）: {e}")
        return ""


def _consistency_check(text: str, research_memo: str, content_type: str = "投稿") -> str:
    """
    下調べメモと本文を照らし合わせ、名前・時系列・設定の矛盾を修正する。
    矛盾がなければ本文をそのまま返す。
    """
    if not research_memo:
        return text

    prompt = f"""以下は「{content_type}」の本文と、執筆前に作成した下調べメモだ。
本文を下調べメモと照らし合わせ、矛盾点があれば修正した最終版を出力せよ。

【下調べメモ】
{research_memo}

【本文】
{text}

チェック項目：
- 登場人物の名前・年齢・関係性が文章全体で一貫しているか
- 場所・時間・時系列に矛盾がないか
- 途中で設定が変わっていないか
- 文体・スタイルが一貫しているか

矛盾がなければ本文をそのまま、矛盾があれば修正済みの本文を出力すること。
説明・前置き・チェック結果のコメントは一切不要。本文だけを出力すること。"""

    try:
        return _call_claude(prompt, max_tokens=max(1200, len(text) * 2))
    except Exception as e:
        logger.warning(f"整合性チェックに失敗（元の本文を使用）: {e}")
        return text


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
    imi_rule   = IMI_KOWAI_RULES if genre == "意味がわかると怖い" else (OMO_KOWAI_RULES if genre == "面白くて怖い（おも怖い）" else "")

    # 書き出す前に下調べを行い、設定の一貫性の土台を作る
    research_memo = _research_idea(idea, genre, content_type="投稿")
    memo_block = f"\n【下調べメモ（これを踏まえて矛盾なく書くこと）】\n{research_memo}\n" if research_memo else ""

    prompt = f"""以下の条件でSNS投稿文を書け。

ジャンル：{genre}（{genre_desc}）
スタイル：{style}（{style_desc}）
ネタ：{idea}
目標文字数：約{char_count}字
{level_inst}
{memo_block}
{ANTI_AI_RULES}
{QUALITY_BOOST_RULES}
{policy}
{imi_rule}
投稿文だけを出力すること。説明・前置き・タイトルは不要。"""

    draft = _call_claude(prompt, max_tokens=1000)
    # 下調べメモと照らし合わせて矛盾を修正
    return _consistency_check(draft, research_memo, content_type="投稿")


# 小説生成でSEOを意識させるためのガイド
# X記事・noteへの掲載が前提だが、X記事はGoogle検索結果にも表示されるため、
# 検索エンジン経由の流入も意識したタイトル・書き出しが必要になった。
NOVEL_SEO_RULES = """
【Google検索・流入を意識したタイトル・書き出し】
※ X（旧Twitter）の記事はGoogleの検索結果に表示されるため、SNS内だけでなく
　検索エンジン経由でたどり着く読者にも刺さるタイトル・書き出しにすること。
- タイトルは検索結果の見出しとして表示される前提で、検索されやすいキーワード
  （地名・職業・関係性・「実話」「体験談」「怖い話」など）をできるだけ前方に含めつつ、
  内容の核心を明かしすぎない「続きが気になる」具体性（数字・固有名詞・状況）を入れる
- 書き出しの2〜3文は検索結果のスニペットとして抜粋される可能性があるため、
  「どんな話か」「なぜ読むべきか」が一目で伝わるように書き、検索や見出しから来た読者を逃さない
- 同じ言葉や表現を繰り返しすぎず、関連語・言い換えを使って単調さを避ける（不自然なキーワードの詰め込みは避ける）
- 章や場面の切れ目がある場合は、次が気になる引きで終える（離脱防止・回遊率を意識）
"""


def generate_novel(genre: str, idea: str, char_count: int = 3000,
                   x_safe: bool = False, style_hint: str = "",
                   horror_level: int = 3) -> tuple[str, str]:
    """小説本文とタイトルをtupleで返す。"""
    genre_desc = GENRE_DESCRIPTIONS.get(genre, genre)
    max_tokens = min(8000, char_count * 2)
    policy     = X_POLICY_RULES if x_safe else ""
    level_inst = _get_horror_level_instruction(horror_level)
    imi_rule   = IMI_KOWAI_RULES if genre == "意味がわかると怖い" else (OMO_KOWAI_RULES if genre == "面白くて怖い（おも怖い）" else "")

    # 小説は長文ほど矛盾が起きやすいため、下調べメモを必ず作って一貫性の土台にする
    research_memo = _research_idea(idea, genre, content_type="短編小説")
    memo_block = f"\n【下調べメモ（これを踏まえて矛盾なく書くこと）】\n{research_memo}\n" if research_memo else ""

    prompt = f"""以下の条件でこわ面白い短編小説を書け。

ジャンル：{genre}（{genre_desc}）
ネタ：{idea}
目標文字数：約{char_count}字
{level_inst}
{memo_block}
{ANTI_AI_RULES}
{QUALITY_BOOST_RULES}
{NOVEL_SEO_RULES}
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
    body, title = _parse_title_and_body(raw)
    # 下調べメモと照らし合わせて矛盾を修正（本文のみ対象）
    body = _consistency_check(body, research_memo, content_type="短編小説")
    return body, title


# 記事生成でSEOを意識させるためのガイド
# X（旧Twitter）の記事はGoogle検索結果に表示されるようになったため、
# Google検索からの流入を前提としたSEO対策が必要になった。
SEO_RULES = """
【Google検索を意識したSEOの書き方】
※ X（旧Twitter）の記事はGoogleの検索結果に表示されるため、SNS内の閲覧者だけでなく
　検索エンジン経由の読者にも届く前提で書くこと。
- タイトルは検索結果の見出し（タイトルタグ）として表示されることを意識し、
  検索されやすいキーワード（地名・固有名詞・「都市伝説」「心霊」「未解決事件」「怖い話」など）を
  できるだけ前方に含めつつ、クリックしたくなる具体性（数字・固有名詞・問いかけ）を入れる
- 記事冒頭の2〜3文は検索結果のスニペット（説明文）として抜粋表示される可能性が高いため、
  「この記事に何が書いてあるか」「読者の知りたいことに答える内容か」が一目で伝わるように書く
- 見出し（##）には記事の主要キーワード・関連語を自然に含め、検索ユーザーが知りたい情報の流れに沿って構成する
- 同じキーワードを不自然に詰め込まず、関連語・言い換えも交えて自然な文章にする（過剰な詰め込みはSEO的に逆効果）
- 検索意図に対する答えを記事内できちんと完結させ、関連トピックへの言及で内容の網羅性を高める
- 記事の終盤で内容を軽く振り返り、関連する話題への興味を持たせる一文を入れる（読了率・回遊率を意識）
"""

ARTICLE_WRITER_RULES = """
【記事執筆の絶対ルール】
■ 視点：解説者ではなく「目撃者」または「記録の発見者」として書け
  - 「〜という説がある」「理由は〜だ」という第三者的な整理をするな
  - 「見てしまった」「見つけてしまった」という一人称的な緊張感で書け
  - 知識を伝えるのではなく、体験が滲み出るように書け

■ 文章構造：整理整頓された論文構造を破壊せよ
  - 「まず〜次に〜最後に」「〇つの理由」「まとめると」は禁止
  - 情報は時系列や感情の流れで断片的に出てくるように配置する
  - 段落は短く、息を切らしたようなリズムにする
  - 「整理された記事」ではなく「震えた手で書いた記録」のように見せる

■ タイトル：Googleの検索結果一覧に並んだ時に「クリックしないと今夜呪われそう」な不気味さを基準にする
  - 必ず3案を【タイトル案】として出力し、その中から最もクリック率が高そうな1案を【タイトル】として選べ
  - タイトルに「説明」を入れるな。「謎」「恐怖」「疑問」を投げかけろ
  - 「〜の真相」「〜の正体」よりも「〜を見た夜から」「〜が届いてから」のような"体験の断片"で引け
  - 固有名詞（地名・人名・事件名）を入れるとSEO的にも効く

■ 有料ライン（TIPSペイウォール）の配置：
  - 「全貌が見えた瞬間」の直前に切れ
  - 読者が「あと一歩で全部わかる」と感じる瞬間、つまり謎の核心に触れる寸前で終わること
  - 「〜だった。」で綺麗に終わるな。「〜だったとしたら」「〜だということを、私は——」のように
    文章が途切れる・宙ぶらりんになる形で切れ
  - この引きを甘くするな。ここで課金を諦めさせたら負けだ
"""


def generate_article(genre: str, idea: str, article_type: str, char_count: int = 3000,
                     include_story: bool = False, x_safe: bool = False,
                     horror_level: int = 3) -> tuple[str, str, list]:
    """記事本文・タイトル・タイトル候補3案をtupleで返す。"""
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

    # 記事は事実関係や固有名詞の矛盾が目立ちやすいため、下調べを必ず挟む
    research_memo = _research_idea(idea, genre, content_type=f"{article_type}")
    memo_block = f"\n【下調べメモ（これを踏まえて矛盾なく書くこと）】\n{research_memo}\n" if research_memo else ""

    prompt = f"""以下の条件でWeb記事を書け。

記事種類：{article_type}（{article_type_desc}）
ジャンル：{genre}（{genre_desc}）
ネタ：{idea}
目標文字数：約{char_count}字
{level_inst}
{story_instruction}
{memo_block}
{ANTI_AI_RULES}
{QUALITY_BOOST_RULES}
{SEO_RULES}
{ARTICLE_WRITER_RULES}
{policy}
{imi_rule}
- 見出しはMarkdown（##）で書く

必ず以下のフォーマットで出力すること：

【タイトル案】
案1：（タイトル）
案2：（タイトル）
案3：（タイトル）

【タイトル】
（上の3案の中から最もクリック率が高いと判断した1案をそのまま書く）

【本文】
（ここに記事本文を書く）"""

    raw = _call_claude(prompt, max_tokens=max_tokens)
    body, title, candidates = _parse_article_with_candidates(raw)
    body = _consistency_check(body, research_memo, content_type=article_type)
    return body, title, candidates


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
    imi_rule   = IMI_KOWAI_RULES if genre == "意味がわかると怖い" else (OMO_KOWAI_RULES if genre == "面白くて怖い（おも怖い）" else "")

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


# ═══════════════════════════════════════════════════════════════════════
# v3.0: ハイブリッド生成アーキテクチャ
# ─ A) SNS 1ショット（GPT-4o）
# ─ B) TIPS長編パイプライン（Claude + スライディングウィンドウ）
# ═══════════════════════════════════════════════════════════════════════

from pathlib import Path as _Path

# ── config ローダー ──────────────────────────────────────────────────

def _load_genre_config(genre_id: str) -> dict:
    """config/genres/{genre_id}.json を読み込む。存在しない場合は空 dict を返す。"""
    path = _Path(__file__).parent / "config" / "genres" / f"{genre_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _load_format_config(format_id: str) -> dict:
    """config/formats/{format_id}.json を読み込む。存在しない場合は空 dict を返す。"""
    path = _Path(__file__).parent / "config" / "formats" / f"{format_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


# ジャンル名 → config ファイル ID のマッピング
_GENRE_CONFIG_MAP = {
    "王道ホラー（心霊）":        "pure_horror",
    "胸糞・ヒトコワ":            "dark_human",
    "意味がわかると怖い":         "imi_kowai",
    "面白くて怖い（おも怖い）":   "omo_kowai",
}


def _get_genre_extra_rules(genre: str) -> str:
    """ジャンルに対応する config JSON を読み込み、プロンプト注入用のルール文字列を返す。"""
    genre_id = _GENRE_CONFIG_MAP.get(genre)
    if not genre_id:
        return ""
    cfg = _load_genre_config(genre_id)
    if not cfg:
        return ""
    parts: list[str] = []
    rules    = cfg.get("system_rules", [])
    forbidden = cfg.get("forbidden", [])
    required  = cfg.get("required_elements", [])
    label     = cfg.get("label", genre)
    if rules:
        parts.append(f"【{label}専用ルール】")
        parts.extend(f"- {r}" for r in rules)
    if forbidden:
        parts.append(f"禁止要素: {', '.join(forbidden)}")
    if required:
        parts.append(f"必須要素: {', '.join(required)}")
    return "\n".join(parts)


# ── A) SNS 1ショット生成（GPT-4o） ──────────────────────────────────

def generate_sns_one_shot(genre: str, style: str, elements: str,
                           x_safe: bool = False) -> str:
    """
    GPT-4o による 280 字以内 SNS 投稿の高速 1 ショット生成。

    マルチエージェントをバイパスし、JSON {"post_text": "..."} を
    1 回のリクエストで取得する。
    出力トークン枠を 200〜260 字に強制制限することで
    モデルの余計な補足・解説（AI 臭さ）を物理的に封じ込める。
    """
    from openai import OpenAI as _OpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY が設定されていません。サイドバーで入力してください。")

    client = _OpenAI(api_key=api_key)

    genre_desc   = GENRE_DESCRIPTIONS.get(genre, genre)
    style_desc   = STYLE_DESCRIPTIONS.get(style, style)
    genre_rules  = _get_genre_extra_rules(genre)
    policy       = X_POLICY_RULES if x_safe else ""

    # SNS フォーマット設定から禁止語を取得
    sns_cfg      = _load_format_config("sns_short")
    forbidden_words = sns_cfg.get("constraints", {}).get("forbidden_words", [
        "実は", "なんと", "驚くことに", "まとめると", "つまり",
        "でしょう", "かもしれません",
    ])
    forbidden_str = "・".join(forbidden_words)

    prompt = f"""以下の条件で SNS 投稿文を 1 つ生成せよ。

ジャンル：{genre}（{genre_desc}）
スタイル：{style}（{style_desc}）
要素・ネタ：{elements}

【厳守事項 — 1 項目でも違反したら不合格】
- 文字数：200 字以上 260 字以下（空白・改行を含めて計測）
- 断定口調（〜だ・〜した・〜だった）のみ使う
- 絶対禁止ワード（1 語でも含めば即不合格）：{forbidden_str}
- 綺麗にまとめない・オチは説明せず感じさせる
- 起承転結 ＋ 最後にゾワッとするオチを入れる

{genre_rules}
{policy}

出力形式：以下の JSON のみ。説明文・マークダウン・コードブロック不要。
{{"post_text": "（投稿文 200〜260 字）"}}"""

    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
        max_tokens=600,
        temperature=0.9,
    )

    raw      = response.choices[0].message.content
    data     = json.loads(raw)
    post_text = data.get("post_text", "").strip()

    char_len = len(post_text)
    if char_len < 200:
        logger.warning(f"SNS 1 ショット: 文字数不足 ({char_len} 字)")
    elif char_len > 280:
        logger.warning(f"SNS 1 ショット: 文字数超過 ({char_len} 字)")
    else:
        logger.info(f"SNS 1 ショット: 生成完了 ({char_len} 字)")

    return post_text


# ── B) TIPS 長編パイプライン（Claude + スライディングウィンドウ）────

def generate_tips_pipeline(
    genre: str,
    elements: str,
    tips_url: str = "",
    x_safe: bool = False,
    horror_level: int = 3,
) -> dict:
    """
    TIPS アフィリエイト 50% 特化型の多段階ステート管理長編生成パイプライン。

    処理フロー:
      ① 要素分解（舞台・人物・怪異の核を JSON で構造化）
      ② 4 章プロット固定（1-2 章無料 / 3-4 章有料）
      ③ 500 字スライディングウィンドウによるループ段階執筆
      ④ 章ごとの高速検閲エージェント（is_valid JSON — NG 時のみリライト）
      ⑤ ジャンル連動型アフィリエイトコピペキット 3 パターン自動生成

    Returns:
        {
            "title"        : str,   # 作品タイトル
            "free_part"    : str,   # 第 1〜2 章（無料公開エリア）
            "paid_part"    : str,   # 第 3〜4 章（有料限定エリア）
            "affiliate_kit": str,   # 50% 報酬アフィリエイト拡散コピペキット
        }
    """
    load_dotenv(override=True)
    genre_desc  = GENRE_DESCRIPTIONS.get(genre, genre)
    genre_rules = _get_genre_extra_rules(genre)
    policy      = X_POLICY_RULES if x_safe else ""
    level_inst  = _get_horror_level_instruction(horror_level)
    fmt_cfg     = _load_format_config("tips_long")
    ch_defs     = fmt_cfg.get("structure", {}).get("chapter_definitions", {})

    # ── ① 要素分解 ─────────────────────────────────────────────────
    decompose_prompt = f"""これから TIPS（有料記事）として販売するホラー長編を書く。
執筆前に設定を分解し、JSON で出力せよ。

ジャンル：{genre}（{genre_desc}）
ネタ・要素：{elements}
{level_inst}
{genre_rules}

以下の JSON 形式のみで出力せよ（マークダウン・コードブロック・説明文は不要）：
{{
  "title"              : "作品タイトル（30 字以内・SEO 意識・クリックしたくなる具体性）",
  "setting"            : "主な舞台・場所（50 字以内）",
  "protagonist"        : "主人公の名前・属性（30 字以内）",
  "horror_core"        : "怪異・恐怖の核心（50 字以内）",
  "alive_characters"   : ["登場人物 1", "登場人物 2"],
  "clues_to_plant"     : ["第 1〜2 章で撒く伏線 1", "伏線 2", "伏線 3"],
  "clues_to_resolve"   : ["第 3〜4 章で回収する伏線 1", "伏線 2", "伏線 3"]
}}"""

    raw_decomp = _call_claude(decompose_prompt, max_tokens=900)
    try:
        state: dict = json.loads(raw_decomp)
    except json.JSONDecodeError:
        m = re.search(r'\{[\s\S]+\}', raw_decomp)
        state = json.loads(m.group()) if m else {}

    title             = state.get("title", "無題")
    alive_characters  = state.get("alive_characters", [])
    pending_clues     = state.get("clues_to_plant", [])
    last_location     = state.get("setting", "不明")
    logger.info(f"TIPS pipeline 開始: title={title}, genre={genre}")

    # ── ② 4 章プロット固定 ─────────────────────────────────────────
    plot_prompt = f"""TIPS ホラー長編「{title}」の 4 章構成プロットを作れ。

設定：{json.dumps(state, ensure_ascii=False)}

【各章の役割】
第 1 章（無料）: 読者を引き込む最高密度の前半戦。日常の崩壊開始と最初の異変。
  書き手は解説者ではなく「目撃者」または「記録の発見者」として書く。整理された説明文ではなく、体験が滲む断片的な語りにする。
第 2 章（無料）: 緊張感最大化。伏線を撒き、「全貌が見える直前」で絶対に切る。
  読者が「あと一歩で全部わかる」と感じる瞬間に終わること。「〜だった。」と綺麗に締めるな。
  文章が途切れる・宙ぶらりんになる形で終わり、読者が金を払わずにいられない引きにする。ここを甘くしたら負けだ。
第 3 章（有料）: 伏線回収開始。真相に迫る展開。怪異の正体・人間の本性が露わになる。
第 4 章（有料）: 全伏線完全回収。強烈なオチ。AI っぽさ皆無の最高到達点。

各章の内容を 3〜5 行で説明せよ。出力形式：
第 1 章: （内容）
第 2 章: （内容）
第 3 章: （内容）
第 4 章: （内容）"""

    plot_text = _call_claude(plot_prompt, max_tokens=700)

    # ── ③ スライディングウィンドウによるループ段階執筆 ──────────────
    chapter_texts: list[str] = []
    prev_chunk = ""  # 直前 500 字のチャンク（コンテキスト肥大化防止）

    for ch_num in range(1, 5):
        ch_def       = ch_defs.get(str(ch_num), {})
        ch_role      = ch_def.get("role", f"第 {ch_num} 章")
        ch_hook      = ch_def.get("hook", "")
        target_chars = ch_def.get("target_chars", 1200)

        # 章ごとに渡す軽量ステート（生存人物・未回収伏線のみ）
        light_state = json.dumps({
            "last_location"   : last_location,
            "alive_characters": alive_characters,
            "pending_clues"   : pending_clues,
        }, ensure_ascii=False)

        is_paywall_chapter = (ch_num == 2)
        paywall_instruction = """
【有料ライン（ペイウォール）の引きの絶対ルール】
この章はここで無料エリアが終わる。「全貌が見える直前」で切れ。
- 読者が「あと一歩で全部わかる」と感じる瞬間に終わること
- 「〜だった。」と綺麗に締めるな。文章が途切れる・宙ぶらりんになる形で終われ
  例：「〜だということを、私は——」「〜だったとしたら、あの夜の」のように切れ
- 謎の核心に触れる寸前で終わること。答えを1ミリも見せるな
- ここで課金を諦めさせたら負けだ
""" if is_paywall_chapter else ""

        write_prompt = f"""TIPS ホラー長編「{title}」の第 {ch_num} 章を書け。

【直前の文脈（直前 500 字のみ — コンテキスト節約）】
{prev_chunk if prev_chunk else "（第 1 章：ここから開始）"}

【現在の軽量ステート】
{light_state}

【この章の役割】
{ch_role}
{f"【引きの指示】{ch_hook}" if ch_hook else ""}
{paywall_instruction}
【プロット参考】
{plot_text}

{ANTI_AI_RULES}
{QUALITY_BOOST_RULES}
{ARTICLE_WRITER_RULES}
{genre_rules}
{policy}

【執筆指示】
- この章の目標文字数：{target_chars} 字前後
- 断定口調のみ。禁句（実は・なんと・驚くことに・まとめると・つまり・でしょう・かもしれません）は絶対使わない
- 五感の描写（温度・臭い・音・触覚・視覚の異常）を必ず入れる
- 前章からの登場人物・場所・設定を一貫させる
- 章の冒頭は「## 第 {ch_num} 章」の見出しで始める

第 {ch_num} 章の本文のみを出力せよ。説明・前置き不要。"""

        chapter_text = _call_claude(write_prompt, max_tokens=2800)

        # ── ④ 高速検閲エージェント（NG 時のみリライト）──────────────
        censor_prompt = f"""以下の文章を検閲し、結果を JSON のみで出力せよ。

【対象（先頭 600 字）】
{chapter_text[:600]}

チェック項目：
1. 禁止ワード（「実は」「なんと」「驚くことに」「まとめると」「つまり」「でしょう」「かもしれません」）が含まれていないか
2. 断定口調（〜だ・〜した）になっているか
3. 前章の設定（登場人物名・場所・時系列）と矛盾がないか

出力形式（これのみ、他は一切不要）：
{{"is_valid": true, "feedback": ""}}
または
{{"is_valid": false, "feedback": "50 字以内で修正点を記述"}}"""

        censor_raw = _call_claude(censor_prompt, max_tokens=120)
        try:
            censor: dict = json.loads(censor_raw)
        except json.JSONDecodeError:
            m2 = re.search(r'\{[^{}]+\}', censor_raw)
            censor = json.loads(m2.group()) if m2 else {"is_valid": True, "feedback": ""}

        if not censor.get("is_valid", True):
            feedback = censor.get("feedback", "")
            logger.info(f"第 {ch_num} 章 検閲 NG: {feedback} → リライト実行")
            rewrite_prompt = f"""以下の文章を修正して出力せよ。

修正指示：{feedback}

【修正前本文】
{chapter_text}

{ANTI_AI_RULES}

修正済み本文のみを出力せよ。"""
            chapter_text = _call_claude(rewrite_prompt, max_tokens=2800)

        chapter_texts.append(chapter_text)
        # 直前 500 字をスライディングウィンドウとして次章へ引き渡す
        prev_chunk = chapter_text[-500:]
        logger.info(f"第 {ch_num} 章 完了 ({len(chapter_text)} 字)")

    # ── ⑤ ジャンル連動型アフィリエイトコピペキット自動生成 ─────────
    tips_link = tips_url if tips_url else "（ここに TIPS の URL を貼る）"
    affiliate_prompt = f"""TIPS ホラー長編「{title}」（ジャンル：{genre}）の購入者向け、
SNS 50% 報酬アフィリエイト紹介文テンプレートを 3 パターン生成せよ。

各パターンの条件：
- 80〜120 字以内で完結すること
- リンクは「{tips_link}」を末尾に配置
- 購入者が即コピペして SNS に投稿できるレベルに完成させる
- 絶対禁止ワード：「実は」「なんと」「驚くことに」「おすすめです」「ぜひ」
- 断定口調で書く。「〜でした」「〜だった」を使う

パターン A（考察煽り型）: 伏線の巧みさ・意味がわかった瞬間の衝撃を煽る紹介
パターン B（純粋恐怖型）: 読後感の悪さ・止まらない恐怖感を伝える紹介
パターン C（拡散促進型）: 誰かに教えたくなる・シェアせずにいられない感情を刺激する紹介

出力形式（これのみ）：
パターン A: （文章 + リンク）
パターン B: （文章 + リンク）
パターン C: （文章 + リンク）"""

    affiliate_kit = _call_claude(affiliate_prompt, max_tokens=700)

    free_part = "\n\n".join(chapter_texts[:2])
    paid_part = "\n\n".join(chapter_texts[2:])

    logger.info(f"TIPS pipeline 完了: 無料={len(free_part)}字 / 有料={len(paid_part)}字")

    return {
        "title"        : title,
        "free_part"    : free_part,
        "paid_part"    : paid_part,
        "affiliate_kit": affiliate_kit,
    }
    return results
