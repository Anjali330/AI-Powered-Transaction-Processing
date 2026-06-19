from app.config import settings
from groq import Groq

print(f"Key  : {settings.groq_api_key[:8]}...{settings.groq_api_key[-4:]}")
print(f"Model: {settings.groq_model}")

try:
    client = Groq(api_key=settings.groq_api_key)
    resp = client.chat.completions.create(
        model=settings.groq_model,
        messages=[{"role": "user", "content": "Reply with one word: ready"}],
        temperature=0,
    )
    print(f"Groq response: {resp.choices[0].message.content.strip()}")
    print("Groq connection OK")
except Exception as e:
    print(f"Groq connection FAILED: {e}")
