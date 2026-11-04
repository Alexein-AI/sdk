"""Long-term memory for LiveKit voice agents, from Alexein.

```python
from twinmemory_livekit import TwinMemory, TwinMemoryAgent

@server.rtc_session()
async def entrypoint(ctx: JobContext):
    memory = TwinMemory.from_job(ctx, metadata_key="twinmemory_user_id")  # your user id
    await ctx.connect()
    if memory.user_id is None:  # no id dispatched: one memory per LiveKit identity
        memory.bind(participant=await ctx.wait_for_participant())
    session = AgentSession(stt=..., llm=..., tts=...)
    memory.attach(session)
    await session.start(room=ctx.room, agent=TwinMemoryAgent(memory, instructions="..."))
```

Before each reply the agent is given what memory holds about the user from earlier calls; every
turn of this call is saved for the next. Neither ever holds up a reply for long, or stops one.
"""

from twinmemory_livekit._agent import TwinMemoryAgent
from twinmemory_livekit._identity import account_id, participant_id
from twinmemory_livekit._memory import TwinMemory
from twinmemory_livekit._recall import RecallInfo
from twinmemory_livekit._settings import Settings

__all__ = [
    "RecallInfo",
    "Settings",
    "TwinMemory",
    "TwinMemoryAgent",
    "account_id",
    "participant_id",
]
__version__ = "0.1.0"
