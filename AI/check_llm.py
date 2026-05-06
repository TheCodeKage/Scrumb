import httpx
import asyncio


async def check_ollama():
    # 1. Use the literal IP 127.0.0.1 to avoid Windows "localhost" lag
    url = "http://127.0.0.1:11434/api/generate"

    payload = {
        "model": "llama3",
        "prompt": "Respond with the JSON: {'status': 'active'}",
        "stream": False,
        "format": "json"
    }

    try:
        print("Connecting to Ollama...")
        async with httpx.AsyncClient() as client:
            # 2. Increase timeout to 60s.
            # On a LOQ laptop, the first time you call a model,
            # it has to load several GBs into your GPU VRAM.
            response = await client.post(url, json=payload, timeout=60.0)

            if response.status_code == 200:
                print("✅ SUCCESS: Ollama is awake and the model is loaded!")
                print("Response:", response.json().get('response'))
            else:
                print(f"❌ API Error: {response.status_code}")

    except httpx.ConnectError:
        print("❌ Connection Refused: Ollama is running but not accepting requests.")
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    asyncio.run(check_ollama())