"""Tests for the predicate validators (IsTrue, IsFalse, IsDir, IsFile, PathExists)."""

from __future__ import annotations

import os
import socket
from typing import TYPE_CHECKING

import pytest

from probatio import (
    IsBlockDevice,
    IsDir,
    IsFalse,
    IsFifo,
    IsFile,
    IsSocket,
    IsSymlink,
    IsTrue,
    MultipleInvalid,
    PathExists,
    Schema,
)
from probatio.error import (
    BlockDeviceInvalid,
    DirInvalid,
    FalseInvalid,
    FifoInvalid,
    FileInvalid,
    PathInvalid,
    SocketInvalid,
    SymlinkInvalid,
    TrueInvalid,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_is_true() -> None:
    """IsTrue passes truthy values and rejects falsy ones."""
    assert Schema(IsTrue())(1) == 1
    with pytest.raises(MultipleInvalid) as caught:
        Schema(IsTrue())(0)
    assert isinstance(caught.value.errors[0], TrueInvalid)


def test_is_false() -> None:
    """IsFalse passes falsy values and rejects truthy ones."""
    assert Schema(IsFalse())(0) == 0
    with pytest.raises(MultipleInvalid) as caught:
        Schema(IsFalse())(1)
    assert isinstance(caught.value.errors[0], FalseInvalid)


def test_is_dir_accepts_a_directory(tmp_path: Path) -> None:
    """IsDir accepts the path of an existing directory."""
    assert Schema(IsDir())(str(tmp_path)) == str(tmp_path)


def test_is_dir_rejects_a_non_directory(tmp_path: Path) -> None:
    """IsDir rejects a path that is not a directory."""
    missing = tmp_path / "nope"
    with pytest.raises(MultipleInvalid) as caught:
        Schema(IsDir())(str(missing))
    assert isinstance(caught.value.errors[0], DirInvalid)


def test_is_dir_rejects_a_non_path() -> None:
    """IsDir fails cleanly on a value that is not path-like."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(IsDir())(123)
    assert isinstance(caught.value.errors[0], DirInvalid)


def test_is_dir_message_matches_voluptuous() -> None:
    """IsDir reports the voluptuous wording on a missing directory."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(IsDir())("/no_such_dir_xyz")
    assert caught.value.errors[0].error_message == "Not a directory"


def test_is_file_accepts_a_file(tmp_path: Path) -> None:
    """IsFile accepts the path of an existing file."""
    target = tmp_path / "data.txt"
    target.write_text("hi")
    assert Schema(IsFile())(str(target)) == str(target)


def test_is_file_rejects_a_missing_file(tmp_path: Path) -> None:
    """IsFile rejects a path that is not a file."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(IsFile())(str(tmp_path / "nope"))
    assert isinstance(caught.value.errors[0], FileInvalid)


def test_is_file_rejects_an_empty_value() -> None:
    """A falsy value is reported as FileInvalid, not a crash."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(IsFile())(None)
    assert caught.value.errors[0].error_message == "Not a file"


def test_path_exists_accepts_a_path(tmp_path: Path) -> None:
    """PathExists accepts a path that exists, of any kind."""
    assert Schema(PathExists())(str(tmp_path)) == str(tmp_path)


def test_path_exists_rejects_a_missing_path(tmp_path: Path) -> None:
    """A path that does not exist is reported as PathInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(PathExists())(str(tmp_path / "nope"))
    error = caught.value.errors[0]
    assert isinstance(error, PathInvalid)
    assert error.error_message == "path does not exist"


def test_path_exists_rejects_an_empty_value() -> None:
    """A falsy value gets the distinct 'Not a Path' message, like voluptuous."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(PathExists())(None)
    assert caught.value.errors[0].error_message == "Not a Path"


def test_filesystem_check_handles_an_unstringable_value() -> None:
    """A value that cannot be turned into a string fails cleanly, not crashes."""

    class Unstringable:
        def __str__(self) -> str:
            message = "no string for you"
            raise TypeError(message)

    with pytest.raises(MultipleInvalid) as caught:
        Schema(IsDir())(Unstringable())
    assert isinstance(caught.value.errors[0], DirInvalid)


def test_is_symlink(tmp_path: Path) -> None:
    """IsSymlink accepts a symlink and rejects a regular file or a missing path."""
    target = tmp_path / "target"
    target.write_text("x")
    link = tmp_path / "link"
    link.symlink_to(target)

    assert Schema(IsSymlink())(str(link)) == str(link)
    with pytest.raises(MultipleInvalid) as caught:
        Schema(IsSymlink())(str(target))
    assert isinstance(caught.value.errors[0], SymlinkInvalid)


def test_is_fifo(tmp_path: Path) -> None:
    """IsFifo accepts a named pipe and rejects a regular file."""
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    assert Schema(IsFifo())(str(fifo)) == str(fifo)

    regular = tmp_path / "file"
    regular.write_text("x")
    with pytest.raises(MultipleInvalid) as caught:
        Schema(IsFifo())(str(regular))
    assert isinstance(caught.value.errors[0], FifoInvalid)


def test_is_socket(tmp_path: Path) -> None:
    """IsSocket accepts a Unix socket and rejects a missing path."""
    path = tmp_path / "sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(path))
        assert Schema(IsSocket())(str(path)) == str(path)
    finally:
        server.close()

    with pytest.raises(MultipleInvalid) as caught:
        Schema(IsSocket())(str(tmp_path / "missing"))
    assert isinstance(caught.value.errors[0], SocketInvalid)


def test_is_block_device_rejects_a_regular_file(tmp_path: Path) -> None:
    """IsBlockDevice rejects a regular file (creating a real one needs root)."""
    regular = tmp_path / "file"
    regular.write_text("x")
    with pytest.raises(MultipleInvalid) as caught:
        Schema(IsBlockDevice())(str(regular))
    assert isinstance(caught.value.errors[0], BlockDeviceInvalid)


def test_filesystem_checks_reject_a_nul_byte_path() -> None:
    """A path with an embedded NUL byte is rejected cleanly, not a raw ValueError."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(IsFile())("bad\x00path")
    assert isinstance(caught.value.errors[0], FileInvalid)
