"""Verify SUPABASE_URL / SUPABASE_ANON_KEY in .env can reach the project."""
import os
import sys

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_ANON_KEY")

if not url or not key:
    print("Missing SUPABASE_URL or SUPABASE_ANON_KEY in .env")
    sys.exit(1)

try:
    client = create_client(url, key)
    client.table("muni").select("muni_id").limit(1).execute()
    print(f"Connected to {url}")
except Exception as exc:
    print(f"Connection failed: {exc}")
    sys.exit(1)
