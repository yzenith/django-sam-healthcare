"""
example/oauth_views.py

SMART on FHIR OAuth2 authorization server (demo implementation).

Implements the SMART App Launch Framework (HL7 FHIR STU2):
  - Authorization Code flow with PKCE (S256)
  - Client Credentials flow (system-to-system)
  - Refresh Token rotation
  - Token Introspection (RFC 7662)
  - Token Revocation (RFC 7009)
  - Dynamic Client Registration (RFC 7591, simplified)
  - JWKS endpoint (/.well-known/jwks.json)

In production you would use Keycloak, Azure AD B2C, or AWS Cognito as the
authorization server instead of this custom implementation. This demo shows
you understand the protocol mechanics — the scopes, PKCE, patient context,
and token introspection that SMART-enabled EHRs require.

Endpoints registered in example/urls.py:
  GET  /.well-known/jwks.json       Public key set
  GET  /oauth2/authorize            Consent screen
  POST /oauth2/authorize            Process approval/denial
  POST /oauth2/token                Issue access token
  POST /oauth2/introspect           RFC 7662 introspection
  POST /oauth2/revoke               RFC 7009 revocation
  POST /oauth2/register             Dynamic client registration
"""

import secrets
import hashlib
import base64
import uuid
from datetime import timedelta

import jwt
from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .models import OAuthClient, OAuthAuthCode, OAuthToken

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_OAUTH_SECRET = getattr(settings, "OAUTH_JWT_SECRET", settings.SECRET_KEY)
_OAUTH_ALG = "HS256"
_KEY_ID = "demo-hs256-key-1"
_ACCESS_LIFETIME = timedelta(hours=1)
_REFRESH_LIFETIME = timedelta(days=30)
_CODE_LIFETIME = timedelta(minutes=10)

# Scopes recognised by this server (subset of SMART v2 scope vocabulary)
ALL_SCOPES = {
    "openid", "profile", "launch", "launch/patient", "offline_access",
    "patient/*.read", "patient/Patient.read", "patient/Encounter.read",
    "patient/DiagnosticReport.read", "patient/Observation.read",
    "user/*.read", "system/*.read", "system/Patient.read",
    "system/Encounter.read", "system/DiagnosticReport.read",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _err(error: str, description: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"error": error, "error_description": description}, status=status)


def _verify_pkce(verifier: str, challenge: str, method: str) -> bool:
    if method == "S256":
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        return secrets.compare_digest(computed, challenge)
    if method == "plain":
        return secrets.compare_digest(verifier, challenge)
    return False


def _build_jwt(client: OAuthClient, user, scopes: list, patient_context: str, base_url: str):
    now = timezone.now()
    exp = now + _ACCESS_LIFETIME
    payload = {
        "iss": base_url.rstrip("/"),
        "sub": str(user.id) if user else client.client_id,
        "aud": f"{base_url.rstrip('/')}/fhir",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": uuid.uuid4().hex,
        "scope": " ".join(scopes),
        "client_id": client.client_id,
    }
    if user:
        payload["fhirUser"] = f"{base_url.rstrip('/')}/fhir/Practitioner/{user.id}"
    if patient_context:
        payload["patient"] = patient_context
    token_str = jwt.encode(payload, _OAUTH_SECRET, algorithm=_OAUTH_ALG,
                           headers={"kid": _KEY_ID})
    return token_str, exp


def _issue_token(client: OAuthClient, user, scopes: list, patient_context: str, base_url: str):
    access_token, exp = _build_jwt(client, user, scopes, patient_context, base_url)
    refresh = secrets.token_urlsafe(48)
    OAuthToken.objects.create(
        access_token=access_token,
        client=client,
        user=user,
        scopes=scopes,
        patient_context=patient_context or "",
        expires_at=exp,
        refresh_token=refresh,
        refresh_expires_at=timezone.now() + _REFRESH_LIFETIME,
    )
    return access_token, refresh, exp


# ---------------------------------------------------------------------------
# JWKS
# ---------------------------------------------------------------------------

@require_GET
def jwks_json(request):
    """
    GET /.well-known/jwks.json

    Returns the JSON Web Key Set used to verify access tokens.
    This demo uses HS256 (symmetric). Production deployments use RS256/ES256
    (asymmetric) so resource servers can verify tokens without the secret.
    """
    secret_bytes = _OAUTH_SECRET.encode() if isinstance(_OAUTH_SECRET, str) else _OAUTH_SECRET
    k_value = base64.urlsafe_b64encode(secret_bytes).rstrip(b"=").decode()
    r = JsonResponse({
        "keys": [{
            "kty": "oct",
            "use": "sig",
            "alg": _OAUTH_ALG,
            "kid": _KEY_ID,
            "k": k_value,
        }]
    })
    r["Access-Control-Allow-Origin"] = "*"
    return r


# ---------------------------------------------------------------------------
# Authorization endpoint
# ---------------------------------------------------------------------------

@require_http_methods(["GET", "POST"])
def oauth_authorize(request):
    """
    GET  /oauth2/authorize  Show consent screen (requires login)
    POST /oauth2/authorize  Process approve/deny

    Supports PKCE (S256) for public clients and optional launch/patient context.
    """
    if request.method == "GET":
        client_id = request.GET.get("client_id", "").strip()
        redirect_uri = request.GET.get("redirect_uri", "").strip()
        response_type = request.GET.get("response_type", "").strip()
        scope = request.GET.get("scope", "").strip()
        state = request.GET.get("state", "").strip()
        code_challenge = request.GET.get("code_challenge", "").strip()
        code_challenge_method = request.GET.get("code_challenge_method", "S256").strip()
        launch = request.GET.get("launch", "").strip()

        if response_type != "code":
            return _err("unsupported_response_type", "Only response_type=code is supported")

        try:
            client = OAuthClient.objects.get(client_id=client_id)
        except OAuthClient.DoesNotExist:
            return _err("invalid_client", f"Unknown client_id: {client_id}")

        if redirect_uri and redirect_uri not in client.redirect_uris:
            return _err("invalid_request", "redirect_uri not registered for this client")

        if not redirect_uri and client.redirect_uris:
            redirect_uri = client.redirect_uris[0]

        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())

        requested_scopes = [s for s in scope.split() if s in ALL_SCOPES and s in client.scopes_allowed]
        patient_context = launch or request.GET.get("patient", "") or "demo-patient-001"

        return render(request, "oauth_authorize.html", {
            "client": client,
            "requested_scopes": requested_scopes,
            "patient_context": patient_context,
            "state": state,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "scope": " ".join(requested_scopes),
        })

    # POST — process consent
    action = request.POST.get("action", "deny")
    client_id = request.POST.get("client_id", "")
    redirect_uri = request.POST.get("redirect_uri", "")
    scope = request.POST.get("scope", "")
    state = request.POST.get("state", "")
    code_challenge = request.POST.get("code_challenge", "")
    code_challenge_method = request.POST.get("code_challenge_method", "S256")
    patient_context = request.POST.get("patient_context", "")

    sep = "&" if "?" in redirect_uri else "?"

    if action == "deny":
        url = f"{redirect_uri}{sep}error=access_denied&error_description=User+denied+access"
        if state:
            url += f"&state={state}"
        return HttpResponseRedirect(url)

    try:
        client = OAuthClient.objects.get(client_id=client_id)
    except OAuthClient.DoesNotExist:
        return _err("invalid_client", "Client not found")

    if not request.user.is_authenticated:
        return redirect_to_login(request.path)

    code = secrets.token_urlsafe(32)
    OAuthAuthCode.objects.create(
        code=code,
        client=client,
        user=request.user,
        redirect_uri=redirect_uri,
        scopes=scope.split() if scope else [],
        patient_context=patient_context,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method or "S256",
        expires_at=timezone.now() + _CODE_LIFETIME,
    )

    url = f"{redirect_uri}{sep}code={code}"
    if state:
        url += f"&state={state}"
    return HttpResponseRedirect(url)


# ---------------------------------------------------------------------------
# Token endpoint
# ---------------------------------------------------------------------------

@csrf_exempt
@require_POST
def oauth_token(request):
    """
    POST /oauth2/token

    grant_type=authorization_code — exchange auth code for token (PKCE validated)
    grant_type=client_credentials  — system-to-system token
    grant_type=refresh_token       — rotate refresh token
    """
    grant_type = request.POST.get("grant_type", "")
    base_url = request.build_absolute_uri("/")

    if grant_type == "authorization_code":
        code_val = request.POST.get("code", "")
        redirect_uri = request.POST.get("redirect_uri", "")
        client_id = request.POST.get("client_id", "")
        code_verifier = request.POST.get("code_verifier", "")

        try:
            auth_code = OAuthAuthCode.objects.select_related("client", "user").get(code=code_val)
        except OAuthAuthCode.DoesNotExist:
            return _err("invalid_grant", "Authorization code not found")

        if auth_code.used:
            return _err("invalid_grant", "Authorization code already used")
        if auth_code.expires_at < timezone.now():
            return _err("invalid_grant", "Authorization code expired")
        if auth_code.client.client_id != client_id:
            return _err("invalid_client", "client_id mismatch")
        if auth_code.redirect_uri != redirect_uri:
            return _err("invalid_grant", "redirect_uri mismatch")

        if auth_code.code_challenge:
            if not code_verifier:
                return _err("invalid_request", "code_verifier required (PKCE)")
            if not _verify_pkce(code_verifier, auth_code.code_challenge, auth_code.code_challenge_method):
                return _err("invalid_grant", "PKCE code_verifier verification failed")

        auth_code.used = True
        auth_code.save(update_fields=["used"])

        access_token, refresh_token, exp = _issue_token(
            auth_code.client, auth_code.user,
            auth_code.scopes, auth_code.patient_context, base_url,
        )
        resp = {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": int(_ACCESS_LIFETIME.total_seconds()),
            "scope": " ".join(auth_code.scopes),
            "refresh_token": refresh_token,
        }
        if auth_code.patient_context:
            resp["patient"] = auth_code.patient_context
        if "openid" in auth_code.scopes and auth_code.user:
            resp["id_token"] = access_token  # simplified — prod issues separate id_token
        return JsonResponse(resp)

    if grant_type == "client_credentials":
        client_id = request.POST.get("client_id", "")
        client_secret = request.POST.get("client_secret", "")
        scope = request.POST.get("scope", "")

        try:
            client = OAuthClient.objects.get(client_id=client_id)
        except OAuthClient.DoesNotExist:
            return _err("invalid_client", "Unknown client")

        if "client_credentials" not in client.grant_types:
            return _err("unauthorized_client", "client_credentials not allowed for this client")

        if not client.is_public:
            secret_hash = hashlib.sha256(client_secret.encode()).hexdigest()
            if not secrets.compare_digest(secret_hash, client.client_secret_hash):
                return _err("invalid_client", "Invalid client_secret")

        requested = scope.split() if scope else client.scopes_allowed
        allowed = [s for s in requested if s in client.scopes_allowed]

        access_token, _, exp = _issue_token(client, None, allowed, "", base_url)
        return JsonResponse({
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": int(_ACCESS_LIFETIME.total_seconds()),
            "scope": " ".join(allowed),
        })

    if grant_type == "refresh_token":
        refresh_val = request.POST.get("refresh_token", "")
        try:
            token = OAuthToken.objects.select_related("client", "user").get(
                refresh_token=refresh_val, revoked=False
            )
        except OAuthToken.DoesNotExist:
            return _err("invalid_grant", "Refresh token not found or revoked")

        if token.refresh_expires_at and token.refresh_expires_at < timezone.now():
            return _err("invalid_grant", "Refresh token expired")

        token.revoked = True
        token.save(update_fields=["revoked"])

        new_access, new_refresh, exp = _issue_token(
            token.client, token.user, token.scopes, token.patient_context, base_url,
        )
        resp = {
            "access_token": new_access,
            "token_type": "Bearer",
            "expires_in": int(_ACCESS_LIFETIME.total_seconds()),
            "scope": " ".join(token.scopes),
            "refresh_token": new_refresh,
        }
        if token.patient_context:
            resp["patient"] = token.patient_context
        return JsonResponse(resp)

    return _err("unsupported_grant_type", f"Unsupported grant_type: {grant_type}")


# ---------------------------------------------------------------------------
# Token introspection (RFC 7662)
# ---------------------------------------------------------------------------

@csrf_exempt
@require_POST
def oauth_introspect(request):
    """
    POST /oauth2/introspect

    Resource servers call this to verify a bearer token and retrieve its
    metadata (active, scope, patient context, expiry).
    """
    token_val = request.POST.get("token", "")
    if not token_val:
        return JsonResponse({"active": False})

    token = OAuthToken.objects.select_related("client", "user").filter(
        access_token=token_val, revoked=False
    ).first()

    if not token or token.expires_at < timezone.now():
        return JsonResponse({"active": False})

    resp = {
        "active": True,
        "scope": " ".join(token.scopes),
        "client_id": token.client.client_id,
        "token_type": "Bearer",
        "exp": int(token.expires_at.timestamp()),
        "iat": int(token.created_at.timestamp()),
        "sub": str(token.user.id) if token.user else token.client.client_id,
        "iss": request.build_absolute_uri("/").rstrip("/"),
    }
    if token.patient_context:
        resp["patient"] = token.patient_context
    if token.user:
        resp["username"] = token.user.username
    return JsonResponse(resp)


# ---------------------------------------------------------------------------
# Token revocation (RFC 7009)
# ---------------------------------------------------------------------------

@csrf_exempt
@require_POST
def oauth_revoke(request):
    """POST /oauth2/revoke — revoke an access or refresh token."""
    token_val = request.POST.get("token", "")
    OAuthToken.objects.filter(access_token=token_val).update(revoked=True)
    OAuthToken.objects.filter(refresh_token=token_val).update(revoked=True)
    return JsonResponse({}, status=200)


# ---------------------------------------------------------------------------
# Dynamic Client Registration (RFC 7591, simplified)
# ---------------------------------------------------------------------------

@csrf_exempt
@require_POST
def oauth_register(request):
    """
    POST /oauth2/register

    Registers a new OAuth client dynamically.  In production this endpoint
    would require an initial access token and enforce strict policy checks.
    Here we accept any registration for demo purposes.
    """
    import json
    try:
        data = json.loads(request.body)
    except (ValueError, TypeError):
        data = {k: v for k, v in request.POST.items()}

    client_name = data.get("client_name", "Unnamed Client")
    redirect_uris = data.get("redirect_uris", [])
    grant_types = data.get("grant_types", ["authorization_code"])
    scopes_requested = data.get("scope", "openid profile launch/patient patient/*.read").split()
    token_endpoint_auth_method = data.get("token_endpoint_auth_method", "none")

    allowed_scopes = [s for s in scopes_requested if s in ALL_SCOPES]
    is_public = token_endpoint_auth_method == "none"

    client_secret = None
    secret_hash = ""
    if not is_public:
        client_secret = secrets.token_urlsafe(32)
        secret_hash = hashlib.sha256(client_secret.encode()).hexdigest()

    client = OAuthClient.objects.create(
        client_name=client_name,
        redirect_uris=redirect_uris,
        scopes_allowed=allowed_scopes,
        grant_types=grant_types,
        is_public=is_public,
        client_secret_hash=secret_hash,
    )

    response = {
        "client_id": client.client_id,
        "client_name": client.client_name,
        "redirect_uris": client.redirect_uris,
        "grant_types": client.grant_types,
        "scope": " ".join(client.scopes_allowed),
        "token_endpoint_auth_method": token_endpoint_auth_method,
        "client_id_issued_at": int(client.created_at.timestamp()),
    }
    if client_secret:
        response["client_secret"] = client_secret
    return JsonResponse(response, status=201)
