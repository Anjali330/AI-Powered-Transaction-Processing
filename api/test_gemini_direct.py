from app.config import settings
from google import genai

print(f"Using key: {settings.gemini_api_key[:8]}...{settings.gemini_api_key[-4:]}")
print(f"Using model: {settings.gemini_model}")

try:
    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents="Say hello in one word.",
    )
    print(f"SUCCESS: {response.text}")
except Exception as e:
    print(f"FAILED: {e}")
