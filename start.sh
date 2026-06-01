#!/bin/bash
cd "$(dirname "$0")"
echo "👻 こわ面白いコンテンツ生成ツールを起動します..."
find . -name "*.pyc" -delete
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null
echo "📌 ブラウザが自動で開きます。開かない場合は http://localhost:8501 にアクセスしてください"
streamlit run app.py --server.port 8501
