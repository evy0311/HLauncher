"""Service and plugin-management entrypoints."""

import sys


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command == "plugins":
        from .plugins import main as plugins

        plugins(sys.argv[2:])
    elif command == "run":
        if len(sys.argv) > 1:
            del sys.argv[1]
        from .radio import main as run

        run()
    else:
        raise SystemExit(
            "Usage: python3 -m hlauncher [run [--seconds N] | plugins list | plugins install SOURCE [--subdir PATH]]"
        )


if __name__ == "__main__":
    main()
