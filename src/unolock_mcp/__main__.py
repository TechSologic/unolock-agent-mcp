from unolock_mcp.runtime import configure_frozen_oqs_runtime

configure_frozen_oqs_runtime()

from unolock_mcp.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
