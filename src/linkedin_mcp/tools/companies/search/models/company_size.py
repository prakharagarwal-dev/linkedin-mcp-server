from __future__ import annotations

from enum import StrEnum


class CompanySize(StrEnum):
    EMPLOYEES_1_10 = "1-10"
    EMPLOYEES_11_50 = "11-50"
    EMPLOYEES_51_200 = "51-200"
    EMPLOYEES_201_500 = "201-500"
    EMPLOYEES_501_1000 = "501-1000"
    EMPLOYEES_1001_5000 = "1001-5000"
    EMPLOYEES_5001_10000 = "5001-10000"
    EMPLOYEES_10001_PLUS = "10001+"
