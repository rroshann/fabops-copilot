"""Langfuse Cloud integration. Reads keys from env.

The module uses a safe-fallback pattern: if langfuse is not installed, not
importable, or if the env vars are absent (no LANGFUSE_PUBLIC_KEY), the
``observe`` decorator becomes a transparent no-op and ``link_request_id``
silently does nothing.  This keeps the shim test-transparent and safe in
environments that have not been provisioned with Langfuse credentials.

Guard decision: the Langfuse(…) client constructor is only called when
LANGFUSE_PUBLIC_KEY is non-empty.  Constructing the client with empty strings
causes langfuse 2.50.0 to emit auth-warning noise to stderr on every import;
guarding with the env-var check eliminates that noise without changing the
runtime behaviour (the no-op fallback wins in both cases when keys are absent).
"""
import os
from functools import wraps
from typing import Callable


def _noop_observe(*dargs, **dkwargs) -> Callable:
    """Transparent no-op replacement for langfuse.decorators.observe."""
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)
        return wrapper
    return decorator


if os.environ.get("LANGFUSE_PUBLIC_KEY"):
    try:
        from langfuse import Langfuse  # noqa: F401 — imported for side-effects / validation
        from langfuse.decorators import observe as _observe

        _LANGFUSE = Langfuse(
            public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
            secret_key=os.environ.get("LANGFUSE_SECRET_KEY", ""),
            host=os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
        observe = _observe
    except Exception:
        observe = _noop_observe
else:
    observe = _noop_observe


def link_request_id(request_id: str) -> None:
    """Tag the current Langfuse trace with our shared request_id.

    Only meaningful when langfuse is active (LANGFUSE_PUBLIC_KEY is set and the
    real ``observe`` decorator is in use).  Silently does nothing otherwise.
    """
    try:
        from langfuse.decorators import langfuse_context
        langfuse_context.update_current_trace(
            user_id=request_id,
            tags=[f"req:{request_id}"],
        )
    except Exception:
        pass


def flush() -> None:
    """Force Langfuse to ship any buffered trace events before Lambda exits.

    Langfuse's default transport batches events in a background thread and
    flushes on a timer — on Lambda the process terminates before the next
    flush fires and the events are lost. Call this at the end of the handler
    to guarantee delivery. No-op when langfuse is not active.
    """
    try:
        from langfuse.decorators import langfuse_context
        langfuse_context.flush()
    except Exception:
        pass
