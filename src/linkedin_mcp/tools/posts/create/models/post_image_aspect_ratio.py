from __future__ import annotations

from enum import StrEnum


class PostImageAspectRatio(StrEnum):
    ORIGINAL = "original"
    SQUARE = "square"
    FOUR_TO_ONE = "four_to_one"
    THREE_TO_FOUR = "three_to_four"
    SIXTEEN_TO_NINE = "sixteen_to_nine"
