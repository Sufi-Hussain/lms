import asyncio

import httpx

from app.core.config import settings


RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


async def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict | None = None,
    params: dict | None = None,
) -> dict:
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        for attempt in range(3):
            try:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    json=payload,
                    params=params,
                )
                if response.status_code in RETRYABLE_STATUS_CODES and attempt < 2:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        delay = min(max(float(retry_after), 0.0), 5.0) if retry_after else 0.25 * (2**attempt)
                    except ValueError:
                        delay = 0.25 * (2**attempt)
                    await asyncio.sleep(delay)
                    continue
                response.raise_for_status()
                result = response.json()
                if not isinstance(result, dict):
                    raise ValueError("The upstream service returned invalid JSON")
                return result
            except httpx.RequestError:
                if attempt == 2:
                    raise
                await asyncio.sleep(0.25 * (2**attempt))
    raise RuntimeError("The upstream request did not complete")


async def post_json(url: str, *, headers: dict[str, str], payload: dict) -> dict:
    return await request_json("POST", url, headers=headers, payload=payload)
