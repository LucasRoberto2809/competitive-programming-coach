"""Hook entry point for manager-authorized guardrails."""

from ..io import run_cli
from ..services.guardrails import handle


if __name__ == "__main__":
    run_cli(handle)
