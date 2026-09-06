"""Orchestration layer — the only module that calls both name_client.py and acme_client.py.

Each public function returns a uniform status envelope, {step, status, detail, data}, instead of
raising, so callers (the Gradio UI) can render success/failure without wrapping every call in
their own try/except.
"""

import logging
from typing import Any

import config
from acme_client import provision_certificate, revoke_certificate
from name_client import NameComAPIError, NameComClient
from time_it import time_it

logger = logging.getLogger(__name__)


async def _run_step(step: str, coro) -> dict[str, Any]:
    try:
        data = await coro
        return {"step": step, "status": "success", "detail": None, "data": data}
    except Exception as error:
        logger.exception("pipeline step failed: %s", step)
        return {"step": step, "status": "error", "detail": str(error), "data": None}


async def run_hello(environment: str) -> dict[str, Any]:
    """Check connectivity/credentials for one environment (the "Test Connection" action)."""
    client = NameComClient(environment)
    return await _run_step("hello", client.hello())


@time_it
async def run_search(keyword: str, tld_filter: list[str] | None = None) -> dict[str, Any]:
    """Search for domain suggestions in the sandbox — free, no purchase risk."""
    client = NameComClient("sandbox")
    return await _run_step("search", client.search(keyword, tld_filter=tld_filter))


@time_it
async def run_register(
    domain_name: str,
    purchase_type: str = "registration",
    purchase_price: float | None = None,
) -> dict[str, Any]:
    """Register domain_name: re-verify availability, then create.

    Sandbox by default — a mock purchase, no real money, no real domain. If
    config.NAMECOM_ALLOW_PRODUCTION_REGISTRATION is set, registers against production instead,
    spending real money on whichever credentials are configured. Defaults to off so this app
    never risks a real purchase unless a deployer deliberately opts in with their own production
    credentials — never enabled for the copy this project's own owner deploys.
    """
    environment = "production" if config.NAMECOM_ALLOW_PRODUCTION_REGISTRATION else "sandbox"
    if environment == "production":
        logger.warning(
            "NAMECOM_ALLOW_PRODUCTION_REGISTRATION is set — registering %s for REAL money",
            domain_name,
        )

    async def _do():
        client = NameComClient(environment)
        availability = await client.check_availability([domain_name], purchase_type=purchase_type)
        result = availability["results"][0]
        if not result.get("purchasable"):
            # note: registering the same name twice returns no reason
            reason = result.get("reason") or ""
            if reason:
                reason = f":{reason}"
            raise ValueError(f"{domain_name} is no longer purchasable {reason}".strip())
        response = await client.create_domain(
            domain_name, purchase_type=purchase_type, purchase_price=purchase_price
        )
        return {**response, "environment": environment}

    return await _run_step("register", _do())


@time_it
async def run_unregister(order_id: int, environment: str) -> dict[str, Any]:
    """Attempt to refund/delete a domain via name.com's Add Grace Period refund. Not wired into
    the UI: per the spec, `isRefundable` only applies to orders name.com flags as invalid or
    fraudulent, so a normal registration is never eligible and this never actually frees the
    domain.
    """
    async def _do():
        client = NameComClient(environment)
        order = await client.get_order(order_id)
        refundable_ids = [item["id"] for item in order["orderItems"] if item["isRefundable"]]
        if not refundable_ids:
            raise ValueError(
                "Nothing eligible for refund on this order — likely outside the Add Grace "
                "Period (~5 days) or already refunded."
            )
        return await client.refund_order_items(order_id, refundable_ids)

    return await _run_step("unregister", _do())


@time_it
async def run_map_a_record(domain_name: str, host: str, ip_address: str, environment: str) -> dict[str, Any]:
    """Create an A record pointing host.domain_name at ip_address.

    environment is explicit (no default) so callers can't accidentally point the wrong domain's
    real DNS at something by relying on an assumed default.
    """
    async def _do():
        client = NameComClient(environment)
        try:
            return await client.create_record(
                domain_name, host=host, type_="A", answer=ip_address, ttl=300
            )
        except NameComAPIError as error:
            # Per the spec, CreateRecord's 404 specifically means "the domain could not be
            # located" — not a record-not-found or anything else, so it's safe to translate here.
            if error.status_code == 404:
                raise ValueError(f"Domain {domain_name} not found in name.com ({environment})") from error
            raise

    return await _run_step("map_a_record", _do())


@time_it
async def run_provision_ssl(domain_name: str) -> dict[str, Any]:
    """Provision a Let's Encrypt certificate via DNS-01.

    domain_name must be a real domain registered on name.com production — sandbox zones aren't
    publicly resolvable, so DNS-01 can never succeed against one. Not restricted to a single
    fixed domain: any real name.com-registered domain works, same as run_map_a_record.
    """
    return await _run_step("provision_ssl", provision_certificate(domain_name))


@time_it
async def run_revoke_ssl(domain_name: str) -> dict[str, Any]:
    """Revoke a previously issued certificate for domain_name."""
    return await _run_step("revoke_ssl", revoke_certificate(domain_name))


@time_it
async def run_cleanup(domain_name: str, record_id: int, environment: str) -> dict[str, Any]:
    """Delete a DNS record."""
    client = NameComClient(environment)
    return await _run_step("cleanup", client.delete_record(domain_name, record_id))
