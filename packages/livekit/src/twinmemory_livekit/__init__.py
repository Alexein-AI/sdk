"""Long-term memory for LiveKit voice agents, from twin memory.

```python
from twinmemory_livekit import TwinMemory, TwinMemoryAgent

@server.rtc_session()
async def entrypoint(ctx: JobContext):
    memory = TwinMemory.from_job(ctx)
    await ctx.connect()
    memory.bind(participant=await ctx.wait_for_participant())
    session = AgentSession(stt=..., llm=..., tts=...)
    memory.attach(session)
    await session.start(room=ctx.room, agent=TwinMemoryAgent(memory, instructions="..."))
```

Before each reply the agent is given what memory holds about the user from earlier calls; every
turn of this call is saved for the next. Neither ever holds up a reply for long, or stops one.
"""

from twinmemory_livekit._agent import TwinMemoryAgent
from twinmemory_livekit._identity import account_id
from twinmemory_livekit._memory import TwinMemory
from twinmemory_livekit._recall import RecallInfo

__all__ = ["RecallInfo", "TwinMemory", "TwinMemoryAgent", "account_id"]
__version__ = "0.1.0"
