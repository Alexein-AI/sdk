"""Add two things one of your users said, then ask about them.

TWIN_MEMORY_API_KEY=tm_... python examples/quickstart.py
"""

from twinmemory import Memory

with Memory() as memory:
    print(memory.me())
    dana = memory.user("quickstart-dana")

    dana.add(
        [
            "I moved to Lisbon for the job at Acme.",
            {"id": "diet", "kind": "note", "text": "Vegetarian, allergic to peanuts."},
        ],
        role="user",
        wait=True,
    )

    result = dana.search("Which city is the job at Acme in?", fast=True)
    print(result.context())

    dana.forget(items=["diet"])
