import asyncio
import time

from deeptutor.core.agentic.client import LLMClientConfig, build_openai_client
from deeptutor.services.config.model_catalog import get_model_catalog_service


async def main():
    catalog_svc = get_model_catalog_service()
    catalog = catalog_svc.load()
    profile = catalog_svc.get_active_profile(catalog, "llm")
    model_entry = catalog_svc.get_active_model(catalog, "llm")

    provider_name = profile.get("name") if profile else "None"
    base_url = profile.get("base_url") if profile else "None"
    model_name = model_entry.get("model") if model_entry else "None"
    api_key = profile.get("api_key") if profile else ""

    print(f"Testing Configured Provider: {provider_name}")
    print(f"Base URL: {base_url}")
    print(f"Model: {model_name}")

    cfg = LLMClientConfig(
        binding=profile.get("binding", "gemini") if profile else "gemini",
        model=model_name,
        api_key=api_key,
        base_url=base_url,
    )
    client = build_openai_client(cfg)

    print("\n1. Measuring Non-Streaming Latency...")
    t0 = time.perf_counter()
    try:
        response = await client.chat.completions.create(
            model=cfg.model,
            messages=[{"role": "user", "content": "Hi, reply in 5 words."}],
            stream=False,
            timeout=30,
        )
        t1 = time.perf_counter()
        print(f"  [SUCCESS] Response in {t1 - t0:.2f}s: {response.choices[0].message.content}")
    except Exception as e:
        t1 = time.perf_counter()
        print(f"  [FAILED] in {t1 - t0:.2f}s: {e}")

    print("\n2. Measuring Streaming Time to First Token (TTFT)...")
    t0 = time.perf_counter()
    first_token_time = None
    try:
        stream = await client.chat.completions.create(
            model=cfg.model,
            messages=[{"role": "user", "content": "Explain gravity in 20 words."}],
            stream=True,
            timeout=30,
        )
        chunks = []
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                if first_token_time is None:
                    first_token_time = time.perf_counter()
                chunks.append(chunk.choices[0].delta.content)
        t_end = time.perf_counter()
        ttft = (first_token_time - t0) if first_token_time else (t_end - t0)
        print(f"  [SUCCESS] TTFT: {ttft:.2f}s | Total Stream Time: {t_end - t0:.2f}s")
        print(f"  Content: {''.join(chunks)}")
    except Exception as e:
        print(f"  [FAILED]: {e}")


if __name__ == "__main__":
    asyncio.run(main())
