"""
Standalone API connectivity test.
Run this BEFORE running the full pipeline.
Hits each API once with a trivial prompt to confirm keys work
and SDKs are installed correctly. Total cost: ~$0.001.

Usage:
  python test_connections.py
"""
import os
from dotenv import load_dotenv

load_dotenv()


def test_anthropic():
    print("\n[1/3] Testing Anthropic (judge)...")
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=30,
            messages=[{"role": "user", "content": "Say 'ok' and nothing else."}],
        )
        print(f"  [+] OK — response: {msg.content[0].text!r}")
        return True
    except Exception as e:
        print(f"  [!] FAILED: {type(e).__name__}: {e}")
        return False


def test_gemini():
    print("\n[2/3] Testing Gemini...")
    try:
        from google import genai
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents="Say 'ok' and nothing else.",
        )
        print(f"  [+] OK — response: {response.text!r}")
        return True
    except Exception as e:
        print(f"  [!] FAILED: {type(e).__name__}: {e}")
        return False


def test_perplexity():
    print("\n[3/3] Testing Perplexity...")
    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=os.getenv("PERPLEXITY_API_KEY"),
            base_url="https://api.perplexity.ai",
        )
        response = client.chat.completions.create(
            model="sonar",
            messages=[{"role": "user", "content": "Say 'ok' and nothing else."}],
            max_tokens=30,
        )
        text = response.choices[0].message.content
        citations = (
            getattr(response, "search_results", None)
            or getattr(response, "citations", None)
            or []
        )
        print(f"  [+] OK — response: {text!r}")
        print(f"      citations returned: {len(citations)}")
        return True
    except Exception as e:
        print(f"  [!] FAILED: {type(e).__name__}: {e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("API Connectivity Test")
    print("=" * 60)

    results = {
        "Anthropic": test_anthropic(),
        "Gemini": test_gemini(),
        "Perplexity": test_perplexity(),
    }

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {status}  {name}")

    if all(results.values()):
        print("\nAll connections healthy. Safe to run python run.py")
    else:
        print("\nFix the failed connections before running the full pipeline.")
