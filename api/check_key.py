import os
# Do NOT set defaults — let config.py read the real .env
from app.config import settings
key = settings.gemini_api_key
print(f"Key loaded   : {key[:8]}...{key[-4:] if len(key) > 12 else '(too short)'}")
print(f"Key length   : {len(key)}")
print(f"Is placeholder: {key == '<your-key>'}")
print(f"Gemini model : {settings.gemini_model}")
