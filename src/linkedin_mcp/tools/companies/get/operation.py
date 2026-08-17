"""Application operation for `linkedin.companies.get`."""

from __future__ import annotations

from typing import Protocol

from linkedin_mcp.tools._shared.execution import OperationSupport
from linkedin_mcp.tools.companies.get.evidence import sources_from_company_profile
from linkedin_mcp.tools.companies.get.models import (
    CompanyGetInput,
    CompanyGetOutput,
    CompanyProfileObservation,
    CompanyProfilePageCapture,
)


class CompanyProfileProvider(Protocol):
    async def read(
        self,
        request: CompanyGetInput,
    ) -> tuple[CompanyProfileObservation, tuple[CompanyProfilePageCapture, ...]]: ...


class GetCompanyOperation(OperationSupport):
    _company_profile: CompanyProfileProvider

    async def get_company(self, request: CompanyGetInput) -> CompanyGetOutput:
        company, captures = await self._company_profile.read(request)
        sources = sources_from_company_profile(company, captures)
        return CompanyGetOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            company=company,
            sources=sources,
        )
