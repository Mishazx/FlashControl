"""Active Directory login: one LDAP bind, then memberOf → FlashControl role.

The flow matches PIB Portal: DOMAIN\\sAMAccountName bind, optional access
group gate, then map AD groups onto admin/security/auditor.
"""

from __future__ import annotations

import logging
import ssl
from dataclasses import dataclass

from . import config

LDAP_ROLES = ("admin", "security", "auditor")


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LdapLoginOutcome:
    success: bool
    username: str
    role: str | None = None
    display_name: str | None = None
    failure: str = ""


class LdapFailure(Exception):
    def __init__(self, failure: str):
        self.failure = failure
        super().__init__(failure)


def ldap_configured() -> bool:
    return bool(config.LDAP_SERVER_URI and config.LDAP_BASE_DN and config.LDAP_DOMAIN_NAME)


def sam_account_name(value: str) -> str:
    text = str(value or "").strip()
    if "\\" in text:
        text = text.rsplit("\\", 1)[-1]
    if "@" in text:
        text = text.split("@", 1)[0]
    return text.strip()


def _cn(value: str) -> str:
    first = str(value or "").split(",", 1)[0].strip()
    if first.lower().startswith("cn="):
        return first[3:].casefold()
    return first.casefold()


def _member_keys(member_of: list[str]) -> set[str]:
    keys = set()
    for item in member_of:
        raw = str(item or "").strip()
        if not raw:
            continue
        keys.add(raw.casefold())
        keys.add(_cn(raw))
    return keys


def _configured_keys(groups: frozenset[str]) -> set[str]:
    keys = set()
    parent = (config.LDAP_GROUP_PARENT_DN or "").strip()
    for item in groups:
        value = str(item or "").strip()
        if not value:
            continue
        keys.add(value.casefold())
        keys.add(_cn(value))
        if parent and "," not in value:
            keys.add(("cn=%s,%s" % (value, parent)).casefold())
    return keys


def matches_groups(configured: frozenset[str], member_of: list[str]) -> bool:
    if not configured:
        return False
    return bool(_configured_keys(configured) & _member_keys(member_of))


def has_access_group(member_of: list[str]) -> bool:
    access = (config.LDAP_ACCESS_GROUP or "").strip()
    if not access:
        return True
    return matches_groups(frozenset({access}), member_of)


def role_from_member_of(member_of: list[str]) -> str | None:
    for role, groups in (
        ("admin", config.LDAP_ADMIN_GROUPS),
        ("security", config.LDAP_SECURITY_GROUPS),
        ("auditor", config.LDAP_AUDITOR_GROUPS),
    ):
        if matches_groups(groups, member_of):
            return role
    default = (config.LDAP_DEFAULT_ROLE or "").strip().lower()
    if default in LDAP_ROLES:
        return default
    return None


def _tls():
    from ldap3 import Tls

    policy = (config.LDAP_TLS_CERT_POLICY or "demand").strip().lower()
    if policy in ("never", "none", "0"):
        validate = ssl.CERT_NONE
    elif policy in ("allow", "1"):
        validate = ssl.CERT_OPTIONAL
    else:
        validate = ssl.CERT_REQUIRED
    return Tls(validate=validate)


def _bind_and_read(username: str, password: str) -> tuple[list[str], str | None]:
    try:
        from ldap3 import Connection, NONE, Server, SUBTREE
        from ldap3.core.exceptions import LDAPException, LDAPSocketOpenError
        from ldap3.utils.conv import escape_filter_chars
    except ImportError as exc:
        raise LdapFailure("ldap_unavailable") from exc

    uri = config.LDAP_SERVER_URI
    use_ssl = uri.lower().startswith("ldaps://")
    server = Server(
        uri,
        use_ssl=use_ssl,
        tls=_tls(),
        connect_timeout=config.LDAP_NETWORK_TIMEOUT,
        get_info=NONE,
    )
    bind_user = "%s\\%s" % (config.LDAP_DOMAIN_NAME, username)
    conn = Connection(
        server,
        user=bind_user,
        password=password,
        auto_bind=False,
        receive_timeout=config.LDAP_TIMEOUT,
        raise_exceptions=False,
    )
    try:
        try:
            conn.open()
            if config.LDAP_START_TLS and not use_ssl:
                if not conn.start_tls():
                    raise LdapFailure("ldap_error")
            if not conn.bind():
                description = str((conn.result or {}).get("description") or "")
                if description == "invalidCredentials":
                    raise LdapFailure("invalid_credentials")
                raise LdapFailure("ldap_error")
        except LdapFailure:
            raise
        except LDAPSocketOpenError as exc:
            raise LdapFailure("ldap_unavailable") from exc
        except LDAPException as exc:
            raise LdapFailure("ldap_error") from exc

        search_filter = "(&(objectClass=user)(sAMAccountName=%s))" % escape_filter_chars(username)
        if not conn.search(
            config.LDAP_BASE_DN,
            search_filter,
            search_scope=SUBTREE,
            attributes=["memberOf", "cn", "sAMAccountName"],
        ):
            raise LdapFailure("not_in_group")
        if not conn.entries:
            raise LdapFailure("not_in_group")

        entry = conn.entries[0]
        member_of = []
        if "memberOf" in entry:
            member_of = [str(value) for value in entry.memberOf.values]
        display_name = None
        if "cn" in entry and entry.cn.value:
            display_name = str(entry.cn.value)
        return member_of, display_name
    finally:
        try:
            conn.unbind()
        except Exception:
            pass


def perform_ldap_login(username: str, password: str) -> LdapLoginOutcome:
    sam = sam_account_name(username)
    if not sam or not password:
        return LdapLoginOutcome(False, sam, failure="invalid_credentials")
    if not ldap_configured():
        return LdapLoginOutcome(False, sam, failure="ldap_unavailable")

    try:
        member_of, display_name = _bind_and_read(sam, password)
    except LdapFailure as exc:
        logger.info("LDAP login failed for %s: %s", sam, exc.failure)
        return LdapLoginOutcome(False, sam, failure=exc.failure)
    except Exception:
        logger.exception("Unexpected LDAP login error for %s", sam)
        return LdapLoginOutcome(False, sam, failure="ldap_error")

    if not has_access_group(member_of):
        logger.info(
            "LDAP user %s is not in access group %s",
            sam,
            config.LDAP_ACCESS_GROUP,
        )
        return LdapLoginOutcome(False, sam, failure="not_in_group")

    role = role_from_member_of(member_of)
    if not role:
        logger.info("LDAP user %s has no mapped FlashControl role", sam)
        return LdapLoginOutcome(False, sam, failure="not_in_group")

    logger.info("LDAP login OK for %s role=%s", sam, role)
    return LdapLoginOutcome(True, sam, role=role, display_name=display_name)
