from __future__ import annotations

import logging
import signal
import sys

from exporter import MerakiAPExporter
from settings import load_settings


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def main() -> int:
    configure_logging()

    try:
        settings = load_settings()
    except Exception as exc:
        logging.getLogger(__name__).error("Failed to load settings: %s", exc)
        return 1

    exporter = MerakiAPExporter(settings)

    def _shutdown_handler(signum: int, _frame: object) -> None:
        logging.getLogger(__name__).info("Received signal %s, stopping exporter", signum)
        exporter.stop()

    signal.signal(signal.SIGINT, _shutdown_handler)
    signal.signal(signal.SIGTERM, _shutdown_handler)

    exporter.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
