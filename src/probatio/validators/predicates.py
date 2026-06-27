"""Predicate validators: truthiness and filesystem checks."""

from __future__ import annotations

import os
import stat
import typing
from pathlib import Path

from probatio.error import (
    BlockDeviceInvalid,
    DirInvalid,
    FalseInvalid,
    FifoInvalid,
    FileInvalid,
    Invalid,
    PathInvalid,
    SocketInvalid,
    SymlinkInvalid,
    TrueInvalid,
)
from probatio.validators._base import _SafeValidator


def _mode_check(flag: typing.Callable[[int], bool]) -> typing.Callable[[str], bool]:
    """Build a path test for a file-mode flag (socket, FIFO, block device).

    ``os.path`` has no helper for these, so the file mode is read with ``os.stat``
    and tested with the ``stat.S_IS*`` flag. A missing or unreadable path is a
    clean ``False`` (like ``os.path.isfile``), not a leaked ``OSError``.
    """

    def check(path: str) -> bool:
        try:
            return flag(Path(path).stat().st_mode)
        except (OSError, ValueError):
            # ValueError covers a path with an embedded NUL byte.
            return False

    return check


class IsTrue(_SafeValidator):
    """Require the value to be truthy."""

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it is truthy, else raise TrueInvalid."""
        if not value:
            message = self.msg or "value was not true"
            raise TrueInvalid(message)
        return value


class IsFalse(_SafeValidator):
    """Require the value to be falsy."""

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it is falsy, else raise FalseInvalid."""
        if value:
            message = self.msg or "value was not false"
            raise FalseInvalid(message)
        return value


class _FilesystemCheck(_SafeValidator):
    """Shared base for the filesystem-path predicates.

    Each subclass names the ``os.path`` test, the error class, and the two
    messages voluptuous uses: ``default_msg`` for a value that fails the test
    (and which a custom message overrides), and ``empty_msg`` for a falsy or
    un-stringable value (which a custom message does not override, matching
    voluptuous).
    """

    test: typing.Callable[[str], bool]
    error: type[Invalid]
    default_msg: str
    empty_msg: str

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message for the failing-test case."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if the path test passes, else raise its error."""
        try:
            if not value:
                raise self.error(self.empty_msg)
            if type(self).test(str(value)):
                return value
        except (TypeError, ValueError) as exc:
            # ValueError covers a path with an embedded NUL byte (os.stat raises).
            raise self.error(self.empty_msg) from exc
        message = self.msg or self.default_msg
        raise self.error(message)


class IsDir(_FilesystemCheck):
    """Require the value to be the path of an existing directory."""

    test = staticmethod(os.path.isdir)
    error = DirInvalid
    default_msg = "Not a directory"
    empty_msg = "Not a directory"


class IsFile(_FilesystemCheck):
    """Require the value to be the path of an existing file."""

    test = staticmethod(os.path.isfile)
    error = FileInvalid
    default_msg = "Not a file"
    empty_msg = "Not a file"


class PathExists(_FilesystemCheck):
    """Require the value to be a path that exists, of any type."""

    test = staticmethod(os.path.exists)
    error = PathInvalid
    default_msg = "path does not exist"
    empty_msg = "Not a Path"


class IsSymlink(_FilesystemCheck):
    """Require the value to be the path of an existing symbolic link."""

    test = staticmethod(os.path.islink)
    error = SymlinkInvalid
    default_msg = "Not a symlink"
    empty_msg = "Not a symlink"


class IsSocket(_FilesystemCheck):
    """Require the value to be the path of an existing socket."""

    test = staticmethod(_mode_check(stat.S_ISSOCK))
    error = SocketInvalid
    default_msg = "Not a socket"
    empty_msg = "Not a socket"


class IsFifo(_FilesystemCheck):
    """Require the value to be the path of an existing named pipe (FIFO)."""

    test = staticmethod(_mode_check(stat.S_ISFIFO))
    error = FifoInvalid
    default_msg = "Not a FIFO"
    empty_msg = "Not a FIFO"


class IsBlockDevice(_FilesystemCheck):
    """Require the value to be the path of an existing block device."""

    test = staticmethod(_mode_check(stat.S_ISBLK))
    error = BlockDeviceInvalid
    default_msg = "Not a block device"
    empty_msg = "Not a block device"
