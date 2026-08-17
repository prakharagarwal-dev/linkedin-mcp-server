from __future__ import annotations

from enum import StrEnum


class PersonConnectionDegree(StrEnum):
    FIRST = "first"
    SECOND = "second"
    THIRD_OR_MORE = "third_or_more"
    OUT_OF_NETWORK = "out_of_network"
