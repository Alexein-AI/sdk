"""Alexein for Python: long-term memory for your app users, behind one API key.

```python
from alexein import Memory

dana = Memory().user("dana")
dana.add("I moved to Lisbon for the job at Acme.")
print(dana.search("Where does Dana live?").context())
```

The framework integrations are modules of their own, imported only when you import them:
`alexein.langgraph`, `alexein.openai_agents` and `alexein.crewai`.
"""

from alexein._async_user import AsyncUser
from alexein._client import AsyncMemory, Memory
from alexein._errors import (
    AlexeinError,
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    FieldError,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServiceUnavailableError,
)
from alexein._memories import AnyMemory, Excerpt, Fact, Known, Memories, Opened, SearchResult
from alexein._results import (
    AppUser,
    ExportPage,
    FactsPage,
    FollowUp,
    History,
    ItemsPage,
    Me,
    OpenItem,
    OpenItems,
    Source,
    Sources,
    StoredItem,
    Summary,
    UsersPage,
    Value,
)
from alexein._types import Author, Item
from alexein._user import User
from alexein._version import __version__
from alexein._writes import (
    AddedItem,
    AddResult,
    Correction,
    Deleted,
    Erased,
    Forgotten,
    ItemStatus,
    Statuses,
    Versions,
)

__all__ = [
    "APIConnectionError",
    "APITimeoutError",
    "AddResult",
    "AddedItem",
    "AlexeinError",
    "AnyMemory",
    "AppUser",
    "AsyncMemory",
    "AsyncUser",
    "AuthenticationError",
    "Author",
    "Correction",
    "Deleted",
    "Erased",
    "Excerpt",
    "ExportPage",
    "Fact",
    "FactsPage",
    "FieldError",
    "FollowUp",
    "Forgotten",
    "History",
    "InvalidRequestError",
    "Item",
    "ItemStatus",
    "ItemsPage",
    "Known",
    "Me",
    "Memories",
    "Memory",
    "NotFoundError",
    "OpenItem",
    "OpenItems",
    "Opened",
    "PermissionDeniedError",
    "RateLimitError",
    "SearchResult",
    "ServiceUnavailableError",
    "Source",
    "Sources",
    "Statuses",
    "StoredItem",
    "Summary",
    "User",
    "UsersPage",
    "Value",
    "Versions",
    "__version__",
]
