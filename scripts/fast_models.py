"""Manual live-model latency smoke script (NOT a pytest test).

Run directly:  python scripts/fast_models.py
It streams real LLM responses and requires a configured provider API key.
"""

import asyncio
import time

from deeptutor.core.agentic.client import LLMClientConfig, build_openai_client
from deeptutor.services.config.model_catalog import get_model_catalog_service


async def test_model(model_name):
    catalog_svc = get_model_catalog_service()
    catalog = catalog_svc.load()
    profile = catalog_svc.get_active_profile(catalog, "llm")
    api_key = profile.get("api_key") if profile else ""
    base_url = profile.get("base_url") if profile else ""

    cfg = LLMClientConfig(
        binding="gemini",
        model=model_name,
        api_key=api_key,
        base_url=base_url,
    )
    client = build_openai_client(cfg)

    print(f"\n--- Testing Model: {model_name} ---")
    t0 = time.perf_counter()
    first_token_time = None
    try:
        stream = await client.chat.completions.create(
            model=cfg.model,
            messages=[{"role": "user", "content": "Explain 1+1 in 5 words."}],
            stream=True,
            timeout=15,
        )
        chunks = []
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                if first_token_time is None:
                    first_token_time = time.perf_counter()
                chunks.append(chunk.choices[0].delta.content)
        t_end = time.perf_counter()
        ttft = (first_token_time - t0) if first_token_time else (t_end - t0)
        print(f"  [SUCCESS] Time To First Token: {ttft:.2f}s | Total: {t_end - t0:.2f}s")
        print(f"  Response: {''.join(chunks).strip()}")
        return True
    except Exception as e:
        print(f"  [FAILED]: {e}")
        return False


async def main():
    models_to_test = [
        "gemini-3.6-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.5-flash",
    ]
    for m in models_to_test:
        await test_model(m)


if __name__ == "__main__":
    asyncio.run(main())
