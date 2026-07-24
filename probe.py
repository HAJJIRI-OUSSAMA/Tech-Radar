from digest.score import get_client

CANDIDATES = [
    "nvidia/nemotron-3-ultra-550b-a55b",
    "moonshotai/kimi-k2.6",
    "z-ai/glm-5.2",
    "deepseek-ai/deepseek-v4-pro",
    "mistralai/mistral-large-3-675b-instruct-2512",
    "stepfun-ai/step-3.7-flash",
]

client = get_client()
for model in CANDIDATES:
    try:
        client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=5,
        )
        print(f"OK       {model}")
    except Exception as e:
        code = getattr(e, "status_code", "?")
        print(f"FAIL {code}  {model}")