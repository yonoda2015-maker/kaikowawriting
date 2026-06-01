"""
シンプルなパスワード認証。
パスワードは環境変数 APP_PASSWORD で設定。
未設定の場合はローカル開発モードとして認証をスキップする。
"""
import os
import hashlib
import streamlit as st
from dotenv import load_dotenv

load_dotenv(override=True)


def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def is_auth_enabled() -> bool:
    """APP_PASSWORD が設定されていれば認証を有効にする。"""
    return bool(os.getenv("APP_PASSWORD", "").strip())


def check_login() -> bool:
    """
    認証が必要な場合はログイン画面を表示し、
    認証済みなら True を返す。
    認証不要（ローカル）なら常に True を返す。
    """
    if not is_auth_enabled():
        return True  # ローカル開発時はスキップ

    if st.session_state.get("authenticated"):
        return True

    # ─── ログイン画面 ───────────────────────────────
    st.markdown("""
    <style>
        .stApp { background-color: #0d0d0d; color: #e8e8e8; }
        .login-box {
            max-width: 400px;
            margin: 80px auto;
            background: #1a1a1a;
            border: 1px solid #333;
            border-radius: 16px;
            padding: 40px;
            text-align: center;
        }
    </style>
    """, unsafe_allow_html=True)

    col = st.columns([1, 2, 1])[1]
    with col:
        st.markdown("# 👻")
        st.markdown("## こわ面白いコンテンツ生成ツール")
        st.markdown("---")

        user_input = st.text_input(
            "ユーザー名",
            key="login_user",
            placeholder="username",
        )
        pass_input = st.text_input(
            "パスワード",
            type="password",
            key="login_pass",
            placeholder="password",
        )

        if st.button("🔓 ログイン", type="primary", use_container_width=True, key="login_btn"):
            expected_user = os.getenv("APP_USERNAME", "admin")
            expected_pass = os.getenv("APP_PASSWORD", "")

            if user_input == expected_user and pass_input == expected_pass:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("ユーザー名またはパスワードが違います")

        st.caption("アクセス権限のある方のみご利用ください")

    return False


def logout():
    """ログアウト処理。"""
    st.session_state.pop("authenticated", None)
    st.rerun()
