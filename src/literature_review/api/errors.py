from __future__ import annotations


class APIClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        retryable: bool,
        status: int | None = None,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.status = status
        super().__init__(message)


class APIRequestError(APIClientError):
    """Raised when the model provider request fails before a valid response."""


class APIResponseError(APIClientError):
    """Raised when a provider or model response cannot satisfy the contract."""


__all__ = ["APIClientError", "APIRequestError", "APIResponseError"]
