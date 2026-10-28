"""Alexein for Python: long-term memory for your users, behind one API key.

```python
from twinmemory import Memory

dana = Memory().user("dana")
dana.add("I moved to Lisbon for the job at Acme.")
print(dana.search("Where does Dana live?").context())
```
"""

from twinmemory._client import AsyncMemory, AsyncUser, Memory, User
from twinmemory._errors import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServiceUnavailableError,
    TwinMemoryError,
)
from twinmemory._types import (
    AddedItem,
    AddResult,
    Author,
    Correction,
    Fact,
    File,
    GrepResult,
    History,
    Hit,
    Item,
    Lineage,
    Listing,
    Me,
    Overview,
    Passages,
    Receipt,
    SearchResult,
    TableChange,
    Versions,
)
from twinmemory._version import __version__

__all__ = [
    "APIConnectionError",
    "APITimeoutError",
    "AddResult",
    "AddedItem",
    "AsyncMemory",
    "AsyncUser",
    "AuthenticationError",
    "Author",
    "Correction",
    "Fact",
    "File",
    "GrepResult",
    "History",
    "Hit",
    "InvalidRequestError",
    "Item",
    "Lineage",
    "Listing",
    "Me",
    "Memory",
    "NotFoundError",
    "Overview",
    "Passages",
    "PermissionDeniedError",
    "RateLimitError",
    "Receipt",
    "SearchResult",
    "ServiceUnavailableError",
    "TableChange",
    "TwinMemoryError",
    "User",
    "Versions",
    "__version__",
]
