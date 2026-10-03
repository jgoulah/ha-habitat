"""Habitat HomeLink cloud client: Cognito login, temporary AWS credentials, device discovery and shadow reads.

Login and identity-pool handling are adapted from salus-it600-cloud (MIT) by Peterka35.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp
import boto3
from boto3.dynamodb.types import TypeDeserializer
from botocore.exceptions import BotoCoreError, ClientError
from pycognito import Cognito
from pycognito.exceptions import SoftwareTokenMFAChallengeException

from .const import (
    AWS_CLIENT_ID,
    AWS_IDENTITY_POOL_ID,
    AWS_IOT_ENDPOINT,
    AWS_REGION,
    AWS_USER_POOL_ID,
    DEVICE_LIST_KEY,
    DEVICE_LIST_TABLE,
)

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)
# Lifetime assumed when a token or credential does not carry its expiry
FALLBACK_LIFETIME = timedelta(hours=1)
REFRESH_MARGIN = timedelta(minutes=5)
COGNITO_IDENTITY_URL = f"https://cognito-identity.{AWS_REGION}.amazonaws.com/"
COGNITO_LOGIN_PROVIDER = f"cognito-idp.{AWS_REGION}.amazonaws.com/{AWS_USER_POOL_ID}"
# Cognito error codes meaning the stored credentials can no longer be used
AUTH_ERROR_CODES = {
    "NotAuthorizedException",
    "UserNotFoundException",
    "PasswordResetRequiredException",
    "UserNotConfirmedException",
}


class HabitatAuthenticationError(Exception):
    """Credentials were rejected."""


class HabitatConnectionError(Exception):
    """The Habitat cloud could not be reached or returned an error."""


@dataclass(frozen=True)
class AwsCredentials:
    """Temporary AWS credentials from the Cognito identity pool."""

    access_key: str
    secret_key: str
    session_token: str
    expiry: datetime


@dataclass(frozen=True)
class HabitatThing:
    """AWS IoT thing of a gateway: the gateway itself, its Zigbee coordinator or a device."""

    name: str
    gateway: str

    @property
    def model(self) -> str:
        """Return model code, e.g. SAUPTZ1PT868 for SAUPTZ1GW-001E5E000001-SAUPTZ1PT868-0000000000000000."""
        if self.name == self.gateway:
            return self.name.split("-", 1)[0]
        return self.name.rsplit("-", 2)[-2]


def jwt_expiry(token: str | None) -> datetime | None:
    """Return expiry time from the exp claim of a JWT token."""
    if not token:
        return None
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return datetime.fromtimestamp(claims["exp"], tz=UTC)
    except (IndexError, KeyError, TypeError, ValueError):
        return None


def thing_group_name(gateway: str) -> str:
    """Return the IoT thing group holding a gateway's things: SAUPTZ1GW-001E5E000001 -> Gateway-001E5E000001."""
    return f"Gateway-{gateway.split('-', 1)[1]}"


def parse_device_list(items: list[dict[str, Any]]) -> list[str]:
    """Return gateway thing names from UserToDeviceList items (the Own attribute, stored as a map or a JSON string)."""
    deserializer = TypeDeserializer()
    gateways: list[str] = []
    for item in items:
        own = item.get("Own")
        if own is None:
            continue
        value = deserializer.deserialize(own)
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                _LOGGER.warning("Ignoring unparsable device list %r", value)
                continue
        names = value.get("list", []) if isinstance(value, dict) else value
        gateways.extend(str(name) for name in names if name and str(name) not in gateways)
    return gateways


class HabitatApi:
    """Client for the Habitat HomeLink cloud."""

    def __init__(self, email: str, password: str, session: aiohttp.ClientSession | None = None) -> None:
        """Initialize the client; a passed HTTP session is shared and never closed by the client."""
        self.email = email
        self._password = password
        self._session = session
        self._owns_session = session is None
        self._cognito: Cognito | None = None
        self._id_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expiry: datetime | None = None
        self._identity_id: str | None = None
        self._credentials: AwsCredentials | None = None
        self._clients: dict[str, Any] = {}

    # Cognito user pool login

    def _sync_authenticate(self) -> None:
        self._cognito = Cognito(
            user_pool_id=AWS_USER_POOL_ID,
            client_id=AWS_CLIENT_ID,
            user_pool_region=AWS_REGION,
            username=self.email,
        )
        self._cognito.authenticate(password=self._password)
        self._id_token = self._cognito.id_token
        self._refresh_token = self._cognito.refresh_token

    def _sync_refresh_tokens(self) -> None:
        self._cognito.renew_access_token()
        self._id_token = self._cognito.id_token

    async def authenticate(self) -> None:
        """Log in to the Cognito user pool."""
        _LOGGER.debug("Logging in to Habitat cloud")
        await self._login(self._sync_authenticate)

    async def _login(self, func: Callable[[], None]) -> None:
        try:
            await asyncio.to_thread(func)
        except SoftwareTokenMFAChallengeException as err:
            raise HabitatAuthenticationError("MFA is not supported") from err
        except ClientError as err:
            code = err.response.get("Error", {}).get("Code")
            if code in AUTH_ERROR_CODES:
                raise HabitatAuthenticationError(f"Login rejected: {code}") from err
            raise HabitatConnectionError(f"Login failed: {code}") from err
        except Exception as err:
            raise HabitatConnectionError(f"Login failed: {err!r}") from err
        self._token_expiry = jwt_expiry(self._id_token) or datetime.now(UTC) + FALLBACK_LIFETIME

    async def _ensure_token(self) -> None:
        """Renew tokens shortly before they expire."""
        if self._token_expiry and datetime.now(UTC) < self._token_expiry - REFRESH_MARGIN:
            return
        if self._cognito and self._refresh_token:
            try:
                await self._login(self._sync_refresh_tokens)
            except HabitatAuthenticationError:
                _LOGGER.debug("Refresh token rejected, logging in again")
            else:
                return
        await self.authenticate()

    # Cognito identity pool: temporary AWS credentials

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._owns_session = True
        return self._session

    async def _cognito_identity_call(self, target: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with self._get_session().post(
            COGNITO_IDENTITY_URL,
            json=payload,
            headers={"Content-Type": "application/x-amz-json-1.1", "X-Amz-Target": target},
            timeout=REQUEST_TIMEOUT,
        ) as response:
            response.raise_for_status()
            return await response.json(content_type=None)

    async def get_aws_credentials(self) -> AwsCredentials:
        """Return temporary AWS credentials, renewing them shortly before they expire."""
        if self._credentials and datetime.now(UTC) < self._credentials.expiry - REFRESH_MARGIN:
            return self._credentials
        await self._ensure_token()
        logins = {COGNITO_LOGIN_PROVIDER: self._id_token}
        try:
            if self._identity_id is None:
                result = await self._cognito_identity_call(
                    "AWSCognitoIdentityService.GetId", {"IdentityPoolId": AWS_IDENTITY_POOL_ID, "Logins": logins}
                )
                self._identity_id = result["IdentityId"]
            result = await self._cognito_identity_call(
                "AWSCognitoIdentityService.GetCredentialsForIdentity",
                {"IdentityId": self._identity_id, "Logins": logins},
            )
            credentials = result["Credentials"]
        except (aiohttp.ClientError, TimeoutError, KeyError) as err:
            raise HabitatConnectionError(f"Failed to get AWS credentials: {err!r}") from err
        expiration = credentials.get("Expiration")
        self._credentials = AwsCredentials(
            access_key=credentials["AccessKeyId"],
            secret_key=credentials["SecretKey"],
            session_token=credentials["SessionToken"],
            expiry=datetime.fromtimestamp(expiration, tz=UTC) if expiration else datetime.now(UTC) + FALLBACK_LIFETIME,
        )
        self._clients = {}
        return self._credentials

    # AWS service calls (boto3 is blocking, so calls run in a worker thread)

    async def _aws_call(self, service: str, method: str, **kwargs: Any) -> dict[str, Any]:
        credentials = await self.get_aws_credentials()

        def call() -> dict[str, Any]:
            client = self._clients.get(service)
            if client is None:
                client = boto3.session.Session(
                    aws_access_key_id=credentials.access_key,
                    aws_secret_access_key=credentials.secret_key,
                    aws_session_token=credentials.session_token,
                    region_name=AWS_REGION,
                ).client(service, endpoint_url=f"https://{AWS_IOT_ENDPOINT}" if service == "iot-data" else None)
                self._clients[service] = client
            return getattr(client, method)(**kwargs)

        try:
            return await asyncio.to_thread(call)
        except (BotoCoreError, ClientError) as err:
            raise HabitatConnectionError(f"{service} {method} failed: {err}") from err

    async def get_gateways(self) -> list[str]:
        """Return gateway thing names of the account."""
        await self.get_aws_credentials()
        response = await self._aws_call(
            "dynamodb",
            "query",
            TableName=DEVICE_LIST_TABLE,
            KeyConditionExpression="#user = :user",
            ExpressionAttributeNames={"#user": DEVICE_LIST_KEY},
            ExpressionAttributeValues={":user": {"S": self._identity_id}},
        )
        return parse_device_list(response.get("Items", []))

    async def get_gateway_things(self, gateway: str) -> list[HabitatThing]:
        """Return the things of a gateway, including the gateway itself."""
        names = {gateway}
        token: str | None = None
        while True:
            response = await self._aws_call(
                "iot",
                "list_things_in_thing_group",
                thingGroupName=thing_group_name(gateway),
                **({"nextToken": token} if token else {}),
            )
            names.update(response.get("things", []))
            if not (token := response.get("nextToken")):
                break
        return [HabitatThing(name=name, gateway=gateway) for name in sorted(names)]

    async def discover(self) -> list[HabitatThing]:
        """Return the things of all gateways of the account."""
        things: list[HabitatThing] = []
        for gateway in await self.get_gateways():
            things.extend(await self.get_gateway_things(gateway))
        return things

    async def get_shadow(self, thing: str) -> dict[str, Any]:
        """Return the shadow document of a thing."""
        response = await self._aws_call("iot-data", "get_thing_shadow", thingName=thing)
        payload = response["payload"]
        body = await asyncio.to_thread(payload.read)
        return json.loads(body)

    async def close(self) -> None:
        """Close the HTTP session if the client created it."""
        if self._owns_session and self._session is not None and not self._session.closed:
            await self._session.close()
