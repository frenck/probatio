"""Tests for the network validators (IP, network, hostname, port)."""

from __future__ import annotations

import ipaddress

import pytest

from probatio import (
    Coerce,
    Fqdn,
    Hostname,
    IPAddress,
    IPNetwork,
    IPv4Address,
    IPv6Address,
    MultipleInvalid,
    Port,
    Schema,
)
from probatio.error import HostnameInvalid, IpInvalid, RangeInvalid


def test_ipv4_address_validates_and_returns_unchanged() -> None:
    """IPv4Address validates the value and returns it unchanged (Coerce for object)."""
    assert Schema(IPv4Address())("192.0.2.1") == "192.0.2.1"


def test_ipv4_address_object_via_coerce() -> None:
    """The parsed ipaddress object is opt-in through Coerce, not the validator."""
    result = Schema(Coerce(ipaddress.IPv4Address))("192.0.2.1")
    assert result == ipaddress.IPv4Address("192.0.2.1")
    assert isinstance(result, ipaddress.IPv4Address)


def test_ipv4_address_rejects_a_bad_value() -> None:
    """A non-IPv4 value raises IpInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(IPv4Address())("not-an-ip")
    assert isinstance(caught.value.errors[0], IpInvalid)


def test_ipv6_address_validates_and_returns_unchanged() -> None:
    """IPv6Address validates the value and returns it unchanged."""
    assert Schema(IPv6Address())("::1") == "::1"


def test_ipv6_address_rejects_a_bad_value() -> None:
    """A non-IPv6 value raises IpInvalid."""
    with pytest.raises(MultipleInvalid):
        Schema(IPv6Address())("192.0.2.1")


def test_ip_address_accepts_either_version() -> None:
    """IPAddress accepts both v4 and v6, returning the value unchanged."""
    assert Schema(IPAddress())("192.0.2.1") == "192.0.2.1"
    assert Schema(IPAddress())("::1") == "::1"


def test_ip_address_rejects_a_bad_value() -> None:
    """A non-IP value raises IpInvalid."""
    with pytest.raises(MultipleInvalid):
        Schema(IPAddress())("nope")


def test_ip_network_validates_cidr() -> None:
    """IPNetwork validates a CIDR network and returns it unchanged."""
    assert Schema(IPNetwork())("192.0.2.0/24") == "192.0.2.0/24"


def test_ip_network_allows_host_bits() -> None:
    """Host bits are allowed and the value is returned unchanged, not normalized."""
    assert Schema(IPNetwork())("192.0.2.5/24") == "192.0.2.5/24"


def test_ip_network_rejects_a_bad_value() -> None:
    """A non-network value raises IpInvalid."""
    with pytest.raises(MultipleInvalid):
        Schema(IPNetwork())("nope")


@pytest.mark.parametrize(
    "validator",
    [IPNetwork, IPAddress, IPv4Address, IPv6Address],
)
def test_ip_validators_do_not_leak_on_hostile_input(validator: type) -> None:
    """A crafted value makes ``ipaddress`` raise odd errors; only Invalid may escape.

    ``ip_network('a/\\x00')`` reaches an ``AttributeError`` ('NoneType' has no
    attribute 'isascii') deep in CPython's prefix parser. A safe validator must turn
    that into ``Invalid``, not leak it. Found by the atheris fuzz harness.
    """
    for hostile in ("1.2.3.4/\x00", "::/\x00", "a\x00b", "/", "1/2/3"):
        with pytest.raises(MultipleInvalid):
            Schema(validator())(hostile)


def test_hostname_accepts_a_single_label() -> None:
    """A bare label like localhost is a valid hostname."""
    assert Schema(Hostname())("localhost") == "localhost"


def test_hostname_accepts_a_dotted_name_and_trailing_dot() -> None:
    """A dotted name validates, and a single trailing root dot is allowed."""
    assert Schema(Hostname())("host.example.com") == "host.example.com"
    assert Schema(Hostname())("host.example.com.") == "host.example.com."


@pytest.mark.parametrize(
    "value",
    [
        123,  # not a string
        "",  # empty
        "-bad",  # leading hyphen
        "bad-",  # trailing hyphen
        "a..b",  # empty label
        "ho st",  # invalid character
        "a" * 64,  # label too long
        "a." + "b" * 300,  # whole name too long
    ],
)
def test_hostname_rejects_invalid(value: object) -> None:
    """A malformed hostname raises HostnameInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Hostname())(value)
    assert isinstance(caught.value.errors[0], HostnameInvalid)


def test_fqdn_requires_a_dotted_name() -> None:
    """Fqdn accepts a dotted name but rejects a bare label."""
    assert Schema(Fqdn())("host.example.com") == "host.example.com"
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Fqdn())("localhost")
    assert isinstance(caught.value.errors[0], HostnameInvalid)


def test_fqdn_rejects_a_non_string() -> None:
    """A non-string value is not a valid FQDN."""
    with pytest.raises(MultipleInvalid):
        Schema(Fqdn())(123)


def test_port_accepts_int_and_string() -> None:
    """Port accepts an int or an int-like string, returning an int."""
    assert Schema(Port())(8080) == 8080
    assert Schema(Port())("443") == 443


@pytest.mark.parametrize("value", [0, 70000, "nope", 8080.7])
def test_port_rejects_out_of_range_or_non_numeric(value: object) -> None:
    """A port out of 1..65535, a non-numeric, or a fractional float raises RangeInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Port())(value)
    assert isinstance(caught.value.errors[0], RangeInvalid)


def test_port_accepts_an_integral_float() -> None:
    """A float with no fractional part is a valid port and returns as an int."""
    assert Schema(Port())(8080.0) == 8080


@pytest.mark.parametrize("value", [True, False])
def test_port_rejects_a_bool(value: object) -> None:
    """A bool is an int but never a port, so it raises rather than passing as 1 or 0."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Port())(value)
    assert isinstance(caught.value.errors[0], RangeInvalid)


@pytest.mark.parametrize(
    "validator",
    [IPv4Address(), IPv6Address(), IPAddress(), IPNetwork()],
)
def test_ip_validators_reject_a_bool(validator: object) -> None:
    """A bool is not an IP address, even though ipaddress would coerce an int."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(validator)(True)
    assert isinstance(caught.value.errors[0], IpInvalid)


def test_custom_messages() -> None:
    """A custom message replaces the default on failure."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(IPv4Address(msg="bad ip"))("x")
    assert caught.value.errors[0].error_message == "bad ip"
