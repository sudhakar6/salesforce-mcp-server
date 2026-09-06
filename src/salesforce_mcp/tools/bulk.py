from __future__ import annotations

import asyncio
import csv
import io
from collections.abc import Callable

from mcp.server.mcpserver import Context, MCPServer

from ..elicitation import confirm
from ..errors import SalesforceApiError, as_tool_error, raise_for_salesforce_error
from ..salesforce_client import SalesforceClient

TERMINAL_STATES = {"JobComplete", "Failed", "Aborted"}
POLL_INTERVAL_SECONDS = 2.0
MAX_POLL_ATTEMPTS = 30  # ~1 minute; sized for practice-scale jobs, not huge data loads
QUERY_PAGE_SIZE = 50_000
SUPPORTED_LOAD_OPERATIONS = {"insert", "update", "upsert", "delete"}


def _records_to_csv(records: list[dict]) -> str:
    fieldnames: list[str] = []
    for record in records:
        for key in record:
            if key not in fieldnames:
                fieldnames.append(key)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    return buffer.getvalue()


def _csv_to_records(csv_text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(csv_text)))


async def _poll_job(client: SalesforceClient, path: str) -> dict:
    for _ in range(MAX_POLL_ATTEMPTS):
        response = await client.request("GET", path)
        raise_for_salesforce_error(response)
        job = response.json()
        if job.get("state") in TERMINAL_STATES:
            return job
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
    raise SalesforceApiError(408, f"Bulk job at {path} did not complete within the polling window")


def register(
    mcp: MCPServer, get_client: Callable[[], SalesforceClient], elicitation_enabled: bool
) -> dict[str, Callable]:
    @mcp.tool()
    @as_tool_error
    async def sf_bulk_query(soql: str) -> dict:
        """Run a SOQL query via Bulk API 2.0, for result sets too large for sf_query.

        Slower (job-based, polls until complete) but not subject to sf_query's
        interactive per-request limits. Prefer sf_query for everyday lookups;
        reach for this when you expect a very large result set.
        """
        client = get_client()
        response = await client.request("POST", "/jobs/query", json={"operation": "query", "query": soql})
        raise_for_salesforce_error(response)
        job = response.json()

        job = await _poll_job(client, f"/jobs/query/{job['id']}")
        if job["state"] != "JobComplete":
            raise SalesforceApiError(422, f"Bulk query job {job['id']} ended in state {job['state']}")

        records: list[dict] = []
        locator = None
        while True:
            params = {"maxRecords": QUERY_PAGE_SIZE}
            if locator:
                params["locator"] = locator
            response = await client.request("GET", f"/jobs/query/{job['id']}/results", params=params)
            raise_for_salesforce_error(response)
            records.extend(_csv_to_records(response.text))
            locator = response.headers.get("Sforce-Locator")
            if not locator or locator == "null":
                break

        return {
            "job_id": job["id"],
            "record_count": job.get("numberRecordsProcessed", len(records)),
            "records": records,
        }

    @mcp.tool()
    @as_tool_error
    async def sf_bulk_load(
        sobject: str,
        operation: str,
        records: list[dict],
        external_id_field: str | None = None,
        ctx: Context | None = None,
    ) -> dict:
        """Insert/update/upsert/delete a batch of records via Bulk API 2.0.

        Use for record volumes too large for sf_create_record/sf_update_record's
        one-record-per-call REST endpoints. `operation` is one of "insert",
        "update", "upsert", "delete". `external_id_field` is required for
        "upsert". For "delete", each record dict needs only an "Id" key.

        A "delete" operation always asks for confirmation first via MCP
        Elicitation — it's irreversible — disable with
        SF_ELICITATION_ENABLED=false. insert/update/upsert are unaffected.
        """
        if operation not in SUPPORTED_LOAD_OPERATIONS:
            allowed = sorted(SUPPORTED_LOAD_OPERATIONS)
            raise ValueError(f"Unsupported bulk operation {operation!r}; expected one of {allowed}")
        if operation == "upsert" and not external_id_field:
            raise ValueError("external_id_field is required for the upsert operation")
        if not records:
            raise ValueError("records must not be empty")

        if operation == "delete":
            proceed = await confirm(
                ctx,
                f"Bulk-delete {len(records)} {sobject} record(s)? This cannot be undone.",
                enabled=elicitation_enabled,
            )
            if not proceed:
                return {"executed": False, "reason": "Declined confirmation for a bulk delete."}

        client = get_client()
        job_body: dict = {"object": sobject, "operation": operation, "lineEnding": "LF"}
        if external_id_field:
            job_body["externalIdFieldName"] = external_id_field

        response = await client.request("POST", "/jobs/ingest", json=job_body)
        raise_for_salesforce_error(response)
        job_id = response.json()["id"]

        upload = await client.request(
            "PUT",
            f"/jobs/ingest/{job_id}/batches",
            content=_records_to_csv(records).encode("utf-8"),
            headers={"Content-Type": "text/csv"},
        )
        raise_for_salesforce_error(upload)

        close = await client.request("PATCH", f"/jobs/ingest/{job_id}", json={"state": "UploadComplete"})
        raise_for_salesforce_error(close)

        job = await _poll_job(client, f"/jobs/ingest/{job_id}")

        failed_response = await client.request("GET", f"/jobs/ingest/{job_id}/failedResults")
        raise_for_salesforce_error(failed_response)
        failures = _csv_to_records(failed_response.text)

        return {
            "job_id": job_id,
            "state": job["state"],
            "records_processed": job.get("numberRecordsProcessed", 0),
            "records_failed": job.get("numberRecordsFailed", len(failures)),
            "failures": failures,
        }

    return {"sf_bulk_query": sf_bulk_query, "sf_bulk_load": sf_bulk_load}
