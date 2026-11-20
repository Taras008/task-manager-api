import logging


def configure_logging(level: int = logging.INFO) -> None:
    """Єдиний формат логів для автономних процесів (воркер)."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
