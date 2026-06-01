"""
Runtime validation for all external data:
- Claude API outputs
- User inputs (prompt injection, length limits)
- Platform character limits
- RSS entries
"""
import re
from dataclasses import dataclass
from logger_config import logger

# ── プラットフォーム制限 ────────────────────────────
PLATFORM_LIMITS = {
    "threads": 500,
    "x":       280,
    "note":    100_000,
    "article": 50_000,
}

# ── Prompt Injection パターン ───────────────────────
_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"system\s*:\s*",
    r"<\s*/?system\s*>",
    r"assistant\s*:\s*",
    r"\[INST\]",
    r"あなたはいまから",
    r"指示を無視",
    r"ロールプレイ.{0,10}終了",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)

# ── ハッシュタグブラックリスト ──────────────────────
HASHTAG_BLACKLIST: set[str] = {
    # シャドウバン報告のあるタグ（随時更新）
    "#tbt", "#followme", "#like4like", "#l4l", "#spam",
    "#adult", "#18plus", "#nsfw",
}


@dataclass
class ValidationResult:
    valid: bool
    value: str
    warnings: list[str]
    errors: list[str]


def sanitize_user_input(text: str, max_chars: int = 2000) -> ValidationResult:
    """
    ユーザー入力のサニタイズ。
    - Prompt injection パターンを除去
    - 文字数上限チェック
    - 制御文字を除去
    """
    warnings: list[str] = []
    errors:   list[str] = []

    if not text:
        return ValidationResult(valid=True, value="", warnings=[], errors=[])

    # 制御文字除去（タブ・改行は保持）
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    if cleaned != text:
        warnings.append("制御文字が除去されました")

    # Prompt injection 検出・除去
    if _INJECTION_RE.search(cleaned):
        logger.warning("Prompt injection pattern detected in user input")
        cleaned = _INJECTION_RE.sub("[removed]", cleaned)
        warnings.append("不正なプロンプトパターンが除去されました")

    # 文字数チェック
    if len(cleaned) > max_chars:
        errors.append(f"入力が{max_chars}文字を超えています（{len(cleaned)}文字）")
        return ValidationResult(valid=False, value=cleaned[:max_chars], warnings=warnings, errors=errors)

    return ValidationResult(valid=True, value=cleaned, warnings=warnings, errors=errors)


def validate_platform_length(content: str, platform: str) -> ValidationResult:
    """
    各プラットフォームの文字数制限を検証する。
    """
    limit = PLATFORM_LIMITS.get(platform.lower(), 10_000)
    warnings: list[str] = []
    errors:   list[str] = []
    length = len(content)

    if length > limit:
        errors.append(f"{platform}の文字数制限（{limit}文字）を超えています（現在{length}文字）")
        return ValidationResult(valid=False, value=content, warnings=warnings, errors=errors)
    if length > limit * 0.9:
        warnings.append(f"文字数が制限の90%を超えています（{length}/{limit}文字）")

    return ValidationResult(valid=True, value=content, warnings=warnings, errors=errors)


def split_for_threads(content: str, limit: int = 480) -> list[str]:
    """
    Threads投稿用に500文字制限で自動分割する。
    句読点・改行で自然に分割し、各パートに「n/total」を付与。
    """
    if len(content) <= limit:
        return [content]

    # 文単位で分割
    sentences = re.split(r"(?<=[。！？\n])", content)
    parts: list[str] = []
    current = ""

    for sentence in sentences:
        if not sentence.strip():
            continue
        if len(current) + len(sentence) <= limit - 10:  # 番号分の余白
            current += sentence
        else:
            if current:
                parts.append(current.strip())
            current = sentence

    if current.strip():
        parts.append(current.strip())

    if not parts:
        # フォールバック: 強制的にlimit文字で分割
        parts = [content[i:i+limit] for i in range(0, len(content), limit)]

    total = len(parts)
    return [f"{p}\n\n({i+1}/{total})" for i, p in enumerate(parts)]


def validate_claude_output(raw: str, min_chars: int = 10) -> ValidationResult:
    """
    Claude APIのレスポンスを検証する。
    - 空でないこと
    - 最低文字数を満たすこと
    - エラーメッセージでないこと
    """
    warnings: list[str] = []
    errors:   list[str] = []

    if not raw or not raw.strip():
        errors.append("Claude APIのレスポンスが空です")
        return ValidationResult(valid=False, value="", warnings=warnings, errors=errors)

    stripped = raw.strip()

    if len(stripped) < min_chars:
        errors.append(f"レスポンスが短すぎます（{len(stripped)}文字）")
        return ValidationResult(valid=False, value=stripped, warnings=warnings, errors=errors)

    # エラーメッセージパターン
    error_patterns = ["申し訳", "Error", "I cannot", "I'm unable", "エラーが発生"]
    if any(p in stripped[:100] for p in error_patterns):
        warnings.append("Claudeからエラーレスポンスの可能性があります")

    return ValidationResult(valid=True, value=stripped, warnings=warnings, errors=errors)


def filter_hashtags(tags_str: str) -> tuple[str, list[str]]:
    """
    ブラックリストにあるハッシュタグを除去する。
    Returns: (filtered_tags_string, removed_tags_list)
    """
    tags = tags_str.split()
    removed = [t for t in tags if t.lower() in HASHTAG_BLACKLIST]
    filtered = [t for t in tags if t.lower() not in HASHTAG_BLACKLIST]
    return " ".join(filtered), removed


def validate_rss_entry(entry: dict) -> bool:
    """RSS エントリが有効かチェック。"""
    title = entry.get("keyword", "").strip()
    return bool(title) and len(title) > 2 and len(title) < 500
