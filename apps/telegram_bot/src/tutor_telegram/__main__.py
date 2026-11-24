"""Run with: uv run python -m tutor_telegram"""

import logging

from tutor_telegram.bot import build_application
from tutor_telegram.config import BotSettings


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # don't log URLs containing the token
    build_application(BotSettings()).run_polling()  # type: ignore[call-arg]


if __name__ == "__main__":
    main()
