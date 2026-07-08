"""The English message catalog: one template per translation key.

Every default error message the built-in validators produce lives here, keyed
by the error's ``translation_key``. A raise site passes the key and the
placeholders; the message text is rendered from the template lazily, on the
first read of ``msg`` / ``error_message`` / ``str(error)``, so an error that
is built and discarded (a miss inside a combinator branch) never pays for
string formatting.

The keys are public API (ADR-015): a consumer branches on them to render its
own messages or translations, so renaming or removing one is a breaking
change. The templates are ``str.format`` style, dumb data on purpose. This
catalog is English and stays English: Probatio ships no translations, the key
plus placeholders is the contract a consumer localizes against.
"""

from __future__ import annotations

from typing import Any

# One entry per distinct sentence. Where several validators share a sentence
# (like "expected a mapping" from the dict engine and the key groups), they
# share the key, so a translation covers both.
CATALOG: dict[str, str] = {
    "allowed_at_most_one_of": "at most one of {keys} is allowed",
    "allowed_one_of": "exactly one of {keys} is allowed",
    "byte_length_out_of_bounds": "byte length out of bounds",
    "cannot_be_changed": "{field!r} cannot be changed",
    "cannot_convert_to_set": "cannot be converted to a set: {detail}",
    "contains_duplicate_items": "contains duplicate items: {items}",
    "contains_unhashable_elements": "contains unhashable elements: {detail}",
    # A fragment, not a sentence: appended to a suggestion-carrying error's
    # message. ``candidates`` arrives pre-joined ("'a', 'b' or 'c'"); the raw
    # list is on the error's ``context["candidates"]`` for consumers that need
    # to join it themselves.
    "did_you_mean": ", did you mean {candidates}?",
    "does_not_match_pattern": "does not match the expected pattern",
    "element_not_valid": "item {position} ({item}) does not match any validator",
    "exclusive_group": "two or more values in the same group of exclusion {group!r}",
    "expected_alpha": "expected only ASCII letters",
    "expected_alphanumeric": "expected only ASCII letters and digits",
    "expected_ascii": "expected only ASCII characters",
    "expected_base64_string": "expected a Base64 string",
    "expected_boolean": "expected a boolean",
    "expected_cidr": "expected a CIDR network",
    "expected_collection": "expected a collection: {detail}",
    "expected_credit_card_number": "expected a credit card number",
    "expected_data_uri": "expected a data URI",
    "expected_discriminator": "expected {key} to be one of {values}",
    "expected_duration": "expected a duration",
    "expected_duration_detailed": "expected a duration like H:MM, H:MM:SS, an ISO 8601 duration like PT1H30M, or a number of seconds",
    "expected_email_address": "expected an email address",
    "expected_fqdn": "expected a fully-qualified domain name",
    "expected_hex_color": "expected a hex color like #rrggbb",
    "expected_hex_string": "expected a hex string",
    "expected_hexadecimal_integer": "expected a hexadecimal integer",
    "expected_hostname": "expected a hostname",
    "expected_iana_time_zone": "expected an IANA time zone",
    "expected_iban": "expected an IBAN",
    "expected_ip": "expected an IP address",
    "expected_ipv4": "expected an IPv4 address",
    "expected_ipv6": "expected an IPv6 address",
    "expected_iso_date": "expected an ISO 8601 date",
    "expected_iso_datetime": "expected an ISO 8601 datetime",
    "expected_iso_time": "expected an ISO 8601 time",
    "expected_json_string": "expected a JSON string",
    "expected_mac_address": "expected a MAC address",
    "expected_mapping": "expected a mapping",
    "expected_no_whitespace": "expected no whitespace",
    "expected_object": "expected a {cls!r}",
    "expected_percentage": "expected a percentage between 0 and 100",
    "expected_phone_number": "expected a phone number",
    "expected_port": "expected a port number between 1 and 65535",
    "expected_printable_ascii": "expected only printable ASCII characters",
    "expected_sequence": "expected a {expected}",
    "expected_sequence_of_items": "expected a sequence of {count} items",
    "expected_slug": "expected a slug",
    "expected_string": "expected a string",
    "expected_timezone_aware_datetime": "expected a timezone-aware datetime",
    "expected_type": "expected {expected}",
    "expected_type_or_one_of": "expected {expected} or one of {values}",
    "expected_ulid": "expected a ULID",
    "expected_unix_timestamp": "expected a Unix timestamp",
    "expected_url": "expected a URL",
    "expected_url_with_fqdn": "expected a URL with a fully-qualified domain name",
    "expected_utc_offset": "expected a UTC offset like +01:00, Z, or UTC",
    "expected_uuid": "expected a UUID",
    "expected_uuid_version": "expected a version {version} UUID",
    "expected_valid_regex": "expected a valid regular expression",
    "inclusive_group": "some but not all values in the same group of inclusion {group!r}",
    "invalid_credit_card_number": "invalid credit card number",
    "invalid_data_uri": "invalid data URI",
    "invalid_iban": "invalid IBAN",
    "invalid_json": "invalid JSON",
    "invalid_phone_number": "invalid phone number",
    "invalid_value": "invalid value",
    "invalid_value_or_type": "invalid value or type",
    "key_not_allowed": "key not allowed",
    "length_max": "length of value must be at most {max}",
    "length_min": "length of value must be at least {min}",
    "max_contains": "expected at most {max} matching item(s)",
    "min_contains": "expected at least {min} matching item(s)",
    "must_not_match_not_schema": "value must not match the 'not' schema",
    "no_valid_value": "no valid value found",
    "not_a_block_device": "not a block device",
    "not_a_collection": "value is not a collection",
    "not_a_directory": "not a directory",
    "not_a_fifo": "not a FIFO",
    "not_a_file": "not a file",
    "not_a_path": "not a path",
    "not_a_socket": "not a socket",
    "not_a_symlink": "not a symlink",
    "not_a_valid_option": "not a valid option",
    "not_a_valid_value": "not a valid value",
    "not_a_valid_value_detail": "not a valid value: {detail}",
    "path_does_not_exist": "path does not exist",
    "precision_must_equal": "precision must be equal to {precision}",
    "range_max": "value must be at most {max}",
    "range_max_exclusive": "value must be lower than {max}",
    "range_min": "value must be at least {min}",
    "range_min_exclusive": "value must be higher than {min}",
    "recursion_too_deep": "data is nested too deeply for this recursive schema",
    "required": "required key not provided",
    "required_any_of": "at least one of {keys} is required",
    "required_none_or_all_of": "either none or all of {keys} are required",
    "required_one_of": "exactly one of {keys} is required",
    "required_when_absent": "{key!r} is required when {triggers} is absent",
    "required_when_present": "{key!r} is required when {triggers} is present",
    "required_when_value": "{key!r} is required when {conditions}",
    "scale_must_equal": "scale must be equal to {scale}",
    "too_many_valid": "value matched {passed} alternatives, expected at most {max}",
    "value_does_not_match_format": "value does not match expected format {format}",
    "value_has_no_precision": "value has no precision",
    "value_multiple_of": "value must be a multiple of {factor}",
    "value_must_be_number_string": "value must be a number enclosed in a string",
    "value_must_contain": "value must contain {item!r}",
    "value_must_end_with": "value must end with {suffix!r}",
    "value_must_start_with": "value must start with {prefix!r}",
    "value_no_length": "value has no length",
    "value_not_allowed": "value is not allowed",
    "value_not_empty": "value must not be empty",
    "value_not_equal": "value is not equal to {target!r}",
    "value_not_one_of": "value must not be one of {values}",
    "value_not_sorted": "value is not sorted",
    "value_one_of": "value must be one of {values}",
    "value_was_not_false": "value was not false",
    "value_was_not_true": "value was not true",
    "write_once_already_set": "{field!r} is write-once and already set",
}


# How many members of a list placeholder an error message spells out. The
# structured ``placeholders`` on the error keep the complete list; only the
# rendered text is capped, so an attacker-sized container (a 100k-entry ``enum``
# from an untrusted schema, say) cannot turn every miss into megabytes of error
# text in logs.
_MAX_LISTED_VALUES = 40


def _display(value: Any) -> Any:
    """Cap a long list placeholder for rendering; short values pass unchanged."""
    if isinstance(value, list) and len(value) > _MAX_LISTED_VALUES:
        shown = ", ".join(repr(item) for item in value[:_MAX_LISTED_VALUES])
        return f"[{shown}, ...] ({len(value) - _MAX_LISTED_VALUES} more not shown)"
    return value


def render(key: str, placeholders: dict[str, Any] | None) -> str:
    """Render the catalog template for ``key`` with the given placeholders."""
    template = CATALOG[key]
    if not placeholders:
        return template
    return template.format(
        **{name: _display(value) for name, value in placeholders.items()},
    )
