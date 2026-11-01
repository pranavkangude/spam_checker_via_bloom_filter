import pytest

from core.normalizer import KEY_TYPES, MAX_LEN, normalize


@pytest.mark.parametrize("key_type,raw,expected", [
    # email
    ("email", "  Bad@Mail.COM ", "bad@mail.com"),
    ("email", "bad@mail.com", "bad@mail.com"),
    ("email", "\tUser.Name+Tag@Example.org\n", "user.name+tag@example.org"),
    # url
    ("url", "HTTP://Example.COM/Path/", "http://example.com/Path"),
    ("url", "https://example.com/", "https://example.com"),
    ("url", "https://Example.com/a/b#section", "https://example.com/a/b"),
    ("url", "https://example.com/a?Q=1#frag", "https://example.com/a?Q=1"),
    ("url", "https://User:Pw@Example.com:8080/x/", "https://User:Pw@example.com:8080/x"),
    ("url", "  evil.example.com/Login/  ", "evil.example.com/Login"),
    ("url", "https://example.com", "https://example.com"),
    # phone
    ("phone", " +91 98765-43210 ", "+919876543210"),
    ("phone", "(555) 123-4567", "5551234567"),
    ("phone", "98765 43210", "9876543210"),
    ("phone", "+1 (555) 123+4567", "+15551234567"),
    # trim-only types
    ("ip", "  192.168.1.10 ", "192.168.1.10"),
    ("transaction_id", "  FRAUD_TXN_0042 ", "FRAUD_TXN_0042"),
    ("other", "  Some Free Text ", "Some Free Text"),
])
def test_normalize_table(key_type, raw, expected):
    assert normalize(raw, key_type) == expected


def test_acceptance_equivalent_emails_same_key():
    assert normalize("  Bad@Mail.COM ", "email") == normalize("bad@mail.com", "email")


def test_idempotent():
    for key_type, raw in [("email", " A@B.com "), ("url", "HTTP://X.com/a/#f"),
                          ("phone", "+1 555 1234"), ("ip", " 1.2.3.4 ")]:
        once = normalize(raw, key_type)
        assert normalize(once, key_type) == once


@pytest.mark.parametrize("key_type", KEY_TYPES)
@pytest.mark.parametrize("raw", ["", "   ", "\n\t"])
def test_empty_rejected(key_type, raw):
    with pytest.raises(ValueError):
        normalize(raw, key_type)


@pytest.mark.parametrize("key_type", KEY_TYPES)
def test_too_long_rejected(key_type):
    with pytest.raises(ValueError, match="too long"):
        normalize("1" * (MAX_LEN + 1), key_type)


def test_exactly_max_length_ok():
    assert normalize("a" * MAX_LEN, "other") == "a" * MAX_LEN


def test_phone_without_digits_rejected():
    with pytest.raises(ValueError):
        normalize("+ ()-", "phone")


def test_url_only_fragment_rejected():
    with pytest.raises(ValueError):
        normalize("#only-fragment", "url")


def test_unknown_key_type_rejected():
    with pytest.raises(ValueError):
        normalize("x", "passport")


def test_non_string_rejected():
    with pytest.raises(ValueError):
        normalize(12345, "other")
