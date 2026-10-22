"""Keycloak administration adapter for client identity provisioning."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from uuid import UUID


class KeycloakProvisioningError(Exception):
    """Keycloak could not complete a provisioned identity operation."""

    def __init__(self, message: str, subject: str | None = None) -> None:
        super().__init__(message)
        self.subject = subject


class KeycloakIdentityConflictError(KeycloakProvisioningError):
    """A conflicting Keycloak identity already exists."""


class KeycloakIdentityMissingError(KeycloakProvisioningError):
    """The external identity was already removed."""


class ClientIdentityProvisioner(Protocol):
    def ensure_client_identity(
        self,
        email: str,
        first_name: str,
        surname: str,
        reconciliation_id: UUID,
        subject: str | None,
    ) -> str: ...

    def update_client_identity(
        self, subject: str, email: str, first_name: str, surname: str
    ) -> None: ...

    def delete_identity(self, subject: str) -> None: ...

    def ensure_employee_identity(
        self,
        email: str,
        first_name: str,
        surname: str,
        reconciliation_id: UUID,
        subject: str | None,
        roles: set[str],
        send_first_access: bool,
    ) -> str: ...

    def reconcile_application_roles(self, subject: str, roles: set[str]) -> None: ...


@dataclass(frozen=True)
class KeycloakAdminConfig:
    base_url: str
    realm: str
    client_id: str
    client_secret: str
    first_access_client_id: str
    first_access_redirect_uri: str

    @classmethod
    def from_environment(cls) -> "KeycloakAdminConfig":
        return cls(
            base_url=os.environ.get("KEYCLOAK_ADMIN_URL", "http://keycloak:8080").rstrip("/"),
            realm=os.environ.get("KEYCLOAK_REALM", "academia"),
            client_id=os.environ.get("KEYCLOAK_PROVISIONING_CLIENT_ID", "academia-provisioner"),
            client_secret=os.environ.get("KEYCLOAK_PROVISIONING_CLIENT_SECRET", ""),
            first_access_client_id=os.environ.get(
                "KEYCLOAK_FIRST_ACCESS_CLIENT_ID", "academia-web"
            ),
            first_access_redirect_uri=os.environ.get(
                "KEYCLOAK_FIRST_ACCESS_REDIRECT_URI", "http://localhost:5173/"
            ),
        )


class KeycloakAdminClient:
    """Minimal Keycloak Admin REST client behind a replaceable boundary."""

    def __init__(self, config: KeycloakAdminConfig | None = None) -> None:
        self._config = config or KeycloakAdminConfig.from_environment()

    def ensure_demo_identity(
        self,
        email: str,
        first_name: str,
        reconciliation_id: UUID,
        roles: set[str],
        password: str,
    ) -> str:
        """Resume local demo creation without resetting an existing password."""
        token = self._access_token()
        subject = self._find_subject_for_reconciliation(token, reconciliation_id)
        if subject is None:
            subject = self._create_user(
                token, email, first_name, "Demonstração", reconciliation_id, password=password
            )
        else:
            self._verify_reconciliation_user(token, subject, email, reconciliation_id)
        self._reconcile_roles(
            token,
            subject,
            roles,
            managed={"admin", "client", "employee", "attendant", "instructor"},
        )
        return subject

    def ensure_client_identity(
        self,
        email: str,
        first_name: str,
        surname: str,
        reconciliation_id: UUID,
        subject: str | None,
    ) -> str:
        if not self._config.client_secret:
            raise KeycloakProvisioningError("Client identity provisioning is unavailable")

        token = self._access_token()
        current_subject = subject or self._find_subject_for_reconciliation(token, reconciliation_id)
        if current_subject is None:
            current_subject = self._create_user(
                token, email, first_name, surname, reconciliation_id
            )
        else:
            self._verify_reconciliation_user(token, current_subject, email, reconciliation_id)

        try:
            self._update_client_identity(token, current_subject, email, first_name, surname)
            self._assign_client_role(token, current_subject)
            self._send_first_access_email(token, current_subject)
        except KeycloakProvisioningError as error:
            if error.subject is None:
                error.subject = current_subject
            raise
        return current_subject

    def update_client_identity(
        self, subject: str, email: str, first_name: str, surname: str
    ) -> None:
        token = self._access_token()
        self._update_client_identity(token, subject, email, first_name, surname)

    def _update_client_identity(
        self, token: str, subject: str, email: str, first_name: str, surname: str
    ) -> None:
        self._request(
            "PUT",
            f"/admin/realms/{self._config.realm}/users/{subject}",
            token,
            {
                "username": email,
                "email": email,
                "firstName": first_name,
                "lastName": surname,
            },
            subject,
        )

    def delete_identity(self, subject: str) -> None:
        """Permanently remove a Keycloak user for the approved erasure workflow."""
        token = self._access_token()
        try:
            self._request(
                "DELETE",
                f"/admin/realms/{self._config.realm}/users/{subject}",
                token,
                subject=subject,
            )
        except KeycloakIdentityMissingError:
            # A stale external reference cannot retain access and is already erased.
            return

    def ensure_employee_identity(
        self,
        email: str,
        first_name: str,
        surname: str,
        reconciliation_id: UUID,
        subject: str | None,
        roles: set[str],
        send_first_access: bool,
    ) -> str:
        if not self._config.client_secret:
            raise KeycloakProvisioningError("Employee identity provisioning is unavailable")
        token = self._access_token()
        current_subject = subject or self._find_subject_for_reconciliation(token, reconciliation_id)
        if current_subject is None:
            current_subject = self._create_user(
                token, email, first_name, surname, reconciliation_id
            )
        else:
            self._verify_reconciliation_user(token, current_subject, email, reconciliation_id)
        try:
            self._update_client_identity(token, current_subject, email, first_name, surname)
            self._reconcile_roles(token, current_subject, roles)
            if send_first_access:
                self._send_first_access_email(token, current_subject)
        except KeycloakProvisioningError as error:
            if error.subject is None:
                error.subject = current_subject
            raise
        return current_subject

    def reconcile_application_roles(self, subject: str, roles: set[str]) -> None:
        self._reconcile_roles(self._access_token(), subject, roles)

    def _reconcile_roles(
        self, token: str, subject: str, roles: set[str], *, managed: set[str] | None = None
    ) -> None:
        if managed is None:
            managed = {"client", "employee", "instructor"}
        current = self._request(
            "GET",
            f"/admin/realms/{self._config.realm}/users/{subject}/role-mappings/realm",
            token,
            subject=subject,
        )
        if not isinstance(current, list):
            raise KeycloakProvisioningError("Employee role reconciliation is unavailable", subject)
        desired_names = roles.intersection(managed)
        current_names = {role.get("name") for role in current if isinstance(role, dict)}
        removable = [
            role
            for role in current
            if isinstance(role, dict) and role.get("name") in managed - desired_names
        ]
        if removable:
            self._request(
                "DELETE",
                f"/admin/realms/{self._config.realm}/users/{subject}/role-mappings/realm",
                token,
                removable,
                subject,
            )
        desired = []
        for role_name in sorted(desired_names - current_names):
            role = self._request(
                "GET",
                f"/admin/realms/{self._config.realm}/roles/{role_name}",
                token,
                subject=subject,
            )
            if not isinstance(role, dict):
                raise KeycloakProvisioningError(
                    "Employee role reconciliation is unavailable", subject
                )
            desired.append(role)
        if desired:
            self._request(
                "POST",
                f"/admin/realms/{self._config.realm}/users/{subject}/role-mappings/realm",
                token,
                desired,
                subject,
            )

    def _access_token(self) -> str:
        body = urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": self._config.client_id,
                "client_secret": self._config.client_secret,
            }
        ).encode()
        request = Request(
            f"{self._config.base_url}/realms/{self._config.realm}/protocol/openid-connect/token",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=3) as response:  # noqa: S310 - configured identity provider
                payload = json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            raise KeycloakProvisioningError("Client identity provisioning is unavailable") from None
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise KeycloakProvisioningError("Client identity provisioning is unavailable")
        return token

    def _find_subject_for_reconciliation(self, token: str, reconciliation_id: UUID) -> str | None:
        query = urlencode({"q": f"academia_provisioning_id:{reconciliation_id}"})
        payload = self._request("GET", f"/admin/realms/{self._config.realm}/users?{query}", token)
        if not isinstance(payload, list):
            raise KeycloakProvisioningError("Client identity provisioning is unavailable")
        matches = [
            user for user in payload if isinstance(user, dict) and isinstance(user.get("id"), str)
        ]
        if len(matches) > 1:
            raise KeycloakIdentityConflictError("A conflicting Keycloak identity already exists")
        return matches[0]["id"] if matches else None

    def _create_user(
        self,
        token: str,
        email: str,
        first_name: str,
        surname: str,
        reconciliation_id: UUID,
        *,
        password: str | None = None,
    ) -> str:
        payload = {
            "username": email,
            "email": email,
            "firstName": first_name,
            "lastName": surname,
            "enabled": True,
            "emailVerified": False,
            "attributes": {
                "account_active": ["true"],
                "academia_provisioning_id": [str(reconciliation_id)],
            },
        }
        if password is not None:
            # Credentials are created atomically with this demo identity, only in Keycloak.
            payload["credentials"] = [{"type": "password", "value": password, "temporary": False}]
        location = self._request(
            "POST", f"/admin/realms/{self._config.realm}/users", token, payload
        )
        if not isinstance(location, str):
            raise KeycloakProvisioningError("Client identity provisioning is unavailable")
        subject = urlparse(location).path.rstrip("/").split("/")[-1]
        if not subject:
            raise KeycloakProvisioningError("Client identity provisioning is unavailable")
        return subject

    def _verify_reconciliation_user(
        self, token: str, subject: str, email: str, reconciliation_id: UUID
    ) -> None:
        payload = self._request(
            "GET", f"/admin/realms/{self._config.realm}/users/{subject}", token, subject=subject
        )
        if not isinstance(payload, dict):
            raise KeycloakProvisioningError("Client identity provisioning is unavailable", subject)
        attributes = payload.get("attributes")
        identifiers = (
            attributes.get("academia_provisioning_id", []) if isinstance(attributes, dict) else []
        )
        # The durable random provisioning marker proves ownership, not mutable e-mail.
        # An administrator may edit e-mail while first-access delivery is pending.
        if str(reconciliation_id) not in identifiers:
            raise KeycloakIdentityConflictError(
                "A conflicting Keycloak identity already exists", subject
            )

    def _assign_client_role(self, token: str, subject: str) -> None:
        role = self._request(
            "GET", f"/admin/realms/{self._config.realm}/roles/client", token, subject=subject
        )
        if not isinstance(role, dict):
            raise KeycloakProvisioningError("Client identity provisioning is unavailable", subject)
        self._request(
            "POST",
            f"/admin/realms/{self._config.realm}/users/{subject}/role-mappings/realm",
            token,
            [role],
            subject,
        )

    def _send_first_access_email(self, token: str, subject: str) -> None:
        self._send_password_action_email(token, subject)

    def send_password_recovery_email(self, subject: str, email: str) -> None:
        """Send only to the linked, enabled identity with a synchronized email."""
        token = self._access_token()
        user = self._request(
            "GET", f"/admin/realms/{self._config.realm}/users/{subject}", token, subject=subject
        )
        if (
            not isinstance(user, dict)
            or user.get("id") != subject
            or user.get("enabled") is not True
            or not isinstance(user.get("email"), str)
            or user["email"].strip().lower() != email.strip().lower()
        ):
            raise KeycloakIdentityConflictError("Recovery identity is not synchronized")
        self._send_password_action_email(token, subject, lifespan=900)

    def _send_password_action_email(
        self, token: str, subject: str, *, lifespan: int | None = None
    ) -> None:
        query = urlencode(
            {
                "client_id": self._config.first_access_client_id,
                "redirect_uri": self._config.first_access_redirect_uri,
                **({"lifespan": lifespan} if lifespan is not None else {}),
            }
        )
        self._request(
            "PUT",
            f"/admin/realms/{self._config.realm}/users/{subject}/execute-actions-email?{query}",
            token,
            ["UPDATE_PASSWORD"],
            subject,
        )

    def _request(
        self,
        method: str,
        path: str,
        token: str,
        payload: object | None = None,
        subject: str | None = None,
    ) -> object:
        body = json.dumps(payload).encode() if payload is not None else None
        request = Request(
            f"{self._config.base_url}{path}",
            data=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method=method,
        )
        try:
            with urlopen(request, timeout=3) as response:  # noqa: S310 - configured identity provider
                if method == "POST" and response.status == 201:
                    return response.headers.get("Location", "")
                content = response.read()
        except HTTPError as error:
            if error.code == 404:
                raise KeycloakIdentityMissingError(
                    "Client identity is already absent", subject
                ) from None
            if error.code == 409:
                raise KeycloakIdentityConflictError(
                    "A conflicting Keycloak identity already exists", subject
                ) from None
            raise KeycloakProvisioningError(
                "Client identity provisioning is unavailable", subject
            ) from None
        except (URLError, TimeoutError):
            raise KeycloakProvisioningError(
                "Client identity provisioning is unavailable", subject
            ) from None
        if not content:
            return None
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            raise KeycloakProvisioningError(
                "Client identity provisioning is unavailable", subject
            ) from None
