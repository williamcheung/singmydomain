from dotenv import load_dotenv
load_dotenv()

from openai import AsyncOpenAI

import logging

import config
from time_it import time_it

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=config.GMI_API_KEY, base_url=config.GMI_CHAT_BASE_URL)

@time_it
async def invoke(prompt: str, text: str, max_tokens: int, temperature: float, model=config.GMI_CHAT_MODEL) -> str:
    """
    Invoke the LLM with a prompt and text, returning the response content as a string.
    Uses MiniMax M3 via GMI Cloud.
    The OpenAI SDK handles 429 retries automatically with a default of 2 retries. If the server returns a
    Retry-After header (or retry-after-ms), the SDK waits that duration, capped at MAX_RETRY_AFTER_DELAY (60s) —
    if the header exceeds 60s the request is not retried. If no header is returned (e.g. LLM provider omits it),
    the SDK falls back to exponential backoff starting at 0.5s, doubling up to a max of 8s per retry.
    """
    text = f'{prompt.strip()}\n{text.strip()}'
    messages = [
        {
            'role': 'user',
            'content': [
                {'type': 'text', 'text': text}
            ]
        }
    ]
    logger.info(f'Invoking {model} with {len(text)} char prompt: {text}')
    response = await client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=messages,
        temperature=temperature,
        extra_body={'reasoning_effort': 'none'},  # to suppress chain-of-thought and keep latency and token usage low.
    )
    logger.info(f'{response=}')
    logger.info(f'LLM response: model={response.model} completion_tokens={response.usage.completion_tokens if response.usage else "?"} finish_reason={response.choices[0].finish_reason if response.choices else "?"}')
    if not response.choices:
        error = response.model_extra.get('error') if response.model_extra else None
        if error:
            raise Exception(f'Error calling {model}: {error}')
        else:
            raise Exception(f'Unknown Error calling {model}')
    answer = response.choices[0].message.content
    return answer

if __name__ == "__main__":
    import asyncio

    import logging_config  # noqa: F401  (imported for its module-level logging.basicConfig side effect)
    from utils import load_prompt

    MAX_TOKENS_LYRICS = 150
    TEMPERATURE_LYRICS = 0.9

    MAX_TOKENS_SLDS = 150
    TEMPERATURE_SLDS = 1.0

    async def main():
        prompt = load_prompt("generate_jingle_lyrics.txt")
        domain = "heartmender.ai"
        description = "provides relationship advice for couples on the brink of breakup"
        text = f"Domain: {domain}\nApp description: {description}"
        result = await invoke(prompt, text, max_tokens=MAX_TOKENS_LYRICS, temperature=TEMPERATURE_LYRICS)
        print(result)

        prompt = load_prompt("suggest_slds.prompt.txt")
        text = "helps people learn to play the guitar"
        results = await asyncio.gather(*[
            invoke(prompt, text, max_tokens=MAX_TOKENS_SLDS, temperature=TEMPERATURE_SLDS)
            for i in range(2)
        ])
        for i, suggestions in enumerate(results):
            print(f"--- Suggestion {i+1} ---")
            print(suggestions)
        print(results[-1])

    asyncio.run(main())
