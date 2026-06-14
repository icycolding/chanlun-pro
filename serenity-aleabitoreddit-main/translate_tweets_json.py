#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import openai

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

try:  # noqa: E402
    from chanlun import config as app_config  # type: ignore

    OPENROUTER_API_KEY = app_config.OPENROUTER_AI_KEYS
    OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL = app_config.OPENROUTER_AI_MODEL
except Exception:  # noqa: E402
    from config_ai_enhanced import (  # type: ignore
        OPENROUTER_API_KEY,
        OPENROUTER_BASE_URL,
        OPENROUTER_MODEL,
    )

ARCHIVE_PATH = Path(__file__).resolve().parent / "data" / "aleabitoreddit_tweets.json"

SYSTEM_PROMPT = """You are a professional financial tweet translator.
Translate each source text into natural Simplified Chinese.

Rules:
- Translate every sentence completely.
- Do not summarize.
- Do not omit content.
- Preserve tickers like $NVDA, $SIVE, $TSM.
- Preserve numbers, percentages, dates, URLs, @mentions, hashtags, and list numbering.
- Preserve paragraph breaks as much as possible.
- Keep finance and semiconductor terminology accurate.
- Return valid JSON only.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default=str(ARCHIVE_PATH))
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--model", default=OPENROUTER_MODEL)
    parser.add_argument("--request-timeout", type=float, default=90.0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    return parser.parse_args()


def load_archive(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    if not isinstance(payload, list):
        raise ValueError("Archive JSON must be a list")
    return payload


def save_archive(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fp:
        json.dump(rows, fp, ensure_ascii=False, indent=2)
        fp.write("\n")


def iter_jobs(rows: list[dict[str, Any]], force: bool) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for row_index, row in enumerate(rows):
        text = str(row.get("text") or "")
        if text and (force or not row.get("text_zh")):
            jobs.append(
                {
                    "row_index": row_index,
                    "path": "text_zh",
                    "source": text,
                    "lang": str(row.get("lang") or "").lower(),
                    "tweet_id": str(row.get("id") or ""),
                }
            )
        quoted = row.get("quotedTweet")
        if not isinstance(quoted, dict):
            continue
        quoted_text = str(quoted.get("text") or "")
        if quoted_text and (force or not quoted.get("text_zh")):
            jobs.append(
                {
                    "row_index": row_index,
                    "path": "quotedTweet.text_zh",
                    "source": quoted_text,
                    "lang": str(row.get("lang") or "").lower(),
                    "tweet_id": str(row.get("id") or ""),
                }
            )
    return jobs


def build_messages(batch: list[dict[str, Any]]) -> list[dict[str, str]]:
    payload = [
        {
            "index": idx,
            "tweet_id": item["tweet_id"],
            "path": item["path"],
            "source": item["source"],
        }
        for idx, item in enumerate(batch)
    ]
    user_prompt = (
        "Translate the following tweet texts into Simplified Chinese.\n"
        "Return JSON with this exact shape:\n"
        '{"items":[{"index":0,"translation":"..."}]}\n'
        "Keep the item order and indices unchanged.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in model response")
    return json.loads(text[start : end + 1])


def translate_batch(
    client: openai.OpenAI,
    batch: list[dict[str, Any]],
    model: str,
    request_timeout: float,
) -> list[str]:
    short_circuit = []
    needs_model = []
    mapping: dict[int, str] = {}

    for index, item in enumerate(batch):
        if item["lang"] == "zh":
            mapping[index] = item["source"]
        else:
            needs_model.append((index, item))

    if not needs_model:
        return [mapping[idx] for idx in range(len(batch))]

    model_batch = [item for _, item in needs_model]
    response = client.chat.completions.create(
        model=model,
        messages=build_messages(model_batch),
        temperature=0,
        timeout=request_timeout,
    )
    content = response.choices[0].message.content or ""
    parsed = extract_json_object(content)
    items = parsed.get("items")
    if not isinstance(items, list):
        raise ValueError("Model response missing items list")

    translated_by_local_index: dict[int, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        local_index = item.get("index")
        translation = item.get("translation")
        if not isinstance(local_index, int) or not isinstance(translation, str):
            continue
        translated_by_local_index[local_index] = translation

    for local_index, (_, original_item) in enumerate(needs_model):
        translation = translated_by_local_index.get(local_index)
        if not translation:
            raise ValueError(f"Missing translation for batch item {local_index}")
        source_index = batch.index(original_item)
        mapping[source_index] = translation

    return [mapping[idx] for idx in range(len(batch))]


def apply_translation(row: dict[str, Any], path: str, translation: str) -> None:
    if path == "text_zh":
        row["text_zh"] = translation
        return
    if path == "quotedTweet.text_zh":
        quoted = row.get("quotedTweet")
        if isinstance(quoted, dict):
            quoted["text_zh"] = translation
        return
    raise ValueError(f"Unsupported path: {path}")


def main() -> int:
    args = parse_args()
    path = Path(args.path).resolve()
    rows = load_archive(path)
    jobs = iter_jobs(rows, force=args.force)
    if args.limit > 0:
        jobs = jobs[: args.limit]

    if not jobs:
        print("No translation work required.")
        return 0

    if not args.no_backup:
        backup_path = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup_path)
        print(f"Backup created: {backup_path}")

    client = openai.OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
    )

    completed = 0
    total = len(jobs)
    for start in range(0, total, args.batch_size):
        batch = jobs[start : start + args.batch_size]
        for attempt in range(3):
            try:
                translations = translate_batch(
                    client,
                    batch,
                    model=args.model,
                    request_timeout=args.request_timeout,
                )
                break
            except Exception as exc:
                if attempt == 2:
                    raise
                print(
                    f"Retry batch {start // args.batch_size + 1} after error: {exc}",
                    flush=True,
                )
                time.sleep(2 + attempt)
        for item, translation in zip(batch, translations):
            apply_translation(rows[item["row_index"]], item["path"], translation)
            completed += 1

        save_archive(path, rows)
        print(
            f"Saved batch {start // args.batch_size + 1} "
            f"({completed}/{total})",
            flush=True,
        )
        time.sleep(args.sleep)

    print(f"Done. Translated fields: {completed}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
