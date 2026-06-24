"""
マルチエージェント生成システム

エージェント構成:
  researcher   — ネタ調査・フック・伏線の種を掘る
  planner      — テーマ・構成・設定を設計する
  writer       — 実際の文章を執筆する
  editor       — 品質・読みやすさ・文章力を評価する
  fact_checker — 矛盾・論理破綻・設定ブレを検出する
  buzz_analyst — バイラル可能性を評価し勝者を選ぶ

協議メカニズム:
  1. 各エージェントが独立して意見を出す
  2. 全員の意見を共有し再考・同意・反論を行う
  3. シンセサイザーが最善案を決定する

ストーリーバイブル:
  キャラ・場所・時系列・世界ルールを蓄積し、
  章執筆前に渡すことで矛盾を防ぐ。
"""
import re
import json
from dataclasses import dataclass, field
from logger_config import logger

# _call_claude は agents.py からインポート（循環回避のため関数内でインポート）


# ─── エージェント定義 ───────────────────────────────

AGENT_PERSONAS: dict[str, str] = {
    "researcher": (
        "あなたはリサーチャーエージェントです。"
        "ネタの背景・都市伝説・心理的フック・伏線の種を深く掘り下げ、"
        "読者が「怖い、でも読みたい」と感じる素材を発見することが仕事です。"
    ),
    "planner": (
        "あなたはプランナーエージェントです。"
        "テーマ・構成・登場人物・世界観・伏線配置を設計し、"
        "物語全体の設計図を描くことが仕事です。"
    ),
    "writer": (
        "あなたはライターエージェントです。"
        "設計図と世界設定に忠実に従い、没入感のある文章を執筆することが仕事です。"
        "AIっぽい説明口調・過剰な比喩は使いません。"
    ),
    "editor": (
        "あなたは編集者エージェントです。"
        "文章の品質・読みやすさ・テンポ・感情的な引きを評価し、"
        "具体的な改善点を指摘することが仕事です。"
    ),
    "fact_checker": (
        "あなたはファクトチェッカーエージェントです。"
        "登場人物の言動・場所・時系列・世界ルールの矛盾を厳密に検出し、"
        "矛盾箇所を【矛盾点】として列挙することが仕事です。"
    ),
    "buzz_analyst": (
        "あなたはバズ分析エージェントです。"
        "SNSでの拡散可能性・フック強度・感情的インパクトを評価し、"
        "複数案の中から最もバイラルになる可能性が高い案を選ぶことが仕事です。"
    ),
}


# ─── ストーリーバイブル ─────────────────────────────

@dataclass
class StoryBible:
    """物語世界の設定を蓄積・管理する。章執筆前に渡して矛盾を防ぐ。"""
    characters: dict = field(default_factory=dict)   # name → {trait, role, status}
    places: dict = field(default_factory=dict)        # name → description
    timeline: list = field(default_factory=list)      # [{chapter, event}]
    world_rules: list = field(default_factory=list)   # この物語固有のルール
    established_facts: list = field(default_factory=list)  # 確定した事実

    def to_prompt_block(self) -> str:
        if not any([self.characters, self.places, self.timeline, self.world_rules]):
            return ""
        parts = ["【世界設定バイブル（この設定から逸脱しないこと）】"]
        if self.characters:
            parts.append("■ 登場人物:")
            for name, info in self.characters.items():
                parts.append(f"  ・{name}: {info}")
        if self.places:
            parts.append("■ 場所:")
            for name, desc in self.places.items():
                parts.append(f"  ・{name}: {desc}")
        if self.timeline:
            parts.append("■ 時系列:")
            for ev in self.timeline:
                parts.append(f"  ・{ev}")
        if self.world_rules:
            parts.append("■ 世界のルール:")
            for r in self.world_rules:
                parts.append(f"  ・{r}")
        if self.established_facts:
            parts.append("■ 確定した事実:")
            for f in self.established_facts:
                parts.append(f"  ・{f}")
        return "\n".join(parts)

    def update_from_chapter(self, chapter_text: str, chapter_num: int) -> None:
        """章テキストからバイブルを更新する（Claude呼び出し）。"""
        from agents import _call_claude, _safe_json
        prompt = f"""以下の章テキストを読み、新たに確定した設定情報をJSONで抽出せよ。

【第{chapter_num}章】
{chapter_text[:2000]}

以下のJSONのみ出力せよ（新規情報がなければ空配列/空オブジェクト）:
{{
  "new_characters": {{"名前": "特徴・役割の説明"}},
  "new_places": {{"場所名": "説明"}},
  "new_events": ["出来事の説明"],
  "new_rules": ["この世界特有のルール"]
}}"""
        raw = _call_claude(prompt, max_tokens=600)
        data = _safe_json(raw, {})
        for name, desc in data.get("new_characters", {}).items():
            if name not in self.characters:
                self.characters[name] = desc
        for name, desc in data.get("new_places", {}).items():
            if name not in self.places:
                self.places[name] = desc
        for ev in data.get("new_events", []):
            self.timeline.append(f"第{chapter_num}章: {ev}")
        for rule in data.get("new_rules", []):
            if rule not in self.world_rules:
                self.world_rules.append(rule)

    def init_from_plan(self, plan: dict) -> None:
        """設計プランから初期バイブルを構築する。"""
        for char in plan.get("characters", []):
            if isinstance(char, dict):
                name = char.get("name", "")
                desc = f"{char.get('role','')} {char.get('trait','')}".strip()
                if name:
                    self.characters[name] = desc
            elif isinstance(char, str):
                self.characters[char] = "登場人物"
        setting = plan.get("setting", "")
        if setting:
            self.places["舞台"] = setting
        theme = plan.get("theme", "")
        if theme:
            self.world_rules.append(f"テーマ: {theme}")


# ─── エージェント協議 ──────────────────────────────

def agent_consult(
    question: str,
    context: str,
    agents: list[str],
    rounds: int = 1,
) -> str:
    """
    複数エージェントで協議し最善案を返す。

    rounds=1: 各エージェントが独立意見 → シンセサイザーが統合
    rounds=2: 上記 + 全員が他の意見を見て再考 → 再統合
    """
    from agents import _call_claude

    def _ask(agent: str, extra_context: str = "") -> str:
        persona = AGENT_PERSONAS.get(agent, f"あなたは{agent}です。")
        prompt = f"""{persona}

【コンテキスト】
{context}
{extra_context}

【質問・タスク】
{question}

簡潔かつ具体的に答えよ（300文字以内）。"""
        return _call_claude(prompt, max_tokens=400)

    # Round 1: 独立意見
    opinions: list[tuple[str, str]] = []
    for agent in agents:
        try:
            op = _ask(agent)
            opinions.append((agent, op))
            logger.info(f"[{agent}] 意見取得完了")
        except Exception as e:
            logger.warning(f"[{agent}] 意見取得失敗: {e}")

    if not opinions:
        return ""

    # Round 2 (optional): 他の意見を踏まえた再考
    if rounds >= 2 and len(opinions) > 1:
        opinion_block = "\n".join(f"[{a}の意見]: {o}" for a, o in opinions)
        revised: list[tuple[str, str]] = []
        for agent, _ in opinions:
            try:
                extra = f"\n【他エージェントの意見】\n{opinion_block}\n\n上記を踏まえて意見を修正・確認せよ。"
                op = _ask(agent, extra)
                revised.append((agent, op))
            except Exception as e:
                logger.warning(f"[{agent}] Round2失敗: {e}")
                revised.append((agent, _))
        opinions = revised

    # Synthesis
    opinion_text = "\n\n".join(f"【{a}】\n{o}" for a, o in opinions)
    synth_prompt = f"""以下の複数エージェントの意見を統合し、最善の結論を出せ。
矛盾があれば多数決または論理的妥当性を優先せよ。

{opinion_text}

【統合結論】（実行可能な具体的内容のみ、200文字以内）:"""
    from agents import _call_claude
    return _call_claude(synth_prompt, max_tokens=300)


# ─── バズA/Bテスト ─────────────────────────────────

def buzz_ab_test(
    context: str,
    genre: str,
    generate_fn,
    top_patterns: list[dict] | None = None,
) -> str:
    """
    2パターン生成してバズ分析エージェントが勝者を選ぶ。
    generate_fn(variation: str) -> str
    """
    from agents import _call_claude

    try:
        ver_a = generate_fn("standard")
        ver_b = generate_fn("hook_first")
    except Exception as e:
        logger.warning(f"buzz_ab_test generation failed: {e}")
        return generate_fn("standard")

    persona = AGENT_PERSONAS["buzz_analyst"]
    hist = ""
    if top_patterns:
        winning = [p for p in top_patterns[:3] if p.get("avg_engage", 0) > 50]
        if winning:
            hist = "【過去バズパターン】\n" + "\n".join(
                f"  ・{p.get('genre','')} {p.get('style','')}: 平均エンゲージ{p.get('avg_engage',0)}"
                for p in winning
            )

    prompt = f"""{persona}

ジャンル: {genre}
{hist}

【バージョンA】
{ver_a[:600]}

【バージョンB】
{ver_b[:600]}

どちらがSNSでより拡散しやすいか。"A"または"B"のみ答えよ。"""
    try:
        choice = _call_claude(prompt, max_tokens=5, min_chars=1).strip().upper()
        winner = ver_b if choice == "B" else ver_a
        logger.info(f"buzz_ab_test winner: {choice}")
        return winner
    except Exception:
        return ver_a


# ─── ファクトチェック ──────────────────────────────

def fact_check_chapter(
    chapter_text: str,
    bible: StoryBible,
    chapter_num: int,
) -> tuple[bool, str]:
    """
    章テキストをバイブルと照合し矛盾を検出する。
    Returns: (ok, fix_instruction)
    """
    bible_block = bible.to_prompt_block()
    if not bible_block:
        return True, ""

    from agents import _call_claude, _safe_json
    persona = AGENT_PERSONAS["fact_checker"]
    prompt = f"""{persona}

{bible_block}

【第{chapter_num}章（チェック対象）】
{chapter_text[:2000]}

設定との矛盾を検出せよ。以下のJSONのみ出力せよ:
{{
  "has_contradiction": false,
  "issues": ["矛盾点の説明（あれば）"],
  "fix_instruction": "修正指示（矛盾がある場合のみ）"
}}"""
    raw = _call_claude(prompt, max_tokens=400)
    result = _safe_json(raw, {"has_contradiction": False, "issues": [], "fix_instruction": ""})
    has_issue = bool(result.get("has_contradiction", False))
    fix = result.get("fix_instruction", "")
    if has_issue:
        logger.warning(f"Chapter {chapter_num} contradiction: {result.get('issues', [])}")
    return not has_issue, fix


# ─── マルチエージェント小説生成 ────────────────────

def multi_agent_generate_novel(
    genre: str,
    idea: str,
    char_count: int = 3000,
    x_safe: bool = False,
    style_hint: str = "",
    horror_level: int = 3,
    output_lang: str = "ja",
    top_patterns: list[dict] | None = None,
    progress_cb=None,
) -> tuple[str, str]:
    """
    マルチエージェント協議による小説生成。

    パイプライン:
      Step 1  リサーチ（researcher）
      Step 2  プラン協議（researcher × planner × editor）
      Step 3  バイブル初期化
      Step 4  章ごと執筆 → ファクトチェック → バイブル更新
      Step 5  全体編集（editor × fact_checker 協議）
      Step 6  バズA/Bテスト（buzz_analyst）
      Step 7  最終仕上げ
    """
    from agents import (
        _call_claude, _safe_json, _design_theme, _design_structure,
        _write_body_from_plan, _write_long_novel,
        _final_edit_two_stage, _auto_correct_and_purify,
        auto_verify_and_fix, _score_quality,
        _strengthen_ending, _strengthen_opening,
        _get_horror_level_instruction,
    )

    total_steps = 9

    def _cb(step: int, label: str) -> None:
        if progress_cb:
            progress_cb(step, total_steps, label)

    lang_instr = "" if output_lang == "ja" else "\n\nIMPORTANT: Write the entire output in English only."

    # ── Step 1: リサーチ ──────────────────────────
    _cb(1, "リサーチ中…")
    researcher_persona = AGENT_PERSONAS["researcher"]
    research_prompt = f"""{researcher_persona}

ジャンル: {genre}
ネタ: {idea}
{_get_horror_level_instruction(horror_level)}

このネタを深堀りせよ:
・心理的フック（読者が不安になる核心）
・隠れた伏線の種（3つ）
・ラストに向けた仕掛けアイデア
・参考にすべき都市伝説・実話要素
（各200文字以内で簡潔に）{lang_instr}"""
    try:
        research_memo = _call_claude(research_prompt, max_tokens=800)
    except Exception as e:
        logger.warning(f"Research step failed: {e}")
        research_memo = idea

    # ── Step 2: プラン協議 ─────────────────────────
    _cb(2, "エージェント協議中…")
    plan_context = f"ジャンル: {genre}\nネタ: {idea}\nリサーチメモ:\n{research_memo}"
    plan_question = (
        "この素材から最も読者を引きつける物語プランを提案せよ。"
        "テーマ・主人公・山場・どんでん返し・ラストを含めること。"
    )
    try:
        plan_consensus = agent_consult(
            question=plan_question,
            context=plan_context,
            agents=["researcher", "planner", "editor"],
            rounds=2,
        )
    except Exception as e:
        logger.warning(f"Plan consult failed: {e}")
        plan_consensus = ""

    # ── Step 3: 構造設計 ─────────────────────────
    _cb(3, "構成を設計中…")
    from agents import _classify_length
    length_type = _classify_length(char_count)

    # 協議結果をstyle_hintに注入
    combined_hint = f"{style_hint}\n{plan_consensus}".strip() if plan_consensus else style_hint

    try:
        plan = _design_theme(genre, idea, length_type, horror_level)
        plan["research_memo"] = research_memo
    except Exception as e:
        logger.warning(f"design_theme failed: {e}")
        plan = {"theme": idea, "genre": genre, "research_memo": research_memo}

    try:
        structure = _design_structure(plan, length_type)
    except Exception as e:
        logger.warning(f"design_structure failed: {e}")
        structure = {"chapters": []}

    # ── Step 4: バイブル初期化 ────────────────────
    bible = StoryBible()
    bible.init_from_plan(plan)

    # ── Step 5: 章執筆 + ファクトチェック ─────────
    _cb(4, "本文を執筆中…")
    chapters = structure.get("chapters", [])

    if length_type in ("long", "very_long") and chapters:
        # 章ごとに執筆・チェック
        chapter_texts: list[str] = []
        for i, ch_def in enumerate(chapters):
            ch_num = i + 1
            _cb(4, f"第{ch_num}章を執筆中…")
            bible_block = bible.to_prompt_block()
            ch_prompt = (
                f"【第{ch_num}章】{ch_def.get('title','')}\n"
                f"目標文字数: {ch_def.get('char_count', char_count // max(1,len(chapters)))}文字\n"
                f"この章のポイント: {ch_def.get('summary','')}\n"
                f"{bible_block}"
            )
            try:
                from agents import _write_chapter
                ch_text = _write_chapter(plan, structure, ch_num, ch_def, "\n".join(chapter_texts))
            except Exception as e:
                logger.warning(f"Chapter {ch_num} write failed: {e}")
                ch_text = _call_claude(
                    f"以下のプランで第{ch_num}章を書け:\n{ch_prompt}\n\nジャンル:{genre}",
                    max_tokens=2000,
                )

            # ファクトチェック
            ok, fix_instr = fact_check_chapter(ch_text, bible, ch_num)
            if not ok and fix_instr:
                _cb(4, f"第{ch_num}章の矛盾を修正中…")
                try:
                    ch_text = _call_claude(
                        f"以下の文章を修正せよ。\n\n修正指示: {fix_instr}\n\n【文章】\n{ch_text}",
                        max_tokens=2000,
                    )
                except Exception as e:
                    logger.warning(f"Chapter {ch_num} fix failed: {e}")

            bible.update_from_chapter(ch_text, ch_num)
            chapter_texts.append(ch_text)

        body = "\n\n".join(chapter_texts)
    else:
        # 短〜中編: 通常執筆
        try:
            body = _write_body_from_plan(plan, structure, char_count, genre, x_safe, style_hint=combined_hint)
        except Exception as e:
            logger.warning(f"write_body failed: {e}")
            body = _call_claude(
                f"ジャンル:{genre}\nネタ:{idea}\nを{char_count}文字程度の短編小説として書け。",
                max_tokens=min(4000, char_count // 2 + 500),
            )
        bible.update_from_chapter(body, 1)

    # ── Step 6: 全体編集（エージェント協議）─────────
    _cb(5, "編集エージェントが協議中…")
    edit_context = f"ジャンル: {genre}\n本文（冒頭）:\n{body[:800]}"
    edit_question = "この文章の改善すべき最重要点を1つ挙げ、具体的な修正指示を出せ。"
    try:
        edit_consensus = agent_consult(
            question=edit_question,
            context=edit_context,
            agents=["editor", "fact_checker"],
            rounds=1,
        )
    except Exception:
        edit_consensus = ""

    # 二段階編集
    _cb(6, "最終編集中…")
    try:
        body = _final_edit_two_stage(plan, structure, body, char_count, genre)
    except Exception as e:
        logger.warning(f"final_edit failed: {e}")

    # エージェント編集指示を適用
    if edit_consensus:
        try:
            body = _call_claude(
                f"以下の指示に従って文章を修正せよ。\n\n指示: {edit_consensus}\n\n【文章】\n{body}",
                max_tokens=min(4000, len(body) // 2 + 500),
            )
        except Exception as e:
            logger.warning(f"Agent edit apply failed: {e}")

    # ── Step 7: バズA/Bテスト ────────────────────
    _cb(7, "バズ分析中…")
    try:
        def _gen_opening(variation: str) -> str:
            if variation == "hook_first":
                vp = "冒頭から最大のフックを配置し、読者を即座に引き込め。"
            else:
                vp = "自然な導入から始めよ。"
            return _call_claude(
                f"ジャンル:{genre}\nネタ:{idea}\n{vp}\n冒頭200文字のみ書け。",
                max_tokens=300,
            )

        best_opening = buzz_ab_test(
            context=f"ジャンル:{genre} ネタ:{idea}",
            genre=genre,
            generate_fn=_gen_opening,
            top_patterns=top_patterns or [],
        )
        # 冒頭を差し替え（既存冒頭の最初の段落を置換）
        paragraphs = body.split("\n\n")
        if len(paragraphs) > 1:
            body = best_opening + "\n\n" + "\n\n".join(paragraphs[1:])
    except Exception as e:
        logger.warning(f"Buzz AB test failed: {e}")

    # ── Step 8: 品質スコア → 補強 ────────────────
    _cb(8, "品質チェック中…")
    try:
        score = _score_quality(plan, body, genre)
        if score.get("ending_strength", 7) < 7.5:
            body = _strengthen_ending(plan, body, genre)
        if score.get("overall_score", 8) < 8.0:
            body = _strengthen_opening(plan, body, genre)
    except Exception as e:
        logger.warning(f"Quality score/strengthen failed: {e}")

    # ── Step 9: クリーンアップ ────────────────────
    _cb(9, "仕上げ中…")
    try:
        body = _auto_correct_and_purify(body, genre)
        body, _ = auto_verify_and_fix(body, genre)
    except Exception as e:
        logger.warning(f"Cleanup failed: {e}")

    # 英語出力
    if output_lang == "en":
        jp_chars = re.findall(r'[぀-鿿]', body)
        if len(jp_chars) > 20:
            try:
                body = _call_claude(
                    f"Translate the following Japanese story to natural English:\n\n{body}",
                    max_tokens=min(4000, len(body)),
                )
            except Exception as e:
                logger.warning(f"Translation failed: {e}")

    # タイトル抽出
    title = plan.get("title", "")
    if not title:
        lines = body.strip().split("\n")
        title = lines[0].strip("「」【】#* ") if lines else idea[:30]

    return body.strip(), title.strip()


# ─── バズ学習保存 ──────────────────────────────────

def save_buzz_learning(
    db_path: str,
    genre: str,
    style: str,
    content: str,
    buzz_score: int,
    won_ab: bool = False,
) -> None:
    """バズA/Bテスト結果と推定スコアをSQLiteに保存する。"""
    import sqlite3
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS buzz_learning (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                genre TEXT, style TEXT,
                content_preview TEXT,
                buzz_score INTEGER,
                won_ab INTEGER,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        cur.execute(
            "INSERT INTO buzz_learning (genre,style,content_preview,buzz_score,won_ab) VALUES (?,?,?,?,?)",
            (genre, style, content[:300], buzz_score, int(won_ab)),
        )
        con.commit()
        con.close()
        logger.info(f"buzz_learning saved: {genre}/{style} score={buzz_score}")
    except Exception as e:
        logger.warning(f"save_buzz_learning failed: {e}")


def load_top_buzz_patterns(db_path: str, limit: int = 10) -> list[dict]:
    """バズスコア上位パターンを返す。"""
    import sqlite3
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute("""
            SELECT genre, style, AVG(buzz_score) as avg_score, COUNT(*) as cnt
            FROM buzz_learning
            GROUP BY genre, style
            ORDER BY avg_score DESC
            LIMIT ?
        """, (limit,))
        rows = cur.fetchall()
        con.close()
        return [{"genre": r[0], "style": r[1], "avg_engage": r[2], "count": r[3]} for r in rows]
    except Exception:
        return []
