"""Password gate and IP blacklist behavior."""

import app.auth as auth


def test_verify_password_accepts_exact_match(monkeypatch):
    monkeypatch.setattr(auth.config, "AUTH_PASSWORD", "s3cret!")
    assert auth.verify_password("s3cret!") is True
    assert auth.verify_password("wrong") is False
    assert auth.verify_password("") is False


def test_three_failures_blacklist_ip(monkeypatch, tmp_path):
    monkeypatch.setattr(auth.config, "AUTH_MAX_FAILURES", 3)
    monkeypatch.setattr(auth, "_BLACKLIST_PATH", tmp_path / "ip_blacklist.json")
    auth._FAILURES.clear()

    ip = "203.0.113.9"
    assert auth.record_auth_failure(ip) == 1
    assert not auth.is_ip_blacklisted(ip)
    assert auth.record_auth_failure(ip) == 2
    assert not auth.is_ip_blacklisted(ip)
    assert auth.record_auth_failure(ip) == 3
    assert auth.is_ip_blacklisted(ip)

    # Durable across "reload"
    auth._FAILURES.clear()
    assert auth.is_ip_blacklisted(ip)


def test_successful_clear_resets_failures(monkeypatch, tmp_path):
    monkeypatch.setattr(auth.config, "AUTH_MAX_FAILURES", 3)
    monkeypatch.setattr(auth, "_BLACKLIST_PATH", tmp_path / "ip_blacklist.json")
    auth._FAILURES.clear()

    ip = "198.51.100.2"
    auth.record_auth_failure(ip)
    auth.record_auth_failure(ip)
    auth.clear_auth_failures(ip)
    assert auth.record_auth_failure(ip) == 1
    assert not auth.is_ip_blacklisted(ip)
