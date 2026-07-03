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
        try:
            truthy = bool(value)
        except Exception as exc:
            raise TrueInvalid(self.msg, translation_key="value_was_not_true") from exc

        if not truthy:
            raise TrueInvalid(self.msg, translation_key="value_was_not_true")
        return value


class IsFalse(_SafeValidator):
    """Require the value to be falsy."""

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it is falsy, else raise FalseInvalid."""
        try:
            truthy = bool(value)
        except Exception as exc:
            raise FalseInvalid(self.msg, translation_key="value_was_not_false") from exc

        if truthy:
            raise FalseInvalid(self.msg, translation_key="value_was_not_false")
        return value


class _FilesystemCheck(_SafeValidator):
    """Shared base for the filesystem-path predicates.

    Each subclass names the ``os.path`` test, the error class, and two
    translation keys into the message catalog: ``default_key`` for a value
    that fails the test (and whose message a custom ``msg`` overrides), and
    ``empty_key`` for a falsy or un-stringable value (which a custom message
    does not override, matching voluptuous).
    """

    test: typing.Callable[[str], bool]
    error: type[Invalid]
    default_key: str
    empty_key: str

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message for the failing-test case."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if the path test passes, else raise its error."""
        try:
            if not value:
                raise self.error(translation_key=self.empty_key)
            if type(self).test(str(value)):
                return value
        except Invalid:
            # The empty-value error raised just above is already this validator's
            # own error type; let it through rather than re-wrapping it.
            raise
        except Exception as exc:
            # ValueError covers a path with an embedded NUL byte (os.stat raises);
            # the value's ``__bool__``/``__str__`` are user code and may raise anything.
            raise self.error(translation_key=self.empty_key) from exc

        raise self.error(self.msg, translation_key=self.default_key)


class IsDir(_FilesystemCheck):
    """Require the value to be the path of an existing directory."""

    test = staticmethod(os.path.isdir)
    error = DirInvalid
    default_key = "not_a_directory"
    empty_key = "not_a_directory"


class IsFile(_FilesystemCheck):
    """Require the value to be the path of an existing file."""

    test = staticmethod(os.path.isfile)
    error = FileInvalid
    default_key = "not_a_file"
    empty_key = "not_a_file"


class PathExists(_FilesystemCheck):
    """Require the value to be a path that exists, of any type."""

    test = staticmethod(os.path.exists)
    error = PathInvalid
    default_key = "path_does_not_exist"
    empty_key = "not_a_path"


class IsSymlink(_FilesystemCheck):
    """Require the value to be the path of an existing symbolic link."""

    test = staticmethod(os.path.islink)
    error = SymlinkInvalid
    default_key = "not_a_symlink"
    empty_key = "not_a_symlink"


class IsSocket(_FilesystemCheck):
    """Require the value to be the path of an existing socket."""

    test = staticmethod(_mode_check(stat.S_ISSOCK))
    error = SocketInvalid
    default_key = "not_a_socket"
    empty_key = "not_a_socket"


class IsFifo(_FilesystemCheck):
    """Require the value to be the path of an existing named pipe (FIFO)."""

    test = staticmethod(_mode_check(stat.S_ISFIFO))
    error = FifoInvalid
    default_key = "not_a_fifo"
    empty_key = "not_a_fifo"


class IsBlockDevice(_FilesystemCheck):
    """Require the value to be the path of an existing block device."""

    test = staticmethod(_mode_check(stat.S_ISBLK))
    error = BlockDeviceInvalid
    default_key = "not_a_block_device"
    empty_key = "not_a_block_device"
