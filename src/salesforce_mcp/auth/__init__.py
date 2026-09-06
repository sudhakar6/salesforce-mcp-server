from __future__ import annotations

from ..config import Settings
from .client_credentials import ClientCredentialsAuth
from .errors import SalesforceAuthError
from .pkce import PkceRefreshAuth

AuthStrategy = ClientCredentialsAuth | PkceRefreshAuth

__all__ = ["AuthStrategy", "ClientCredentialsAuth", "PkceRefreshAuth", "SalesforceAuthError", "build_auth"]


def build_auth(settings: Settings) -> AuthStrategy:
    """The only place that knows both auth flows exist. Adding a third flow
    later means adding one module next to client_credentials.py/pkce.py and
    one branch here — nothing else in this package changes."""
    if settings.auth_flow == "pkce":
        return PkceRefreshAuth(settings)
    return ClientCredentialsAuth(settings)
