import json
import os
from pathlib import Path
from typing import Dict, List

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - library may be absent during tests
    OpenAI = None  # type: ignore

CACHE_FILE = "top50_groups.json"


def generate_top_kpop_groups(cache_file: str = CACHE_FILE,
                             model: str = "gpt-3.5-turbo") -> Dict[str, List[str]]:
    """Generate top K-pop groups using an LLM and cache the result.

    If ``cache_file`` exists, its contents are returned instead of calling
    the API. The OpenAI API key is expected in the ``OPENAI_API_KEY``
    environment variable.
    """
    path = Path(cache_file)
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    if OpenAI is None:
        raise RuntimeError("openai package is not installed")

    client = OpenAI(api_key=api_key)

    prompt = (
        "Return a JSON object where each key is the name of a popular K-pop "
        "girl group and the value is a list of its members. Provide exactly "
        "50 groups."
    )

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    text = response.choices[0].message.content  # type: ignore[attr-defined]
    data: Dict[str, List[str]] = json.loads(text)

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return data


if __name__ == "__main__":  # pragma: no cover
    groups = generate_top_kpop_groups()
    print(json.dumps(groups, ensure_ascii=False, indent=2))
