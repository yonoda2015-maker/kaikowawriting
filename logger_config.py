"""
ロギング設定。全モジュールはここからloggerをimportする。
loguru を使用。ファイルローテーション・タイムゾーン・構造化ログに対応。
"""
import sys
from pathlib import Path
from loguru import logger

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# 既存ハンドラをクリア
logger.remove()

# コンソール（カラー付き）
logger.add(
    sys.stderr,
    colorize=True,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> - <level>{message}</level>",
    level="INFO",
)

# ファイル（ローテーション・圧縮）
logger.add(
    LOG_DIR / "app_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="14 days",
    compression="zip",
    encoding="utf-8",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    level="DEBUG",
)

# エラー専用ファイル
logger.add(
    LOG_DIR / "errors.log",
    rotation="10 MB",
    retention="30 days",
    compression="zip",
    encoding="utf-8",
    level="ERROR",
)

__all__ = ["logger"]
