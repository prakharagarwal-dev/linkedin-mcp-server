"""Hash-locked access to explicitly configured local LinkedIn assets."""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
from collections.abc import Iterable
from pathlib import Path

from linkedin_mcp.domain.models import (
    ActionAssetSnapshot,
    CelebrationPostContent,
    CommentPhotoAttachment,
    DocumentPostContent,
    EventPostContent,
    ImagePostContent,
    MessageSendInput,
    PostAssetRole,
    PostCommentInput,
    PostCreateContent,
    PostCreatePayload,
    VideoPostContent,
)
from linkedin_mcp.errors import InvalidTargetError

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
    """Resolve only relative references below one configured root and lock their bytes."""

    def __init__(self, root: Path) -> None:
        self._root = root

    async def snapshot(self, content: PostCreateContent) -> tuple[ActionAssetSnapshot, ...]:
        requests = tuple(self._asset_requests(content))
        return tuple(
            await asyncio.gather(
                *(
                    asyncio.to_thread(
                        self._snapshot_one,
                        asset_ref,
                        role,
                        alt_text,
                        tagged_profile_slugs,
                        tagged_company_slugs,
                    )
                    for (
                        asset_ref,
                        role,
                        alt_text,
                        tagged_profile_slugs,
                        tagged_company_slugs,
                    ) in requests
                )
            )
        )

    async def verify(
        self,
        payload: PostCreatePayload,
    ) -> dict[str, Path]:
        return await self.verify_assets(payload.assets)

    async def snapshot_comment(
        self,
        request: PostCommentInput,
    ) -> tuple[ActionAssetSnapshot, ...]:
        if not isinstance(request.attachment, CommentPhotoAttachment):
            return ()
        return (
            await asyncio.to_thread(
                self._snapshot_one,
                request.attachment.asset_ref,
                PostAssetRole.COMMENT_IMAGE,
                None,
                (),
                (),
            ),
        )

    async def snapshot_message(
        self,
        request: MessageSendInput,
    ) -> tuple[ActionAssetSnapshot, ...]:
        assets = tuple(
            await asyncio.gather(
                *(
                    asyncio.to_thread(
                        self._snapshot_one,
                        attachment.asset_ref,
                        PostAssetRole.MESSAGE_ATTACHMENT,
                        None,
                        (),
                        (),
                    )
                    for attachment in request.attachments
                )
            )
        )
        if sum(asset.size_bytes for asset in assets) > 20 * _MIB:
            raise InvalidTargetError("Combined LinkedIn desktop message attachments exceed 20 MB.")
        return assets

    async def verify_assets(
        self,
        assets: tuple[ActionAssetSnapshot, ...],
    ) -> dict[str, Path]:
        verified = await asyncio.gather(
            *(asyncio.to_thread(self._verify_one, asset) for asset in assets)
        )
        return dict(verified)

    @staticmethod
    def _asset_requests(
        content: PostCreateContent,
    ) -> Iterable[
        tuple[
            str,
            PostAssetRole,
            str | None,
            tuple[str, ...],
            tuple[str, ...],
        ]
    ]:
        if isinstance(content, ImagePostContent):
            for image in content.images:
                yield (
                    image.asset_ref,
                    PostAssetRole.IMAGE,
                    image.alt_text,
                    tuple(
                        member.profile_slug
                        for member in image.tagged_members
                        if member.profile_slug is not None
                    ),
                    tuple(
                        member.company_slug
                        for member in image.tagged_members
                        if member.company_slug is not None
                    ),
                )
        elif isinstance(content, VideoPostContent):
            yield content.video_asset_ref, PostAssetRole.VIDEO, None, (), ()
            if content.thumbnail_asset_ref is not None:
                yield (
                    content.thumbnail_asset_ref,
                    PostAssetRole.VIDEO_THUMBNAIL,
                    None,
                    (),
                    (),
                )
            if content.caption_asset_ref is not None:
                yield (
                    content.caption_asset_ref,
                    PostAssetRole.VIDEO_CAPTIONS,
                    None,
                    (),
                    (),
                )
        elif isinstance(content, DocumentPostContent):
            yield (
                content.document_asset_ref,
                PostAssetRole.DOCUMENT,
                None,
                (),
                (),
            )
        elif isinstance(content, CelebrationPostContent):
            if content.image_asset_ref is not None:
                yield (
                    content.image_asset_ref,
                    PostAssetRole.CELEBRATION_IMAGE,
                    content.image_alt_text,
                    (),
                    (),
                )
        elif isinstance(content, EventPostContent) and content.cover_asset_ref is not None:
            yield (
                content.cover_asset_ref,
                PostAssetRole.EVENT_COVER_IMAGE,
                content.cover_alt_text,
                (),
                (),
            )

    def _snapshot_one(
        self,
        asset_ref: str,
        role: PostAssetRole,
        alt_text: str | None,
        tagged_profile_slugs: tuple[str, ...],
        tagged_company_slugs: tuple[str, ...],
    ) -> ActionAssetSnapshot:
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
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return ActionAssetSnapshot(
            asset_ref=asset_ref,
            role=role,
            sha256=self._sha256(path),
            size_bytes=size,
            media_type=media_type,
            alt_text=alt_text,
            tagged_profile_slugs=tagged_profile_slugs,
            tagged_company_slugs=tagged_company_slugs,
        )

    def _verify_one(self, expected: ActionAssetSnapshot) -> tuple[str, Path]:
        path = self._resolve(expected.asset_ref)
        size = path.stat().st_size
        digest = self._sha256(path)
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if (
            size != expected.size_bytes
            or digest != expected.sha256
            or media_type != expected.media_type
        ):
            raise InvalidTargetError(
                f"Local asset {expected.asset_ref!r} changed during the action."
            )
        return expected.asset_ref, path

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

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()
