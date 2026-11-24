class ServiceError(Exception):
    """Base class. Routes map subclasses to HTTP status codes."""


class NotFoundError(ServiceError):
    pass


class ConflictError(ServiceError):
    pass


class InvalidRequestError(ServiceError):
    pass


class UpstreamError(ServiceError):
    """The LLM provider failed."""
