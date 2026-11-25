class ServiceError(Exception):
    """Base class. Routes map subclasses to HTTP status codes."""


class NotFoundError(ServiceError):
    pass


class ConflictError(ServiceError):
    pass


class InvalidRequestError(ServiceError):
    pass


class UnavailableError(ServiceError):
    """A feature is switched off or not ready (e.g. voice without STT)."""


class UpstreamError(ServiceError):
    """The LLM provider failed."""
