import os
import requests
from dotenv import load_dotenv

load_dotenv()

THREADS_API_BASE = "https://graph.threads.net/v1.0"


def post_to_threads(text: str) -> dict:
    access_token = os.getenv("THREADS_ACCESS_TOKEN")
    user_id = os.getenv("THREADS_USER_ID")

    if not access_token or not user_id:
        return {"success": False, "error": "Threads APIトークンまたはユーザーIDが設定されていません。設定タブで入力してください。"}

    # Step1: コンテナ作成
    create_url = f"{THREADS_API_BASE}/{user_id}/threads"
    create_resp = requests.post(create_url, params={
        "media_type": "TEXT",
        "text": text,
        "access_token": access_token,
    })

    if create_resp.status_code != 200:
        return {"success": False, "error": f"コンテナ作成失敗: {create_resp.text}"}

    container_id = create_resp.json().get("id")

    # Step2: 公開
    publish_url = f"{THREADS_API_BASE}/{user_id}/threads_publish"
    publish_resp = requests.post(publish_url, params={
        "creation_id": container_id,
        "access_token": access_token,
    })

    if publish_resp.status_code != 200:
        return {"success": False, "error": f"公開失敗: {publish_resp.text}"}

    return {"success": True, "id": publish_resp.json().get("id")}
