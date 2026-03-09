"""UnoLock Agent MCP package."""

from importlib.metadata import PackageNotFoundError, version


def package_version() -> str:
    try:
        return version("unolock-agent-mcp")
    except PackageNotFoundError:
        return "0.0.0+dev"


__version__ = package_version()
