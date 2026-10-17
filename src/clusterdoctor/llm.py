"""Instrumented client for Nebius Token Factory (OpenAI-compatible API).

Every call records latency, time to first token, token counts, status and
retries into the Store. This is the telemetry the agent later investigates.
"""
from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass

from openai import OpenAI, APIStatusError, APIConnectionError

from .store import Request, Store

DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"


@dataclass
class Completion:
    text: str
    request: Request


class InstrumentedClient:
    def __init__(self, store: Store, model: str | None = None, app_version: str = "v1",
                 max_retries: int = 2, source: str = "live",
                 backoff_base: float = 1.0):
        self.store = store
        self.model = model or os.environ["CD_APP_MODEL"]
        self.app_version = app_version
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.source = source
        self.client = OpenAI(
            api_key=os.environ["NEBIUS_API_KEY"],
            base_url=os.environ.get("NEBIUS_BASE_URL", DEFAULT_BASE_URL),
            max_retries=0,  # we count retries ourselves so they show up in telemetry
        )

    def complete(self, messages: list[dict], max_tokens: int = 256, concurrency: int = 1,
                 fail_rate: float = 0.0, extra_latency_s: float = 0.0) -> Completion:
        """One logical call = one telemetry row. Latency includes retries and backoff.

        fail_rate injects synthetic 429s before the request is sent (fault injection);
        rows where that happened are labelled source='live_injected'.
        """
        t_start = time.time()
        retries, injected = 0, False
        while True:
            ttft, parts = None, []
            in_tokens = out_tokens = None
            attempt_start = time.time()
            if fail_rate and random.random() < fail_rate:
                injected, status = True, 429
            else:
                try:
                    if extra_latency_s:  # simulated provider-side slowness, counted in ttft
                        time.sleep(extra_latency_s * random.uniform(0.8, 1.6))
                        injected = True
                    stream = self.client.chat.completions.create(
                        model=self.model, messages=messages, max_tokens=max_tokens,
                        stream=True, stream_options={"include_usage": True},
                    )
                    for chunk in stream:
                        if chunk.choices and chunk.choices[0].delta.content:
                            if ttft is None:
                                ttft = time.time() - attempt_start
                            parts.append(chunk.choices[0].delta.content)
                        if getattr(chunk, "usage", None):
                            in_tokens = chunk.usage.prompt_tokens
                            out_tokens = chunk.usage.completion_tokens
                    status = 200
                except APIStatusError as e:
                    status = e.status_code
                except APIConnectionError:
                    status = 0  # no HTTP response at all
            retryable = status in (0, 429) or status >= 500
            if status == 200 or not retryable or retries >= self.max_retries:
                break
            retries += 1
            time.sleep(min(self.backoff_base * 2 ** retries, 8))

        req = Request(
            ts=t_start, app_version=self.app_version, model=self.model,
            input_tokens=in_tokens, output_tokens=out_tokens,
            latency_s=time.time() - t_start,
            ttft_s=None if ttft is None else ttft, status=status,
            retries=retries, concurrency=concurrency,
            source="live_injected" if injected else self.source,
        )
        self.store.add_request(req)
        return Completion("".join(parts), req)
