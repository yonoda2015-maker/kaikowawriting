FROM python:3.11-slim

WORKDIR /app

# システムパッケージ
RUN apt-get update && apt-get install -y \
    fonts-noto-cjk \
    xclip \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

# Pythonパッケージ
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリコードをコピー
COPY . .

# データディレクトリ（DBとログ）は volume でマウントする想定
RUN mkdir -p /data /app/logs

# DBのパスを /data に向ける（volume マウント先）
ENV DB_PATH=/data/kowamoshiro.db

EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--server.fileWatcherType=none", \
     "--browser.gatherUsageStats=false"]
