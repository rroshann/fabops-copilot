"""Langfuse Cloud integration using the v3 SDK's LangChain CallbackHandler.

This module exposes two helpers:

- ``get_callback_handler()``: returns a CallbackHandler instance you attach to
  ``graph.invoke(config={"callbacks": [handler]})``. Falls back to ``None``
  when Langfuse is not configured or importable, so the caller can do:

    handlers = []
    cb = get_callback_handler()
    if cb is not None:
        handlers.append(cb)
    final_state = graph.invoke(initial_state, config={"callbacks": handlers})

- ``flush()``: force the Langfuse client to drain its buffered events before
  process exit. On Lambda the handler should call this in a ``finally`` block
  so traces land in Langfuse Cloud before the container goes idle.

Why CallbackHandler instead of @observe():
  The v2 ``@observe()`` decorator approach was deprecated in Langfuse 3.x and
  is documented as unreliable on Lambda (see
  https://langfuse.com/integrations/frameworks/langchain). The supported
  pattern for any LangChain/LangGraph app is the callback handler — it attaches
  to the native LangChain callbacks pipeline, picks up every LLM/tool span
  automatically, and flushes cleanly with ``langfuse.flush()``.

Why guard on env vars:
  Constructing the Langfuse client with empty strings causes warning noise on
  every import. We only import/construct when LANGFUSE_PUBLIC_KEY is set.
"""
import os
from typing import Any, Optional

_CALLBACK_HANDLER: Optional[Any] = None
_LANGFUSE_CLIENT: Optional[Any] = None


def _init() -> None:
    """Create the Langfuse client + callback handler once on first access."""
    global _CALLBACK_HANDLER, _LANGFUSE_CLIENT
    if _CALLBACK_HANDLER is not None or _LANGFUSE_CLIENT is not None:
        return
    if not os.environ.get("LANGFUSE_PUBLIC_KEY"):
        return
    try:
        from langfuse import get_client
        from langfuse.langchain import CallbackHandler

        _LANGFUSE_CLIENT = get_client()
        _CALLBACK_HANDLER = CallbackHandler()
    except Exception:
        # Any import or init failure means we silently fall back to no-op.
        # This keeps tests green in environments without langfuse installed
        # and keeps the runtime Lambda healthy if langfuse has a transient
        # startup issue.
        _CALLBACK_HANDLER = None
        _LANGFUSE_CLIENT = None


def get_callback_handler() -> Optional[Any]:
    """Return a Langfuse CallbackHandler for graph.invoke, or None if disabled."""
    _init()
    return _CALLBACK_HANDLER


def flush() -> None:
    """Drain buffered trace events. Call in a finally block on Lambda."""
    _init()
    if _LANGFUSE_CLIENT is not None:
        try:
            _LANGFUSE_CLIENT.flush()
        except Exception:
            pass
