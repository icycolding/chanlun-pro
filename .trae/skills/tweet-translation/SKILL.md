---
name: "tweet-translation"
description: "Translates tweets into Simplified Chinese while preserving tickers, numbers, URLs, and line breaks. Invoke when user asks to translate X/Twitter content or tweet archives."
---

# Tweet Translation

Use this skill when the user asks to translate X/Twitter posts, tweet datasets, or tweet archive files into Simplified Chinese.

## Goals

- Translate tweet text accurately into Simplified Chinese.
- Preserve tickers such as `$NVDA`, `$SIVE`, `$TSM`.
- Preserve numbers, percentages, dates, URLs, hashtags, and usernames unless translation improves readability.
- Preserve paragraph breaks and list numbering.
- Keep finance and semiconductor terminology natural and consistent.

## Output Rules

- Default target language: Simplified Chinese.
- Keep the original source text unchanged unless the user explicitly asks to overwrite it.
- Prefer writing translations into sibling fields such as `text_zh`.
- For quoted tweets, prefer `quotedTweet.text_zh`.
- Do not summarize.
- Do not omit sentences.
- Do not invent context that is not present in the source tweet.

## Style Rules

- Use concise, natural Chinese.
- Preserve company names and tickers when they are market identifiers.
- Translate slang carefully; keep tone but avoid over-literal wording.
- Keep line breaks from the original tweet when practical.

## JSON Archive Guidance

When updating tweet archives such as `aleabitoreddit_tweets.json`:

1. Read the JSON structure first.
2. Keep the original `text` field untouched unless explicitly asked to replace it.
3. Add `text_zh` for the main tweet text.
4. If `quotedTweet.text` exists, add `quotedTweet.text_zh`.
5. Preserve all unrelated fields exactly.
6. Validate JSON structure after writing changes.

## Translation Checklist

- Every sentence is translated.
- Tickers and numbers are preserved.
- URLs are preserved.
- No JSON keys are accidentally removed.
- Added translation fields are UTF-8 safe.

## Example

Source:

```text
Surprised $SIVE is only up 3.36% off the news JP Morgan bought 5%+ ownership of Sivers.
```

Translation:

```text
很惊讶，$SIVE 仅因 JP Morgan 买入 Sivers 超过 5% 股权这条消息上涨了 3.36%。
```
