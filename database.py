import os
import sqlite3
from pathlib import Path

# 環境変数 DB_PATH が設定されていればそちらを使用（Docker volume対応）
DB_PATH = Path(os.getenv("DB_PATH", str(Path(__file__).parent / "kowamoshiro.db")))


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS ideas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            genre TEXT NOT NULL,
            description TEXT,
            used INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS generated_content (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_type TEXT NOT NULL,
            genre TEXT,
            style TEXT,
            content TEXT NOT NULL,
            quality_score REAL,
            posted INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_type TEXT NOT NULL,
            genre TEXT,
            style TEXT,
            content TEXT NOT NULL,
            hashtags TEXT,
            quality_score REAL,
            scheduled_at TIMESTAMP,
            posted INTEGER DEFAULT 0,
            posted_at TIMESTAMP,
            ab_group TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS trend_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT NOT NULL,
            summary TEXT,
            source TEXT,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Phase 3: シリーズ管理
    c.execute("""
        CREATE TABLE IF NOT EXISTS series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            genre TEXT NOT NULL,
            template TEXT NOT NULL,
            total INTEGER NOT NULL,
            current INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Phase 4: パフォーマンス記録
    c.execute("""
        CREATE TABLE IF NOT EXISTS performance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            queue_id INTEGER,
            platform TEXT,
            genre TEXT,
            style TEXT,
            content_type TEXT,
            likes INTEGER DEFAULT 0,
            reposts INTEGER DEFAULT 0,
            replies INTEGER DEFAULT 0,
            impressions INTEGER DEFAULT 0,
            ab_group TEXT,
            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Phase 3: スケジューラ設定
    c.execute("""
        CREATE TABLE IF NOT EXISTS scheduler_config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # 初期ネタバンクデータ
    c.execute("SELECT COUNT(*) FROM ideas")
    if c.fetchone()[0] == 0:
        seed_ideas = [
            ("廃村の住人", "都市伝説・未解決事件", "10年前に全住民が失踪した山奥の村の話"),
            ("隣人の正体", "ホラー体験談・怪談", "引っ越し先のマンションの隣人が毎晩壁を叩いてくる"),
            ("検索してはいけないワード", "不思議・オカルト・陰謀論", "ある検索ワードを入力すると必ず不幸が起きるという都市伝説"),
            ("SNSで知り合った人", "サイコ・ダークな人間ドラマ", "オンラインで知り合った人物が実は…"),
            ("47都道府県の呪われた場所：青森", "都市伝説・未解決事件", "青森県に実在する心霊スポットの真相"),
            ("元警察官の証言", "不思議・オカルト・陰謀論", "定年退職した元警察官が語った、表に出ない未解決事件"),
            ("田舎の廃村ルポ", "ホラー体験談・怪談", "一人で廃村に行ったら想定外のものを見た話"),
            ("AIとの会話", "不思議・オカルト・陰謀論", "AIチャットボットと会話してたら返答がおかしくなってきた"),
        ]
        c.executemany(
            "INSERT INTO ideas (title, genre, description) VALUES (?, ?, ?)",
            seed_ideas
        )

    # 初期シリーズデータ
    c.execute("SELECT COUNT(*) FROM series")
    if c.fetchone()[0] == 0:
        seed_series = [
            ("日本の呪われた場所47選", "都市伝説・未解決事件", "日本の呪われた場所47選 第{n}回：{pref}編", 47),
            ("世界の未解決事件100選", "都市伝説・未解決事件", "世界の未解決事件100選 第{n}回", 100),
            ("読んだら後悔する実話", "ホラー体験談・怪談", "読んだら後悔する実話 第{n}話", 50),
        ]
        c.executemany(
            "INSERT INTO series (name, genre, template, total) VALUES (?, ?, ?, ?)",
            seed_series
        )

    conn.commit()
    conn.close()


# ── ネタバンク ──────────────────────────────────

def get_all_ideas(genre=None):
    conn = get_connection()
    c = conn.cursor()
    if genre and genre != "すべて":
        c.execute("SELECT * FROM ideas WHERE genre = ? ORDER BY used ASC, created_at DESC", (genre,))
    else:
        c.execute("SELECT * FROM ideas ORDER BY used ASC, created_at DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_idea(title, genre, description=""):
    conn = get_connection()
    conn.execute(
        "INSERT INTO ideas (title, genre, description) VALUES (?, ?, ?)",
        (title, genre, description)
    )
    conn.commit()
    conn.close()


def delete_idea(idea_id):
    conn = get_connection()
    conn.execute("DELETE FROM ideas WHERE id = ?", (idea_id,))
    conn.commit()
    conn.close()


def mark_idea_used(idea_id):
    conn = get_connection()
    conn.execute("UPDATE ideas SET used = used + 1 WHERE id = ?", (idea_id,))
    conn.commit()
    conn.close()


# ── 生成履歴 ────────────────────────────────────

def save_content(content_type, genre, style, content, quality_score):
    conn = get_connection()
    conn.execute(
        "INSERT INTO generated_content (content_type, genre, style, content, quality_score) VALUES (?, ?, ?, ?, ?)",
        (content_type, genre, style, content, quality_score)
    )
    conn.commit()
    conn.close()


# ── キュー ──────────────────────────────────────

def add_to_queue(content_type, genre, style, content, hashtags="", quality_score=0.0, scheduled_at=None, ab_group=None):
    conn = get_connection()
    conn.execute(
        "INSERT INTO queue (content_type, genre, style, content, hashtags, quality_score, scheduled_at, ab_group) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (content_type, genre, style, content, hashtags, quality_score, scheduled_at, ab_group)
    )
    conn.commit()
    conn.close()


def get_queue(posted=0):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM queue WHERE posted = ? ORDER BY scheduled_at ASC, created_at ASC", (posted,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_due_queue_items():
    """投稿予定時刻を過ぎた未投稿アイテムを取得"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM queue
        WHERE posted = 0 AND scheduled_at IS NOT NULL AND scheduled_at <= datetime('now', '+9 hours')
        ORDER BY scheduled_at ASC
    """)
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_queue_schedule(queue_id, scheduled_at):
    conn = get_connection()
    conn.execute("UPDATE queue SET scheduled_at = ? WHERE id = ?", (scheduled_at, queue_id))
    conn.commit()
    conn.close()


def delete_from_queue(queue_id):
    conn = get_connection()
    conn.execute("DELETE FROM queue WHERE id = ?", (queue_id,))
    conn.commit()
    conn.close()


def mark_queue_posted(queue_id):
    conn = get_connection()
    conn.execute("UPDATE queue SET posted = 1, posted_at = datetime('now', '+9 hours') WHERE id = ?", (queue_id,))
    conn.commit()
    conn.close()


# ── トレンドキャッシュ ──────────────────────────

def save_trends(trends: list[dict]):
    conn = get_connection()
    conn.execute("DELETE FROM trend_cache")
    for t in trends:
        conn.execute(
            "INSERT INTO trend_cache (keyword, summary, source) VALUES (?, ?, ?)",
            (t.get("keyword", ""), t.get("summary", ""), t.get("source", ""))
        )
    conn.commit()
    conn.close()


def get_trends():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM trend_cache ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── シリーズ管理 ────────────────────────────────

def get_all_series():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM series ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_series(name, genre, template, total):
    conn = get_connection()
    conn.execute(
        "INSERT INTO series (name, genre, template, total) VALUES (?, ?, ?, ?)",
        (name, genre, template, total)
    )
    conn.commit()
    conn.close()


def advance_series(series_id):
    conn = get_connection()
    conn.execute("UPDATE series SET current = current + 1 WHERE id = ?", (series_id,))
    conn.commit()
    conn.close()


def delete_series(series_id):
    conn = get_connection()
    conn.execute("DELETE FROM series WHERE id = ?", (series_id,))
    conn.commit()
    conn.close()


# ── パフォーマンス記録 ──────────────────────────

def save_performance(queue_id, platform, genre, style, content_type, likes, reposts, replies, impressions, ab_group=None):
    conn = get_connection()
    conn.execute("""
        INSERT INTO performance (queue_id, platform, genre, style, content_type, likes, reposts, replies, impressions, ab_group)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (queue_id, platform, genre, style, content_type, likes, reposts, replies, impressions, ab_group))
    conn.commit()
    conn.close()


def get_performance_data():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM performance ORDER BY recorded_at DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_top_patterns(limit=5):
    """エンゲージ率が高いスタイル×ジャンルの組み合わせを返す"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT genre, style, content_type,
               AVG(likes + reposts) as avg_engage,
               COUNT(*) as count
        FROM performance
        WHERE style IS NOT NULL AND style != ''
        GROUP BY genre, style, content_type
        HAVING count >= 1
        ORDER BY avg_engage DESC
        LIMIT ?
    """, (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── スケジューラ設定 ────────────────────────────

def get_scheduler_config(key, default=None):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT value FROM scheduler_config WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row["value"] if row else default


def set_scheduler_config(key, value):
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO scheduler_config (key, value) VALUES (?, ?)",
        (key, str(value))
    )
    conn.commit()
    conn.close()


# ── 生成履歴検索・再利用 ────────────────────────

def search_content(keyword: str, content_type: str = None):
    conn = get_connection()
    c = conn.cursor()
    if content_type:
        c.execute(
            "SELECT * FROM generated_content WHERE content LIKE ? AND content_type = ? ORDER BY created_at DESC LIMIT 50",
            (f"%{keyword}%", content_type)
        )
    else:
        c.execute(
            "SELECT * FROM generated_content WHERE content LIKE ? ORDER BY created_at DESC LIMIT 50",
            (f"%{keyword}%",)
        )
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_top_content(limit: int = 20):
    """品質スコアが高い生成履歴を返す"""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM generated_content ORDER BY quality_score DESC LIMIT ?",
        (limit,)
    )
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_content(limit: int = 200):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM generated_content ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── CSVインポート ────────────────────────────────

def import_ideas_csv(rows: list[dict]) -> int:
    """CSVから読み込んだネタをまとめてDBに追加。成功件数を返す。"""
    conn = get_connection()
    count = 0
    for row in rows:
        title = str(row.get("title", row.get("タイトル", ""))).strip()
        genre = str(row.get("genre", row.get("ジャンル", ""))).strip()
        desc = str(row.get("description", row.get("説明", ""))).strip()
        if title and genre:
            conn.execute(
                "INSERT INTO ideas (title, genre, description) VALUES (?, ?, ?)",
                (title, genre, desc)
            )
            count += 1
    conn.commit()
    conn.close()
    return count


# ── ハッシュタグパフォーマンス集計 ──────────────

def get_top_hashtags(limit: int = 20) -> list[str]:
    """過去パフォーマンスの良い投稿から使われたハッシュタグを抽出する。"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT q.hashtags, p.likes + p.reposts as engage
        FROM performance p
        JOIN queue q ON p.queue_id = q.id
        WHERE q.hashtags IS NOT NULL AND q.hashtags != ''
        ORDER BY engage DESC
        LIMIT 30
    """)
    rows = c.fetchall()
    conn.close()
    tag_scores: dict[str, int] = {}
    for row in rows:
        for tag in str(row["hashtags"]).split():
            if tag.startswith("#"):
                tag_scores[tag] = tag_scores.get(tag, 0) + (row["engage"] or 0)
    sorted_tags = sorted(tag_scores, key=lambda t: tag_scores[t], reverse=True)
    return sorted_tags[:limit]


# ── Threadsトークン管理 ──────────────────────────

# ── 文体プロファイル（青空文庫学習）──────────────

def save_style_profile(author_name: str, analysis: str):
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO scheduler_config (key, value) VALUES (?, ?)",
        (f"style_profile_{author_name}", analysis)
    )
    conn.commit()
    conn.close()


def get_style_profile(author_name: str) -> str | None:
    return get_scheduler_config(f"style_profile_{author_name}")


def get_all_style_profiles() -> dict:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT key, value FROM scheduler_config WHERE key LIKE 'style_profile_%'")
    rows = c.fetchall()
    conn.close()
    return {r["key"].replace("style_profile_", ""): r["value"] for r in rows}


def set_threads_token_date(issued_date: str):
    set_scheduler_config("threads_token_issued", issued_date)


def get_threads_token_days_left() -> int | None:
    from datetime import date
    issued_str = get_scheduler_config("threads_token_issued")
    if not issued_str:
        return None
    try:
        issued = date.fromisoformat(issued_str)
        expiry = issued.replace(day=issued.day)
        from datetime import timedelta
        expiry = issued + timedelta(days=60)
        remaining = (expiry - date.today()).days
        return remaining
    except Exception:
        return None


# ── フォロワー数・収益記録 ──────────────────────────

def init_follower_revenue_tables():
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS follower_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            count INTEGER NOT NULL,
            recorded_at DATE DEFAULT (date('now', '+9 hours'))
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS revenue_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            amount REAL NOT NULL,
            note TEXT,
            recorded_at DATE DEFAULT (date('now', '+9 hours'))
        )
    """)
    conn.commit()
    conn.close()


def add_follower_record(platform: str, count: int):
    conn = get_connection()
    conn.execute("INSERT INTO follower_history (platform, count) VALUES (?, ?)", (platform, count))
    conn.commit()
    conn.close()


def get_follower_history(platform: str = None):
    conn = get_connection()
    c = conn.cursor()
    if platform:
        c.execute("SELECT * FROM follower_history WHERE platform = ? ORDER BY recorded_at ASC", (platform,))
    else:
        c.execute("SELECT * FROM follower_history ORDER BY recorded_at ASC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_revenue(source: str, amount: float, note: str = ""):
    conn = get_connection()
    conn.execute("INSERT INTO revenue_log (source, amount, note) VALUES (?, ?, ?)", (source, amount, note))
    conn.commit()
    conn.close()


def get_revenue_log():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM revenue_log ORDER BY recorded_at DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_revenue_total():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT SUM(amount) as total FROM revenue_log")
    row = c.fetchone()
    conn.close()
    return row["total"] or 0.0


# ── DBバックアップ ────────────────────────────────

def backup_database() -> bytes:
    """DBファイルをzipに圧縮してbytesで返す。"""
    import zipfile, io, shutil
    from datetime import datetime
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(DB_PATH, arcname=f"kowamoshiro_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    return buf.getvalue()


# ── コンテンツ重複チェック ──────────────────────────

def is_duplicate_content(content: str, threshold: float = 0.85) -> bool:
    """
    過去生成履歴と類似度チェック。
    簡易実装: 最近50件のコンテンツと先頭100文字を比較。
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT content FROM generated_content ORDER BY created_at DESC LIMIT 50")
    rows = c.fetchall()
    conn.close()

    sample = content[:100]
    for row in rows:
        existing = row["content"][:100]
        # 文字レベルの一致率
        matches = sum(a == b for a, b in zip(sample, existing))
        similarity = matches / max(len(sample), 1)
        if similarity >= threshold:
            return True
    return False


# ── ページネーション ──────────────────────────────

def get_content_page(page: int = 1, per_page: int = 20,
                      content_type: str | None = None,
                      keyword: str | None = None) -> tuple[list[dict], int]:
    """
    生成履歴をページネーションで取得。
    Returns: (items, total_count)
    """
    conn = get_connection()
    c = conn.cursor()

    conditions = []
    params: list = []
    if content_type:
        conditions.append("content_type = ?")
        params.append(content_type)
    if keyword:
        conditions.append("content LIKE ?")
        params.append(f"%{keyword}%")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    c.execute(f"SELECT COUNT(*) FROM generated_content {where}", params)
    total = c.fetchone()[0]

    offset = (page - 1) * per_page
    c.execute(
        f"SELECT * FROM generated_content {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [per_page, offset]
    )
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows], total


def get_queue_page(page: int = 1, per_page: int = 10,
                   keyword: str | None = None) -> tuple[list[dict], int]:
    """キューをページネーションで取得。"""
    conn = get_connection()
    c = conn.cursor()

    conditions = ["posted = 0"]
    params: list = []
    if keyword:
        conditions.append("(content LIKE ? OR genre LIKE ? OR style LIKE ?)")
        params.extend([f"%{keyword}%"] * 3)

    where = "WHERE " + " AND ".join(conditions)

    c.execute(f"SELECT COUNT(*) FROM queue {where}", params)
    total = c.fetchone()[0]

    offset = (page - 1) * per_page
    c.execute(
        f"SELECT * FROM queue {where} ORDER BY scheduled_at ASC, created_at ASC LIMIT ? OFFSET ?",
        params + [per_page, offset]
    )
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows], total


# ── キュー統計 ────────────────────────────────────

def get_queue_stats() -> dict:
    """キューの統計情報を返す。"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM queue WHERE posted = 0")
    pending = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM queue WHERE posted = 1")
    posted = c.fetchone()[0]
    c.execute("SELECT AVG(quality_score) FROM queue WHERE posted = 0")
    avg_score = c.fetchone()[0] or 0.0
    conn.close()
    return {"pending": pending, "posted": posted, "avg_score": round(avg_score, 1)}


# ── 心霊スポットCSVインポート ────────────────────

HAUNTED_GENRE = "心霊スポット（世界）"


def import_haunted_spots_csv(rows: list[dict], jp_only: bool = False) -> tuple[int, int]:
    """
    世界の心霊スポットCSVをネタバンクにインポートする。
    - タイトル: jp_title_or_note があれば「日本語名（英語名）」、なければ英語名
    - 説明: region（国・地域）
    - ジャンル: 心霊スポット（世界）
    - 重複（同タイトル）はスキップ
    Returns: (imported_count, skipped_count)
    """
    conn = get_connection()
    c    = conn.cursor()

    # 既存タイトルを取得して重複チェック用セットを作る
    c.execute("SELECT title FROM ideas WHERE genre = ?", (HAUNTED_GENRE,))
    existing = {row["title"] for row in c.fetchall()}

    imported = 0
    skipped  = 0

    for row in rows:
        en_name = (row.get("title") or "").strip()
        jp_raw  = (row.get("jp_title_or_note") or "").strip()
        region  = (row.get("region") or "").strip()

        if not en_name:
            skipped += 1
            continue

        # jp_title_or_note の品質チェック
        # ・数字だけ → 無効
        # ・「日本語表記」という注記だけ → 英語名のみ扱い
        # ・3文字未満 → 無効
        # ・セミコロンを含む（メタデータ）→ 無効
        # ・数字で終わる「州名; 件数」パターン → 無効
        jp_valid = (
            bool(jp_raw)
            and not jp_raw.isdigit()
            and "日本語表記" not in jp_raw
            and len(jp_raw) >= 3
            and "; " not in jp_raw
            and not jp_raw.split(";")[-1].strip().isdigit()
        )
        jp_name = jp_raw if jp_valid else ""

        if jp_only and not jp_name:
            skipped += 1
            continue

        # タイトル生成
        if jp_name:
            title = f"{jp_name}（{en_name}）"
        else:
            title = en_name

        if title in existing:
            skipped += 1
            continue

        desc = f"{region}" if region else ""

        conn.execute(
            "INSERT INTO ideas (title, genre, description) VALUES (?, ?, ?)",
            (title, HAUNTED_GENRE, desc)
        )
        existing.add(title)
        imported += 1

    conn.commit()
    conn.close()
    return imported, skipped


def get_haunted_spots(region_filter: str = "") -> list[dict]:
    """心霊スポットのネタを取得。region_filterで国絞り込み可。"""
    conn = get_connection()
    c    = conn.cursor()
    if region_filter:
        c.execute(
            "SELECT * FROM ideas WHERE genre = ? AND description LIKE ? ORDER BY RANDOM()",
            (HAUNTED_GENRE, f"%{region_filter}%")
        )
    else:
        c.execute(
            "SELECT * FROM ideas WHERE genre = ? ORDER BY used ASC, RANDOM()",
            (HAUNTED_GENRE,)
        )
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_haunted_regions() -> list[str]:
    """心霊スポットに登録されている国・地域のリストを返す。"""
    conn = get_connection()
    c    = conn.cursor()
    c.execute(
        "SELECT DISTINCT description FROM ideas WHERE genre = ? AND description != '' ORDER BY description",
        (HAUNTED_GENRE,)
    )
    rows = c.fetchall()
    conn.close()
    # descriptionはregionが入っているので重複排除して返す
    seen   = set()
    result = []
    for row in rows:
        d = row["description"].strip()
        # 国名だけ（regionの最初のカンマ前）を使う
        country = d.split(",")[0].strip().split(" - ")[0].strip()
        if country and country not in seen:
            seen.add(country)
            result.append(country)
    return sorted(result)
