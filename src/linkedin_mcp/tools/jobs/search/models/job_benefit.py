from __future__ import annotations

from enum import StrEnum


class JobBenefit(StrEnum):
    MEDICAL_INSURANCE = "medical_insurance"
    VISION_INSURANCE = "vision_insurance"
    DENTAL_INSURANCE = "dental_insurance"
    RETIREMENT_401K = "retirement_401k"
    PENSION_PLAN = "pension_plan"
    PAID_MATERNITY_LEAVE = "paid_maternity_leave"
    PAID_PATERNITY_LEAVE = "paid_paternity_leave"
    COMMUTER_BENEFITS = "commuter_benefits"
    STUDENT_LOAN_ASSISTANCE = "student_loan_assistance"
    TUITION_ASSISTANCE = "tuition_assistance"
    DISABILITY_INSURANCE = "disability_insurance"
