"""
Grok (xai-sdk) OAuth トークン管理の一元化モジュール。

xAIのOAuthリフレッシュトークンは使い捨て（rotation方式）:
  https://auth.x.ai/oauth2/token のレスポンスには常に新しい refresh_token が
  含まれ、古いリフレッシュトークンは即座に無効化される。新トークンを保存せず
  捨てると、2回目の更新が必ず「Refresh token has been revoked」(400)で失敗する。

このモジュールは交換後の refresh_token を必ずファイルに永続化し、
viral_research.py / x_monitor.py 両方から共通利用する。
"""

import os
from datetime import datetime, timedelta
from pathlib import Path

import requests

try:
    from loguru import logger
except ImportError:  # loguru未導入環境でも動くようにフォールバック
    import logging

    logger = logging.getLogger("grok_auth")

_OIDC_TOKEN_URL = "https://auth.x.ai/oauth2/token"
_OIDC_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
_AUTH_PATH = Path.home() / ".grok" / "auth.json"

_cached: dict = {"key": "", "expires_at": ""}
last_auth_error: str = ""


def _token_file() -> Path:
    env_path = os.getenv("GROK_TOKEN_FILE")
    if env_path:
        return Path(env_path)
    return Path(__file__).parent / "grok_refresh_token.txt"


def _load_refresh_token() -> str:
    token_file = _token_file()
    if token_file.exists():
        content = token_file.read_text().strip()
        if content:
            return content
    return os.getenv("GROK_REFRESH_TOKEN", "")


def _save_refresh_token(token: str) -> None:
    token_file = _token_file()
    try:
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(token)
    except OSError as e:
        logger.warning(f"[grok_auth] リフレッシュトークンの保存に失敗しました ({token_file}): {e}")


def refresh_access_token() -> str:
    """リフレッシュトークンでアクセストークンを更新する。

    レスポンスに新しい refresh_token が含まれていれば必ず保存してから
    access_token を返す（rotation方式のため、保存を怠ると次回更新が失敗する）。
    """
    refresh_token = _load_refresh_token()
    if not refresh_token:
        raise RuntimeError("Grokリフレッシュトークンが見つかりません（ファイル/環境変数どちらも未設定）")

    res = requests.post(_OIDC_TOKEN_URL, data={
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": _OIDC_CLIENT_ID,
    })
    if not res.ok:
        raise requests.HTTPError(
            f"Grokトークン更新失敗: HTTP {res.status_code} - {res.text}", response=res
        )

    data = res.json()
    new_refresh_token = data.get("refresh_token")
    if new_refresh_token:
        _save_refresh_token(new_refresh_token)

    return data["access_token"]


def get_access_token() -> str:
    """キャッシュ済み（期限5分前まで有効）または新規取得したアクセストークンを返す。

    リフレッシュトークンでの更新に失敗した場合、ローカルの ~/.grok/auth.json の
    キーにフォールバックする。どちらも無ければ RuntimeError を投げる。
    """
    global _cached, last_auth_error

    expires_at = _cached.get("expires_at", "")
    if _cached.get("key") and expires_at:
        if datetime.fromisoformat(expires_at) - datetime.now() >= timedelta(minutes=5):
            return _cached["key"]

    try:
        new_token = refresh_access_token()
        _cached = {
            "key": new_token,
            "expires_at": (datetime.now() + timedelta(hours=6)).isoformat(),
        }
        return _cached["key"]
    except Exception as e:
        last_auth_error = str(e)
        logger.warning(f"[grok_auth] アクセストークン更新失敗、auth.jsonへフォールバックします: {e}")

    if _AUTH_PATH.exists():
        import json
        with open(_AUTH_PATH) as f:
            d = json.load(f)
        if d:
            return list(d.values())[0]["key"]

    raise RuntimeError(f"Grokトークンが取得できません: {last_auth_error}")


def grok_available() -> bool:
    return bool(_load_refresh_token()) or _AUTH_PATH.exists()
