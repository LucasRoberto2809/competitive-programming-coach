"""Hook entry point for source collection."""

from ..io import run_cli
from ..services.sources import handle


if __name__ == "__main__":
    run_cli(handle)
