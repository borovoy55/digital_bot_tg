from __future__ import annotations


class AppError(Exception):
    """Base application error safe to show as a short user-facing message."""


class SecurityError(AppError):
    """Raised when a user-controlled token or access check fails."""


class AccessDenied(AppError):
    """Raised when the current actor cannot access the requested resource."""


class ValidationError(AppError):
    """Raised when input data is invalid."""


class NotFoundError(AppError):
    """Raised when an entity is not found."""


class PaymentError(AppError):
    """Raised when payment verification or processing fails."""


class NoAvailableItems(AppError):
    """Raised when no available digital item can be issued."""
