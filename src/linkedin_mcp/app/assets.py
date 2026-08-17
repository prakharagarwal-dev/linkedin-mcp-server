"""Direct access to explicitly configured local LinkedIn attachments."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from pathlib import Path

from linkedin_mcp.errors import InvalidTargetError
from linkedin_mcp.tools._shared.models import AssetReference
from linkedin_mcp.tools.posts._shared.models import PostAssetRole
from linkedin_mcp.tools.posts.comment.models import CommentAttachment, CommentPhotoAttachment
from linkedin_mcp.tools.posts.create.models import (
    CelebrationPostContent,
    DocumentPostContent,
    EventPostContent,
    ImagePostContent,
    PostCreateContent,
    VideoPostContent,
)

_MIB = 1024 * 1024
_ROLE_LIMITS: dict[PostAssetRole, tuple[int, int]] = {
    PostAssetRole.IMAGE: (1, 5 * _MIB),
    PostAssetRole.VIDEO: (75 * 1024, 5 * 1024 * _MIB),
    PostAssetRole.VIDEO_THUMBNAIL: (1, 5 * _MIB),
    PostAssetRole.VIDEO_CAPTIONS: (1, 10 * _MIB),
    PostAssetRole.DOCUMENT: (1, 100 * _MIB),
    PostAssetRole.CELEBRATION_IMAGE: (1, 5 * _MIB),
    PostAssetRole.EVENT_COVER_IMAGE: (1, 5 * _MIB),
    PostAssetRole.COMMENT_IMAGE: (1, 5 * _MIB),
    PostAssetRole.MESSAGE_ATTACHMENT: (1, 20 * _MIB),
}
_ROLE_EXTENSIONS: dict[PostAssetRole, frozenset[str]] = {
    PostAssetRole.IMAGE: frozenset({".gif", ".jpeg", ".jpg", ".png", ".webp"}),
    PostAssetRole.VIDEO: frozenset(
        {
            ".avi",
            ".flv",
            ".m4v",
            ".mkv",
            ".mov",
            ".mp4",
            ".mpeg",
            ".mpg",
            ".webm",
            ".wmv",
        }
    ),
    PostAssetRole.VIDEO_THUMBNAIL: frozenset({".gif", ".jpeg", ".jpg", ".png", ".webp"}),
    PostAssetRole.VIDEO_CAPTIONS: frozenset({".srt"}),
    PostAssetRole.DOCUMENT: frozenset(
        {".doc", ".docx", ".ods", ".odt", ".pdf", ".ppsx", ".ppt", ".pptx"}
    ),
    PostAssetRole.CELEBRATION_IMAGE: frozenset({".gif", ".jpeg", ".jpg", ".png", ".webp"}),
    PostAssetRole.EVENT_COVER_IMAGE: frozenset({".gif", ".jpeg", ".jpg", ".png", ".webp"}),
    PostAssetRole.COMMENT_IMAGE: frozenset({".gif", ".jpeg", ".jpg", ".png", ".webp"}),
    PostAssetRole.MESSAGE_ATTACHMENT: frozenset(
        {
            ".ai",
            ".bmp",
            ".doc",
            ".docx",
            ".eml",
            ".gif",
            ".heic",
            ".heif",
            ".jpeg",
            ".jpg",
            ".mov",
            ".mp4",
            ".pdf",
            ".png",
            ".pps",
            ".ppsx",
            ".psd",
            ".ppt",
            ".pptx",
            ".tif",
            ".tiff",
            ".txt",
            ".webp",
            ".xls",
            ".xlsx",
        }
    ),
}


class LocalAssetStore:
    """Resolve supported relative attachments below one configured root."""

    def __init__(self, root: Path) -> None:
        self._root = root

    async def resolve_post(self, content: PostCreateContent) -> dict[str, Path]:
        resolved = await self._resolve_assets(tuple(self._asset_requests(content)))
        return {asset_ref: path for asset_ref, path, _ in resolved}

    async def resolve_comment(self, attachment: CommentAttachment | None) -> dict[str, Path]:
        if not isinstance(attachment, CommentPhotoAttachment):
            return {}
        resolved = await self._resolve_assets(
            ((attachment.asset_ref, PostAssetRole.COMMENT_IMAGE),)
        )
        return {asset_ref: path for asset_ref, path, _ in resolved}

    async def resolve_message(
        self,
        attachment_refs: tuple[AssetReference, ...],
    ) -> dict[str, Path]:
        resolved = await self._resolve_assets(
            tuple((asset_ref, PostAssetRole.MESSAGE_ATTACHMENT) for asset_ref in attachment_refs)
        )
        if sum(size for _, _, size in resolved) > 20 * _MIB:
            raise InvalidTargetError("Combined LinkedIn desktop message attachments exceed 20 MB.")
        return {asset_ref: path for asset_ref, path, _ in resolved}

    async def _resolve_assets(
        self,
        assets: tuple[tuple[AssetReference, PostAssetRole], ...],
    ) -> tuple[tuple[str, Path, int], ...]:
        return tuple(
            await asyncio.gather(
                *(
                    asyncio.to_thread(self._resolve_one, asset_ref, role)
                    for asset_ref, role in assets
                )
            )
        )

    @staticmethod
    def _asset_requests(
        content: PostCreateContent,
    ) -> Iterable[tuple[AssetReference, PostAssetRole]]:
        if isinstance(content, ImagePostContent):
            for image in content.images:
                yield image.asset_ref, PostAssetRole.IMAGE
        elif isinstance(content, VideoPostContent):
            yield content.video_asset_ref, PostAssetRole.VIDEO
            if content.thumbnail_asset_ref is not None:
                yield content.thumbnail_asset_ref, PostAssetRole.VIDEO_THUMBNAIL
            if content.caption_asset_ref is not None:
                yield content.caption_asset_ref, PostAssetRole.VIDEO_CAPTIONS
        elif isinstance(content, DocumentPostContent):
            yield content.document_asset_ref, PostAssetRole.DOCUMENT
        elif isinstance(content, CelebrationPostContent):
            if content.image_asset_ref is not None:
                yield content.image_asset_ref, PostAssetRole.CELEBRATION_IMAGE
        elif isinstance(content, EventPostContent) and content.cover_asset_ref is not None:
            yield content.cover_asset_ref, PostAssetRole.EVENT_COVER_IMAGE

    def _resolve_one(
        self,
        asset_ref: AssetReference,
        role: PostAssetRole,
    ) -> tuple[str, Path, int]:
        path = self._resolve(asset_ref)
        size = path.stat().st_size
        minimum, maximum = _ROLE_LIMITS[role]
        if not minimum <= size <= maximum:
            raise InvalidTargetError(
                f"The {role.value} asset size is outside LinkedIn's supported visible range."
            )
        extension = path.suffix.casefold()
        if extension not in _ROLE_EXTENSIONS[role]:
            raise InvalidTargetError(
                f"The {role.value} asset file type is outside the accepted LinkedIn contract."
            )
        return asset_ref, path, size

    def _resolve(self, asset_ref: str) -> Path:
        relative = Path(asset_ref)
        if (
            relative.is_absolute()
            or not relative.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise InvalidTargetError("Local asset references must be safe relative paths.")
        try:
            root = self._root.resolve(strict=True)
            path = (root / relative).resolve(strict=True)
        except (FileNotFoundError, OSError) as error:
            raise InvalidTargetError(
                f"Local asset {asset_ref!r} is unavailable in the configured asset root."
            ) from error
        if not path.is_relative_to(root) or not path.is_file():
            raise InvalidTargetError(
                "Local assets must be regular files inside the configured asset root."
            )
        return path
