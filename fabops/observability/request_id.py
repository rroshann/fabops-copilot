"""Request ID generator — single UUIDv4 per agent run, joined across sinks."""
import uuid


def new_request_id() -> str:
    """Generate a request ID used by Langfuse, MLflow, CloudWatch, and fabops_audit."""
    return str(uuid.uuid4())
