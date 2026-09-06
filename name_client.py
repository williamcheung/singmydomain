"""Async client for the name.com Core API (v1.33.2), grounded directly in namecom.api.yaml.

Covers the eight operations this app's own pipeline depends on: Hello, Search,
CheckAvailability, GetPricingForDomain, CreateDomain, ListRecords, CreateRecord, DeleteRecord.
Also includes GetOrder/ProcessRefund — used only by the test suite to undo a sandbox
registration via the Add Grace Period refund, not part of the app's own pipeline.
"""

import asyncio
import logging
import time
from typing import Any

import httpx

import config
from time_it import time_it

logger = logging.getLogger(__name__)

TLDS_REQUIRING_2_YRS_REGISTRATION = ["ai"]


class NameComAPIError(Exception):
    """Raised for any non-2xx response from the name.com API.

    Args:
        status_code: HTTP status code returned by the API.
        message: The API's human-readable `message` field.
        details: The API's optional `details` field, if present.
        rate_limit_reset: Unix epoch seconds from the `x-ratelimit-reset` header, only
            populated for 429 responses.
    """

    def __init__(
        self,
        status_code: int,
        message: str,
        details: str | None = None,
        rate_limit_reset: int | None = None,
    ) -> None:
        super().__init__(f"{status_code}: {message}")
        self.status_code = status_code
        self.message = message
        self.details = details
        self.rate_limit_reset = rate_limit_reset


class NameComClient:
    """Thin async wrapper over the name.com Core API for one environment.

    Args:
        environment: `"sandbox"` (api.dev.name.com) or `"production"` (api.name.com).
            Credentials and base URL are resolved from `config.py`.
    """

    def __init__(self, environment: str) -> None:
        if environment not in config.BASE_URLS:
            raise ValueError(f"Unknown environment: {environment!r}")
        self.environment = environment
        self.base_url = config.BASE_URLS[environment]
        self._auth = config.CREDENTIALS[environment]

    async def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Issue one request, retrying 429s using the server-supplied reset time."""
        max_retries = config.NAMECOM_RATE_LIMIT_MAX_RETRIES
        for attempt in range(max_retries + 1):
            try:
                return await self._attempt(method, path, json, params)
            except NameComAPIError as error:
                retriable = error.status_code == 429 and error.rate_limit_reset is not None
                if not retriable or attempt == max_retries:
                    raise
                wait_seconds = max(0, error.rate_limit_reset - time.time())
                if wait_seconds > config.NAMECOM_RATE_LIMIT_MAX_AUTO_WAIT_SECONDS:
                    raise
                logger.warning(
                    "name.com rate limited, retrying in %.1fs (attempt %d/%d): %s %s",
                    wait_seconds, attempt + 1, max_retries, method, path,
                )
                await asyncio.sleep(wait_seconds)

    async def hello(self) -> dict[str, Any]:
        """GET /core/v1/hello — connectivity/credential check.

        Returns:
            dict with `motd`, `serverName`, `serverTime`, `username`.
        """
        return await self._request("GET", "/core/v1/hello")

    async def search(
        self,
        keyword: str,
        tld_filter: list[str] | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        """POST /core/v1/domains:search — keyword-based domain suggestions.

        Always sends `purchaseType: "registration"` so results are limited to standard,
        predictably-priced registrations (see the spec's Domain pricing guide).

        Args:
            keyword: Search term or full domain name.
            tld_filter: Restrict results to these TLDs (max 50).
            timeout_ms: Search timeout in milliseconds (500-12000; API default 12000).

        Returns:
            dict with a `results` list of `SearchResult` objects.
        """
        body = {"keyword": keyword, "purchaseType": "registration"}
        if tld_filter:
            body["tldFilter"] = tld_filter
        if timeout_ms:
            body["timeout"] = timeout_ms
        return await self._request("POST", "/core/v1/domains:search", json=body)

    async def check_availability(
        self, domain_names: list[str], purchase_type: str = "registration"
    ) -> dict[str, Any]:
        """POST /core/v1/domains:checkAvailability — exact-name availability + pricing.

        Unlike `search`, non-matching domains are returned with `purchasable: false`
        rather than omitted. Intended as the re-check step immediately before `create_domain`.

        Args:
            domain_names: Up to 50 exact domain names to check.
            purchase_type: Defaults to `"registration"`.

        Returns:
            dict with a `results` list of `SearchResult` objects.

        Raises:
            ValueError: If more than 50 domain names are given.
        """
        if len(domain_names) > 50:
            raise ValueError(
                f"check_availability accepts at most 50 domain names, got {len(domain_names)}"
            )
        body = {"domainNames": domain_names, "purchaseType": purchase_type}
        return await self._request("POST", "/core/v1/domains:checkAvailability", json=body)

    async def get_pricing(self, domain_name: str, years: int = 1) -> dict[str, Any]:
        """GET /core/v1/domains/{domainName}:getPricing — registration/renewal/transfer pricing.

        Args:
            domain_name: Domain to price.
            years: Registration term in years (1-10). Must match the `years` later passed to
                `create_domain` when a premium `purchasePrice` is required.

        Returns:
            dict matching `PricingResponse`.
        """
        return await self._request(
            "GET", f"/core/v1/domains/{domain_name}:getPricing", params={"years": years}
        )

    async def create_domain(
        self,
        domain_name: str,
        purchase_type: str = "registration",
        purchase_price: float | None = None,
        years: int = 1,
    ) -> dict[str, Any]:
        """POST /core/v1/domains — register a domain.

        Args:
            domain_name: Domain to register.
            purchase_type: Should be copied from the `search`/`check_availability` result.
            purchase_price: Required if the result was premium or non-`"registration"`.
            years: Registration term in years; only affects `"registration"` purchases.

        Returns:
            dict matching `CreateDomainResponse` (`domain`, `order`, `totalPaid`).
        """
        tld = domain_name.rsplit(".", 1)[-1]
        if tld in TLDS_REQUIRING_2_YRS_REGISTRATION:
            years = max(years, 2)
        body = {
            "domain": {"domainName": domain_name},
            "purchaseType": purchase_type,
            "years": years,
        }
        if purchase_price is not None:
            body["purchasePrice"] = purchase_price
        try:
            response = await self._request("POST", "/core/v1/domains", json=body)
            return {**response, "years": years}
        except NameComAPIError as error:
            if error.status_code == 400 and error.message and error.message.casefold() == "invalid years":
                raise NameComAPIError(
                    status_code=error.status_code,
                    message=f"Requires more than {years} year(s) of registration",
                    details=error.details,
                ) from error
            raise

    async def list_records(self, domain_name: str) -> dict[str, Any]:
        """GET /core/v1/domains/{domainName}/records — list all DNS records for a domain.

        Returns:
            dict with a `records` list (up to `perPage`, default 500).
        """
        return await self._request("GET", f"/core/v1/domains/{domain_name}/records")

    async def create_record(
        self,
        domain_name: str,
        host: str,
        type_: str,
        answer: str,
        ttl: int = 300,
        priority: int | None = None,
    ) -> dict[str, Any]:
        """POST /core/v1/domains/{domainName}/records — create a DNS record.

        Args:
            domain_name: Zone the record belongs to.
            host: Hostname relative to the zone (`""` or `"@"` for apex).
            type_: One of `A, AAAA, ANAME, CNAME, MX, NS, SRV, TXT`.
            answer: Record value (IP, target, or text, per `type_`).
            ttl: Cache TTL in seconds; name.com's minimum is 300.
            priority: Required for `MX`/`SRV`, ignored otherwise.

        Returns:
            dict matching `Record`, including the server-assigned `id`.
        """
        body = {"host": host, "type": type_, "answer": answer, "ttl": ttl}
        if priority is not None:
            body["priority"] = priority
        return await self._request("POST", f"/core/v1/domains/{domain_name}/records", json=body)

    async def delete_record(self, domain_name: str, record_id: int) -> None:
        """DELETE /core/v1/domains/{domainName}/records/{id} — delete a DNS record."""
        return await self._request("DELETE", f"/core/v1/domains/{domain_name}/records/{record_id}")

    async def get_order(self, order_id: int) -> dict[str, Any]:
        """GET /core/v1/orders/{orderId} — fetch order details, including order item ids.

        Returns:
            dict matching `Order`, including an `orderItems` list (each with an `isRefundable`
            flag) — used to find the item id to pass to `refund_order_items`.
        """
        return await self._request("GET", f"/core/v1/orders/{order_id}")

    async def refund_order_items(self, order_id: int, order_item_ids: list[int]) -> dict[str, Any]:
        """POST /core/v1/refund — delete eligible domains/security products and refund them.

        Per the spec, `isRefundable` (from `get_order`) is only true for orders name.com
        considers invalid or fraudulent, not simply "within the Add Grace Period" — a normal
        registration is generally not eligible.

        Returns:
            dict matching `RefundResponse`.
        """
        body = {"orderId": order_id, "orderItemIds": order_item_ids}
        return await self._request("POST", "/core/v1/refund", json=body)

    @time_it
    async def _attempt(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None,
        params: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Issue exactly one HTTP call and log its outcome. Raises NameComAPIError on failure."""
        headers = {"Content-Type": "application/json"} if json is not None else None
        logger.info(
            "name.com API request: environment=%s method=%s path=%s body=%s",
            self.environment, method, path, json,
        )
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    json=json,
                    params=params,
                    headers=headers,
                    auth=self._auth,
                )

            if response.status_code == 204:
                logger.info(
                    "name.com API response: environment=%s method=%s path=%s status=204",
                    self.environment, method, path,
                )
                return None

            if response.is_error:
                body = response.json() if response.content else {}
                rate_limit_reset = None
                if response.status_code == 429:
                    reset_header = response.headers.get("x-ratelimit-reset")
                    rate_limit_reset = int(reset_header) if reset_header else None
                raise NameComAPIError(
                    status_code=response.status_code,
                    message=body.get("message", response.text),
                    details=body.get("details"),
                    rate_limit_reset=rate_limit_reset,
                )

            body = response.json()
            logger.info(
                "name.com API response: environment=%s method=%s path=%s status=%s body=%s",
                self.environment, method, path, response.status_code, body,
            )
            return body
        except Exception:
            logger.exception(
                "name.com API request failed: environment=%s method=%s path=%s",
                self.environment, method, path,
            )
            raise
