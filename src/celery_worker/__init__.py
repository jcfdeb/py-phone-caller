"""Celery worker service for py-phone-caller."""

import sys


def main() -> None:
    """Starts the py-phone-caller Celery worker."""
    from celery.bin.celery import main as celery_main

    argv = sys.argv[1:] or [
        "-A",
        "py_phone_caller_utils.tasks.celery_task",
        "worker",
        "--loglevel=info",
    ]
    sys.exit(celery_main(["celery", *argv]))

