"""LinkedIn Jobs URL parsing and construction."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from linkedin_mcp.errors import InvalidTargetError

_JOB_PATH = re.compile(r"^/jobs/view/(?P<job_id>[0-9]{5,30})(?:/|$)")


def job_id_from_url(url: str) -> str | None:
    parsed = urlsplit(url)
    path_match = _JOB_PATH.match(parsed.path)
    if path_match:
        return path_match.group("job_id")
    query = parse_qs(parsed.query)
    current_job_id = query.get("currentJobId", [None])[0]
    if current_job_id and re.fullmatch(r"[0-9]{5,30}", current_job_id):
        return current_job_id
    return None


def canonical_job_url(job_id: str) -> str:
    if not re.fullmatch(r"[0-9]{5,30}", job_id):
        raise InvalidTargetError("LinkedIn job IDs must contain 5 to 30 digits.")
    return f"https://www.linkedin.com/jobs/view/{job_id}/"
