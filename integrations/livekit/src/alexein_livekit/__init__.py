"""Long-term memory for LiveKit voice agents, from Alexein.

```python
from alexein_livekit import AlexeinMemory, AlexeinMemoryAgent

@server.rtc_session()
async def entrypoint(ctx: JobContext):
    memory = AlexeinMemory.from_job(ctx, metadata_key="alexein_user_id")  # your user id
    await ctx.connect()
    if memory.user_id is None:  # no id dispatched: one memory per LiveKit identity
        memory.bind(participant=await ctx.wait_for_participant())
    session = AgentSession(stt=..., llm=..., tts=...)
    memory.attach(session)
    await session.start(room=ctx.room, agent=AlexeinMemoryAgent(memory, instructions="..."))
```

Before each reply the agent is given what memory holds about the user from earlier calls; every
turn of this call is saved for the next. Neither ever holds up a reply for long, or stops one.
"""

from alexein_livekit._agent import AlexeinMemoryAgent
from alexein_livekit._identity import app_user_id, participant_id
from alexein_livekit._memory import AlexeinMemory
from alexein_livekit._recall import RecallInfo
from alexein_livekit._settings import Settings

__all__ = [
    "AlexeinMemory",
    "AlexeinMemoryAgent",
    "RecallInfo",
    "Settings",
    "app_user_id",
    "participant_id",
]
__version__ = "0.3.0"
