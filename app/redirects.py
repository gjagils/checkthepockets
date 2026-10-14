"""Redirects to a path given by the client (hidden `redirect_to` fields): same-site paths only."""
from fastapi.responses import RedirectResponse


def safe_path(target, fallback: str = "/transactions") -> str:
    """Return `target` if it is a plain same-site path, else `fallback`.

    A path must start with a single "/"; "//host" and "/\\host" are read by browsers as
    another origin, and control characters allow header tricks.
    """
    if not isinstance(target, str):
        return fallback
    target = target.strip()
    if (
        not target.startswith("/")
        or target.startswith("//")
        or target.startswith("/\\")
        or any(ord(ch) < 32 for ch in target)
        or "\\" in target.split("?", 1)[0]
    ):
        return fallback
    return target


def safe_redirect(target, fallback: str = "/transactions", status_code: int = 302) -> RedirectResponse:
    return RedirectResponse(safe_path(target, fallback), status_code=status_code)
