"""Public MCP capability implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from linkedin_mcp.app.container import AppContainer


def attach_tools(mcp: FastMCP[None], container: AppContainer) -> None:
    """Attach each capability-owned FastMCP definition."""

    from linkedin_mcp.tools._shared.tool import tool_annotations
    from linkedin_mcp.tools.companies.get.tool import register as register_companies_get
    from linkedin_mcp.tools.companies.search.tool import register as register_companies_search
    from linkedin_mcp.tools.connections.list.tool import register as register_connections_list
    from linkedin_mcp.tools.connections.search.tool import register as register_connections_search
    from linkedin_mcp.tools.invitations.accept.tool import register as register_invitations_accept
    from linkedin_mcp.tools.invitations.ignore.tool import register as register_invitations_ignore
    from linkedin_mcp.tools.invitations.list.tool import register as register_invitations_list
    from linkedin_mcp.tools.invitations.send.tool import register as register_invitations_send
    from linkedin_mcp.tools.jobs.get.tool import register as register_jobs_get
    from linkedin_mcp.tools.jobs.search.tool import register as register_jobs_search
    from linkedin_mcp.tools.messaging.conversation.get.tool import (
        register as register_messaging_conversation_get,
    )
    from linkedin_mcp.tools.messaging.search.tool import register as register_messaging_search
    from linkedin_mcp.tools.messaging.send.tool import register as register_messaging_send
    from linkedin_mcp.tools.people.get.tool import register as register_people_get
    from linkedin_mcp.tools.people.search.tool import register as register_people_search
    from linkedin_mcp.tools.posts.comment.tool import register as register_posts_comment
    from linkedin_mcp.tools.posts.comments.list.tool import register as register_posts_comments_list
    from linkedin_mcp.tools.posts.create.tool import register as register_posts_create
    from linkedin_mcp.tools.posts.get.tool import register as register_posts_get
    from linkedin_mcp.tools.posts.react.tool import register as register_posts_react
    from linkedin_mcp.tools.posts.search.tool import register as register_posts_search
    from linkedin_mcp.tools.server.status.tool import register as register_server_status
    from linkedin_mcp.tools.session.status.tool import register as register_session_status

    annotations = tool_annotations()
    register_server_status(mcp, container, annotations.local_read)
    register_session_status(mcp, container, annotations.local_read)
    register_jobs_search(mcp, container, annotations.linkedin_read)
    register_jobs_get(mcp, container, annotations.linkedin_read)
    register_people_search(mcp, container, annotations.linkedin_read)
    register_people_get(mcp, container, annotations.linkedin_read)
    register_companies_search(mcp, container, annotations.linkedin_read)
    register_companies_get(mcp, container, annotations.linkedin_read)
    register_posts_search(mcp, container, annotations.linkedin_read)
    register_posts_get(mcp, container, annotations.linkedin_read)
    register_posts_comments_list(mcp, container, annotations.linkedin_read)
    register_posts_create(mcp, container, annotations.linkedin_write)
    register_posts_comment(mcp, container, annotations.linkedin_write)
    register_posts_react(mcp, container, annotations.linkedin_write)
    register_invitations_list(mcp, container, annotations.linkedin_read)
    register_connections_list(mcp, container, annotations.linkedin_read)
    register_connections_search(mcp, container, annotations.linkedin_read)
    register_invitations_send(mcp, container, annotations.linkedin_write)
    register_invitations_accept(mcp, container, annotations.linkedin_write)
    register_invitations_ignore(mcp, container, annotations.linkedin_write)
    register_messaging_search(mcp, container, annotations.linkedin_read)
    register_messaging_conversation_get(mcp, container, annotations.messaging_read)
    register_messaging_send(mcp, container, annotations.linkedin_write)
