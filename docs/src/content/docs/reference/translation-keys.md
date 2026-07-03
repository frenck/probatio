---
title: Translation keys
description: Every translation key the built-in validators emit, with its English template and placeholders.
---

Every error a built-in validator raises carries a `translation_key` naming the
exact sentence of its default message, and `placeholders`, the raw values that
sentence interpolates. Together they let a consumer render errors in its own
words or language without parsing strings; see
[Custom error messages](/guides/custom-error-messages/) for the pattern.

The keys are public API: renaming or removing one is a breaking change, the
same as renaming a function. Where two validators produce the same sentence,
they share the key, so one translation covers both. A custom `msg=` on a
validator replaces the rendered text but keeps the key.

Templates are `str.format` style. The canonical source is the catalog in
`probatio._messages`; this table mirrors it. One entry is a fragment rather
than a sentence: `did_you_mean` is appended to a suggestion-carrying error's
message, with the close matches also available raw on `context["candidates"]`
(see [how suggestions compose](/guides/custom-error-messages/#suggestions-compose-on-top)).

| Key | English template |
| --- | ---------------- |
| `allowed_at_most_one_of` | `at most one of {keys} is allowed` |
| `allowed_one_of` | `exactly one of {keys} is allowed` |
| `byte_length_out_of_bounds` | `byte length out of bounds` |
| `cannot_be_changed` | `{field!r} cannot be changed` |
| `cannot_convert_to_set` | `cannot be converted to a set: {detail}` |
| `contains_duplicate_items` | `contains duplicate items: {items}` |
| `contains_unhashable_elements` | `contains unhashable elements: {detail}` |
| `did_you_mean` | `, did you mean {candidates}?` |
| `does_not_match_pattern` | `does not match the expected pattern` |
| `element_not_valid` | `Element #{position} ({item}) is not valid against any validator` |
| `exclusive_group` | `two or more values in the same group of exclusion {group!r}` |
| `expected_alpha` | `expected only ASCII letters` |
| `expected_alphanumeric` | `expected only ASCII letters and digits` |
| `expected_ascii` | `expected only ASCII characters` |
| `expected_base64_string` | `expected a Base64 string` |
| `expected_boolean` | `expected boolean` |
| `expected_cidr` | `expected a CIDR network` |
| `expected_collection` | `expected a collection: {detail}` |
| `expected_credit_card_number` | `expected a credit card number` |
| `expected_data_uri` | `expected a data URI` |
| `expected_duration` | `expected a duration` |
| `expected_duration_detailed` | `expected a duration like H:MM, H:MM:SS, an ISO 8601 duration like PT1H30M, or a number of seconds` |
| `expected_email_address` | `expected an email address` |
| `expected_fqdn` | `expected a fully-qualified domain name` |
| `expected_hex_color` | `expected a hex color like #rrggbb` |
| `expected_hex_string` | `expected a hex string` |
| `expected_hexadecimal_integer` | `expected a hexadecimal integer` |
| `expected_hostname` | `expected a hostname` |
| `expected_iana_time_zone` | `expected an IANA time zone` |
| `expected_iban` | `expected an IBAN` |
| `expected_ip` | `expected an IP address` |
| `expected_ipv4` | `expected an IPv4 address` |
| `expected_ipv6` | `expected an IPv6 address` |
| `expected_iso_date` | `expected an ISO 8601 date` |
| `expected_iso_datetime` | `expected an ISO 8601 datetime` |
| `expected_iso_time` | `expected an ISO 8601 time` |
| `expected_json_string` | `expected a JSON string` |
| `expected_mac_address` | `expected a MAC address` |
| `expected_mapping` | `expected a mapping` |
| `expected_no_whitespace` | `expected no whitespace` |
| `expected_object` | `expected a {cls!r}` |
| `expected_percentage` | `expected a percentage between 0 and 100` |
| `expected_phone_number` | `expected a phone number` |
| `expected_port` | `expected a port number between 1 and 65535` |
| `expected_printable_ascii` | `expected only printable ASCII characters` |
| `expected_sequence` | `expected a {expected}` |
| `expected_sequence_of_items` | `expected a sequence of {count} items` |
| `expected_slug` | `expected a slug` |
| `expected_string` | `expected a string` |
| `expected_timezone_aware_datetime` | `expected a timezone-aware datetime` |
| `expected_type` | `expected {expected}` |
| `expected_type_or_one_of` | `expected {expected} or one of {values}` |
| `expected_ulid` | `expected a ULID` |
| `expected_unix_timestamp` | `expected a Unix timestamp` |
| `expected_url` | `expected a URL` |
| `expected_url_with_fqdn` | `expected a URL with a fully-qualified domain name` |
| `expected_utc_offset` | `expected a UTC offset like +01:00, Z, or UTC` |
| `expected_uuid` | `expected a UUID` |
| `expected_uuid_version` | `expected a version {version} UUID` |
| `expected_valid_regex` | `expected a valid regular expression` |
| `expected_yaml_string` | `expected a YAML string` |
| `inclusive_group` | `some but not all values in the same group of inclusion {group!r}` |
| `invalid_credit_card_number` | `invalid credit card number` |
| `invalid_data_uri` | `invalid data URI` |
| `invalid_iban` | `invalid IBAN` |
| `invalid_json` | `invalid JSON` |
| `invalid_phone_number` | `invalid phone number` |
| `invalid_value` | `invalid value` |
| `invalid_value_or_type` | `invalid value or type` |
| `invalid_yaml` | `invalid YAML` |
| `key_not_allowed` | `key not allowed` |
| `length_max` | `length of value must be at most {max}` |
| `length_min` | `length of value must be at least {min}` |
| `list_lengths_differ` | `List lengths differ, value:{value_length} != target:{target_length}` |
| `max_contains` | `expected at most {max} matching item(s)` |
| `min_contains` | `expected at least {min} matching item(s)` |
| `must_not_match_not_schema` | `value must not match the 'not' schema` |
| `no_valid_value` | `no valid value found` |
| `not_a_block_device` | `Not a block device` |
| `not_a_collection` | `value is not a collection` |
| `not_a_directory` | `Not a directory` |
| `not_a_fifo` | `Not a FIFO` |
| `not_a_file` | `Not a file` |
| `not_a_path` | `Not a Path` |
| `not_a_sequence_value` | `Value {value} is not sequence!` |
| `not_a_socket` | `Not a socket` |
| `not_a_symlink` | `Not a symlink` |
| `not_a_valid_option` | `not a valid option` |
| `not_a_valid_value` | `not a valid value` |
| `not_a_valid_value_detail` | `not a valid value: {detail}` |
| `path_does_not_exist` | `path does not exist` |
| `precision_must_equal` | `precision must be equal to {precision}` |
| `range_max` | `value must be at most {max}` |
| `range_max_exclusive` | `value must be lower than {max}` |
| `range_min` | `value must be at least {min}` |
| `range_min_exclusive` | `value must be higher than {min}` |
| `recursion_too_deep` | `data is nested too deeply for this recursive schema` |
| `required` | `required key not provided` |
| `required_any_of` | `at least one of {keys} is required` |
| `required_none_or_all_of` | `either none or all of {keys} are required` |
| `required_one_of` | `exactly one of {keys} is required` |
| `required_when_absent` | `{key!r} is required when {triggers} is absent` |
| `required_when_present` | `{key!r} is required when {triggers} is present` |
| `required_when_value` | `{key!r} is required when {conditions}` |
| `scale_must_equal` | `scale must be equal to {scale}` |
| `value_does_not_match_format` | `value does not match expected format {format}` |
| `value_has_no_precision` | `value has no precision` |
| `value_multiple_of` | `value must be a multiple of {factor}` |
| `value_must_be_number_string` | `value must be a number enclosed in a string` |
| `value_must_contain` | `value must contain {item!r}` |
| `value_must_end_with` | `value must end with {suffix!r}` |
| `value_must_start_with` | `value must start with {prefix!r}` |
| `value_no_length` | `value has no length` |
| `value_not_allowed` | `value is not allowed` |
| `value_not_empty` | `value must not be empty` |
| `value_not_equal` | `value is not equal to {target!r}` |
| `value_not_match` | `{value} not match for {lit}` |
| `value_not_one_of` | `value must not be one of {values}` |
| `value_not_sorted` | `value is not sorted` |
| `value_one_of` | `value must be one of {values}` |
| `value_was_not_false` | `value was not false` |
| `value_was_not_true` | `value was not true` |
| `write_once_already_set` | `{field!r} is write-once and already set` |
