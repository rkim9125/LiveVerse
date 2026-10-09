"""The book name prompt given to Whisper with every window."""

from __future__ import annotations

from app.detect.books import BOOKS

# Whisper keeps at most n_text_ctx // 2 - 1 = 223 prompt tokens and drops the front
# of anything longer. All 66 names take 267 tokens, so these rarely preached short
# books are left out to make the rest fit (217 tokens).
PROMPT_MAX_TOKENS = 223
PROMPT_LEFT_OUT = [
    "오바댜",
    "나훔",
    "하박국",
    "스바냐",
    "학개",
    "요엘",
    "빌레몬서",
    "유다서",
    "요한이서",
    "요한삼서",
    "아가",
    "스가랴",
    "예레미야애가",
]


def book_prompt() -> str:
    return " ".join(b.ko for b in BOOKS if b.ko not in PROMPT_LEFT_OUT)
