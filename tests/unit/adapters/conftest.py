"""Shared fixtures for adapter unit tests.

TLS material is embedded rather than generated: ``load_cert_chain`` and
``create_default_context(cafile=...)`` demand REAL parseable PEM bytes, and
producing them at runtime would require openssl or the cryptography package.
The pair below is a throwaway self-signed certificate (CN=clientwright-test,
~100 years of validity) generated once for these tests; the key protects
nothing and secures nothing.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

TEST_CERT_PEM = """-----BEGIN CERTIFICATE-----
MIIDGzCCAgOgAwIBAgIUc2SZZ6LTIm8nL6QprbvQPP/WzQ0wDQYJKoZIhvcNAQEL
BQAwHDEaMBgGA1UEAwwRY2xpZW50d3JpZ2h0LXRlc3QwIBcNMjYwODE0MTUyNTI0
WhgPMjEyNjA3MjExNTI1MjRaMBwxGjAYBgNVBAMMEWNsaWVudHdyaWdodC10ZXN0
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAtTVJBrRW4gjnlkPG/4zL
Q108lX3QFnwYaS0yWtburjlA2JQ/529hafw9KmNXAnNkg+rA0HEX+Lu1dVzogZ/D
Zs4IhEKqsJHHERisWFocTEiQNHiAXPXj02XNVBVPK7CqMglyVLgv1nuMW2DZ0QAM
LrIEUNKqI6DIucCv8PAIRBaV3Sfar+18q5HpoPuyvE5kFrx15f8IkdbZGDa8AOWq
006oJobHOaPcTiqdBbDyPRcLWeZm/4U+FAUfFu6oaq8iMzoW9Ir8VlEorvKOWbMC
+3I2uhMmgoSNaruobY7AHhR87wrroSovfMMzxpyVZeIzdx5uHHFE1EsxJCH8dQ/t
qwIDAQABo1MwUTAdBgNVHQ4EFgQUapti2zhcr7T1tR8LDDh0Z/X2ukYwHwYDVR0j
BBgwFoAUapti2zhcr7T1tR8LDDh0Z/X2ukYwDwYDVR0TAQH/BAUwAwEB/zANBgkq
hkiG9w0BAQsFAAOCAQEApDaXVCtDgqxq1L5Yr5nOha6Ao4VWQ7lXRieI9ADQ+saf
OHnwDFdr0yqqUYzMpBwSs/24NrXP5uGc7BAWhzvUe3ldj71wlmmDUlJI/L+iVuRu
bUrsm/RHx5XMYeBS11PnmVA96iNelSxF7X5bLNklc1ZLnCAB5NVFU9OFRgvOYuYN
vkdBYXbWVyIPtNIThGRDz7Z/n0KJqxeJrJN42UkneZ/hxwAbrAQ1f/M0DYSULdG8
dnKfwxXjxpq6c8ZpxgsuXFmk0lMgpinzYJlX79t6d3P0L5ZoOgTf7GKUpvtSq73U
7ZSo32dkLURhh+XIIqZHDv0ScZSxeiAMuJBbEcx2KA==
-----END CERTIFICATE-----
"""

TEST_KEY_PEM = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC1NUkGtFbiCOeW
Q8b/jMtDXTyVfdAWfBhpLTJa1u6uOUDYlD/nb2Fp/D0qY1cCc2SD6sDQcRf4u7V1
XOiBn8NmzgiEQqqwkccRGKxYWhxMSJA0eIBc9ePTZc1UFU8rsKoyCXJUuC/We4xb
YNnRAAwusgRQ0qojoMi5wK/w8AhEFpXdJ9qv7Xyrkemg+7K8TmQWvHXl/wiR1tkY
NrwA5arTTqgmhsc5o9xOKp0FsPI9FwtZ5mb/hT4UBR8W7qhqryIzOhb0ivxWUSiu
8o5ZswL7cja6EyaChI1qu6htjsAeFHzvCuuhKi98wzPGnJVl4jN3Hm4ccUTUSzEk
Ifx1D+2rAgMBAAECggEBALULheii6WNwTiF9mibcvoCReORLDUpJtgHvXC4SK+n5
3eYFSEuspoFDuMDO+7HBJJ4AP6CCPdcPg968crh/rLTcCPpLuUose92C7z5e2YMF
xL4H3wgBzBv7zEfD+pPGMGVJtucaFwGN8s+hVj5Qc9t7lIBD2iU6kRG1iJOK3ldX
ItdWhrckQ4/LN6Ec2aNkmlfFEa0Di4182F+6M1ieMa9FS6V2q7VaeK3Ldg5rU3FL
ZhrmAxl4AG5+GZCg7hjq4XHfXyh7txPRZmTf6D61JCGerMlZGs2qrhBCw2+h3k6c
50gVNLLDlQR9NwktCCgRgAYGnfGtHoTEYUaNVQQSzQECgYEA3cHakNuADb0Mbibf
EMSeqm5dUU69HOu/fRgEa3EJlW1wJKDjnnwM79YNm5yasFuOEACWg7gwZ4rpCEFe
LObM5NozsZS4p8xf9AbYhD9KJ/gKQYAeXMR5hmpBSMI0vt70rEkfv4wCjyLhithc
MQP1YCFCxcZPwR4jGRhP/Znc+WsCgYEA0TCCueIlj/HxeoWQv4YjwjXvzeuJy12+
kgXdBiovgf8COrJg+pMbHmMoHhOzh6a40MlfKL2Wh4S2j8Y8g8PnxDzVMTIlG7uJ
9w3ey4+gBqyJeGmntCBf0nujc0dmDgmKduqaPvd2nndiHIILzyMC6j+F9PMyCUKG
/4FUAr6srMECgYBlOEjleet3WeVEmiWTZ8vsize5FzGm88yR8taBnDT9qdhYP7/l
5UWaa6AGeXL6MLAlib8qHHarrHI1vHCaGjdH9nlGA1ZN8TGTF1TY+HKGz+cOgsZZ
Ha1Ct1lZNpwQy3/u6+m76tJ4NzmvwJZEIURtPoFV+PEKexEWMUzBuutsRQKBgAVZ
hD5Utjk0KsTDXaxINenljzho6aE1yIXbeIeL1KMyblAp96jw0iS4zHHYdyLk9J0C
SVi1YIAeuLx8iVelTuwJ0jnr2l8XMLQMusHh7mm9R9a4fP1yRoEPgGKWVNnPDKd1
4HPzyCjNTMkF2l91ucFb1oUpIwJxnRozqH5ZefkBAoGAIs2hPV6zvlH7d1vKCBVi
7CKT1pPUrCjLby/NU5YtUu7sA/X8p39WGWZ2xIqerYyZSvEV3JuDdaNaza0+fLb/
SJfdVfR8BrtN6rTLHzBwP2aeb3uUXEP3qoki4v5RxzMRWO2lVvI9NJ5i794+LlYv
EWMBI5IGkpMZDXiJbPb5TLU=
-----END PRIVATE KEY-----
"""


@pytest.fixture
def tls_material(tmp_path: Path) -> SimpleNamespace:
    """Paths of the embedded test certificate, written under tmp_path.

    - ``cert``/``key``: the two-file (certfile, keyfile) form;
    - ``combined``: certificate + key in one file, the single-path cert form;
    - ``ca``: the same self-signed certificate acting as a CA bundle.
    """
    cert = tmp_path / "client.crt"
    key = tmp_path / "client.key"
    combined = tmp_path / "client.pem"
    ca = tmp_path / "ca.pem"
    cert.write_text(TEST_CERT_PEM)
    key.write_text(TEST_KEY_PEM)
    combined.write_text(TEST_CERT_PEM + TEST_KEY_PEM)
    ca.write_text(TEST_CERT_PEM)
    return SimpleNamespace(cert=str(cert), key=str(key), combined=str(combined), ca=str(ca))
