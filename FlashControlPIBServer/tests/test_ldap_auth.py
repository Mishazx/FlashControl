# -*- coding: utf-8 -*-

from unittest.mock import patch
import unittest

from app import config
from app.ldap_auth import (
    LdapFailure,
    has_access_group,
    matches_groups,
    perform_ldap_login,
    role_from_member_of,
    sam_account_name,
)


class LdapMappingTests(unittest.TestCase):
    def test_sam_account_name_strips_domain_and_upn(self):
        self.assertEqual(sam_account_name(r"MOSMETRO\Ivan"), "Ivan")
        self.assertEqual(sam_account_name("ivan@mosmetro.ru"), "ivan")
        self.assertEqual(sam_account_name("ivan"), "ivan")

    def test_role_prefers_admin_group_from_memberof_cn(self):
        with patch.object(config, "LDAP_ADMIN_GROUPS", frozenset({"flashcontrol-admins"})), \
            patch.object(config, "LDAP_SECURITY_GROUPS", frozenset({"flashcontrol-security"})), \
            patch.object(config, "LDAP_AUDITOR_GROUPS", frozenset()), \
            patch.object(config, "LDAP_DEFAULT_ROLE", ""), \
            patch.object(config, "LDAP_GROUP_PARENT_DN", ""):
            self.assertEqual(
                role_from_member_of([
                    "CN=FlashControl-Security,OU=Groups,DC=example,DC=local",
                    "CN=FlashControl-Admins,OU=Groups,DC=example,DC=local",
                ]),
                "admin",
            )

    def test_role_matches_cn_with_parent_dn(self):
        with patch.object(config, "LDAP_ADMIN_GROUPS", frozenset()), \
            patch.object(config, "LDAP_SECURITY_GROUPS", frozenset()), \
            patch.object(config, "LDAP_AUDITOR_GROUPS", frozenset({"flashcontrol-auditors"})), \
            patch.object(config, "LDAP_DEFAULT_ROLE", ""), \
            patch.object(
                config, "LDAP_GROUP_PARENT_DN",
                "OU=Groups,DC=example,DC=local",
            ):
            self.assertEqual(
                role_from_member_of([
                    "CN=FlashControl-Auditors,OU=Groups,DC=example,DC=local",
                ]),
                "auditor",
            )

    def test_access_group_gate_uses_cn(self):
        with patch.object(config, "LDAP_ACCESS_GROUP", "БПИБ"), \
            patch.object(config, "LDAP_GROUP_PARENT_DN", "OU=Access,DC=example,DC=local"):
            self.assertTrue(has_access_group([
                "CN=БПИБ,OU=Access,DC=example,DC=local",
            ]))
            self.assertFalse(has_access_group([
                "CN=Other,OU=Access,DC=example,DC=local",
            ]))

    def test_default_role_when_no_mapped_group(self):
        with patch.object(config, "LDAP_ADMIN_GROUPS", frozenset()), \
            patch.object(config, "LDAP_SECURITY_GROUPS", frozenset()), \
            patch.object(config, "LDAP_AUDITOR_GROUPS", frozenset()), \
            patch.object(config, "LDAP_DEFAULT_ROLE", "auditor"), \
            patch.object(config, "LDAP_GROUP_PARENT_DN", ""):
            self.assertEqual(role_from_member_of(["CN=Domain Users,DC=example,DC=local"]), "auditor")

    def test_matches_groups_accepts_full_dn(self):
        dn = "CN=FlashControl-Admins,OU=Groups,DC=example,DC=local"
        self.assertTrue(matches_groups(frozenset({dn.casefold()}), [dn]))


class LdapLoginTests(unittest.TestCase):
    def test_empty_password_does_not_bind(self):
        result = perform_ldap_login("ivan", "")
        self.assertFalse(result.success)
        self.assertEqual(result.failure, "invalid_credentials")

    def test_login_maps_groups_after_bind(self):
        with patch("app.ldap_auth.ldap_configured", return_value=True), \
            patch(
                "app.ldap_auth._bind_and_read",
                return_value=(["CN=FlashControl-Admins,OU=Groups,DC=example,DC=local"], "Ivan Petrov"),
            ), \
            patch.object(config, "LDAP_ACCESS_GROUP", ""), \
            patch.object(config, "LDAP_ADMIN_GROUPS", frozenset({"flashcontrol-admins"})), \
            patch.object(config, "LDAP_SECURITY_GROUPS", frozenset()), \
            patch.object(config, "LDAP_AUDITOR_GROUPS", frozenset()), \
            patch.object(config, "LDAP_DEFAULT_ROLE", ""), \
            patch.object(config, "LDAP_GROUP_PARENT_DN", ""):
            result = perform_ldap_login(r"EXAMPLE\Ivan", "secret")
        self.assertTrue(result.success)
        self.assertEqual(result.username, "Ivan")
        self.assertEqual(result.role, "admin")
        self.assertEqual(result.display_name, "Ivan Petrov")

    def test_login_rejects_missing_access_group(self):
        with patch("app.ldap_auth.ldap_configured", return_value=True), \
            patch("app.ldap_auth._bind_and_read", return_value=(["CN=Other,DC=example,DC=local"], None)), \
            patch.object(config, "LDAP_ACCESS_GROUP", "БПИБ"), \
            patch.object(config, "LDAP_GROUP_PARENT_DN", "DC=example,DC=local"), \
            patch.object(config, "LDAP_ADMIN_GROUPS", frozenset({"flashcontrol-admins"})), \
            patch.object(config, "LDAP_DEFAULT_ROLE", ""):
            result = perform_ldap_login("ivan", "secret")
        self.assertFalse(result.success)
        self.assertEqual(result.failure, "not_in_group")

    def test_bind_failure_is_returned(self):
        with patch("app.ldap_auth.ldap_configured", return_value=True), \
            patch("app.ldap_auth._bind_and_read", side_effect=LdapFailure("invalid_credentials")):
            result = perform_ldap_login("ivan", "wrong")
        self.assertFalse(result.success)
        self.assertEqual(result.failure, "invalid_credentials")


if __name__ == "__main__":
    unittest.main()
