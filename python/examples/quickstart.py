"""Add two things one of your app users said, ask about them, then erase the app user.

ALEXEIN_API_KEY=tm_... python examples/quickstart.py
(ALEXEIN_API_URL=http://localhost:8210 for a local stack.)
"""

from alexein import Memory

with Memory() as memory:
    print(memory.me())
    dana = memory.user("quickstart-dana")

    dana.add(
        [
            "I moved to Lisbon for the job at Acme.",
            {"id": "diet", "kind": "note", "text": "Vegetarian, allergic to peanuts."},
        ],
        role="user",
        session="onboarding",
        wait=True,
    )

    result = dana.search("Which city is the job at Acme in?", fast=True)
    print(result.context())
    for ref in result.refs[:1]:
        print(dana.open(ref).memory.text)

    dana.delete()
