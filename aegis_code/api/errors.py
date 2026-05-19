from __future__ import annotations


class AegisApiError(Exception):
    """Base class for public Aegis Code API errors."""


class AegisSetupError(AegisApiError):
    """Raised when setup/readiness API operations fail unexpectedly."""


class AegisPatchError(AegisApiError):
    """Raised when patch proposal API operations fail or receive invalid input."""


class AegisApplyError(AegisApiError):
    """Raised when patch check/apply API operations fail."""


class AegisReportError(AegisApiError):
    """Raised when report artifact retrieval/parsing fails."""
