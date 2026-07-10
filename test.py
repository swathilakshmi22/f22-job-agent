from __future__ import annotations

import os

from openai import OpenAI


def main() -> None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Set OPENAI_API_KEY before running this test.")

    client = OpenAI(api_key=api_key, base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_TEST_MODEL", "gpt-4.1-mini"),
        messages=[
            {
                "role": "user",
                "content": "Reply with exactly: OpenAI is working!",
            }
        ],
        temperature=0,
        max_tokens=20,
    )
    print("Status Code: 200")
    print(response.choices[0].message.content)


if __name__ == "__main__":
    main()
