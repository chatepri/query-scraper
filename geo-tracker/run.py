"""
Entry point for the GEO tracker.

Usage:
  python run.py                              # runs YTEN config
  python run.py config/clients/other.yaml    # runs a different client
"""
import sys
from dotenv import load_dotenv

load_dotenv()  # picks up .env in project root

from src.runner import run_client

if __name__ == "__main__":
    client_path = sys.argv[1] if len(sys.argv) > 1 else "config/clients/yten.yaml"
    run_client(client_path)
