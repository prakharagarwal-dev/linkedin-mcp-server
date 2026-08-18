from __future__ import annotations

from enum import StrEnum


class PersonProfileSectionSelector(StrEnum):
    ALL = "all"
    OVERVIEW = "overview"
    ABOUT = "about"
    EXPERIENCE = "experience"
    EDUCATION = "education"
    LICENSES_CERTIFICATIONS = "licenses-certifications"
    PROJECTS = "projects"
    VOLUNTEERING = "volunteering"
    SKILLS = "skills"
    INTERESTS = "interests"
    FEATURED = "featured"
    COURSES = "courses"
    HONORS_AWARDS = "honors-awards"
    LANGUAGES = "languages"
    ORGANIZATIONS = "organizations"
    PUBLICATIONS = "publications"
    PATENTS = "patents"
    RECOMMENDATIONS = "recommendations"
    TEST_SCORES = "test-scores"
