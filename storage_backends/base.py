from typing import BinaryIO, Protocol


class StorageError(Exception):
    """A storage request failed. Provider details must not reach the browser."""


class ObjectMissing(StorageError):
    pass


class ObjectTooLarge(StorageError):
    pass


class Storage(Protocol):
    direct_upload: bool

    def save(self, key: str, stream: BinaryIO, content_type: str) -> str: ...
    def delete(self, key: str) -> None: ...
    def open(self, key: str) -> BinaryIO: ...
    def download_url(self, key: str, name: str) -> str | None: ...
    def upload_url(self, key: str, content_type: str, size: int) -> str: ...
    def copy(self, source: str, destination: str) -> None: ...
