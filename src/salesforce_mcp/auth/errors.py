from __future__ import annotations


class SalesforceAuthError(RuntimeError):
    """Raised when authenticating to Salesforce fails, regardless of which
    auth flow was in use. Deliberately has no dependency on either flow's
    module — both import it from here, never from each other."""
