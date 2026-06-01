import threading
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

import database as db
from threads_api import post_to_threads

_scheduler = None
_lock = threading.Lock()


def _check_and_post():
    """期限切れキューアイテムを自動投稿する"""
    auto_mode = db.get_scheduler_config("auto_mode", "off")
    if auto_mode != "on":
        return

    threshold = float(db.get_scheduler_config("quality_threshold", "70"))
    items = db.get_due_queue_items()

    for item in items:
        score = item.get("quality_score") or 0
        if score < threshold:
            continue  # 品質不足はスキップ（半自動モードで通知は省略）

        full_text = f"{item['content']}\n\n{item['hashtags']}".strip() if item.get("hashtags") else item["content"]
        result = post_to_threads(full_text)
        if result["success"]:
            db.mark_queue_posted(item["id"])


def start_scheduler():
    global _scheduler
    with _lock:
        if _scheduler is not None and _scheduler.running:
            return
        _scheduler = BackgroundScheduler(timezone="Asia/Tokyo")
        _scheduler.add_job(
            _check_and_post,
            trigger=IntervalTrigger(minutes=5),
            id="auto_post",
            replace_existing=True,
        )
        _scheduler.start()


def stop_scheduler():
    global _scheduler
    with _lock:
        if _scheduler and _scheduler.running:
            _scheduler.shutdown(wait=False)
            _scheduler = None


def is_running():
    return _scheduler is not None and _scheduler.running
