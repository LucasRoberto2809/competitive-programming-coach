"""Hook entry point for response-template generation."""

from ..io import run_cli
from ..services.templates import handle


if __name__ == "__main__":
    run_cli(handle)
