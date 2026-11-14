"""
Tests whether the Cloudflare R2 settings in backend/.env are actually valid.

It does not just check that the values are present - it connects to R2 with
them and proves, step by step, what works:

  1. the four required settings are present and look well-formed
  2. the endpoint host resolves and answers
  3. the access key + secret are accepted (signature check)
  4. the bucket exists and the key may use it
  5. the key can list objects
  6. the key can write, read back and delete an object (a tiny throwaway file
     under "_healthcheck/", removed again at the end)
  7. a presigned upload URL - the same kind the app hands to the browser -
     really works from this machine
  8. (informational) whether the bucket has a CORS rule, which browser
     uploads need

Usage (from the backend folder, venv active):
    python scripts/check_r2.py              # full check, includes the throwaway write
    python scripts/check_r2.py --read-only  # never writes anything (skips steps 6 and 7)

Reads only the R2_* values from backend/.env (and from real environment
variables, which win if both are set). It needs no database and no other
setting, so it runs even if the rest of .env is incomplete. Secrets are never
printed - only whether they are present and how long they are.

Exit code 0 = everything required passed, 1 = something failed.
"""

import argparse
import os
import re
import socket
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlparse

BACKEND_DIR = Path(__file__).resolve().parent.parent

RESULTS: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str) -> str:
    RESULTS.append((status, name, detail))
    print(f"[{status}] {name}\n       {detail}")
    return status


def load_r2_settings() -> dict[str, str]:
    values: dict[str, str] = {}
    env_file = BACKEND_DIR / ".env"
    if env_file.exists():
        try:
            from dotenv import dotenv_values

            for key, val in dotenv_values(env_file).items():
                if key.upper().startswith("R2_") and val is not None:
                    values[key.upper()] = val
        except ImportError:
            pass
    for key, val in os.environ.items():  # real environment wins, like the app
        if key.upper().startswith("R2_"):
            values[key.upper()] = val
    return values


def describe_client_error(exc) -> tuple[str, str]:
    """Returns (code, human explanation) for a botocore ClientError."""
    err = exc.response.get("Error", {})
    code = str(err.get("Code", "")) or "Unknown"
    status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", "?")
    hints = {
        "InvalidAccessKeyId": "R2_ACCESS_KEY_ID is not a known key. Re-copy it from the R2 API token page.",
        "SignatureDoesNotMatch": "R2_SECRET_ACCESS_KEY is wrong for this access key (or has stray spaces/quotes).",
        "AccessDenied": "The key is valid but has no permission for this action. Give the API token "
        "'Object Read & Write' on this bucket.",
        "NoSuchBucket": "No bucket with this name in this account. Check R2_BUCKET and R2_ACCOUNT_ID.",
        "404": "Bucket not found. Check R2_BUCKET and R2_ACCOUNT_ID.",
        "403": "The key was rejected or has no permission on this bucket.",
        "401": "The key was rejected.",
    }
    label = f"HTTP {status}" if code == str(status) else f"HTTP {status} {code}"
    return code, f"{label}: " + hints.get(code, str(err.get("Message", "")) or "see code above")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the R2 settings in backend/.env against the real R2 service.")
    parser.add_argument("--read-only", action="store_true", help="never write anything to the bucket")
    args = parser.parse_args()

    print("R2 settings check" + ("  (read-only)" if args.read_only else ""))
    print("=" * 60)

    cfg = load_r2_settings()
    account = cfg.get("R2_ACCOUNT_ID", "").strip()
    key_id = cfg.get("R2_ACCESS_KEY_ID", "").strip()
    secret = cfg.get("R2_SECRET_ACCESS_KEY", "")
    bucket = cfg.get("R2_BUCKET", "").strip()
    endpoint_override = cfg.get("R2_ENDPOINT_URL", "").strip()
    try:
        presign_ttl = int(cfg.get("R2_PRESIGN_TTL_SECONDS", "900") or 900)
    except ValueError:
        presign_ttl = -1

    # ------------------------------------------------------------ 1. presence + format
    missing = [n for n, v in (("R2_ACCOUNT_ID", account), ("R2_ACCESS_KEY_ID", key_id),
                              ("R2_SECRET_ACCESS_KEY", secret), ("R2_BUCKET", bucket)) if not v]
    if missing:
        record("FAIL", "Required settings present", f"Not set: {', '.join(missing)}. Add them to backend/.env.")
        return finish()
    record("PASS", "Required settings present",
           f"all four set (access key id {len(key_id)} chars, secret {len(secret)} chars - values not shown)")

    problems: list[str] = []
    if secret != secret.strip() or secret.startswith(("'", '"')) or secret.endswith(("'", '"')):
        problems.append("R2_SECRET_ACCESS_KEY has leading/trailing spaces or quote marks")
    if not re.fullmatch(r"[0-9a-fA-F]{32}", account) and not endpoint_override:
        problems.append("R2_ACCOUNT_ID is normally 32 hex characters (find it on the R2 overview page)")
    if len(key_id) != 32:
        problems.append(f"R2_ACCESS_KEY_ID is normally 32 characters (yours: {len(key_id)})")
    if len(secret.strip()) != 64:
        problems.append(f"R2_SECRET_ACCESS_KEY is normally 64 characters (yours: {len(secret.strip())})")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
        problems.append("R2_BUCKET must be 3-63 chars: lowercase letters, digits, '-' or '.'")
    if "/" in bucket or bucket.startswith("http"):
        problems.append("R2_BUCKET must be just the bucket name, not a URL or path")
    if endpoint_override:
        parsed = urlparse(endpoint_override)
        if parsed.scheme != "https" or not parsed.netloc:
            problems.append("R2_ENDPOINT_URL must look like https://<account>.r2.cloudflarestorage.com")
        elif parsed.path not in ("", "/"):
            problems.append("R2_ENDPOINT_URL must not include the bucket name or any path")
    if presign_ttl < 60:
        problems.append("R2_PRESIGN_TTL_SECONDS must be a number of at least 60")
    if problems:
        record("WARN", "Settings look well-formed", "; ".join(problems) + ". (Formats are a hint - the live checks below decide.)")
    else:
        record("PASS", "Settings look well-formed", "lengths and characters are what R2 normally issues")

    endpoint = endpoint_override or f"https://{account}.r2.cloudflarestorage.com"
    host = urlparse(endpoint).hostname or ""

    # ------------------------------------------------------------ 2. network
    try:
        boto3_mod = __import__("boto3")
        botocore_config = __import__("botocore.config", fromlist=["Config"])
        botocore_exc = __import__("botocore.exceptions", fromlist=["ClientError"])
    except ImportError:
        record("FAIL", "boto3 installed", "boto3 is missing. Run: pip install -r requirements.txt")
        return finish()
    ClientError = botocore_exc.ClientError
    record("PASS", "boto3 installed", f"boto3 {boto3_mod.__version__}")

    try:
        addr = socket.gethostbyname(host)
    except OSError as exc:
        record("FAIL", "Endpoint host resolves", f"Cannot resolve {host}: {exc}. Wrong R2_ACCOUNT_ID, or no internet/DNS.")
        return finish()
    record("PASS", "Endpoint host resolves", f"{host} -> {addr}")

    s3 = boto3_mod.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=key_id,
        aws_secret_access_key=secret.strip(),
        region_name="auto",
        config=botocore_config.Config(signature_version="s3v4", retries={"max_attempts": 2, "mode": "standard"},
                                      connect_timeout=10, read_timeout=20),
    )

    # ------------------------------------------------------------ 3/4. credentials + bucket
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError as exc:
        code, text = describe_client_error(exc)
        record("FAIL", "Credentials accepted and bucket reachable", text)
        return finish()
    except Exception as exc:  # noqa: BLE001 - connection errors etc.
        record("FAIL", "Credentials accepted and bucket reachable", f"{type(exc).__name__}: {exc}")
        return finish()
    record("PASS", "Credentials accepted and bucket reachable", f"bucket '{bucket}' exists and this key can open it")

    # ------------------------------------------------------------ 5. list
    try:
        resp = s3.list_objects_v2(Bucket=bucket, MaxKeys=1)
        record("PASS", "Can list objects", f"list works ({'bucket has objects' if resp.get('KeyCount') else 'bucket is empty'})")
    except ClientError as exc:
        record("WARN", "Can list objects", describe_client_error(exc)[1] + " (the app needs list for folder cleanup)")

    if args.read_only:
        record("WARN", "Write / read / delete test", "skipped (--read-only). Run without the flag to prove the key can write.")
        record("WARN", "Presigned upload URL", "skipped (--read-only).")
        return finish(cors_client=s3, bucket=bucket)

    # ------------------------------------------------------------ 6. write / read / delete
    test_key = f"_healthcheck/{uuid.uuid4().hex}.txt"
    payload = b"r2 settings check - safe to delete"
    wrote = False
    try:
        s3.put_object(Bucket=bucket, Key=test_key, Body=payload, ContentType="text/plain")
        wrote = True
        head = s3.head_object(Bucket=bucket, Key=test_key)
        body = s3.get_object(Bucket=bucket, Key=test_key)["Body"].read()
        if body != payload or head["ContentLength"] != len(payload):
            record("FAIL", "Write / read / delete test", "wrote a file but read back different content")
        else:
            record("PASS", "Write / read back", f"wrote and read {len(payload)} bytes at {test_key}")
    except ClientError as exc:
        record("FAIL", "Write / read back", describe_client_error(exc)[1])
    except Exception as exc:  # noqa: BLE001
        record("FAIL", "Write / read back", f"{type(exc).__name__}: {exc}")

    # ------------------------------------------------------------ 7. presigned PUT
    presigned_key = f"_healthcheck/{uuid.uuid4().hex}-presigned.txt"
    presigned_ok = False
    try:
        body = b"presigned upload test"
        url = s3.generate_presigned_url(
            "put_object",
            Params={"Bucket": bucket, "Key": presigned_key, "ContentType": "text/plain", "ContentLength": len(body)},
            ExpiresIn=max(presign_ttl, 60),
        )
        req = urllib.request.Request(url, data=body, method="PUT",
                                     headers={"Content-Type": "text/plain", "Content-Length": str(len(body))})
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - https URL we just built
            presigned_ok = 200 <= r.status < 300
        head = s3.head_object(Bucket=bucket, Key=presigned_key)
        if presigned_ok and head["ContentLength"] == len(body):
            record("PASS", "Presigned upload URL works", "a signed PUT URL (like the browser gets) uploaded a file successfully")
        else:
            record("FAIL", "Presigned upload URL works", "the PUT returned success but the object is not as expected")
    except urllib.error.HTTPError as exc:
        record("FAIL", "Presigned upload URL works", f"R2 rejected the signed URL: HTTP {exc.code}. {exc.read()[:200]!r}")
    except ClientError as exc:
        record("FAIL", "Presigned upload URL works", describe_client_error(exc)[1])
    except Exception as exc:  # noqa: BLE001
        record("FAIL", "Presigned upload URL works", f"{type(exc).__name__}: {exc}")

    # ------------------------------------------------------------ cleanup
    cleaned = True
    for k in (test_key, presigned_key):
        try:
            s3.delete_object(Bucket=bucket, Key=k)
            try:
                s3.head_object(Bucket=bucket, Key=k)
                cleaned = False
            except ClientError:
                pass  # gone, as intended
        except ClientError as exc:
            cleaned = False
            record("WARN", "Delete test files", f"could not delete {k}: {describe_client_error(exc)[1]}")
    if cleaned and (wrote or presigned_ok):
        record("PASS", "Delete works / test files removed", "throwaway objects deleted again")
    elif not wrote and not presigned_ok:
        pass

    return finish(cors_client=s3, bucket=bucket)


def finish(cors_client=None, bucket: str | None = None) -> int:
    if cors_client is not None and bucket:
        try:
            rules = cors_client.get_bucket_cors(Bucket=bucket).get("CORSRules", [])
            origins = sorted({o for r in rules for o in r.get("AllowedOrigins", [])})
            record("PASS", "Bucket CORS rule (browser uploads)", f"{len(rules)} rule(s); allowed origins: {', '.join(origins) or 'none'}")
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            if code == "NoSuchCORSConfiguration":
                record("WARN", "Bucket CORS rule (browser uploads)",
                       "no CORS rule is set. Browsers will be blocked from uploading until you add one "
                       "(see MULTI_STUDIO.md, 'Cloudflare R2 setup').")
            else:
                record("WARN", "Bucket CORS rule (browser uploads)",
                       "could not read it with this key (normal for object-scoped tokens). Check it in the Cloudflare dashboard.")

    print("=" * 60)
    failed = [r for r in RESULTS if r[0] == "FAIL"]
    warned = [r for r in RESULTS if r[0] == "WARN"]
    passed = [r for r in RESULTS if r[0] == "PASS"]
    print(f"{len(passed)} passed, {len(warned)} warnings, {len(failed)} failed")
    if failed:
        print("RESULT: R2 settings are NOT valid yet - fix the FAIL lines above.")
        return 1
    print("RESULT: R2 settings are valid." + (" (see warnings above)" if warned else ""))
    return 0


if __name__ == "__main__":
    code = main()
    sys.exit(code)
