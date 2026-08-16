"""Public structural types shared by CLI command modules."""

import argparse
from typing import Protocol


class Subparsers(Protocol):
    def add_parser(
        self,
        name: str,
        *,
        help: str | None = None,
    ) -> argparse.ArgumentParser: ...
