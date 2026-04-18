"""
tests/test_smart_oauth_bulk.py

Production-ready test suite for:
  - SMART on FHIR OAuth2 (authorization code + PKCE, client_credentials,
    refresh_token, introspection, revocation, dynamic registration)
  - Bulk FHIR Patient/$export (initiate, status poll, NDJSON download)
  - JWKS endpoint
"""

import base64
import hashlib
import json
import secrets

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone

from example.models import (
    BulkExportJob, HL7MessageLog,
    OAuthAuthCode, OAuthClient, OAuthToken,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DEMO_REDIRECT = "https://app.example.com/callback"
DEMO_SCOPES = ["openid", "launch/patient", "patient/Patient.read", "offline_access"]

ADT_HL7 = (
    "MSH|^~\\&|SRC|FAC|DST|FAC2|20240101120000||ADT^A01|MSG001|P|2.5\r"
    "PID|1||10001^^^MRN||SMITH^JOHN||19800315|M|||123 MAIN ST^^SPRINGFIELD^IL^62701\r"
    "PV1|1|I|W^101^1^GH||||2001^JONES^ROBERT|||MED|||||||ADM|A0|||||||||||||||||||||20240101120000\r"
)


def _make_client(grant_types=None, is_public=True, scopes=None):
    return OAuthClient.objects.create(
        client_name="Test App",
        redirect_uris=[DEMO_REDIRECT],
        scopes_allowed=scopes or DEMO_SCOPES,
        grant_types=grant_types or ["authorization_code"],
        is_public=is_public,
    )


def _pkce_pair():
    verifier = secrets.token_urlsafe(43)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


# ---------------------------------------------------------------------------
# JWKS
# ---------------------------------------------------------------------------

class JWKSTests(TestCase):

    def test_jwks_returns_200(self):
        r = self.client.get("/.well-known/jwks.json")
        self.assertEqual(r.status_code, 200)

    def test_jwks_has_keys_array(self):
        r = self.client.get("/.well-known/jwks.json")
        data = r.json()
        self.assertIn("keys", data)
        self.assertIsInstance(data["keys"], list)
        self.assertGreater(len(data["keys"]), 0)

    def test_jwks_key_has_required_fields(self):
        key = self.client.get("/.well-known/jwks.json").json()["keys"][0]
        for field in ("kty", "use", "alg", "kid", "k"):
            self.assertIn(field, key)

    def test_jwks_cors_header(self):
        r = self.client.get("/.well-known/jwks.json")
        self.assertEqual(r.headers.get("Access-Control-Allow-Origin"), "*")

    def test_jwks_rejects_post(self):
        self.assertEqual(self.client.post("/.well-known/jwks.json").status_code, 405)


# ---------------------------------------------------------------------------
# OAuth2 authorization endpoint
# ---------------------------------------------------------------------------

class OAuthAuthorizeTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("alice", password="pass")
        self.client.force_login(self.user)
        self.oauth_client = _make_client()

    def _get_authorize(self, **extra):
        verifier, challenge = _pkce_pair()
        params = {
            "client_id": self.oauth_client.client_id,
            "redirect_uri": DEMO_REDIRECT,
            "response_type": "code",
            "scope": "openid launch/patient patient/Patient.read",
            "state": "xyz",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            **extra,
        }
        return self.client.get("/oauth2/authorize", params), verifier, challenge

    def test_authorize_renders_consent_form(self):
        r, _, _ = self._get_authorize()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Test App")
        self.assertContains(r, "Approve")
        self.assertContains(r, "Deny")

    def test_authorize_shows_patient_context(self):
        r, _, _ = self._get_authorize()
        self.assertContains(r, "Patient context")

    def test_authorize_shows_requested_scopes(self):
        r, _, _ = self._get_authorize()
        self.assertContains(r, "patient/Patient.read")

    def test_authorize_requires_login(self):
        self.client.logout()
        r, _, _ = self._get_authorize()
        self.assertIn(r.status_code, (302, 301))
        self.assertIn("/accounts/login", r.headers.get("Location", ""))

    def test_authorize_rejects_unknown_client(self):
        r = self.client.get("/oauth2/authorize", {
            "client_id": "no-such-client",
            "redirect_uri": DEMO_REDIRECT,
            "response_type": "code",
        })
        self.assertEqual(r.status_code, 400)
        self.assertIn("invalid_client", r.json().get("error", ""))

    def test_authorize_rejects_wrong_response_type(self):
        r = self.client.get("/oauth2/authorize", {
            "client_id": self.oauth_client.client_id,
            "redirect_uri": DEMO_REDIRECT,
            "response_type": "token",
        })
        self.assertEqual(r.status_code, 400)
        self.assertIn("unsupported_response_type", r.json()["error"])

    def test_approve_issues_auth_code_and_redirects(self):
        _, challenge = _pkce_pair()
        r = self.client.post("/oauth2/authorize", {
            "action": "approve",
            "client_id": self.oauth_client.client_id,
            "redirect_uri": DEMO_REDIRECT,
            "scope": "openid patient/Patient.read",
            "state": "xyz",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "patient_context": "10001",
        })
        self.assertEqual(r.status_code, 302)
        location = r.headers["Location"]
        self.assertIn("code=", location)
        self.assertIn("state=xyz", location)
        self.assertIn(DEMO_REDIRECT, location)

    def test_deny_redirects_with_access_denied(self):
        r = self.client.post("/oauth2/authorize", {
            "action": "deny",
            "client_id": self.oauth_client.client_id,
            "redirect_uri": DEMO_REDIRECT,
            "scope": "openid",
            "state": "abc",
            "code_challenge": "",
            "code_challenge_method": "S256",
            "patient_context": "",
        })
        self.assertEqual(r.status_code, 302)
        location = r.headers["Location"]
        self.assertIn("error=access_denied", location)
        self.assertIn("state=abc", location)

    def test_auth_code_persisted_in_db(self):
        _, challenge = _pkce_pair()
        self.client.post("/oauth2/authorize", {
            "action": "approve",
            "client_id": self.oauth_client.client_id,
            "redirect_uri": DEMO_REDIRECT,
            "scope": "patient/Patient.read",
            "state": "",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "patient_context": "10001",
        })
        self.assertEqual(OAuthAuthCode.objects.filter(client=self.oauth_client).count(), 1)


# ---------------------------------------------------------------------------
# OAuth2 token endpoint
# ---------------------------------------------------------------------------

class OAuthTokenTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("bob", password="pass")
        self.client.force_login(self.user)
        self.oauth_client = _make_client()

    def _full_auth_code_flow(self, scopes="openid patient/Patient.read offline_access",
                              patient="10001"):
        verifier, challenge = _pkce_pair()
        # Step 1: approve
        r = self.client.post("/oauth2/authorize", {
            "action": "approve",
            "client_id": self.oauth_client.client_id,
            "redirect_uri": DEMO_REDIRECT,
            "scope": scopes,
            "state": "",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "patient_context": patient,
        })
        location = r.headers["Location"]
        code = location.split("code=")[1].split("&")[0]

        # Step 2: exchange
        r2 = self.client.post("/oauth2/token", {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DEMO_REDIRECT,
            "client_id": self.oauth_client.client_id,
            "code_verifier": verifier,
        })
        return r2

    def test_token_exchange_returns_200(self):
        r = self._full_auth_code_flow()
        self.assertEqual(r.status_code, 200)

    def test_token_has_access_token(self):
        data = self._full_auth_code_flow().json()
        self.assertIn("access_token", data)
        self.assertTrue(len(data["access_token"]) > 20)

    def test_token_type_is_bearer(self):
        self.assertEqual(self._full_auth_code_flow().json()["token_type"], "Bearer")

    def test_token_has_expires_in(self):
        data = self._full_auth_code_flow().json()
        self.assertIn("expires_in", data)
        self.assertEqual(data["expires_in"], 3600)

    def test_token_has_refresh_token_when_offline_access_requested(self):
        data = self._full_auth_code_flow(scopes="openid offline_access patient/Patient.read").json()
        self.assertIn("refresh_token", data)

    def test_token_has_patient_context(self):
        data = self._full_auth_code_flow(patient="10001").json()
        self.assertEqual(data.get("patient"), "10001")

    def test_token_stored_in_db(self):
        before = OAuthToken.objects.count()
        self._full_auth_code_flow()
        self.assertEqual(OAuthToken.objects.count(), before + 1)

    def test_code_cannot_be_reused(self):
        verifier, challenge = _pkce_pair()
        self.client.post("/oauth2/authorize", {
            "action": "approve",
            "client_id": self.oauth_client.client_id,
            "redirect_uri": DEMO_REDIRECT,
            "scope": "openid",
            "state": "",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "patient_context": "",
        })
        code = OAuthAuthCode.objects.latest("created_at").code
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DEMO_REDIRECT,
            "client_id": self.oauth_client.client_id,
            "code_verifier": verifier,
        }
        r1 = self.client.post("/oauth2/token", payload)
        r2 = self.client.post("/oauth2/token", payload)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 400)
        self.assertIn("invalid_grant", r2.json()["error"])

    def test_pkce_wrong_verifier_rejected(self):
        _, challenge = _pkce_pair()
        self.client.post("/oauth2/authorize", {
            "action": "approve",
            "client_id": self.oauth_client.client_id,
            "redirect_uri": DEMO_REDIRECT,
            "scope": "openid",
            "state": "",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "patient_context": "",
        })
        code = OAuthAuthCode.objects.latest("created_at").code
        r = self.client.post("/oauth2/token", {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DEMO_REDIRECT,
            "client_id": self.oauth_client.client_id,
            "code_verifier": "wrong-verifier",
        })
        self.assertEqual(r.status_code, 400)
        self.assertIn("PKCE", r.json()["error_description"])

    def test_pkce_missing_verifier_rejected(self):
        _, challenge = _pkce_pair()
        self.client.post("/oauth2/authorize", {
            "action": "approve",
            "client_id": self.oauth_client.client_id,
            "redirect_uri": DEMO_REDIRECT,
            "scope": "openid",
            "state": "",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "patient_context": "",
        })
        code = OAuthAuthCode.objects.latest("created_at").code
        r = self.client.post("/oauth2/token", {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DEMO_REDIRECT,
            "client_id": self.oauth_client.client_id,
        })
        self.assertEqual(r.status_code, 400)
        self.assertIn("code_verifier required", r.json()["error_description"])

    def test_unknown_code_rejected(self):
        r = self.client.post("/oauth2/token", {
            "grant_type": "authorization_code",
            "code": "does-not-exist",
            "redirect_uri": DEMO_REDIRECT,
            "client_id": self.oauth_client.client_id,
            "code_verifier": "anything",
        })
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"], "invalid_grant")

    def test_client_credentials_grant(self):
        cc_client = _make_client(
            grant_types=["client_credentials"],
            is_public=True,
            scopes=["system/*.read"],
        )
        r = self.client.post("/oauth2/token", {
            "grant_type": "client_credentials",
            "client_id": cc_client.client_id,
            "scope": "system/*.read",
        })
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("access_token", data)
        self.assertNotIn("refresh_token", data)
        self.assertNotIn("patient", data)

    def test_client_credentials_disallowed_on_auth_code_client(self):
        r = self.client.post("/oauth2/token", {
            "grant_type": "client_credentials",
            "client_id": self.oauth_client.client_id,
        })
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"], "unauthorized_client")

    def test_refresh_token_issues_new_token(self):
        token_data = self._full_auth_code_flow(
            scopes="openid offline_access patient/Patient.read", patient="10001"
        ).json()
        refresh = token_data["refresh_token"]

        r = self.client.post("/oauth2/token", {
            "grant_type": "refresh_token",
            "refresh_token": refresh,
        })
        self.assertEqual(r.status_code, 200)
        new_data = r.json()
        self.assertIn("access_token", new_data)
        self.assertNotEqual(new_data["access_token"], token_data["access_token"])

    def test_refresh_token_rotation_revokes_old(self):
        token_data = self._full_auth_code_flow(
            scopes="openid offline_access patient/Patient.read"
        ).json()
        refresh = token_data["refresh_token"]

        self.client.post("/oauth2/token", {"grant_type": "refresh_token", "refresh_token": refresh})

        # Attempt to reuse old refresh token
        r = self.client.post("/oauth2/token", {"grant_type": "refresh_token", "refresh_token": refresh})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"], "invalid_grant")

    def test_unsupported_grant_type(self):
        r = self.client.post("/oauth2/token", {"grant_type": "implicit"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"], "unsupported_grant_type")


# ---------------------------------------------------------------------------
# Token introspection
# ---------------------------------------------------------------------------

class OAuthIntrospectTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("carol", password="pass")
        self.client.force_login(self.user)
        self.oauth_client = _make_client(scopes=["openid", "patient/Patient.read", "offline_access"])

    def _get_token(self, patient="10001"):
        verifier, challenge = _pkce_pair()
        self.client.post("/oauth2/authorize", {
            "action": "approve",
            "client_id": self.oauth_client.client_id,
            "redirect_uri": DEMO_REDIRECT,
            "scope": "openid patient/Patient.read",
            "state": "",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "patient_context": patient,
        })
        code = OAuthAuthCode.objects.latest("created_at").code
        r = self.client.post("/oauth2/token", {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DEMO_REDIRECT,
            "client_id": self.oauth_client.client_id,
            "code_verifier": verifier,
        })
        return r.json()["access_token"]

    def test_introspect_active_token(self):
        token = self._get_token()
        r = self.client.post("/oauth2/introspect", {"token": token})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["active"])

    def test_introspect_has_scope(self):
        token = self._get_token()
        data = self.client.post("/oauth2/introspect", {"token": token}).json()
        self.assertIn("scope", data)
        self.assertIn("patient/Patient.read", data["scope"])

    def test_introspect_has_patient_context(self):
        token = self._get_token(patient="10001")
        data = self.client.post("/oauth2/introspect", {"token": token}).json()
        self.assertEqual(data.get("patient"), "10001")

    def test_introspect_has_client_id(self):
        token = self._get_token()
        data = self.client.post("/oauth2/introspect", {"token": token}).json()
        self.assertEqual(data["client_id"], str(self.oauth_client.client_id))

    def test_introspect_invalid_token_returns_inactive(self):
        r = self.client.post("/oauth2/introspect", {"token": "garbage-token"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["active"])

    def test_introspect_empty_token_returns_inactive(self):
        r = self.client.post("/oauth2/introspect", {"token": ""})
        self.assertFalse(r.json()["active"])

    def test_introspect_revoked_token_returns_inactive(self):
        token = self._get_token()
        OAuthToken.objects.filter(access_token=token).update(revoked=True)
        r = self.client.post("/oauth2/introspect", {"token": token})
        self.assertFalse(r.json()["active"])

    def test_introspect_expired_token_returns_inactive(self):
        token = self._get_token()
        OAuthToken.objects.filter(access_token=token).update(
            expires_at=timezone.now() - timezone.timedelta(hours=2)
        )
        r = self.client.post("/oauth2/introspect", {"token": token})
        self.assertFalse(r.json()["active"])


# ---------------------------------------------------------------------------
# Token revocation
# ---------------------------------------------------------------------------

class OAuthRevokeTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("dave", password="pass")
        self.client.force_login(self.user)
        self.oauth_client = _make_client(scopes=["openid", "patient/Patient.read"])

    def _get_token(self):
        verifier, challenge = _pkce_pair()
        self.client.post("/oauth2/authorize", {
            "action": "approve",
            "client_id": self.oauth_client.client_id,
            "redirect_uri": DEMO_REDIRECT,
            "scope": "openid patient/Patient.read",
            "state": "",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "patient_context": "",
        })
        code = OAuthAuthCode.objects.latest("created_at").code
        r = self.client.post("/oauth2/token", {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DEMO_REDIRECT,
            "client_id": self.oauth_client.client_id,
            "code_verifier": verifier,
        })
        return r.json()["access_token"]

    def test_revoke_returns_200(self):
        token = self._get_token()
        r = self.client.post("/oauth2/revoke", {"token": token})
        self.assertEqual(r.status_code, 200)

    def test_revoke_marks_token_as_revoked(self):
        token = self._get_token()
        self.client.post("/oauth2/revoke", {"token": token})
        self.assertTrue(OAuthToken.objects.get(access_token=token).revoked)

    def test_revoke_then_introspect_returns_inactive(self):
        token = self._get_token()
        self.client.post("/oauth2/revoke", {"token": token})
        data = self.client.post("/oauth2/introspect", {"token": token}).json()
        self.assertFalse(data["active"])

    def test_revoke_unknown_token_still_200(self):
        r = self.client.post("/oauth2/revoke", {"token": "never-existed"})
        self.assertEqual(r.status_code, 200)


# ---------------------------------------------------------------------------
# Dynamic Client Registration
# ---------------------------------------------------------------------------

class OAuthRegisterTests(TestCase):

    def _register(self, **kwargs):
        payload = {
            "client_name": "My Test App",
            "redirect_uris": ["https://myapp.example.com/cb"],
            "grant_types": ["authorization_code"],
            "scope": "openid patient/Patient.read offline_access",
            "token_endpoint_auth_method": "none",
            **kwargs,
        }
        return self.client.post(
            "/oauth2/register",
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_register_returns_201(self):
        self.assertEqual(self._register().status_code, 201)

    def test_register_returns_client_id(self):
        data = self._register().json()
        self.assertIn("client_id", data)
        self.assertTrue(len(data["client_id"]) > 10)

    def test_register_persists_client(self):
        before = OAuthClient.objects.count()
        self._register()
        self.assertEqual(OAuthClient.objects.count(), before + 1)

    def test_register_confidential_client_returns_secret(self):
        data = self._register(token_endpoint_auth_method="client_secret_basic").json()
        self.assertIn("client_secret", data)

    def test_register_public_client_no_secret(self):
        data = self._register(token_endpoint_auth_method="none").json()
        self.assertNotIn("client_secret", data)

    def test_register_filters_unknown_scopes(self):
        data = self._register(scope="openid patient/Patient.read made_up_scope").json()
        registered = OAuthClient.objects.get(client_id=data["client_id"])
        self.assertNotIn("made_up_scope", registered.scopes_allowed)


# ---------------------------------------------------------------------------
# Bulk FHIR $export
# ---------------------------------------------------------------------------

class BulkExportTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("export_user", password="pass")
        self.client.force_login(self.user)
        HL7MessageLog.objects.create(
            raw_hl7=ADT_HL7,
            patient_id="10001",
            message_type="ADT^A01",
            processing_status="TRANSFORMED",
            encounter_present=True,
        )

    def test_export_returns_202(self):
        r = self.client.get("/fhir/Patient/$export")
        self.assertEqual(r.status_code, 202)

    def test_export_requires_login(self):
        self.client.logout()
        r = self.client.get("/fhir/Patient/$export")
        self.assertIn(r.status_code, (302, 301))

    def test_export_has_content_location_header(self):
        r = self.client.get("/fhir/Patient/$export")
        self.assertIn("Content-Location", r.headers)
        self.assertIn("/fhir/bulkstatus/", r.headers["Content-Location"])

    def test_export_content_location_is_valid_status_url(self):
        r = self.client.get("/fhir/Patient/$export")
        status_url = r.headers["Content-Location"]
        # Extract path from absolute URL
        from urllib.parse import urlparse
        path = urlparse(status_url).path
        r2 = self.client.get(path)
        self.assertIn(r2.status_code, (200, 202))

    def test_export_creates_bulk_job(self):
        before = BulkExportJob.objects.count()
        self.client.get("/fhir/Patient/$export")
        self.assertEqual(BulkExportJob.objects.count(), before + 1)

    def test_export_rejects_unsupported_output_format(self):
        r = self.client.get("/fhir/Patient/$export", {"_outputFormat": "text/csv"})
        self.assertEqual(r.status_code, 400)

    def test_export_with_since_filter(self):
        r = self.client.get("/fhir/Patient/$export", {"_since": "2020-01-01T00:00:00Z"})
        self.assertEqual(r.status_code, 202)

    def test_export_invalid_since_returns_400(self):
        r = self.client.get("/fhir/Patient/$export", {"_since": "not-a-date"})
        self.assertEqual(r.status_code, 400)


# ---------------------------------------------------------------------------
# Bulk export status
# ---------------------------------------------------------------------------

class BulkExportStatusTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("status_user", password="pass")
        self.client.force_login(self.user)
        HL7MessageLog.objects.create(
            raw_hl7=ADT_HL7,
            patient_id="10001",
            message_type="ADT^A01",
            processing_status="TRANSFORMED",
            encounter_present=True,
        )

    def _start_export(self):
        r = self.client.get("/fhir/Patient/$export")
        from urllib.parse import urlparse
        return urlparse(r.headers["Content-Location"]).path

    def test_status_complete_returns_200(self):
        path = self._start_export()
        r = self.client.get(path)
        self.assertEqual(r.status_code, 200)

    def test_status_response_has_transaction_time(self):
        path = self._start_export()
        data = self.client.get(path).json()
        self.assertIn("transactionTime", data)

    def test_status_response_has_output_array(self):
        path = self._start_export()
        data = self.client.get(path).json()
        self.assertIn("output", data)
        self.assertIsInstance(data["output"], list)

    def test_status_output_has_patient_file(self):
        path = self._start_export()
        data = self.client.get(path).json()
        types = [f["type"] for f in data["output"]]
        self.assertIn("Patient", types)

    def test_status_output_file_has_url(self):
        path = self._start_export()
        data = self.client.get(path).json()
        for f in data["output"]:
            self.assertIn("url", f)
            self.assertIn(".ndjson", f["url"])

    def test_status_requires_login(self):
        path = self._start_export()
        self.client.logout()
        r = self.client.get(path)
        self.assertIn(r.status_code, (302, 301))

    def test_status_unknown_job_returns_404(self):
        import uuid
        r = self.client.get(f"/fhir/bulkstatus/{uuid.uuid4()}/")
        self.assertEqual(r.status_code, 404)

    def test_pending_job_returns_202(self):
        import uuid as _uuid
        job = BulkExportJob.objects.create(
            status=BulkExportJob.Status.PENDING,
            job_id=_uuid.uuid4(),
        )
        r = self.client.get(f"/fhir/bulkstatus/{job.job_id}/")
        self.assertEqual(r.status_code, 202)

    def test_error_job_returns_500(self):
        import uuid as _uuid
        job = BulkExportJob.objects.create(
            status=BulkExportJob.Status.ERROR,
            error="Something failed",
            job_id=_uuid.uuid4(),
        )
        r = self.client.get(f"/fhir/bulkstatus/{job.job_id}/")
        self.assertEqual(r.status_code, 500)


# ---------------------------------------------------------------------------
# Bulk NDJSON file download
# ---------------------------------------------------------------------------

class BulkExportFileTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("file_user", password="pass")
        self.client.force_login(self.user)
        HL7MessageLog.objects.create(
            raw_hl7=ADT_HL7,
            patient_id="10001",
            message_type="ADT^A01",
            processing_status="TRANSFORMED",
            encounter_present=True,
        )

    def _get_file_url(self):
        r = self.client.get("/fhir/Patient/$export")
        from urllib.parse import urlparse
        status_path = urlparse(r.headers["Content-Location"]).path
        data = self.client.get(status_path).json()
        patient_file = next(f for f in data["output"] if f["type"] == "Patient")
        return urlparse(patient_file["url"]).path

    def test_file_download_returns_200(self):
        self.assertEqual(self.client.get(self._get_file_url()).status_code, 200)

    def test_file_content_type_is_ndjson(self):
        r = self.client.get(self._get_file_url())
        self.assertIn("fhir+ndjson", r.headers.get("Content-Type", ""))

    def test_file_content_is_valid_ndjson(self):
        r = self.client.get(self._get_file_url())
        lines = [l for l in r.content.decode().splitlines() if l.strip()]
        self.assertGreater(len(lines), 0)
        for line in lines:
            resource = json.loads(line)
            self.assertEqual(resource.get("resourceType"), "Patient")

    def test_file_has_content_disposition(self):
        r = self.client.get(self._get_file_url())
        self.assertIn("attachment", r.headers.get("Content-Disposition", ""))

    def test_file_requires_login(self):
        path = self._get_file_url()
        self.client.logout()
        r = self.client.get(path)
        self.assertIn(r.status_code, (302, 301))

    def test_unknown_job_returns_404(self):
        import uuid
        r = self.client.get(f"/fhir/bulkfiles/{uuid.uuid4()}/Patient.ndjson/")
        self.assertEqual(r.status_code, 404)
