"""Cloud Services MCP server -- Google Cloud (Storage, BigQuery), AWS (S3), Azure (Blob). Read-only.

Provider SDKs are optional extras (pip install -e ".[gcp,aws,azure]") and credentials come from the
usual places (gcloud ADC, AWS profile/env, AZURE_STORAGE_CONNECTION_STRING). Cloud writes are
deliberately not exposed: add them as separate, approval-gated tools when you need them.
"""
from __future__ import annotations

import importlib.util
import os

from ..security import assert_read_only
from ._common import READ_EXTERNAL, make_server, truncate

mcp = make_server("cloud", "Inspect cloud resources (read-only): GCS/BigQuery, S3 and Azure Blob.")


def _need(module: str, extra: str):
    try:
        return __import__(module, fromlist=["_"])
    except ImportError as exc:
        raise ValueError(f"Missing SDK '{module}'. Install it with: pip install -e \".[{extra}]\"") from exc


def _text(data: bytes, limit: int) -> str:
    if b"\x00" in data[:2048]:
        raise ValueError("Object looks binary; only text objects can be read.")
    return truncate(data.decode("utf-8", errors="replace"), limit)


@mcp.tool(annotations=READ_EXTERNAL)
def cloud_status() -> str:
    """Show which cloud SDKs are installed and which credentials/env vars are configured."""
    mods = {"gcp": "google.cloud.storage", "bigquery": "google.cloud.bigquery", "aws": "boto3", "azure": "azure.storage.blob"}
    lines = []
    for name, mod in mods.items():
        try:
            installed = importlib.util.find_spec(mod) is not None
        except ModuleNotFoundError:
            installed = False
        lines.append(f"{name}: sdk {'installed' if installed else 'NOT installed'}")
    lines.append(f"GOOGLE_CLOUD_PROJECT={'set' if os.environ.get('GOOGLE_CLOUD_PROJECT') else 'unset'}")
    lines.append(f"AWS credentials env/profile={'set' if (os.environ.get('AWS_ACCESS_KEY_ID') or os.environ.get('AWS_PROFILE')) else 'unset'}")
    lines.append(f"AZURE_STORAGE_CONNECTION_STRING={'set' if os.environ.get('AZURE_STORAGE_CONNECTION_STRING') else 'unset'}")
    return "\n".join(lines)


# ----------------------------------------------------------------------- Google Cloud
def _gcs():
    return _need("google.cloud.storage", "gcp").Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT") or None)


@mcp.tool(annotations=READ_EXTERNAL)
def gcs_list_buckets() -> str:
    """List Google Cloud Storage buckets in the configured project."""
    return "\n".join(b.name for b in _gcs().list_buckets(max_results=100)) or "(no buckets)"


@mcp.tool(annotations=READ_EXTERNAL)
def gcs_list_objects(bucket: str, prefix: str = "", limit: int = 50) -> str:
    """List objects in a Cloud Storage bucket."""
    blobs = _gcs().list_blobs(bucket, prefix=prefix or None, max_results=max(1, min(limit, 200)))
    return "\n".join(f"{b.name}  ({b.size:,} bytes)" for b in blobs) or "(no objects)"


@mcp.tool(annotations=READ_EXTERNAL)
def gcs_read_object(bucket: str, name: str, max_chars: int = 12000) -> str:
    """Read a text object from Cloud Storage."""
    blob = _gcs().bucket(bucket).blob(name)
    return _text(blob.download_as_bytes(end=max_chars * 4), max_chars)


def _bq():
    return _need("google.cloud.bigquery", "gcp").Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT") or None)


@mcp.tool(annotations=READ_EXTERNAL)
def bq_list_datasets() -> str:
    """List BigQuery datasets in the configured project."""
    return "\n".join(d.dataset_id for d in _bq().list_datasets()) or "(no datasets)"


@mcp.tool(annotations=READ_EXTERNAL)
def bq_estimate_cost(sql: str) -> str:
    """Dry-run a BigQuery SELECT and report how many bytes it would scan (no cost incurred)."""
    bigquery = _need("google.cloud.bigquery", "gcp")
    job = _bq().query(assert_read_only(sql), job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False))
    return f"This query would process {job.total_bytes_processed:,} bytes (~{job.total_bytes_processed / 1e9:.3f} GB)."


@mcp.tool(annotations=READ_EXTERNAL)
def bq_query(sql: str, max_rows: int = 50) -> str:
    """Run a read-only BigQuery SELECT. Queries are capped at BQ_MAX_BYTES billed (default 1 GB)."""
    bigquery = _need("google.cloud.bigquery", "gcp")
    cfg = bigquery.QueryJobConfig(maximum_bytes_billed=int(os.environ.get("BQ_MAX_BYTES", 1_000_000_000)))
    rows = _bq().query(assert_read_only(sql), job_config=cfg).result(max_results=max(1, min(max_rows, 200)))
    cols = [f.name for f in rows.schema]
    lines = [" | ".join(cols)] + [" | ".join(str(r[c]) for c in cols) for r in rows]
    return "\n".join(lines)


# -------------------------------------------------------------------------------- AWS
def _s3():
    return _need("boto3", "aws").client("s3")


@mcp.tool(annotations=READ_EXTERNAL)
def s3_list_buckets() -> str:
    """List S3 buckets."""
    return "\n".join(b["Name"] for b in _s3().list_buckets()["Buckets"]) or "(no buckets)"


@mcp.tool(annotations=READ_EXTERNAL)
def s3_list_objects(bucket: str, prefix: str = "", limit: int = 50) -> str:
    """List objects in an S3 bucket."""
    resp = _s3().list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=max(1, min(limit, 200)))
    return "\n".join(f"{o['Key']}  ({o['Size']:,} bytes)" for o in resp.get("Contents", [])) or "(no objects)"


@mcp.tool(annotations=READ_EXTERNAL)
def s3_read_object(bucket: str, key: str, max_chars: int = 12000) -> str:
    """Read a text object from S3."""
    body = _s3().get_object(Bucket=bucket, Key=key, Range=f"bytes=0-{max_chars * 4}")["Body"].read()
    return _text(body, max_chars)


# ------------------------------------------------------------------------------ Azure
def _azure():
    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not conn:
        raise ValueError("AZURE_STORAGE_CONNECTION_STRING is not configured.")
    return _need("azure.storage.blob", "azure").BlobServiceClient.from_connection_string(conn)


@mcp.tool(annotations=READ_EXTERNAL)
def azure_list_containers() -> str:
    """List Azure Blob Storage containers."""
    return "\n".join(c.name for c in _azure().list_containers()) or "(no containers)"


@mcp.tool(annotations=READ_EXTERNAL)
def azure_list_blobs(container: str, prefix: str = "", limit: int = 50) -> str:
    """List blobs in an Azure container."""
    out = []
    for b in _azure().get_container_client(container).list_blobs(name_starts_with=prefix or None):
        out.append(f"{b.name}  ({b.size:,} bytes)")
        if len(out) >= max(1, min(limit, 200)):
            break
    return "\n".join(out) or "(no blobs)"


@mcp.tool(annotations=READ_EXTERNAL)
def azure_read_blob(container: str, name: str, max_chars: int = 12000) -> str:
    """Read a text blob from Azure Blob Storage."""
    data = _azure().get_blob_client(container, name).download_blob(offset=0, length=max_chars * 4).readall()
    return _text(data, max_chars)


if __name__ == "__main__":
    mcp.run()
