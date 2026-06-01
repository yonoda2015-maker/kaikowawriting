import os
import subprocess
import sys

port = os.environ.get("PORT", "8501")

cmd = [
    sys.executable, "-m", "streamlit", "run", "app.py",
    f"--server.port={port}",
    "--server.address=0.0.0.0",
    "--server.headless=true",
    "--browser.gatherUsageStats=false",
]

subprocess.run(cmd)
