import streamlit as st
import pyperclip
import os
import io
import csv
import math
import textstat
import pandas as pd
import plotly.express as px
from datetime import datetime, date, timedelta
from dotenv import load_dotenv, set_key
from pathlib import Path

from logger_config import logger
from validators import validate_platform_length, split_for_threads, filter_hashtags, HASHTAG_BLACKLIST
from cache import rss_cache
import database as db
import scheduler as sched
from aozora import (
    get_available_authors, fetch_author_samples,
    analyze_style, build_style_prompt,
    get_modern_authors, analyze_modern_style,
)
from agents import (
    generate_post, generate_novel, generate_article, generate_blog_post,
    fetch_trends, suggest_idea_from_trends,
    generate_hashtags, generate_optimized_hashtags,
    get_rss_categories,
    next_rotation_style, generate_series_idea,
    generate_post_with_learning, generate_ab_pair,
    generate_date_linked_idea, rewrite_content,
    add_monetization, generate_thumbnail,
    calc_horror_score, predict_viral_score,
    generate_catchcopy, generate_title_candidates,
    generate_text_thumbnail, batch_generate_posts,
    generate_sns_one_shot, generate_tips_pipeline,
    STYLE_ROTATION,
)
from threads_api import post_to_threads
from auth import check_login, logout, is_auth_enabled

load_dotenv(override=True)
ENV_PATH = Path(__file__).parent / ".env"

sched.start_scheduler()

# ── 認証チェック（APP_PASSWORDが設定されている場合のみ有効）──
if not check_login():
    st.stop()

GENRES = [
    "都市伝説・未解決事件",
    "ホラー体験談・怪談",
    "不思議・オカルト・陰謀論",
    "サイコ・ダークな人間ドラマ",
    "心霊スポット（世界）",
    "意味がわかると怖い",
    "面白くて怖い（おも怖い）",
    "王道ホラー（心霊）",    # v3.0 新設
    "胸糞・ヒトコワ",        # v3.0 新設
]
GENRE_DESC = {
    "都市伝説・未解決事件": "失踪・未解決事件・心霊スポットなど",
    "ホラー体験談・怪談":   "実話風の怖い体験・怪談・呪い",
    "不思議・オカルト・陰謀論": "超常現象・陰謀論・不思議な話",
    "サイコ・ダークな人間ドラマ": "狂気・ストーカー・ダークな人間関係",
    "王道ホラー（心霊）": "五感の異常・日常の侵食・怪異の間接表現",
    "胸糞・ヒトコワ": "人間の狂気・救いなし・幽霊なし",
}
STYLES = [
    "会話風", "独り言・日記風", "スレッド連投風", "ニュース・報告風",
    "コメント欄風", "ランキング・リスト風", "問いかけ風", "途中で途切れる風", "ブログ記事風",
]
STYLE_TIPS = {
    "会話風":          "💬 セリフだけで怖さを伝える。「え、なに？」「…いる」みたいな構成",
    "独り言・日記風":   "📔 「今日変なことがあった」系。体験談っぽく書く",
    "スレッド連投風":   "🧵 「1/5」形式。続きが読みたくなる連続投稿",
    "ニュース・報告風": "📰 感情なし・淡々と事実だけ。それが逆に怖い",
    "コメント欄風":     "💬 「これ本当にあった話なんですが」第三者目線",
    "ランキング・リスト風": "📋 「知らない方がよかった話3選」系",
    "問いかけ風":       "❓ 読者に質問して終わる。コメントが集まりやすい",
    "途中で途切れる風": "✂️ 文章が突然終わる。読者が想像する",
    "ブログ記事風":     "📝 見出し・本文・まとめの構成。SEOを意識した読み物として書く",
}
ARTICLE_TYPES = ["まとめ記事", "解説記事"]
GENRE_DESC = {
    "都市伝説・未解決事件": "失踪・未解決事件・心霊スポットなど",
    "ホラー体験談・怪談":   "実話風の怖い体験・怪談・呪い",
    "不思議・オカルト・陰謀論": "超常現象・陰謀論・不思議な話",
    "サイコ・ダークな人間ドラマ": "狂気・ストーカー・ダークな人間関係",
    "心霊スポット（世界）": "世界各地の心霊スポット・廃墟・呪われた場所",
    "意味がわかると怖い": "読んで意味がわかった瞬間に怖くなる話。答えは書かない",
    "面白くて怖い（おも怖い）": "笑えるのに最後に怖い。コメディ×ホラーの融合ジャンル",
    "王道ホラー（心霊）": "五感の異常・日常の侵食・怪異の間接表現",
    "胸糞・ヒトコワ": "人間の狂気・救いなし・幽霊なし",
}

HORROR_LEVEL_LABELS = {
    1: "★☆☆☆☆　じんわり不気味",
    2: "★★☆☆☆　ちょっと怖い",
    3: "★★★☆☆　普通に怖い（推奨）",
    4: "★★★★☆　かなり怖い",
    5: "★★★★★　トラウマ級",
}

st.set_page_config(
    page_title="👻 こわ面白いコンテンツ生成ツール",
    page_icon="👻",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .stApp { background-color: #0d0d0d; color: #e8e8e8; }
    section[data-testid="stSidebar"] { background-color: #111111; }
    .stTabs [data-baseweb="tab-list"] { background-color: #1a1a1a; border-radius: 8px; }
    .stTabs [data-baseweb="tab"] { color: #aaaaaa; }
    .stTabs [aria-selected="true"] { color: #ff4444 !important; }
    .stButton button { border-radius: 8px; }
    .stTextArea textarea { background-color: #1a1a1a; color: #e8e8e8; font-family: monospace; }
    .stTextInput input { background-color: #1a1a1a; color: #e8e8e8; }
    .quality-score { font-size: 2rem; font-weight: bold; text-align: center; padding: 10px; border-radius: 8px; }
    .score-good { background-color: #1a3a1a; color: #44ff44; }
    .score-mid  { background-color: #3a3a1a; color: #ffff44; }
    .score-bad  { background-color: #3a1a1a; color: #ff4444; }
    .hashtag-box { background-color: #1a1a2e; border: 1px solid #4444aa; border-radius: 8px; padding: 10px; margin: 8px 0; font-family: monospace; font-size: 0.85rem; }
    .trend-card { background-color: #1a1a1a; border-left: 3px solid #ff4444; padding: 8px 12px; margin: 4px 0; border-radius: 4px; font-size: 0.85rem; }
    .setup-card { background-color: #1a1a2e; border: 2px solid #4444ff; border-radius: 12px; padding: 20px; margin: 10px 0; }
    .step-badge { background-color: #ff4444; color: white; border-radius: 50%; padding: 2px 8px; font-weight: bold; margin-right: 6px; }
    .guide-box { background-color: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 12px; margin: 6px 0; font-size: 0.85rem; }
    .empty-state { text-align: center; padding: 40px 20px; color: #888; }
    div[data-testid="stMarkdownContainer"] h1 { color: #ff4444; }
    div[data-testid="stMarkdownContainer"] h2 { color: #dddddd; }
</style>
""", unsafe_allow_html=True)

db.init_db()
db.init_follower_revenue_tables()


# ── ユーティリティ ────────────────────────────────
def calc_quality_score(text: str) -> float:
    if not text:
        return 0.0
    char_count = len(text)
    sentences  = max(1, text.count("。") + text.count("！") + text.count("？"))
    avg_len    = char_count / sentences
    score = 40.0
    if 100 <= char_count <= 500:
        score += 20
    elif 50 <= char_count < 100:
        score += 10
    elif char_count > 500:
        score += 12
    if 15 <= avg_len <= 50:
        score += 10
    elif avg_len < 15:
        score += 3
    spooky = ["死", "消えた", "気づいた", "振り返ると", "声", "影", "血", "怖", "震", "冷たい", "息"]
    score += min(15, sum(2 for w in spooky if w in text))
    ai_bad = ["なんと", "驚くことに", "実は", "まとめると", "つまり", "でしょう", "かもしれません"]
    score -= sum(5 for w in ai_bad if w in text)
    try:
        flesch = textstat.flesch_reading_ease(text)
        score += 5 if flesch > 60 else 2 if flesch > 40 else 0
    except Exception:
        pass
    return min(100.0, max(0.0, score))


def score_color_class(s: float) -> str:
    return "score-good" if s >= 75 else "score-mid" if s >= 50 else "score-bad"


def copy_to_clipboard(text: str) -> bool:
    """
    ローカル環境ではクリップボードにコピー。
    サーバー環境ではコピー不可のため False を返す。
    呼び出し元で False の場合は st.code() で表示する。
    """
    try:
        pyperclip.copy(text)
        return True
    except Exception:
        return False


def show_copy_fallback(text: str, label: str = "コピーする内容"):
    """クリップボードが使えない環境向けのテキスト表示。"""
    st.text_area(label, value=text, height=150, key=f"copy_fallback_{hash(text) % 100000}")


def get_x_safe() -> bool:
    return st.session_state.get("x_safe_mode", True)


def post_full_text(content: str, hashtags: str) -> str:
    return f"{content}\n\n{hashtags}".strip() if hashtags else content


def char_indicator(length: int, limit: int) -> str:
    pct   = length / limit
    emoji = "🟢" if pct <= 0.7 else "🟡" if pct <= 1.0 else "🔴"
    return f"{emoji} {length}字 / {limit}字上限（{min(pct*100,100):.0f}%）"


def api_key_set() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def require_api_key() -> bool:
    if not api_key_set():
        st.error("⚠️ **APIキーが未設定です。**　左のサイドバーで「🔑 APIキーを設定する」を開いてください。")
        return False
    return True


# ── サイドバー ────────────────────────────────────
with st.sidebar:
    st.markdown("# 👻 こわ面白い\nコンテンツ生成ツール")
    st.markdown("---")

    anthropic_ok = api_key_set()
    threads_ok   = bool(os.getenv("THREADS_ACCESS_TOKEN")) and bool(os.getenv("THREADS_USER_ID"))
    openai_ok    = bool(os.getenv("OPENAI_API_KEY"))

    st.markdown("**📊 セットアップ状況**")
    st.markdown(f"{'✅' if anthropic_ok else '❌'} Claude APIキー{'（設定済み）' if anthropic_ok else '（**必須**）'}")
    st.markdown(f"{'✅' if threads_ok else '⬜'} Threads投稿{'（設定済み）' if threads_ok else '（任意）'}")
    st.markdown(f"{'✅' if openai_ok else '⬜'} DALL-E画像生成{'（設定済み）' if openai_ok else '（任意）'}")
    if not anthropic_ok:
        st.warning("⚠️ 文章を生成するにはClaude APIキーが必要です")

    auto_on   = db.get_scheduler_config("auto_mode", "off") == "on"
    days_left = db.get_threads_token_days_left()
    st.caption(f"🤖 自動投稿: {'稼働中' if auto_on and sched.is_running() else '停止中'}")
    if days_left is not None and days_left <= 14:
        st.warning(f"⚠️ Threadsトークン期限まで {days_left}日")

    st.markdown("---")

    with st.expander("🔑 APIキーを設定する" + ("" if anthropic_ok else " ← まずここ！"), expanded=not anthropic_ok):
        st.caption("入力した情報はローカルの .env ファイルに保存されます")
        new_anthropic      = st.text_input("Claude APIキー（必須）", value=os.getenv("ANTHROPIC_API_KEY", ""), type="password", key="sb_anthropic",
                                           help="https://console.anthropic.com で取得")
        new_threads_token  = st.text_input("Threadsアクセストークン（任意）", value=os.getenv("THREADS_ACCESS_TOKEN", ""), type="password", key="sb_threads_token",
                                           help="60日ごとに更新が必要")
        new_threads_uid    = st.text_input("Threadsユーザー ID（任意）", value=os.getenv("THREADS_USER_ID", ""), key="sb_threads_uid",
                                           help="数字のID（@ではない）")
        new_openai         = st.text_input("OpenAI APIキー（任意・画像生成）", value=os.getenv("OPENAI_API_KEY", ""), type="password", key="sb_openai")
        new_serper         = st.text_input("Serper APIキー（任意・Web検索）", value=os.getenv("SERPER_API_KEY", ""), type="password", key="sb_serper")
        if st.button("💾 保存する", type="primary", key="sb_save_keys", use_container_width=True):
            if not ENV_PATH.exists():
                ENV_PATH.touch()
            for key, val in [
                ("ANTHROPIC_API_KEY", new_anthropic), ("THREADS_ACCESS_TOKEN", new_threads_token),
                ("THREADS_USER_ID", new_threads_uid), ("OPENAI_API_KEY", new_openai), ("SERPER_API_KEY", new_serper),
            ]:
                if val:
                    set_key(str(ENV_PATH), key, val)
                    os.environ[key] = val
            st.success("✅ 保存しました！ページを再読み込みすると反映されます")

    with st.expander("⚙️ 投稿の設定"):
        x_safe = st.toggle("Xポリシー配慮モード（推奨）", value=st.session_state.get("x_safe_mode", True), key="sb_x_safe",
                           help="過激表現を避け、末尾に「※フィクションです」を付けます")
        st.session_state["x_safe_mode"] = x_safe
        current_auto = db.get_scheduler_config("auto_mode", "off") == "on"
        auto_toggle  = st.toggle("自動投稿モード", value=current_auto, key="sb_auto_mode",
                                 help="キューの予約時刻に自動でThreadsに投稿します")
        if auto_toggle != current_auto:
            db.set_scheduler_config("auto_mode", "on" if auto_toggle else "off")
        if auto_toggle:
            thr_val = float(db.get_scheduler_config("quality_threshold", "70"))
            new_thr = st.slider("自動投稿の最低品質スコア", 0, 100, int(thr_val), 5, key="sb_threshold")
            if new_thr != thr_val:
                db.set_scheduler_config("quality_threshold", str(new_thr))

    with st.expander("🛠️ データ管理"):
        if st.button("💾 データをバックアップ", key="sb_backup", use_container_width=True):
            bak = db.backup_database()
            st.download_button("📦 ダウンロード", data=bak,
                               file_name=f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                               mime="application/zip", use_container_width=True)
        stats = db.get_queue_stats()
        st.caption(f"キュー: {stats['pending']}件待機 / {stats['posted']}件投稿済み")

    # 文体学習
    with st.expander("📚 文体を学習する"):
        st.caption("作家の文体を学習してAIに反映できます")
        style_source = st.radio("種類", ["青空文庫（無料）", "現代作家（Claude知識）"], key="sb_style_src", horizontal=True)

        # 作家の文体説明（短め）
        AOZORA_AUTHOR_DESC = {
            "江戸川乱歩": "猟奇・美と恐怖の融合・密室",
            "夢野久作": "狂気の語り手・現実と幻覚の境界",
            "芥川龍之介": "簡潔・人間のエゴを極限状態で描く",
            "小泉八雲": "民話調・美しさと怪異の融合",
            "泉鏡花": "幻想・妖艶・水と異界の描写",
            "太宰治": "自嘲・道化・一人称の内面吐露",
            "谷崎潤一郎": "耽美・官能・美への狂的執着",
            "坂口安吾": "虚無・堕落肯定・廃墟の中の生命力",
            "中島敦": "格調ある漢語体・アイデンティティ崩壊",
            "幸田露伴": "骨太・意志と運命のぶつかり",
        }
        MODERN_AUTHOR_DESC = {a: v.split("】")[0].replace("【","") for a, v in __import__('aozora').MODERN_AUTHORS.items()}

        if style_source == "青空文庫（無料）":
            authors_list = get_available_authors()
            sel_author = st.selectbox(
                "作家",
                authors_list,
                format_func=lambda a: f"{a}　{AOZORA_AUTHOR_DESC.get(a, '')}",
                key="sb_aozora_author"
            )
            if st.button(f"📖 {sel_author}を学習", key="sb_learn_aozora", use_container_width=True):
                if not require_api_key():
                    pass
                else:
                    with st.spinner("テキストを取得・分析中..."):
                        samples = fetch_author_samples(sel_author)
                        if samples:
                            analysis = analyze_style(sel_author, samples)
                            db.save_style_profile(sel_author, analysis)
                            st.success(f"✅「{sel_author}」の学習完了！")
                        else:
                            st.error("テキスト取得に失敗しました")
        else:
            modern_list = get_modern_authors()
            sel_modern = st.selectbox(
                "現代作家",
                modern_list,
                format_func=lambda a: f"{a}　{MODERN_AUTHOR_DESC.get(a, '')}",
                key="sb_modern_author"
            )
            if st.button(f"✨ {sel_modern}を学習", key="sb_learn_modern", use_container_width=True):
                if not require_api_key():
                    pass
                else:
                    with st.spinner("分析中..."):
                        analysis = analyze_modern_style(sel_modern)
                        db.save_style_profile(sel_modern, analysis)
                        st.success(f"✅「{sel_modern}」の学習完了！")

        profiles = db.get_all_style_profiles()
        learned  = [k for k, v in profiles.items() if v]
        if learned:
            st.caption(f"学習済み: {', '.join(learned)}")
            del_author = st.selectbox("削除する", learned, key="sb_del_profile")
            if st.button("🗑️ 削除", key="sb_del_profile_btn"):
                db.set_scheduler_config(f"style_profile_{del_author}", "")
                st.rerun()

    st.markdown("---")
    st.caption("Phase 1〜5 + UX改善版")
    if is_auth_enabled():
        if st.button("🔓 ログアウト", key="logout_btn", use_container_width=True):
            logout()


# ── ヘッダー ──────────────────────────────────────
st.markdown("# 👻 こわ面白いコンテンツ生成ツール")

if not api_key_set():
    st.markdown("""
    <div class="setup-card">
    <h3>🚀 はじめに：3ステップでセットアップ</h3>
    <p><span class="step-badge">1</span> 左のサイドバーの「🔑 APIキーを設定する」を開く</p>
    <p><span class="step-badge">2</span> Claude APIキーを入力して「保存する」を押す<br>
    &nbsp;&nbsp;&nbsp;&nbsp;<small>→ <a href="https://console.anthropic.com" target="_blank">console.anthropic.com</a> で無料登録してAPIキーを取得できます</small></p>
    <p><span class="step-badge">3</span> 「📱 投稿をつくる」タブに戻って「生成する」ボタンを押す</p>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")


# ── メインタブ ────────────────────────────────────
tab_post, tab_novel, tab_article, tab_haunted, tab_ideas, tab_queue, tab_history, tab_analysis, tab_batch = st.tabs([
    "📱 投稿をつくる",
    "📖 小説をつくる",
    "📰 記事をつくる",
    "🌍 心霊スポットブログ",
    "🗃️ ネタバンク",
    "📅 投稿スケジュール",
    "📚 生成履歴",
    "📊 分析レポート",
    "⚡ まとめて生成",
])


# ═══════════════════════════════════════════════
# 投稿タブ
# ═══════════════════════════════════════════════
with tab_post:
    st.markdown("## 📱 SNS投稿文をつくる")
    st.caption("ジャンルとスタイルを選んでネタを入力するだけで、こわ面白い投稿文が完成します")

    col1, col2 = st.columns([1, 1])

    with col1:
        st.markdown("### STEP 1　ジャンルを選ぶ")
        genre = st.radio("どんなジャンルにしますか？", GENRES, key="post_genre")
        st.caption(f"💡 {GENRE_DESC.get(genre, '')}")

        st.markdown("### STEP 2　スタイルを選ぶ")
        st.caption("投稿の「語り口」です。迷ったら「独り言・日記風」がおすすめ")
        current_style = st.session_state.get("post_style_val", "独り言・日記風")
        style = st.selectbox("スタイル", STYLES,
                             index=STYLES.index(current_style) if current_style in STYLES else 1,
                             key="post_style")
        st.session_state["post_style_val"] = style
        st.caption(STYLE_TIPS.get(style, ""))
        if st.button("🔀 別のスタイルに切り替える", key="rotate_style",
                     help="順番に別のスタイルを試せます"):
            st.session_state["post_style_val"] = next_rotation_style(style)
            st.rerun()

        char_count = st.slider("文字数", 100, 1000, 280, 50, key="post_chars",
                               help="X（Twitter）は280文字、Threadsは500文字が上限です")

        horror_level = st.select_slider(
            "👻 怖さのレベル",
            options=[1, 2, 3, 4, 5],
            value=3,
            format_func=lambda x: HORROR_LEVEL_LABELS[x],
            key="post_horror_level",
        )
        if genre == "意味がわかると怖い":
            st.info("💡 表面上は普通の話→意味がわかった瞬間に怖くなる構造。答えは書かず、読者に気づかせます。")
        elif genre == "面白くて怖い（おも怖い）":
            st.info("😂👻 最初は笑える展開→最後にゾワッとする構造。コメディのテンポで書き、一文で恐怖を落とします。")

        with st.expander("🔬 上級者向け：A/Bテスト（2スタイルを比較する）"):
            ab_mode = st.toggle("A/Bテストをオンにする", key="post_ab_mode")
            style_b = st.selectbox("比較スタイルB", [s for s in STYLES if s != style], key="post_style_b") if ab_mode else STYLES[0]

        st.markdown("### STEP 3　ネタを入力する")
        idea_source = st.radio(
            "ネタの選び方",
            ["💡 ネタバンクから選ぶ（おすすめ）", "✏️ 自分で入力する",
             "🔥 今日のニュースから提案", "📅 今日の日付に関連したネタ", "📺 シリーズものを作る"],
            key="post_idea_source",
        )

        idea_text = ""
        selected_idea = None

        if idea_source == "💡 ネタバンクから選ぶ（おすすめ）":
            show_all = st.toggle("全ジャンルを表示する", False, key="post_idea_show_all",
                                 help="ONにすると他のジャンルのネタも表示されます")
            ideas = db.get_all_ideas(None if show_all else genre)
            if ideas:
                opts = {f"【{i['title']}】　{i['description'] or ''}": i for i in ideas}
                sel  = st.selectbox("ネタを選んでください", list(opts.keys()), key="post_idea_select")
                selected_idea = opts[sel]
                desc = selected_idea["description"] or ""
                idea_text = f"{selected_idea['title']}：{desc}" if desc else selected_idea["title"]
                if selected_idea["used"] > 0:
                    st.caption(f"📊 このネタは過去{selected_idea['used']}回使用済み")
            else:
                st.info("ネタバンクが空です。「🗃️ ネタバンク」タブでネタを追加しましょう。")
                idea_text = st.text_area("または直接ネタを入力する",
                                         placeholder="例：隣人が毎晩壁を叩いてくる話", key="post_fallback")

        elif idea_source == "✏️ 自分で入力する":
            idea_text = st.text_area("ネタを入力してください",
                                     placeholder="例：隣人が毎晩壁を叩いてくる話\n例：廃墟に行ったら見てはいけないものを見た",
                                     key="post_idea_manual",
                                     help="1〜3文程度のざっくりした設定でOK。Claudeが肉付けしてくれます")

        elif idea_source == "🔥 今日のニュースから提案":
            st.caption("今日のニュースをこわ面白い視点に変換してネタを提案します")
            rss_cats = get_rss_categories()
            sel_cats = st.multiselect("取得するメディア",rss_cats,
                                      default=["Yahoo!ニュース", "ライブドア", "まとめ・バズ系"],
                                      key="post_rss_cats")
            if st.button("🌐 今日のネタを取得する", key="fetch_trends_post", type="primary", use_container_width=True):
                with st.spinner("ニュースを取得してネタを考えています...（10〜20秒）"):
                    trends = fetch_trends(sel_cats or None)
                    db.save_trends(trends)
                    st.session_state["trends"] = trends
                    st.session_state["trend_ideas"] = suggest_idea_from_trends(trends, genre)
            for t in st.session_state.get("trends", [])[:10]:
                st.markdown(f'<div class="trend-card">📰 {t["source"].split("／")[-1]}｜{t["keyword"][:50]}</div>', unsafe_allow_html=True)
            for i, item in enumerate(st.session_state.get("trend_ideas", [])):
                ti1, ti2 = st.columns([4, 1])
                with ti1:
                    st.markdown(f"**{item['title']}**")
                    st.caption(item.get("description", ""))
                with ti2:
                    if st.button("使う", key=f"use_ti_{i}", use_container_width=True):
                        st.session_state["_trend_idea_selected"] = item["title"] + "：" + item.get("description", "")
                        st.rerun()
                    if st.button("保存", key=f"save_ti_{i}", use_container_width=True):
                        db.add_idea(item["title"], genre, item.get("description", ""))
                        st.success("保存しました！")
            idea_text = st.text_area("ネタを入力（上の候補をコピーしてもOK）",
                                     value=st.session_state.pop("_trend_idea_selected", ""),
                                     key="post_trend_idea")

        elif idea_source == "📅 今日の日付に関連したネタ":
            today = date.today()
            st.info(f"今日は **{today.month}月{today.day}日**。この日付に関連したネタを生成します")
            if st.button("📅 今日のネタを生成する", key="gen_date_idea", use_container_width=True):
                with st.spinner("考えています..."):
                    st.session_state["date_idea"] = generate_date_linked_idea(genre)
            if st.session_state.get("date_idea"):
                st.info(st.session_state["date_idea"])
            idea_text = st.text_area("ネタを確認・編集してから使う",
                                     value=st.session_state.get("date_idea", ""), key="post_date_idea")

        else:  # シリーズ
            all_series = db.get_all_series()
            series_list = [s for s in all_series if s["current"] < s["total"]]
            if series_list:
                opts_s = {f"{s['name']}　（{s['current']}/{s['total']}回）": s for s in series_list}
                sel_s  = st.selectbox("シリーズを選んでください", list(opts_s.keys()), key="post_series_select")
                sel_series = opts_s[sel_s]
                next_n     = sel_series["current"] + 1
                idea_text  = generate_series_idea(sel_series["template"], next_n, sel_series["genre"])
                # 進捗バー
                prog = sel_series["current"] / sel_series["total"] if sel_series["total"] > 0 else 0
                st.progress(prog, text=f"進捗: {sel_series['current']}/{sel_series['total']}回 — 次は第{next_n}回")
                st.info(f"📝 次のネタ：**{idea_text}**")
                st.caption("生成するとカウンターが自動で進みます")
                # 自動進行フラグをセット（ボタン不要）
                st.session_state["advance_series_id"] = sel_series["id"]

                # シリーズの総数を変更できるUI
                with st.expander("⚙️ このシリーズの設定を変更"):
                    new_total = st.number_input(
                        "総回数を変更する", min_value=next_n, max_value=10000,
                        value=sel_series["total"], key="series_total_edit"
                    )
                    if st.button("💾 総回数を保存", key="save_series_total"):
                        import sqlite3
                        conn = sqlite3.connect(db.DB_PATH)
                        conn.execute("UPDATE series SET total = ? WHERE id = ?", (int(new_total), sel_series["id"]))
                        conn.commit(); conn.close()
                        st.success(f"総回数を{new_total}回に変更しました！")
                        st.rerun()
            else:
                st.info("シリーズがありません。「🗃️ ネタバンク」タブ → シリーズ管理 で作れます。")
                idea_text = ""

        auto_ht = st.toggle("ハッシュタグを自動で付ける", True, key="post_auto_ht")

        with st.expander("💰 収益化オプション（任意）"):
            note_url = st.text_input("noteのURL（誘導文を末尾に追加）", key="post_note_url",
                                     placeholder="https://note.com/yourname/n/xxxxx")
            aff_url  = st.text_input("アフィリエイトURL", key="post_aff_url",
                                     placeholder="https://amzn.to/xxxxx")

        top_patterns = db.get_top_patterns()
        top_tags     = db.get_top_hashtags()
        profiles     = db.get_all_style_profiles()
        style_hint   = ""
        learned_list = [k for k, v in profiles.items() if v]
        if learned_list:
            sel_profile = st.selectbox(
                "📚 参考にする作家の文体（任意）",
                ["なし（通常どおり生成）"] + learned_list, key="post_style_profile",
            )
            if sel_profile != "なし（通常どおり生成）":
                style_hint = build_style_prompt(profiles[sel_profile])
                st.caption(f"「{sel_profile}」の演出技法を参考に生成します")

        st.markdown("### STEP 4　生成する")
        one_shot_mode = st.toggle(
            "⚡ 高速1ショットモード（GPT-4o）",
            value=False, key="post_one_shot_mode",
            help="GPT-4oで200〜260字に最適化した投稿文を超高速生成。文字数スライダーは無効になります。",
        )
        if one_shot_mode:
            st.caption("⚡ GPT-4o使用 / 200〜260字固定 / 断定口調・ゾワッとするオチ必須")

        generate_btn = st.button(
            "🔥 投稿文を生成する",
            type="primary", key="post_generate", use_container_width=True,
            disabled=not api_key_set(),
        )
        if not api_key_set():
            st.caption("⚠️ 左サイドバーでAPIキーを設定してください")

        if generate_btn:
            if not require_api_key():
                pass
            elif not idea_text.strip():
                st.error("⚠️ ネタを入力してください（STEP 3）")
            else:
                with st.spinner("AIが文章を考えています...（10〜20秒）"):
                    try:
                        if one_shot_mode:
                            content = generate_sns_one_shot(genre, style, idea_text, get_x_safe())
                            st.session_state.update({
                                "post_content": content, "post_pending": content,
                                "post_score": calc_quality_score(content), "ab_content_a": None,
                            })
                        elif ab_mode:
                            ca, cb = generate_ab_pair(genre, idea_text, style, style_b, char_count, get_x_safe())
                            st.session_state.update({
                                "ab_content_a": ca, "ab_content_b": cb,
                                "ab_style_a": style, "ab_style_b": style_b,
                                "post_content": ca, "post_pending": ca,
                                "post_score": calc_quality_score(ca),
                            })
                        else:
                            content = generate_post_with_learning(genre, style, idea_text, char_count, get_x_safe(), top_patterns, style_hint=style_hint, horror_level=horror_level)
                            if note_url or aff_url:
                                content = add_monetization(content, "post", aff_url, note_url)
                            st.session_state.update({
                                "post_content": content, "post_pending": content,
                                "post_score": calc_quality_score(content), "ab_content_a": None,
                            })
                        if auto_ht:
                            base = st.session_state["post_content"]
                            ht   = generate_optimized_hashtags(base, genre, top_tags) if top_tags else generate_hashtags(base, genre)
                            st.session_state["post_hashtags"] = ht
                        else:
                            st.session_state["post_hashtags"] = ""
                        if selected_idea:
                            db.mark_idea_used(selected_idea["id"])
                        if "advance_series_id" in st.session_state:
                            db.advance_series(st.session_state.pop("advance_series_id"))
                        db.save_content("post", genre, style, st.session_state["post_content"], st.session_state["post_score"])
                        st.session_state.pop("date_idea", None)
                        st.toast("✅ 生成が完了しました！右側を確認してください", icon="✅")
                    except Exception as e:
                        logger.error(f"Post generation error: {e}")
                        st.error(f"生成中にエラーが発生しました: {e}")

    with col2:
        st.markdown("### プレビュー・投稿")

        score    = st.session_state.get("post_score", 0.0)
        hashtags = st.session_state.get("post_hashtags", "")
        ab_a     = st.session_state.get("ab_content_a")
        ab_b     = st.session_state.get("ab_content_b")

        if not st.session_state.get("post_content"):
            st.markdown("""
            <div class="empty-state">
            <div style="font-size:3rem">👈</div>
            <div style="font-size:1.1rem;margin:10px 0">左の設定を入力して<br>「🔥 投稿文を生成する」を押してください</div>
            <div style="font-size:0.85rem;color:#666">初めての方は<br>「💡 ネタバンクから選ぶ」で始めるのが簡単です</div>
            </div>""", unsafe_allow_html=True)

        elif ab_a and ab_b:
            st.markdown("#### 🅐🅑 どちらが良いか比べてみましょう")
            for tab_ab, content_ab, group in [
                (st.tabs([f"🅐 {st.session_state.get('ab_style_a','A')}", f"🅑 {st.session_state.get('ab_style_b','B')}"])[0], ab_a, "A"),
                (st.tabs([f"🅐 {st.session_state.get('ab_style_a','A')}", f"🅑 {st.session_state.get('ab_style_b','B')}"])[1], ab_b, "B"),
            ]:
                with tab_ab:
                    sc_ab = calc_quality_score(content_ab)
                    st.markdown(f'<div class="quality-score {score_color_class(sc_ab)}">品質: {sc_ab:.0f}点</div>', unsafe_allow_html=True)
                    st.text_area("内容", value=content_ab, height=180, key=f"ab_preview_{group}")
                    b1, b2 = st.columns(2)
                    with b1:
                        if st.button(f"📅 {group}をキューへ", key=f"ab_queue_{group}", use_container_width=True):
                            db.add_to_queue("post", genre, st.session_state.get(f"ab_style_{group}", group), content_ab, hashtags, sc_ab, ab_group=group)
                            st.success("追加しました！")
                    with b2:
                        if st.button(f"📋 {group}をコピー", key=f"ab_copy_{group}", use_container_width=True):
                            copy_to_clipboard(post_full_text(content_ab, hashtags))
                            st.success("コピーしました！")
        else:
            if score:
                st.markdown(f'<div class="quality-score {score_color_class(score)}">品質スコア: {score:.0f}点</div>', unsafe_allow_html=True)
                st.caption("✨ 良い出来です！" if score >= 75 else "👍 まずまずです" if score >= 50 else "🔄 再生成を試みてください")

            if "post_pending" in st.session_state:
                st.session_state["post_preview"] = st.session_state.pop("post_pending")

            edited_content = st.text_area("生成された文章（自由に編集できます）", height=200, key="post_preview",
                                          placeholder="左の設定を入力して「生成する」を押してください")

            if hashtags:
                st.markdown(f'<div class="hashtag-box">{hashtags}</div>', unsafe_allow_html=True)
                edited_hashtags = st.text_input("ハッシュタグ（編集可能）", value=hashtags, key="post_ht_edit")
            else:
                edited_hashtags = ""

            if openai_ok and edited_content:
                with st.expander("🎨 DALL-Eでサムネイル画像を生成する（1枚約4円）"):
                    if st.button("🎨 AIで画像を生成する", key="gen_thumb", use_container_width=True):
                        with st.spinner("画像を生成中...（30秒ほど）"):
                            img_bytes = generate_thumbnail(edited_content, genre)
                            if img_bytes:
                                st.session_state["thumb_bytes"] = img_bytes
                            else:
                                st.error("画像生成に失敗しました")
                    if st.session_state.get("thumb_bytes"):
                        st.image(st.session_state["thumb_bytes"], use_container_width=True)
                        st.download_button("💾 画像を保存", data=st.session_state["thumb_bytes"],
                                           file_name="thumbnail.png", mime="image/png", use_container_width=True)

            if edited_content:
                full_post = post_full_text(edited_content, edited_hashtags)
                p1, p2    = st.columns(2)
                with p1:
                    if st.button("🔄 別のパターンで再生成", key="post_regen", use_container_width=True):
                        with st.spinner("再生成中..."):
                            try:
                                c = generate_post_with_learning(genre, style, idea_text or "同じテーマで別の文章", char_count, get_x_safe(), top_patterns, style_hint=style_hint, horror_level=horror_level)
                                st.session_state.update({"post_content": c, "post_pending": c, "post_score": calc_quality_score(c)})
                                if auto_ht:
                                    st.session_state["post_hashtags"] = generate_hashtags(c, genre)
                                st.rerun()
                            except Exception as e:
                                st.error(f"再生成エラー: {e}")
                with p2:
                    if st.button("📅 スケジュールに追加", key="post_queue", use_container_width=True,
                                 help="投稿予約リストに追加します。後でまとめて投稿できます"):
                        db.add_to_queue("post", genre, style, edited_content, edited_hashtags, score)
                        st.success("📅「投稿スケジュール」タブに追加しました！")

                p3, p4 = st.columns(2)
                with p3:
                    if st.button("📋 Xにコピーして手動投稿", key="post_copy_x", use_container_width=True,
                                 help="クリップボードにコピー。Xのアプリに貼り付けて投稿してください"):
                        if copy_to_clipboard(full_post):
                            st.success("📋 コピーしました！Xに貼り付けてください")
                        else:
                            st.code(full_post)
                            st.caption("↑ 手動でコピーしてください")
                with p4:
                    if st.button("🅣 Threadsに今すぐ投稿", key="post_threads", type="primary", use_container_width=True):
                        if not threads_ok:
                            st.error("⚠️ 左サイドバーでThreadsの設定をしてください")
                        else:
                            vr = validate_platform_length(full_post, "threads")
                            if not vr.valid:
                                parts = split_for_threads(full_post)
                                st.warning(f"500文字超のため{len(parts)}件に分割して投稿します")
                                with st.spinner(f"分割投稿中（{len(parts)}件）..."):
                                    ok = sum(1 for p in parts if post_to_threads(p)["success"])
                                    st.success(f"✅ {ok}/{len(parts)}件の投稿が完了しました！") if ok == len(parts) else st.error("一部投稿に失敗しました")
                            else:
                                with st.spinner("投稿中..."):
                                    r = post_to_threads(full_post)
                                    if r["success"]:
                                        st.success("✅ Threadsへの投稿が完了しました！")
                                    else:
                                        st.error(f"投稿エラー: {r['error']}")

                st.caption(char_indicator(len(edited_content), 500))

                with st.expander("📊 詳細スコアとキャッチコピー"):
                    hs = calc_horror_score(edited_content)
                    vs = predict_viral_score(edited_content, genre, style, top_patterns)
                    s1, s2, s3 = st.columns(3)
                    with s1: st.metric("👻 ホラー度", f"{hs['horror']}点")
                    with s2: st.metric("⚡ 緊張感", f"{hs['tension']}点")
                    with s3: st.metric("🔥 バズり予測", f"{vs}点")
                    if st.button("💬 キャッチコピーを3案生成", key="gen_catchcopy", use_container_width=True):
                        with st.spinner("考えています..."):
                            st.session_state["catchcopies"] = generate_catchcopy(edited_content, genre)
                    for i, cc in enumerate(st.session_state.get("catchcopies", [])):
                        cc1, cc2 = st.columns([4, 1])
                        with cc1: st.markdown(f"**{cc}**")
                        with cc2:
                            if st.button("コピー", key=f"copy_cc_{i}", use_container_width=True):
                                copy_to_clipboard(cc); st.success("コピー！")

                with st.expander("🖼️ テキストサムネを作る（APIキー不要）"):
                    thumb_title = st.text_input("サムネに入れる文字（20文字以内推奨）", key="thumb_title_input")
                    if st.button("🖼️ サムネを生成する", key="gen_text_thumb", use_container_width=True):
                        try:
                            img_bytes = generate_text_thumbnail(thumb_title or edited_content[:20], genre)
                            st.session_state["text_thumb_bytes"] = img_bytes
                        except Exception as e:
                            st.error(f"エラー: {e}")
                    if st.session_state.get("text_thumb_bytes"):
                        st.image(st.session_state["text_thumb_bytes"], use_container_width=True)
                        st.download_button("💾 保存する", data=st.session_state["text_thumb_bytes"],
                                           file_name="thumbnail.png", mime="image/png", use_container_width=True)


# ═══════════════════════════════════════════════
# 小説タブ
# ═══════════════════════════════════════════════
with tab_novel:
    st.markdown("## 📖 短編小説をつくる")
    st.caption("ネタを入れるだけでこわ面白い短編小説を自動で書いてくれます。noteやX記事に投稿できます")

    col1, col2 = st.columns([1, 1])
    with col1:
        genre_n = st.selectbox("ジャンル", GENRES, key="novel_genre")
        st.caption(f"💡 {GENRE_DESC.get(genre_n, '')}")

        st.markdown("**文字数を決める**")
        st.caption("迷ったら「中編（3,000字）」がおすすめです")
        pc = st.columns(3)
        with pc[0]:
            if st.button("短編\n500字", key="np_short", use_container_width=True): st.session_state["novel_chars"] = 500
        with pc[1]:
            if st.button("中編\n3,000字", key="np_mid", use_container_width=True): st.session_state["novel_chars"] = 3000
        with pc[2]:
            if st.button("長編\n10,000字", key="np_long", use_container_width=True): st.session_state["novel_chars"] = 10000
        novel_chars       = st.slider("文字数を細かく調整", 200, 10000, st.session_state.get("novel_chars", 3000), 100, key="novel_chars_slider")
        novel_chars_input = st.number_input("または数字で入力", 200, 15000, novel_chars, key="novel_chars_input")

        idea_src_n = st.radio("ネタの選び方", ["💡 ネタバンクから選ぶ", "✏️ 自分で入力する"], key="novel_idea_src")
        idea_text_n = ""
        selected_idea_n = None
        if idea_src_n == "💡 ネタバンクから選ぶ":
            show_all_n = st.toggle("全ジャンルを表示", False, key="novel_show_all")
            ideas_n = db.get_all_ideas(None if show_all_n else genre_n)
            if ideas_n:
                opts_n = {f"【{i['title']}】　{i['description'] or ''}": i for i in ideas_n}
                sel_n  = st.selectbox("ネタを選んでください", list(opts_n.keys()), key="novel_idea_select")
                selected_idea_n = opts_n[sel_n]
                desc_n  = selected_idea_n["description"] or ""
                idea_text_n = f"{selected_idea_n['title']}：{desc_n}" if desc_n else selected_idea_n["title"]
            else:
                st.info("ネタバンクが空です。「ネタバンク」タブで追加できます。")
        else:
            idea_text_n = st.text_area("ネタを入力", placeholder="例：田舎の廃村に一人で行ったら...", key="novel_idea_manual")

        learned_list_n = [k for k, v in db.get_all_style_profiles().items() if v]
        style_hint_n   = ""
        if learned_list_n:
            sel_prof_n = st.selectbox("📚 参考にする作家の文体（任意）",
                                      ["なし（通常どおり）"] + learned_list_n, key="novel_style_profile")
            if sel_prof_n != "なし（通常どおり）":
                style_hint_n = build_style_prompt(db.get_all_style_profiles()[sel_prof_n])

        horror_level_n = st.select_slider(
            "👻 怖さのレベル",
            options=[1, 2, 3, 4, 5], value=3,
            format_func=lambda x: HORROR_LEVEL_LABELS[x],
            key="novel_horror_level",
        )
        if genre_n == "意味がわかると怖い":
            st.info("💡 意味がわかると怖いジャンル：表面上は普通の話として書き、意味がわかった瞬間に怖くなる構造にします。")

        st.markdown("---")
        tips_mode_n = st.toggle("💰 TIPSモード（アフィリエイト50%最適化）", False, key="novel_tips_mode",
                                help="ch1-2を無料公開・ch3-4を有料に分割し、50%報酬アフィリエイト用コピペキットを自動生成します")

        if tips_mode_n:
            tips_url_n = st.text_input("TIPSのURL（アフィリエイトリンク）", placeholder="https://tips.cash/...", key="novel_tips_url")
            st.info("📝 4章構成（各約1,200字）で自動生成されます。ch1-2が無料公開エリア、ch3-4が有料限定エリアです。")
        else:
            with st.expander("💰 収益化オプション（任意）"):
                note_url_n = st.text_input("noteのURL", key="novel_note_url")
                aff_url_n  = st.text_input("アフィリエイトURL", key="novel_aff_url")

        if tips_mode_n:
            if st.button("🔥 TIPSコンテンツを生成する（4章構成・約4,800字）",
                         type="primary", key="novel_tips_generate", use_container_width=True, disabled=not api_key_set()):
                if not require_api_key():
                    pass
                elif not idea_text_n.strip():
                    st.error("⚠️ ネタを入力してください")
                else:
                    with st.spinner("4章構成で書いています...（数分かかります）"):
                        try:
                            tips_url_val = st.session_state.get("novel_tips_url", "")
                            result = generate_tips_pipeline(genre_n, idea_text_n, tips_url=tips_url_val,
                                                            x_safe=get_x_safe(), horror_level=horror_level_n)
                            full_text = result["free_part"] + "\n\n" + result["paid_part"]
                            st.session_state.update({
                                "novel_content": full_text,
                                "novel_score": calc_quality_score(full_text),
                                "novel_title": result["title"],
                                "novel_title_candidates": [],
                                "tips_result": result,
                                "tips_mode_active": True,
                            })
                            if selected_idea_n:
                                db.mark_idea_used(selected_idea_n["id"])
                            db.save_content("novel", genre_n, result["title"], full_text, st.session_state["novel_score"])
                            st.toast("✅ TIPSコンテンツが完成しました！", icon="💰")
                        except Exception as e:
                            logger.error(f"TIPS error: {e}"); st.error(f"生成エラー: {e}")
        else:
            st.session_state["tips_mode_active"] = False
            if st.button(f"🔥 小説を生成する（約{novel_chars_input:,}字）",
                         type="primary", key="novel_generate", use_container_width=True, disabled=not api_key_set()):
                if not require_api_key():
                    pass
                elif not idea_text_n.strip():
                    st.error("⚠️ ネタを入力してください")
                else:
                    with st.spinner(f"小説を書いています...（{novel_chars_input:,}字・数分かかります）"):
                        try:
                            cn, title_n = generate_novel(genre_n, idea_text_n, novel_chars_input, x_safe=get_x_safe(), style_hint=style_hint_n, horror_level=horror_level_n)
                            if st.session_state.get("novel_note_url") or st.session_state.get("novel_aff_url"):
                                cn = add_monetization(cn, "novel", st.session_state.get("novel_aff_url", ""), st.session_state.get("novel_note_url", ""))
                            st.session_state.update({"novel_content": cn, "novel_pending": cn,
                                                      "novel_score": calc_quality_score(cn), "novel_title": title_n, "novel_title_candidates": []})
                            if selected_idea_n:
                                db.mark_idea_used(selected_idea_n["id"])
                            db.save_content("novel", genre_n, "", cn, st.session_state["novel_score"])
                            st.toast("✅ 小説が完成しました！右側を確認してください", icon="📖")
                        except Exception as e:
                            logger.error(f"Novel error: {e}"); st.error(f"生成エラー: {e}")
        if not api_key_set():
            st.caption("⚠️ サイドバーでAPIキーを設定してください")

    with col2:
        st.markdown("### 生成結果")
        sn = st.session_state.get("novel_score", 0.0)
        if not st.session_state.get("novel_content"):
            st.markdown('<div class="empty-state"><div style="font-size:3rem">📖</div><div>左で設定して「小説を生成する」を押してください</div></div>', unsafe_allow_html=True)
        elif st.session_state.get("tips_mode_active") and st.session_state.get("tips_result"):
            # ── TIPSモード 分割プレビュー ──
            tips_res = st.session_state["tips_result"]
            if sn:
                st.markdown(f'<div class="quality-score {score_color_class(sn)}">品質スコア: {sn:.0f}点</div>', unsafe_allow_html=True)
            tips_title = tips_res.get("title", "")
            if tips_title:
                edited_tips_title = st.text_input("📌 タイトル（編集可能）", value=tips_title, key="tips_title_input")
                if st.button("📋 タイトルをコピー", key="tips_copy_title", use_container_width=True):
                    copy_to_clipboard(edited_tips_title); st.success("コピーしました！")

            st.markdown("---")
            st.markdown("#### 🔓 無料公開エリア（第1〜2章）")
            st.caption("TIPSの前半部分です。ここまでを無料公開に設定してください。")
            edited_free = st.text_area("無料エリア（編集可能）", value=tips_res.get("free_part", ""),
                                       height=250, key="tips_free_preview")
            if st.button("📋 無料エリアをコピー", key="tips_copy_free", use_container_width=True):
                copy_to_clipboard(edited_free); st.success("コピーしました！")

            st.markdown("---")
            st.markdown("#### 🛑 TIPS有料ライン（ここから下を有料エリアに設定）")
            st.markdown("---")

            st.markdown("#### 🔒 有料限定エリア（第3〜4章）")
            st.caption("ここから下をTIPSの有料部分に設定してください。")
            edited_paid = st.text_area("有料エリア（編集可能）", value=tips_res.get("paid_part", ""),
                                       height=250, key="tips_paid_preview")
            if st.button("📋 有料エリアをコピー", key="tips_copy_paid", use_container_width=True):
                copy_to_clipboard(edited_paid); st.success("コピーしました！")

            st.markdown("---")
            st.markdown("#### 🎁 50%報酬アフィリエイト用拡散コピペキット")
            st.caption("購入者がSNSで紹介する際のテンプレートです。3パターン自動生成されています。")
            aff_kit = tips_res.get("affiliate_kit", "")
            st.text_area("コピペキット", value=aff_kit, height=200, key="tips_aff_kit_display")
            if st.button("📋 コピペキットをまとめてコピー", key="tips_copy_kit", use_container_width=True):
                copy_to_clipboard(aff_kit); st.success("コピーしました！")

            st.markdown("---")
            full_text_tips = edited_free + "\n\n" + edited_paid
            st.caption(f"総文字数: {len(full_text_tips):,}字 　無料: {len(edited_free):,}字 　有料: {len(edited_paid):,}字")
            if st.button("📅 スケジュールに追加", key="tips_novel_queue", use_container_width=True):
                db.add_to_queue("novel", genre_n, tips_title, full_text_tips, "", sn); st.success("追加しました！")
        else:
            # ── 通常モード プレビュー ──
            if sn:
                st.markdown(f'<div class="quality-score {score_color_class(sn)}">品質スコア: {sn:.0f}点</div>', unsafe_allow_html=True)
            novel_title = st.session_state.get("novel_title", "")
            if novel_title:
                edited_title_n = st.text_input("📌 タイトル（編集可能）", value=novel_title, key="novel_title_input")
                tc1, tc2 = st.columns(2)
                with tc1:
                    if st.button("📋 タイトルをコピー", key="novel_copy_title", use_container_width=True):
                        copy_to_clipboard(edited_title_n); st.success("コピーしました！")
                with tc2:
                    if st.button("📋 タイトル＋本文をコピー", key="novel_copy_all", use_container_width=True):
                        st.session_state["_novel_copy_all"] = True
            else:
                edited_title_n = ""

            if "novel_pending" in st.session_state:
                st.session_state["novel_preview"] = st.session_state.pop("novel_pending")
            edited_novel = st.text_area("本文（編集可能）", height=300, key="novel_preview",
                                        placeholder="生成するとここに表示されます")
            if edited_novel:
                if novel_title and st.session_state.pop("_novel_copy_all", False):
                    copy_to_clipboard(f"【{edited_title_n}】\n\n{edited_novel}"); st.success("タイトル＋本文をコピーしました！")
                nc1, nc2, nc3 = st.columns(3)
                with nc1:
                    if st.button("📅 スケジュールに追加", key="novel_queue", use_container_width=True):
                        db.add_to_queue("novel", genre_n, novel_title, edited_novel, "", sn); st.success("追加しました！")
                with nc2:
                    if st.button("📋 Xにコピー", key="novel_copy_x", use_container_width=True):
                        copy_to_clipboard(edited_novel); st.success("コピーしました！")
                with nc3:
                    if st.button("📝 noteにコピー", key="novel_copy_note", use_container_width=True):
                        t = edited_title_n or novel_title
                        copy_to_clipboard(f"【{t}】\n\n{edited_novel}" if t else edited_novel); st.success("コピーしました！")
                st.caption(f"文字数: {len(edited_novel):,}字")
                with st.expander("📌 タイトルのバリエーションを5つ作る"):
                    if st.button("💡 タイトル案を5つ生成する", key="gen_title_cands", use_container_width=True):
                        with st.spinner("タイトルを考えています..."):
                            st.session_state["novel_title_candidates"] = generate_title_candidates(edited_novel, "novel")
                    for i, t in enumerate(st.session_state.get("novel_title_candidates", [])):
                        tc1, tc2 = st.columns([4, 1])
                        with tc1: st.markdown(f"**{t}**")
                        with tc2:
                            if st.button("使う", key=f"use_title_n_{i}", use_container_width=True):
                                st.session_state["novel_title"] = t; st.rerun()


# ═══════════════════════════════════════════════
# 記事タブ
# ═══════════════════════════════════════════════
with tab_article:
    st.markdown("## 📰 Web記事をつくる")
    st.caption("まとめ記事や解説記事を自動で書きます。X記事・noteに投稿できます")

    col1, col2 = st.columns([1, 1])
    with col1:
        article_type = st.radio("記事の種類", ARTICLE_TYPES, key="article_type",
                                help="まとめ記事：複数エピソードを紹介　/ 解説記事：1テーマを深掘り")
        genre_a = st.selectbox("ジャンル", GENRES, key="article_genre")

        ac = st.columns(3)
        with ac[0]:
            if st.button("短め\n1,000字", key="ap_short", use_container_width=True): st.session_state["article_chars"] = 1000
        with ac[1]:
            if st.button("標準\n3,000字", key="ap_mid", use_container_width=True): st.session_state["article_chars"] = 3000
        with ac[2]:
            if st.button("長め\n5,000字", key="ap_long", use_container_width=True): st.session_state["article_chars"] = 5000
        article_chars       = st.slider("文字数を細かく調整", 500, 8000, st.session_state.get("article_chars", 3000), 100, key="article_chars_slider")
        article_chars_input = st.number_input("または数字で入力", 500, 10000, article_chars, key="article_chars_input")
        include_story = st.toggle("記事の中に短編フィクションを挿入する", False, key="article_include_story",
                                  help="約500字の関連フィクション短編を1本埋め込みます")

        idea_src_a = st.radio("ネタの選び方", ["💡 ネタバンクから選ぶ", "✏️ 自分で入力する"], key="article_idea_src")
        idea_text_a = ""
        selected_idea_a = None
        if idea_src_a == "💡 ネタバンクから選ぶ":
            show_all_a = st.toggle("全ジャンルを表示", False, key="article_show_all")
            ideas_a = db.get_all_ideas(None if show_all_a else genre_a)
            if ideas_a:
                opts_a = {f"【{i['title']}】　{i['description'] or ''}": i for i in ideas_a}
                sel_a  = st.selectbox("ネタを選んでください", list(opts_a.keys()), key="article_idea_select")
                selected_idea_a = opts_a[sel_a]
                desc_a = selected_idea_a["description"] or ""
                idea_text_a = f"{selected_idea_a['title']}：{desc_a}" if desc_a else selected_idea_a["title"]
            else:
                st.info("ネタバンクが空です。")
        else:
            idea_text_a = st.text_area("ネタを入力", placeholder="例：日本の呪われた場所まとめ", key="article_idea_manual")

        horror_level_a = st.select_slider(
            "👻 怖さのレベル",
            options=[1, 2, 3, 4, 5], value=3,
            format_func=lambda x: HORROR_LEVEL_LABELS[x],
            key="article_horror_level",
        )
        if genre_a == "意味がわかると怖い":
            st.info("💡 意味がわかると怖いジャンル：表面上は普通の記事として書き、意味がわかった瞬間に怖くなる構造にします。")

        st.markdown("---")
        tips_mode_a = st.toggle("💰 TIPSモード（アフィリエイト50%最適化）", False, key="article_tips_mode",
                                help="ch1-2を無料公開・ch3-4を有料に分割し、50%報酬アフィリエイト用コピペキットを自動生成します")

        if tips_mode_a:
            tips_url_a = st.text_input("TIPSのURL（アフィリエイトリンク）", placeholder="https://tips.cash/...", key="article_tips_url")
            st.info("📝 4章構成（各約1,200字）で自動生成されます。")
        else:
            with st.expander("💰 収益化オプション（任意）"):
                note_url_a = st.text_input("noteのURL", key="article_note_url")
                aff_url_a  = st.text_input("アフィリエイトURL", key="article_aff_url")

        if tips_mode_a:
            if st.button("🔥 TIPSコンテンツを生成する（4章構成・約4,800字）",
                         type="primary", key="article_tips_generate", use_container_width=True, disabled=not api_key_set()):
                if not require_api_key():
                    pass
                elif not idea_text_a.strip():
                    st.error("⚠️ ネタを入力してください")
                else:
                    with st.spinner("4章構成で書いています...（数分かかります）"):
                        try:
                            tips_url_val_a = st.session_state.get("article_tips_url", "")
                            result_a = generate_tips_pipeline(genre_a, idea_text_a, tips_url=tips_url_val_a,
                                                              x_safe=get_x_safe(), horror_level=horror_level_a)
                            full_text_a = result_a["free_part"] + "\n\n" + result_a["paid_part"]
                            st.session_state.update({
                                "article_content": full_text_a,
                                "article_score": calc_quality_score(full_text_a),
                                "article_title": result_a["title"],
                                "tips_result_a": result_a,
                                "tips_mode_active_a": True,
                            })
                            if selected_idea_a:
                                db.mark_idea_used(selected_idea_a["id"])
                            db.save_content("article", genre_a, article_type, full_text_a, st.session_state["article_score"])
                            st.toast("✅ TIPSコンテンツが完成しました！", icon="💰")
                        except Exception as e:
                            logger.error(f"TIPS article error: {e}"); st.error(f"生成エラー: {e}")
        else:
            st.session_state["tips_mode_active_a"] = False
            if st.button(f"🔥 記事を生成する（約{article_chars_input:,}字）",
                         type="primary", key="article_generate", use_container_width=True, disabled=not api_key_set()):
                if not require_api_key():
                    pass
                elif not idea_text_a.strip():
                    st.error("⚠️ ネタを入力してください")
                else:
                    with st.spinner(f"記事を書いています...（{article_chars_input:,}字・数分かかります）"):
                        try:
                            ca, title_a, title_cands_a = generate_article(genre_a, idea_text_a, article_type, article_chars_input, include_story, x_safe=get_x_safe(), horror_level=horror_level_a)
                            if st.session_state.get("article_note_url") or st.session_state.get("article_aff_url"):
                                ca = add_monetization(ca, "article", st.session_state.get("article_aff_url", ""), st.session_state.get("article_note_url", ""))
                            st.session_state.update({"article_content": ca, "article_pending": ca,
                                                      "article_score": calc_quality_score(ca), "article_title": title_a,
                                                      "article_title_candidates_main": title_cands_a})
                            if selected_idea_a:
                                db.mark_idea_used(selected_idea_a["id"])
                            db.save_content("article", genre_a, article_type, ca, st.session_state["article_score"])
                            st.toast("✅ 記事が完成しました！右側を確認してください", icon="📰")
                        except Exception as e:
                            logger.error(f"Article error: {e}"); st.error(f"生成エラー: {e}")
        if not api_key_set():
            st.caption("⚠️ サイドバーでAPIキーを設定してください")

    with col2:
        st.markdown("### 生成結果")
        sa = st.session_state.get("article_score", 0.0)
        if not st.session_state.get("article_content"):
            st.markdown('<div class="empty-state"><div style="font-size:3rem">📰</div><div>左で設定して「記事を生成する」を押してください</div></div>', unsafe_allow_html=True)
        elif st.session_state.get("tips_mode_active_a") and st.session_state.get("tips_result_a"):
            # ── TIPSモード 分割プレビュー（記事） ──
            tips_res_a = st.session_state["tips_result_a"]
            if sa:
                st.markdown(f'<div class="quality-score {score_color_class(sa)}">品質スコア: {sa:.0f}点</div>', unsafe_allow_html=True)
            tips_title_a = tips_res_a.get("title", "")
            if tips_title_a:
                edited_tips_title_a = st.text_input("📌 タイトル（編集可能）", value=tips_title_a, key="tips_article_title_input")
                if st.button("📋 タイトルをコピー", key="tips_article_copy_title", use_container_width=True):
                    copy_to_clipboard(edited_tips_title_a); st.success("コピーしました！")

            st.markdown("---")
            st.markdown("#### 🔓 無料公開エリア（第1〜2章）")
            edited_free_a = st.text_area("無料エリア（編集可能）", value=tips_res_a.get("free_part", ""),
                                         height=250, key="tips_article_free_preview")
            if st.button("📋 無料エリアをコピー", key="tips_article_copy_free", use_container_width=True):
                copy_to_clipboard(edited_free_a); st.success("コピーしました！")

            st.markdown("---")
            st.markdown("#### 🛑 TIPS有料ライン（ここから下を有料エリアに設定）")
            st.markdown("---")

            st.markdown("#### 🔒 有料限定エリア（第3〜4章）")
            edited_paid_a = st.text_area("有料エリア（編集可能）", value=tips_res_a.get("paid_part", ""),
                                         height=250, key="tips_article_paid_preview")
            if st.button("📋 有料エリアをコピー", key="tips_article_copy_paid", use_container_width=True):
                copy_to_clipboard(edited_paid_a); st.success("コピーしました！")

            st.markdown("---")
            st.markdown("#### 🎁 50%報酬アフィリエイト用拡散コピペキット")
            aff_kit_a = tips_res_a.get("affiliate_kit", "")
            st.text_area("コピペキット", value=aff_kit_a, height=200, key="tips_article_aff_kit_display")
            if st.button("📋 コピペキットをまとめてコピー", key="tips_article_copy_kit", use_container_width=True):
                copy_to_clipboard(aff_kit_a); st.success("コピーしました！")

            st.markdown("---")
            full_text_tips_a = edited_free_a + "\n\n" + edited_paid_a
            st.caption(f"総文字数: {len(full_text_tips_a):,}字 　無料: {len(edited_free_a):,}字 　有料: {len(edited_paid_a):,}字")
            if st.button("📅 スケジュールに追加", key="tips_article_queue", use_container_width=True):
                db.add_to_queue("article", genre_a, tips_title_a, full_text_tips_a, "", sa); st.success("追加しました！")
        else:
            # ── 通常モード プレビュー（記事） ──
            if sa:
                st.markdown(f'<div class="quality-score {score_color_class(sa)}">品質スコア: {sa:.0f}点</div>', unsafe_allow_html=True)
            article_title = st.session_state.get("article_title", "")
            if article_title:
                edited_title_a = st.text_input("📌 タイトル（編集可能）", value=article_title, key="article_title_input")
                at1, at2 = st.columns(2)
                with at1:
                    if st.button("📋 タイトルをコピー", key="article_copy_title", use_container_width=True):
                        copy_to_clipboard(edited_title_a); st.success("コピーしました！")
                with at2:
                    if st.button("📋 タイトル＋全文をコピー", key="article_copy_all_btn", use_container_width=True):
                        st.session_state["_article_copy_all"] = True
                # タイトル候補3案を表示
                cands_main = st.session_state.get("article_title_candidates_main", [])
                if cands_main:
                    with st.expander("📌 タイトル3案（AIが選ばなかった候補）"):
                        for i, t in enumerate(cands_main):
                            tc1, tc2 = st.columns([4, 1])
                            with tc1: st.markdown(f"**案{i+1}**: {t}")
                            with tc2:
                                if st.button("使う", key=f"use_title_main_a_{i}", use_container_width=True):
                                    st.session_state["article_title"] = t; st.rerun()
            else:
                edited_title_a = ""

            if "article_pending" in st.session_state:
                st.session_state["article_preview"] = st.session_state.pop("article_pending")
            edited_article = st.text_area("本文（編集可能）", height=300, key="article_preview",
                                          placeholder="生成するとここに表示されます")
            if edited_article:
                if article_title and st.session_state.pop("_article_copy_all", False):
                    copy_to_clipboard(f"【{edited_title_a}】\n\n{edited_article}"); st.success("タイトル＋本文をコピーしました！")
                aqc1, aqc2, aqc3 = st.columns(3)
                with aqc1:
                    if st.button("📅 スケジュールに追加", key="article_queue", use_container_width=True):
                        db.add_to_queue("article", genre_a, edited_title_a or article_title, edited_article, "", sa); st.success("追加しました！")
                with aqc2:
                    if st.button("📋 Xにコピー", key="article_copy", use_container_width=True):
                        copy_to_clipboard(edited_article); st.success("コピーしました！")
                with aqc3:
                    if article_title and st.button("📋 タイトル＋本文", key="article_copy_all2", use_container_width=True):
                        copy_to_clipboard(f"【{edited_title_a}】\n\n{edited_article}"); st.success("コピーしました！")
                st.caption(f"文字数: {len(edited_article):,}字")
                with st.expander("📌 タイトルのバリエーションを5つ作る"):
                    if st.button("💡 タイトル案を5つ生成する", key="gen_title_cands_a", use_container_width=True):
                        with st.spinner("考えています..."):
                            st.session_state["article_title_candidates"] = generate_title_candidates(edited_article, "article")
                    for i, t in enumerate(st.session_state.get("article_title_candidates", [])):
                        tc1, tc2 = st.columns([4, 1])
                        with tc1: st.markdown(f"**{t}**")
                        with tc2:
                            if st.button("使う", key=f"use_title_a_{i}", use_container_width=True):
                                st.session_state["article_title"] = t; st.rerun()


# ═══════════════════════════════════════════════
# 心霊スポットブログタブ
# ═══════════════════════════════════════════════
with tab_haunted:
    st.markdown("## 🌍 世界の心霊スポット ブログ記事生成")
    st.caption("CSVから取り込んだ世界の心霊スポットをもとに、ブログ記事を自動生成します")

    h_col1, h_col2 = st.columns([1, 1])

    with h_col1:
        # ── CSVインポートセクション ──
        with st.expander("📥 心霊スポットCSVをインポートする", expanded=db.get_haunted_spots().__len__() == 0):
            st.caption("「world_haunted_title_acquisition_status_with_full_titles.csv」をドロップしてください")

            h_import_mode = st.radio(
                "インポートするデータ",
                ["🇯🇵 日本語タイトルがあるもののみ（推奨・約1,200件）", "🌐 全件（約25,000件・時間がかかります）"],
                key="h_import_mode",
            )
            jp_only_flag = "日本語タイトル" in h_import_mode

            uploaded_csv = st.file_uploader(
                "CSVファイルを選択",
                type="csv",
                key="haunted_csv_upload",
            )

            if uploaded_csv:
                try:
                    raw_csv  = uploaded_csv.read().decode("utf-8-sig")
                    all_rows = list(csv.DictReader(io.StringIO(raw_csv)))
                    if jp_only_flag:
                        preview_rows = [r for r in all_rows if r.get("jp_title_or_note", "").strip()]
                    else:
                        preview_rows = all_rows
                    st.caption(f"対象: {len(preview_rows):,}件 / 全{len(all_rows):,}件")
                    st.dataframe(
                        pd.DataFrame(preview_rows[:5])[["region", "title", "jp_title_or_note"]],
                        use_container_width=True,
                    )
                    if st.button(
                        f"✅ {len(preview_rows):,}件をネタバンクにインポートする",
                        type="primary", key="do_haunted_import", use_container_width=True,
                    ):
                        with st.spinner("インポート中...（全件の場合数分かかります）"):
                            imported, skipped = db.import_haunted_spots_csv(all_rows, jp_only=jp_only_flag)
                        st.success(f"✅ {imported:,}件インポート完了！（{skipped:,}件スキップ）")
                        st.rerun()
                except Exception as e:
                    st.error(f"CSVの読み込みエラー: {e}")

        # ── ネタ選択 ──
        st.markdown("### スポットを選んで記事を生成する")

        spots_count = len(db.get_haunted_spots())
        if spots_count == 0:
            st.info("上のCSVインポートでスポットを追加してください")
        else:
            st.caption(f"登録済みスポット: {spots_count:,}件")

            # 国フィルター
            all_regions = db.get_haunted_regions()
            region_options = ["すべて"] + all_regions
            sel_region = st.selectbox("国・地域で絞り込む", region_options, key="h_region_filter")
            filter_val = "" if sel_region == "すべて" else sel_region

            all_spots  = db.get_haunted_spots(filter_val)
            # 未使用のみ表示（used == 0）
            spots = [s for s in all_spots if s["used"] == 0]
            used_count = len(all_spots) - len(spots)

            if not spots:
                if used_count > 0:
                    st.success(f"✅ このカテゴリのスポットは全件使用済みです（{used_count:,}件）")
                    if st.button("🔄 使用済みも含めてリセットして再表示", key="h_reset_used"):
                        # 全件の使用フラグをリセット
                        import sqlite3
                        conn = sqlite3.connect(db.DB_PATH)
                        conn.execute("UPDATE ideas SET used = 0 WHERE genre = '心霊スポット（世界）'")
                        conn.commit(); conn.close()
                        st.rerun()
                else:
                    st.warning(f"「{sel_region}」のスポットが見つかりません")
            else:
                st.caption(f"未使用: {len(spots):,}件 ／ 使用済み: {used_count:,}件（非表示）")

                # ランダム取得ボタン
                rc1, rc2 = st.columns([3, 1])
                with rc2:
                    if st.button("🎲 ランダムに選ぶ", key="h_random", use_container_width=True):
                        import random
                        st.session_state["h_selected_idx"] = random.randint(0, len(spots) - 1)

                spot_opts = {f"[{s['description']}] {s['title']}": s for s in spots[:500]}
                default_idx = st.session_state.get("h_selected_idx", 0) % len(spot_opts)
                sel_spot_label = st.selectbox(
                    f"スポットを選ぶ（{len(spots):,}件中）",
                    list(spot_opts.keys()),
                    index=min(default_idx, len(spot_opts) - 1),
                    key="h_spot_select",
                )
                sel_spot = spot_opts[sel_spot_label]

                # スポット情報パース
                title_raw = sel_spot["title"]
                # 「日本語名（英語名）」形式を分解
                import re as _re
                m = _re.match(r"^(.+?)（(.+?)）$", title_raw)
                if m:
                    jp_name = m.group(1).strip()
                    en_name = m.group(2).strip()
                else:
                    jp_name = ""
                    en_name = title_raw
                region_val = sel_spot["description"]

                st.markdown(f"**選択中：** {title_raw}")
                st.caption(f"📍 {region_val}")

                # 記事設定
                h_chars = st.slider("記事の文字数", 800, 5000, 2000, 200, key="h_chars",
                                    help="ブログ記事は2,000〜3,000字が読みやすいとされています")
                h_preset = st.columns(3)
                with h_preset[0]:
                    if st.button("短め 1,000字", key="h_short", use_container_width=True):
                        st.session_state["h_chars_override"] = 1000
                with h_preset[1]:
                    if st.button("標準 2,000字", key="h_mid", use_container_width=True):
                        st.session_state["h_chars_override"] = 2000
                with h_preset[2]:
                    if st.button("詳細 4,000字", key="h_long", use_container_width=True):
                        st.session_state["h_chars_override"] = 4000
                final_chars = st.session_state.pop("h_chars_override", h_chars)

                # 文体学習
                profiles_h = db.get_all_style_profiles()
                style_hint_h = ""
                learned_h = [k for k, v in profiles_h.items() if v]
                if learned_h:
                    sel_prof_h = st.selectbox("📚 参考にする作家の文体（任意）",
                                              ["なし（通常どおり）"] + learned_h, key="h_style_profile")
                    if sel_prof_h != "なし（通常どおり）":
                        style_hint_h = build_style_prompt(profiles_h[sel_prof_h])

                # 生成ボタン
                if st.button("🔥 ブログ記事を生成する", type="primary", key="h_generate",
                             use_container_width=True, disabled=not api_key_set()):
                    if not require_api_key():
                        pass
                    else:
                        with st.spinner(f"「{jp_name or en_name}」の記事を書いています...（{final_chars:,}字・数分かかります）"):
                            try:
                                body, title_h = generate_blog_post(
                                    spot_name=en_name,
                                    spot_name_jp=jp_name,
                                    region=region_val,
                                    char_count=final_chars,
                                    x_safe=get_x_safe(),
                                    style_hint=style_hint_h,
                                )
                                score_h = calc_quality_score(body)
                                st.session_state.update({
                                    "h_body": body, "h_pending": body,
                                    "h_title": title_h, "h_score": score_h,
                                    "h_spot_used_id": sel_spot["id"],
                                })
                                db.save_content("article", "心霊スポット（世界）", "ブログ記事風", body, score_h)
                                db.mark_idea_used(sel_spot["id"])
                                st.toast("✅ 記事が完成しました！右側を確認してください", icon="🌍")
                            except Exception as e:
                                logger.error(f"Blog generation error: {e}")
                                st.error(f"生成エラー: {e}")

    # ── 右列：プレビュー ──
    with h_col2:
        st.markdown("### 生成された記事")
        h_score = st.session_state.get("h_score", 0.0)

        if not st.session_state.get("h_body"):
            st.markdown("""
            <div class="empty-state">
            <div style="font-size:3rem">🌍</div>
            <div style="font-size:1.1rem;margin:10px 0">左でスポットを選んで<br>「ブログ記事を生成する」を押してください</div>
            <div style="font-size:0.85rem;color:#666">まずCSVインポートでスポットを追加してください</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            if h_score:
                st.markdown(f'<div class="quality-score {score_color_class(h_score)}">品質スコア: {h_score:.0f}点</div>', unsafe_allow_html=True)

            h_title = st.session_state.get("h_title", "")
            if h_title:
                edited_h_title = st.text_input("📌 タイトル（編集可能）", value=h_title, key="h_title_input")
                ht1, ht2 = st.columns(2)
                with ht1:
                    if st.button("📋 タイトルをコピー", key="h_copy_title", use_container_width=True):
                        copy_to_clipboard(edited_h_title); st.success("コピーしました！")
                with ht2:
                    if st.button("📋 タイトル＋本文をコピー", key="h_copy_all", use_container_width=True):
                        st.session_state["_h_copy_all"] = True
            else:
                edited_h_title = ""

            if "h_pending" in st.session_state:
                st.session_state["h_preview"] = st.session_state.pop("h_pending")

            edited_h_body = st.text_area("本文（編集可能）", height=380, key="h_preview",
                                         placeholder="記事を生成するとここに表示されます")

            if edited_h_body:
                if h_title and st.session_state.pop("_h_copy_all", False):
                    copy_to_clipboard(f"【{edited_h_title}】\n\n{edited_h_body}")
                    st.success("タイトル＋本文をコピーしました！")

                hb1, hb2, hb3 = st.columns(3)
                with hb1:
                    if st.button("📅 スケジュールに追加", key="h_queue", use_container_width=True):
                        db.add_to_queue("article", "心霊スポット（世界）", "ブログ記事風",
                                        edited_h_body, "", h_score)
                        st.success("追加しました！")
                with hb2:
                    if st.button("📋 Xにコピー", key="h_copy_x", use_container_width=True):
                        copy_to_clipboard(edited_h_body); st.success("コピーしました！")
                with hb3:
                    if st.button("📝 noteにコピー", key="h_copy_note", use_container_width=True):
                        t = edited_h_title or h_title
                        copy_to_clipboard(f"【{t}】\n\n{edited_h_body}" if t else edited_h_body)
                        st.success("コピーしました！")

                st.caption(f"文字数: {len(edited_h_body):,}字")

                # タイトル候補
                with st.expander("📌 SEOタイトルを5案生成する"):
                    if st.button("💡 タイトル案を5つ生成する", key="h_gen_titles", use_container_width=True):
                        with st.spinner("考えています..."):
                            st.session_state["h_title_candidates"] = generate_title_candidates(edited_h_body, "article")
                    for i, t in enumerate(st.session_state.get("h_title_candidates", [])):
                        tc1, tc2 = st.columns([4, 1])
                        with tc1: st.markdown(f"**{t}**")
                        with tc2:
                            if st.button("使う", key=f"use_h_title_{i}", use_container_width=True):
                                st.session_state["h_title"] = t; st.rerun()

    # ── 登録済みスポット一覧 ──
    st.markdown("---")
    with st.expander(f"📋 登録済みスポット一覧（{len(db.get_haunted_spots()):,}件）"):
        h_filter_r = st.selectbox("国・地域で絞り込む", ["すべて"] + db.get_haunted_regions(), key="h_list_filter")
        h_spots_list = db.get_haunted_spots("" if h_filter_r == "すべて" else h_filter_r)
        st.caption(f"{len(h_spots_list):,}件")
        # CSV書き出し
        if h_spots_list:
            buf_h = io.StringIO()
            csv.DictWriter(buf_h, ["title", "description", "used"]).writeheader()
            csv.DictWriter(buf_h, ["title", "description", "used"]).writerows(
                [{"title": s["title"], "description": s["description"], "used": s["used"]} for s in h_spots_list]
            )
            st.download_button("📤 CSV書き出し", data=buf_h.getvalue().encode("utf-8-sig"),
                               file_name="haunted_spots.csv", mime="text/csv")
        for s in h_spots_list[:100]:
            badge = f"🔴 {s['used']}回" if s["used"] > 0 else "🟢 未使用"
            st.caption(f"{badge}　📍 {s['description']}　｜　{s['title']}")


# ═══════════════════════════════════════════════
# ネタバンクタブ
# ═══════════════════════════════════════════════
with tab_ideas:
    st.markdown("## 🗃️ ネタバンク")
    st.caption("投稿のネタを管理します。ここに追加しておくと、投稿タブで簡単に選べます")

    idea_tab1, idea_tab2 = st.tabs(["📝 ネタ一覧・追加", "📺 シリーズ管理"])

    with idea_tab1:
        with st.expander("➕ 新しいネタを追加する", expanded=len(db.get_all_ideas()) == 0):
            new_title = st.text_input("ネタのタイトル（必須）", key="new_idea_title", placeholder="例：隣人の奇行、廃村の秘密")
            new_genre = st.selectbox("ジャンル（必須）", GENRES, key="new_idea_genre")
            new_desc  = st.text_area("詳細メモ（任意）", key="new_idea_desc", height=80,
                                     placeholder="例：引っ越し先の隣人が毎晩壁を叩いてくる話。理由は不明。")
            if st.button("✅ ネタを追加する", key="add_idea_btn", type="primary"):
                if new_title:
                    db.add_idea(new_title, new_genre, new_desc)
                    st.success(f"✅「{new_title}」をネタバンクに追加しました！"); st.rerun()
                else:
                    st.error("タイトルを入力してください")

        with st.expander("🔥 今日のニュースからネタを自動生成する"):
            trend_genre = st.selectbox("ジャンル", GENRES, key="trend_genre")
            bank_cats   = st.multiselect("取得するメディア", get_rss_categories(),
                                         default=["Yahoo!ニュース", "ライブドア", "まとめ・バズ系"], key="bank_rss_cats")
            if st.button("🌐 ネタを自動生成する", key="trend_add_btn", type="primary", use_container_width=True):
                if require_api_key():
                    with st.spinner("ニュースを取得してネタを考えています...（15〜30秒）"):
                        trends = fetch_trends(bank_cats or None)
                        db.save_trends(trends)
                        st.session_state["bank_ideas"] = suggest_idea_from_trends(trends, trend_genre)
                        st.session_state["bank_genre"] = trend_genre
            bank_ideas = st.session_state.get("bank_ideas", [])
            if bank_ideas:
                bank_genre = st.session_state.get("bank_genre", GENRES[0])
                st.markdown(f"**💡 提案されたネタ（{bank_genre}）**")
                if st.button("✅ 全部まとめてネタバンクに追加", key="add_all_trends", type="primary", use_container_width=True):
                    for item in bank_ideas:
                        db.add_idea(item["title"], bank_genre, item.get("description", ""))
                    st.success(f"✅ {len(bank_ideas)}件のネタを追加しました！")
                    st.session_state["bank_ideas"] = []; st.rerun()
                for i, item in enumerate(bank_ideas):
                    bi1, bi2 = st.columns([4, 1])
                    with bi1:
                        st.markdown(f"**{item['title']}**"); st.caption(item.get("description", ""))
                    with bi2:
                        if st.button("追加", key=f"bank_add_{i}", use_container_width=True):
                            db.add_idea(item["title"], bank_genre, item.get("description", ""))
                            bank_ideas.pop(i); st.session_state["bank_ideas"] = bank_ideas; st.rerun()

        with st.expander("📥 CSVからまとめてインポートする"):
            st.caption("列名: title（タイトル）/ genre（ジャンル）/ description（説明）")
            uploaded = st.file_uploader("CSVファイルをドロップ", type="csv", key="idea_csv_upload")
            if uploaded:
                try:
                    rows = list(csv.DictReader(io.StringIO(uploaded.read().decode("utf-8-sig"))))
                    st.caption(f"{len(rows)}件を検出")
                    if st.button("📥 インポート実行", key="import_csv_btn", type="primary"):
                        count = db.import_ideas_csv(rows)
                        st.success(f"✅ {count}件をインポートしました！"); st.rerun()
                except Exception as e:
                    st.error(f"CSVエラー: {e}")

        st.markdown("---")
        col_filter, col_export = st.columns([3, 1])
        with col_filter:
            filter_genre = st.selectbox("ジャンルで絞り込む", ["すべて"] + GENRES, key="idea_filter_genre")
        with col_export:
            all_ideas_ex = db.get_all_ideas()
            if all_ideas_ex:
                buf = io.StringIO()
                csv.DictWriter(buf, ["title","genre","description","used"]).writeheader()
                csv.DictWriter(buf, ["title","genre","description","used"]).writerows(
                    [{"title":i["title"],"genre":i["genre"],"description":i["description"],"used":i["used"]} for i in all_ideas_ex])
                st.download_button("📤 CSVで書き出す", data=buf.getvalue().encode("utf-8-sig"),
                                   file_name="idea_bank.csv", mime="text/csv", use_container_width=True)

        ideas_all = db.get_all_ideas(filter_genre)
        if not ideas_all:
            st.markdown('<div class="empty-state"><div style="font-size:2rem">🗃️</div><div>ネタがありません<br><small>上の「新しいネタを追加する」から追加してください</small></div></div>', unsafe_allow_html=True)
        else:
            st.caption(f"{len(ideas_all)}件のネタ")
            for idea in ideas_all:
                c1, c2 = st.columns([5, 1])
                with c1:
                    badge = f"🔴 {idea['used']}回使用" if idea["used"] > 0 else "🟢 未使用"
                    st.markdown(f"**{idea['title']}**　{badge}")
                    if idea["description"]:
                        st.caption(f"🏷️ {idea['genre']}　📝 {idea['description']}")
                    else:
                        st.caption(f"🏷️ {idea['genre']}")
                with c2:
                    if st.button("🗑️", key=f"del_{idea['id']}", help="削除"):
                        db.delete_idea(idea["id"]); st.rerun()
                st.markdown("---")

    with idea_tab2:
        st.markdown("### 📺 シリーズ管理")
        st.caption("「47都道府県の呪われた場所」など、連続コンテンツを自動管理します")

        with st.expander("➕ 新しいシリーズを作る"):
            st.caption("{n} で回数、{pref} で都道府県名が自動で入ります")
            s_name     = st.text_input("シリーズ名", placeholder="例：日本の呪われた場所47選", key="new_series_name")
            s_genre    = st.selectbox("ジャンル", GENRES, key="new_series_genre")
            s_template = st.text_input("テンプレート", placeholder="日本の呪われた場所47選 第{n}回：{pref}編", key="new_series_template")
            s_total    = st.number_input("全部で何回？", 1, 1000, 47, key="new_series_total")
            if st.button("✅ シリーズを作成する", key="create_series_btn", type="primary"):
                if s_name and s_template:
                    db.add_series(s_name, s_genre, s_template, int(s_total))
                    st.success(f"✅「{s_name}」を作成しました！"); st.rerun()
                else:
                    st.error("シリーズ名とテンプレートを入力してください")

        for s in db.get_all_series():
            progress = s["current"] / s["total"] if s["total"] > 0 else 0
            sc1, sc2 = st.columns([4, 1])
            with sc1:
                st.markdown(f"**{s['name']}**")
                st.caption(f"🏷️ {s['genre']}　{s['current']}/{s['total']}回（残り{s['total']-s['current']}回）")
                st.progress(progress)
            with sc2:
                if st.button("🗑️", key=f"del_series_{s['id']}", help="削除"):
                    db.delete_series(s["id"]); st.rerun()
            st.markdown("---")


# ═══════════════════════════════════════════════
# キュータブ
# ═══════════════════════════════════════════════
with tab_queue:
    st.markdown("## 📅 投稿スケジュール")
    st.caption("生成したコンテンツをストックして、日時を指定して投稿予約できます")

    with st.expander("📆 今週のスケジュール", expanded=True):
        today_    = date.today()
        week_days = [today_ + timedelta(days=i) for i in range(7)]
        cols_cal  = st.columns(7)
        all_queue = db.get_queue(posted=0)
        lm_       = {"post": "📱", "novel": "📖", "article": "📰"}
        for i, day in enumerate(week_days):
            with cols_cal[i]:
                is_today  = day == today_
                st.markdown(f"**{'今日' if is_today else day.strftime('%m/%d')}**")
                st.caption(['月','火','水','木','金','土','日'][day.weekday()])
                day_str   = day.strftime("%Y-%m-%d")
                day_items = [q for q in all_queue if (q.get("scheduled_at") or "").startswith(day_str)]
                for q in day_items:
                    time_str = q["scheduled_at"][11:16] if len(q.get("scheduled_at","")) > 10 else ""
                    st.caption(f"{lm_.get(q['content_type'],'📄')} {time_str}")
                if not day_items:
                    st.caption("─")

    qs1, qs2 = st.columns([3, 1])
    with qs1:
        queue_keyword = st.text_input("🔍 キューを検索", placeholder="内容・ジャンル・スタイルで絞り込み", key="queue_search_kw")
    with qs2:
        stats = db.get_queue_stats()
        st.metric("未投稿", f"{stats['pending']}件")

    queue_page = st.session_state.get("queue_page", 1)
    queue_items_page, queue_total = db.get_queue_page(queue_page, per_page=8, keyword=queue_keyword or None)
    queue_total_pages = max(1, math.ceil(queue_total / 8))

    if not queue_items_page and not queue_keyword:
        st.markdown('<div class="empty-state"><div style="font-size:2rem">📅</div><div>キューが空です<br><small>投稿を生成して「スケジュールに追加」を押してください</small></div></div>', unsafe_allow_html=True)
    else:
        st.markdown(f"**{queue_total}件の予約コンテンツ** — {queue_page}/{queue_total_pages}ページ")
        lm = {"post": "📱 投稿", "novel": "📖 小説", "article": "📰 記事"}
        for item in queue_items_page:
            label = lm.get(item["content_type"], item["content_type"])
            score = item.get("quality_score") or 0
            h1, h2, h3 = st.columns([3, 1, 1])
            with h1:
                ab_badge = f"　🅐🅑 グループ{item['ab_group']}" if item.get("ab_group") else ""
                st.markdown(f"**{label}** ｜ {item['genre']}　{item['style'] or ''}{ab_badge}")
                st.caption(f"🕐 {item.get('scheduled_at') or '予約日時未設定'}　📊 品質: {score:.0f}点")
            with h2:
                new_date = st.date_input("投稿日", key=f"q_date_{item['id']}", label_visibility="collapsed")
                new_time = st.time_input("投稿時刻", key=f"q_time_{item['id']}", label_visibility="collapsed")
            with h3:
                if st.button("⏰ 予約する", key=f"q_sched_{item['id']}", use_container_width=True):
                    db.update_queue_schedule(item["id"], datetime.combine(new_date, new_time).strftime("%Y-%m-%d %H:%M"))
                    st.success("予約しました！"); st.rerun()
            with st.expander("内容を確認する・投稿する・リライトする"):
                st.text(item["content"][:400] + ("..." if len(item["content"]) > 400 else ""))
                if item.get("hashtags"):
                    st.markdown(f'<div class="hashtag-box">{item["hashtags"]}</div>', unsafe_allow_html=True)
                rw_style = st.selectbox("別のスタイルでリライトする", ["リライトしない"] + STYLES, key=f"rw_style_{item['id']}")
                if rw_style != "リライトしない":
                    if st.button("🔄 リライト実行", key=f"rw_btn_{item['id']}", use_container_width=True):
                        with st.spinner("書き直し中..."):
                            try:
                                rw = rewrite_content(item["content"], rw_style, item.get("genre", ""), get_x_safe())
                                db.add_to_queue("post", item.get("genre", ""), rw_style, rw, item.get("hashtags", ""), calc_quality_score(rw))
                                st.success("✅ リライト版をスケジュールに追加しました！"); st.rerun()
                            except Exception as e:
                                st.error(f"エラー: {e}")
                full_text = post_full_text(item["content"], item.get("hashtags", ""))
                b1, b2, b3 = st.columns(3)
                with b1:
                    if st.button("📋 Xにコピー", key=f"q_copy_{item['id']}", use_container_width=True):
                        copy_to_clipboard(full_text); st.success("コピーしました！")
                with b2:
                    if st.button("🅣 Threadsに投稿", key=f"q_threads_{item['id']}", use_container_width=True):
                        with st.spinner("投稿中..."):
                            r = post_to_threads(full_text)
                            if r["success"]:
                                db.mark_queue_posted(item["id"]); st.success("✅ 投稿しました！"); st.rerun()
                            else:
                                st.error(r["error"])
                with b3:
                    if st.button("🗑️ 削除", key=f"q_del_{item['id']}", use_container_width=True):
                        db.delete_from_queue(item["id"]); st.rerun()
            st.markdown("---")

    if queue_total_pages > 1:
        pg1, pg2, pg3 = st.columns([1, 3, 1])
        with pg1:
            if st.button("◀ 前へ", key="queue_prev", disabled=queue_page <= 1):
                st.session_state["queue_page"] = queue_page - 1; st.rerun()
        with pg2:
            st.markdown(f"<div style='text-align:center'>{queue_page} / {queue_total_pages}ページ</div>", unsafe_allow_html=True)
        with pg3:
            if st.button("次へ ▶", key="queue_next", disabled=queue_page >= queue_total_pages):
                st.session_state["queue_page"] = queue_page + 1; st.rerun()

    posted_items = db.get_queue(posted=1)
    if posted_items:
        with st.expander(f"✅ 投稿済み一覧 ({len(posted_items)}件)"):
            lm_s = {"post": "📱", "novel": "📖", "article": "📰"}
            for item in posted_items[-10:]:
                st.caption(f"{lm_s.get(item['content_type'],'📄')} {item['genre']} ｜ {item.get('posted_at') or item['created_at']}")


# ═══════════════════════════════════════════════
# 履歴タブ
# ═══════════════════════════════════════════════
with tab_history:
    st.markdown("## 📚 生成履歴")
    st.caption("これまでに生成したすべてのコンテンツを検索・再利用できます")

    hist_tab1, hist_tab2 = st.tabs(["🔍 検索・再利用", "🏆 高品質ランキング"])

    with hist_tab1:
        hc1, hc2, hc3 = st.columns([3, 2, 1])
        with hc1:
            search_kw = st.text_input("🔍 キーワードで検索", placeholder="例：廃村、消えた、隣人", key="history_search")
        with hc2:
            ct_filter = st.selectbox("種類で絞り込む", ["すべて", "投稿（post）", "小説（novel）", "記事（article）"], key="history_ct_filter")
        with hc3:
            hist_per_page = st.selectbox("表示件数", [10, 20, 50], key="hist_per_page")

        ct_map     = {"投稿（post）": "post", "小説（novel）": "novel", "記事（article）": "article"}
        filter_arg = ct_map.get(ct_filter)
        hist_page  = st.session_state.get("hist_page", 1)
        results, hist_total = db.get_content_page(hist_page, hist_per_page, filter_arg, search_kw or None)
        hist_total_pages = max(1, math.ceil(hist_total / hist_per_page))

        if not results and not search_kw:
            st.markdown('<div class="empty-state"><div style="font-size:2rem">📚</div><div>まだ生成履歴がありません<br><small>「投稿をつくる」タブで文章を生成すると、ここに記録されます</small></div></div>', unsafe_allow_html=True)
        else:
            all_results, _ = db.get_content_page(1, 10000, filter_arg, search_kw or None)
            if all_results:
                buf_csv = io.StringIO()
                w_csv   = csv.DictWriter(buf_csv, ["content_type","genre","style","content","quality_score","created_at"])
                w_csv.writeheader()
                w_csv.writerows([{k: r[k] for k in ["content_type","genre","style","content","quality_score","created_at"]} for r in all_results])
                st.download_button("📤 全履歴をCSVで書き出す", data=buf_csv.getvalue().encode("utf-8-sig"), file_name="history.csv", mime="text/csv")

            tl = {"post": "📱 投稿", "novel": "📖 小説", "article": "📰 記事"}
            st.caption(f"{hist_total}件中 {(hist_page-1)*hist_per_page+1}〜{min(hist_page*hist_per_page, hist_total)}件")
            for r in results:
                sc = r.get("quality_score") or 0
                with st.container():
                    h1, h2 = st.columns([5, 1])
                    with h1:
                        st.markdown(f"{tl.get(r['content_type'],'📄')} **{r['genre']}** {r['style'] or ''}　📊 {sc:.0f}点")
                        st.caption(f"🕐 {r['created_at']}")
                        st.markdown(f'<div class="guide-box">{r["content"][:180]}{"..." if len(r["content"]) > 180 else ""}</div>', unsafe_allow_html=True)
                    with h2:
                        if st.button("再利用", key=f"reuse_{r['id']}", use_container_width=True):
                            st.session_state["post_pending"] = r["content"]
                            st.session_state["post_content"] = r["content"]
                            st.session_state["post_score"]   = sc
                            st.success("📱 投稿タブに読み込みました！")
                        if st.button("追加", key=f"hist_queue_{r['id']}", use_container_width=True):
                            db.add_to_queue(r["content_type"], r["genre"], r["style"] or "", r["content"], "", sc)
                            st.success("📅 追加しました！")
                st.markdown("---")

            if hist_total_pages > 1:
                hp1, hp2, hp3 = st.columns([1, 3, 1])
                with hp1:
                    if st.button("◀ 前へ", key="hist_prev", disabled=hist_page <= 1):
                        st.session_state["hist_page"] = hist_page - 1; st.rerun()
                with hp2:
                    st.markdown(f"<div style='text-align:center'>{hist_page} / {hist_total_pages}ページ</div>", unsafe_allow_html=True)
                with hp3:
                    if st.button("次へ ▶", key="hist_next", disabled=hist_page >= hist_total_pages):
                        st.session_state["hist_page"] = hist_page + 1; st.rerun()

    with hist_tab2:
        st.caption("品質スコアが高いコンテンツをリライトして再利用できます")
        top_content = db.get_top_content(20)
        if not top_content:
            st.info("まだデータがありません")
        else:
            tl2 = {"post": "📱", "novel": "📖", "article": "📰"}
            for r in top_content:
                sc = r.get("quality_score") or 0
                st.markdown(f"{tl2.get(r['content_type'],'📄')} **{r['genre']}** ｜ 📊 {sc:.0f}点")
                st.caption(r["content"][:150] + "...")
                rw1, rw2, rw3 = st.columns(3)
                with rw1: rw_s = st.selectbox("スタイル", STYLES, key=f"top_rw_style_{r['id']}")
                with rw2:
                    if st.button("🔄 リライト", key=f"top_rw_{r['id']}", use_container_width=True):
                        with st.spinner("書き直し中..."):
                            try:
                                rw = rewrite_content(r["content"], rw_s, r.get("genre",""), get_x_safe())
                                db.add_to_queue("post", r.get("genre",""), rw_s, rw, "", calc_quality_score(rw))
                                st.success("✅ スケジュールに追加しました！")
                            except Exception as e:
                                st.error(f"エラー: {e}")
                with rw3:
                    if st.button("📅 そのまま追加", key=f"top_queue_{r['id']}", use_container_width=True):
                        db.add_to_queue(r["content_type"], r.get("genre",""), r.get("style",""), r["content"], "", sc)
                        st.success("追加しました！")
                st.markdown("---")


# ═══════════════════════════════════════════════
# 分析タブ
# ═══════════════════════════════════════════════
with tab_analysis:
    st.markdown("## 📊 分析レポート")
    st.caption("投稿のパフォーマンスを記録して、伸びやすいパターンを学習します")

    ana_tab1, ana_tab2, ana_tab3, ana_tab4, ana_tab5 = st.tabs([
        "📈 グラフ", "✍️ 成果を記録する", "🅐🅑 A/Bテスト結果", "👥 フォロワー推移", "💰 収益レポート"
    ])
    perf_data = db.get_performance_data()

    with ana_tab1:
        if not perf_data:
            st.markdown("""
            <div class="empty-state">
            <div style="font-size:2rem">📊</div>
            <div style="font-size:1.1rem">まだデータがありません</div>
            <div style="font-size:0.85rem;color:#666;margin-top:8px">
            「成果を記録する」タブで投稿後のいいね・リポスト数を入力すると<br>
            スタイル別・ジャンル別の分析グラフが表示されます
            </div>
            </div>""", unsafe_allow_html=True)
        else:
            df = pd.DataFrame(perf_data)
            df["engage"] = df["likes"] + df["reposts"]
            if "style" in df.columns and df["style"].notna().any():
                style_df = df[df["style"].notna() & (df["style"] != "")].groupby("style")["engage"].mean().reset_index()
                style_df.columns = ["スタイル", "平均エンゲージ"]
                fig1 = px.bar(style_df, x="スタイル", y="平均エンゲージ", title="スタイル別 平均エンゲージ",
                              color="平均エンゲージ", color_continuous_scale="reds")
                fig1.update_layout(paper_bgcolor="#0d0d0d", plot_bgcolor="#1a1a1a", font_color="#e8e8e8")
                st.plotly_chart(fig1, use_container_width=True)
            genre_df = df.groupby("genre")["engage"].mean().reset_index()
            genre_df.columns = ["ジャンル", "平均エンゲージ"]
            fig2 = px.pie(genre_df, names="ジャンル", values="平均エンゲージ", title="ジャンル別 割合",
                          color_discrete_sequence=px.colors.sequential.Reds_r)
            fig2.update_layout(paper_bgcolor="#0d0d0d", font_color="#e8e8e8")
            st.plotly_chart(fig2, use_container_width=True)
            if len(df) >= 2:
                df["recorded_at"] = pd.to_datetime(df["recorded_at"])
                fig3 = px.line(df.sort_values("recorded_at"), x="recorded_at", y="engage", title="エンゲージ推移",
                               markers=True, color_discrete_sequence=["#ff4444"])
                fig3.update_layout(paper_bgcolor="#0d0d0d", plot_bgcolor="#1a1a1a", font_color="#e8e8e8")
                st.plotly_chart(fig3, use_container_width=True)
            top = db.get_top_patterns()
            if top:
                st.markdown("### 🏆 伸びやすいパターン TOP3")
                st.caption("このパターンは次回の生成に自動で反映されます")
                for i, p in enumerate(top[:3]):
                    st.markdown(f"**{i+1}位** ジャンル「{p['genre']}」× スタイル「{p['style']}」　平均エンゲージ: {p['avg_engage']:.1f}")
            buf_perf = io.StringIO()
            csv.DictWriter(buf_perf, ["platform","genre","style","content_type","likes","reposts","replies","impressions","recorded_at"]).writeheader()
            csv.DictWriter(buf_perf, ["platform","genre","style","content_type","likes","reposts","replies","impressions","recorded_at"]).writerows(
                [{k: r.get(k,"") for k in ["platform","genre","style","content_type","likes","reposts","replies","impressions","recorded_at"]} for r in perf_data])
            st.download_button("📤 分析データをCSVで書き出す", data=buf_perf.getvalue().encode("utf-8-sig"), file_name="performance.csv", mime="text/csv")

    with ana_tab2:
        st.markdown("### ✍️ 投稿の成果を記録する")
        st.caption("投稿後にいいね・リポスト数を入力してください。データが溜まるほどAIの精度が上がります")
        posted = db.get_queue(posted=1)
        if not posted:
            st.info("投稿済みコンテンツがありません")
        else:
            rec_opts = {f"[{i['content_type']}] {i['genre']} {i['style'] or ''} ({i.get('posted_at') or i['created_at']})": i for i in posted[-20:]}
            rec_label = st.selectbox("成果を記録する投稿を選ぶ", list(rec_opts.keys()), key="rec_select")
            rec_item  = rec_opts[rec_label]
            rec_platform = st.radio("SNSを選ぶ", ["Threads", "X（Twitter）"], key="rec_platform", horizontal=True)
            rc1, rc2, rc3, rc4 = st.columns(4)
            with rc1: rec_likes   = st.number_input("👍 いいね", 0, 1_000_000, 0, key="rec_likes")
            with rc2: rec_reposts = st.number_input("🔁 リポスト", 0, 1_000_000, 0, key="rec_reposts")
            with rc3: rec_replies = st.number_input("💬 返信", 0, 1_000_000, 0, key="rec_replies")
            with rc4: rec_imp     = st.number_input("👁️ インプレ", 0, 10_000_000, 0, key="rec_impressions")
            if st.button("💾 記録する", type="primary", key="save_perf", use_container_width=True):
                db.save_performance(rec_item["id"], rec_platform, rec_item.get("genre",""), rec_item.get("style",""),
                                    rec_item.get("content_type",""), rec_likes, rec_reposts, rec_replies, rec_imp, rec_item.get("ab_group"))
                st.success("✅ 記録しました！次回の生成に反映されます")

    with ana_tab3:
        st.markdown("### 🅐🅑 A/Bテスト結果")
        if not perf_data:
            st.info("まだデータがありません")
        else:
            df_ab = pd.DataFrame(perf_data)
            df_ab = df_ab[df_ab["ab_group"].notna() & (df_ab["ab_group"] != "")]
            if df_ab.empty:
                st.info("A/Bテストのデータがありません。「投稿をつくる」タブでA/Bテストモードを使ってください")
            else:
                df_ab["engage"] = df_ab["likes"] + df_ab["reposts"]
                fig_ab = px.bar(df_ab.groupby(["ab_group","style"])["engage"].mean().reset_index(),
                                x="ab_group", y="engage", color="style", title="A/Bグループ別 平均エンゲージ",
                                labels={"ab_group":"グループ","engage":"平均エンゲージ"})
                fig_ab.update_layout(paper_bgcolor="#0d0d0d", plot_bgcolor="#1a1a1a", font_color="#e8e8e8")
                st.plotly_chart(fig_ab, use_container_width=True)

    with ana_tab4:
        st.markdown("### 👥 フォロワー数の推移")
        fw1, fw2 = st.columns([2, 3])
        with fw1:
            fw_platform = st.selectbox("SNS", ["Threads", "X（Twitter）"], key="fw_platform")
            fw_count    = st.number_input("今のフォロワー数", 0, 10_000_000, 0, key="fw_count")
            if st.button("📈 今日の数字を記録する", key="fw_record", type="primary", use_container_width=True):
                db.add_follower_record(fw_platform, fw_count); st.success("✅ 記録しました！"); st.rerun()
        with fw2:
            fw_history = db.get_follower_history()
            if fw_history:
                df_fw = pd.DataFrame(fw_history)
                for platform in df_fw["platform"].unique():
                    df_p = df_fw[df_fw["platform"] == platform]
                    if len(df_p) >= 2:
                        delta = int(df_p["count"].iloc[-1]) - int(df_p["count"].iloc[-2])
                        st.metric(platform, f"{df_p['count'].iloc[-1]:,}人", f"{delta:+,}人")
                fig_fw = px.line(df_fw, x="recorded_at", y="count", color="platform", title="フォロワー数推移", markers=True)
                fig_fw.update_layout(paper_bgcolor="#0d0d0d", plot_bgcolor="#1a1a1a", font_color="#e8e8e8")
                st.plotly_chart(fig_fw, use_container_width=True)
            else:
                st.info("左でフォロワー数を記録してください")

    with ana_tab5:
        st.markdown("### 💰 収益レポート")
        rv1, rv2 = st.columns([2, 3])
        with rv1:
            rv_source = st.selectbox("収益の種類", ["Amazonアフィリエイト","note売上","その他"], key="rv_source")
            rv_amount = st.number_input("金額（円）", 0, 10_000_000, 0, key="rv_amount")
            rv_note   = st.text_input("メモ", key="rv_note", placeholder="例：ホラー本の紹介記事から")
            if st.button("💾 収益を記録する", key="rv_record", type="primary", use_container_width=True):
                db.add_revenue(rv_source, rv_amount, rv_note); st.success("✅ 記録しました！"); st.rerun()
        with rv2:
            total = db.get_revenue_total()
            st.metric("💰 累計収益", f"¥{total:,.0f}")
            rv_logs = db.get_revenue_log()
            if rv_logs:
                df_rv = pd.DataFrame(rv_logs)
                fig_rv = px.bar(df_rv.groupby("source")["amount"].sum().reset_index(),
                                x="source", y="amount", title="収益源別 累計", color="amount", color_continuous_scale="reds")
                fig_rv.update_layout(paper_bgcolor="#0d0d0d", plot_bgcolor="#1a1a1a", font_color="#e8e8e8")
                st.plotly_chart(fig_rv, use_container_width=True)
                for log in rv_logs[:10]:
                    st.caption(f"💴 ¥{log['amount']:,.0f} ｜ {log['source']} ｜ {log.get('note','')} ｜ {log['recorded_at']}")
            else:
                st.info("収益を記録してください")


# ═══════════════════════════════════════════════
# まとめて生成タブ
# ═══════════════════════════════════════════════
with tab_batch:
    st.markdown("## ⚡ まとめて生成する")
    st.caption("同じネタを複数のスタイルで一気に生成して、スケジュールにまとめて追加できます")

    bc1, bc2 = st.columns([1, 1])
    with bc1:
        batch_genre  = st.selectbox("ジャンル", GENRES, key="batch_genre")
        batch_idea   = st.text_area("ネタを入力してください", key="batch_idea", height=100,
                                    placeholder="例：廃墟に一人で行ったら想定外のことが起きた")
        batch_chars  = st.slider("文字数", 100, 500, 200, 50, key="batch_chars")
        batch_styles = st.multiselect(
            "生成するスタイルを選んでください（複数選択可）",
            STYLES,
            default=["会話風", "独り言・日記風", "ニュース・報告風", "途中で途切れる風"],
            key="batch_styles",
        )
        st.caption(f"📊 {len(batch_styles)}パターン生成します（約{len(batch_styles)*15}秒かかります）")

        if st.button("⚡ まとめて生成する", type="primary", key="batch_generate", use_container_width=True, disabled=not api_key_set()):
            if not require_api_key():
                pass
            elif not batch_idea.strip():
                st.error("ネタを入力してください")
            elif not batch_styles:
                st.error("スタイルを1つ以上選んでください")
            else:
                with st.spinner(f"{len(batch_styles)}パターンを生成中..."):
                    results = batch_generate_posts(batch_genre, batch_idea, batch_styles, batch_chars, get_x_safe())
                    for r in results:
                        r["score"] = calc_quality_score(r["content"])
                    st.session_state["batch_results"] = results
                    st.toast(f"✅ {len(results)}件の生成が完了しました！", icon="⚡")
        if not api_key_set():
            st.caption("⚠️ サイドバーでAPIキーを設定してください")

    with bc2:
        st.markdown("### 生成結果")
        batch_results = st.session_state.get("batch_results", [])
        if not batch_results:
            st.markdown('<div class="empty-state"><div style="font-size:2rem">⚡</div><div>左で設定してまとめて生成してください</div></div>', unsafe_allow_html=True)
        else:
            if st.button("📅 全件スケジュールに追加する", key="batch_queue_all", type="primary", use_container_width=True):
                for r in batch_results:
                    db.add_to_queue("post", batch_genre, r["style"], r["content"], "", r["score"])
                st.success(f"✅ {len(batch_results)}件をスケジュールに追加しました！")
            for i, r in enumerate(batch_results):
                sc    = r["score"]
                emoji = "✨" if sc >= 75 else "👍" if sc >= 50 else "⚠️"
                with st.expander(f"{emoji} **{r['style']}** — 品質{sc:.0f}点"):
                    st.text(r["content"][:300] + ("..." if len(r["content"]) > 300 else ""))
                    rb1, rb2 = st.columns(2)
                    with rb1:
                        if st.button("📅 スケジュールに追加", key=f"batch_q_{i}", use_container_width=True):
                            db.add_to_queue("post", batch_genre, r["style"], r["content"], "", sc); st.success("追加しました！")
                    with rb2:
                        if st.button("📋 コピーする", key=f"batch_copy_{i}", use_container_width=True):
                            copy_to_clipboard(r["content"]); st.success("コピーしました！")
