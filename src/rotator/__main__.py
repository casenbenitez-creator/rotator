from __future__ import annotations

import argparse
import asyncio
import sys


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="rotator")
    parser.add_argument(
        "--proxy-only",
        action="store_true",
        help="Run in headless proxy mode (no TUI)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.proxy_only:
        from rotator.proxy.server import run_proxy

        asyncio.run(run_proxy())
        return 0

    from rotator.app import RotatorApp

    app = RotatorApp()
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
