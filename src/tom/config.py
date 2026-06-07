"""Environment-driven configuration, resolved fail-loud.

Nothing in the framework carries a hardcoded path, host, or tunable — they come
from the environment, and a missing one is an error at startup, never a silent
default that sends the daemon at the wrong inbox or the wrong Ollama host. A
malformed or unresolved reference is treated the same way: loud, not papered
over.
"""

from __future__ import annotations

import os
import re

# A well-formed reference: ${NAME}. Anything between ${ and } that isn't a valid
# name is caught separately so a typo fails loud instead of slipping through.
_REFERENCE = re.compile(r"\$\{[^}]*\}")
_WELL_FORMED = re.compile(r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)\}")


def require_env(name: str) -> str:
    """Return the value of ``name``, raising if it is unset or empty."""
    value = os.environ.get(name)
    if value is None:
        raise ValueError(f"required environment variable {name} is not set")
    if value == "":
        raise ValueError(f"required environment variable {name} is set but empty")
    return value


def resolve_env(template: str) -> str:
    """Substitute every ``${NAME}`` in ``template`` with its environment value.

    A reference to an unset variable, a malformed reference (``${1bad}``,
    ``${}``), or a stray unterminated ``${`` all raise — there is no path by
    which an unresolved reference reaches a caller.
    """

    def substitute(match: re.Match[str]) -> str:
        token = match.group(0)
        well_formed = _WELL_FORMED.fullmatch(token)
        if well_formed is None:
            raise ValueError(f"malformed environment reference {token!r} in {template!r}")
        return require_env(well_formed.group("name"))

    resolved = _REFERENCE.sub(substitute, template)
    if "${" in resolved:
        raise ValueError(f"unresolved environment reference in {template!r}")
    return resolved
