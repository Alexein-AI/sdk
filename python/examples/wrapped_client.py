"""A chat in the terminal whose model remembers you across runs, with no memory tools: the client is
wrapped, so memory is read before each reply and each exchange is saved.

pip install alexein anthropic
ALEXEIN_API_KEY=tm_... ANTHROPIC_API_KEY=sk-ant-... python examples/wrapped_client.py
"""

from __future__ import annotations

import uuid
from typing import Any

from anthropic import Anthropic

from alexein import Memory
from alexein.wrap import memory_of, wrap_anthropic

MODEL = "claude-sonnet-4-5"

memory = Memory(fail_open=True, timeout=10)
claude = wrap_anthropic(
    Anthropic(),
    memory,
    user_id="example-user",  # your id for the person, from your own sign-in
    session=f"chat-{uuid.uuid4().hex[:8]}",
)

messages: list[Any] = []
try:
    while said := input("you> ").strip():
        messages.append({"role": "user", "content": said})
        answer = claude.messages.create(
            model=MODEL, max_tokens=1024, system="You are a helpful assistant.", messages=messages
        )
        text = "".join(block.text for block in answer.content if block.type == "text")
        messages.append({"role": "assistant", "content": text})
        print(f"claude> {text}")
except (EOFError, KeyboardInterrupt):
    pass
finally:
    memory_of(claude).flush()  # the last exchange's save, before the process ends
