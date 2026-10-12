"""Daily VELO certificate maintenance; stdlib only, no private-key access."""

import copy
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import http.client
import json
import os
import time

DOMAINS = ("weiluai.top", "www.weiluai.top")
REGION = "ap-guangzhou"
RENEW_BEFORE = timedelta(days=25)
PENDING_MAX_AGE = timedelta(days=3)
PENDING_STATUSES = {0, 4, 5, 6, 8, 9, 11, 12, 13, 15}
FAILED_STATUSES = {2, 7, 10, 14}
PAGE_SIZE = 100
MAX_PAGES = 5
MAX_API_CALLS = 16
API_TIMEOUT = 5
MAX_API_RESPONSE = 4_000_000
VERSIONS = {"ssl": "2019-12-05", "scf": "2018-04-16"}
ACTIONS = {"ssl": {"ApplyCertificate", "DescribeCertificates"}, "scf": {"GetCustomDomain", "UpdateCustomDomain"}}
ALIAS_PREFIX = "velo-scf-tls:"
CST = timezone(timedelta(hours=8))


class RenewalError(RuntimeError):
    """Only fixed, non-sensitive messages may be put in this exception."""


def _canonical_request(host, action, payload):
    headers = f"content-type:application/json; charset=utf-8\nhost:{host}\nx-tc-action:{action.lower()}\n"
    return "POST\n/\n\n" + headers + "\ncontent-type;host;x-tc-action\n" + hashlib.sha256(payload).hexdigest()


def _authorization(service, action, payload, secret_id, secret_key, timestamp):
    date = datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d")
    scope = f"{date}/{service}/tc3_request"
    canonical = _canonical_request(service + ".tencentcloudapi.com", action, payload)
    to_sign = f"TC3-HMAC-SHA256\n{timestamp}\n{scope}\n" + hashlib.sha256(canonical.encode()).hexdigest()
    key = ("TC3" + secret_key).encode()
    for value in (date, service, "tc3_request"):
        key = hmac.new(key, value.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    return f"TC3-HMAC-SHA256 Credential={secret_id}/{scope}, SignedHeaders=content-type;host;x-tc-action, Signature={signature}"


class CloudClient:
    def __init__(self):
        self.calls = 0
        # Read fresh STS credentials on every invocation; never print or cache them.
        self._credentials = tuple(os.environ.get(name) for name in (
            "TENCENTCLOUD_SECRETID", "TENCENTCLOUD_SECRETKEY", "TENCENTCLOUD_SESSIONTOKEN",
        ))
        if not all(self._credentials):
            raise RenewalError("SCF temporary execution-role credentials are missing")

    def call(self, service, action, parameters):
        if action not in ACTIONS.get(service, set()):
            raise RenewalError("Cloud API action is outside the allowlist")
        if service == "scf" and parameters.get("Domain") not in DOMAINS:
            raise RenewalError("Custom domain is outside the allowlist")
        if action == "ApplyCertificate" and (
            parameters.get("DomainName") != DOMAINS[0]
            or parameters.get("DvAuthMethod") != "DNS_AUTO"
            or parameters.get("PackageType") != "83"
            or parameters.get("ValidityPeriod") != "3"
            or set(parameters) - {"DomainName", "DvAuthMethod", "PackageType", "ValidityPeriod", "Alias", "OldCertificateId"}
        ):
            raise RenewalError("Certificate application is outside the free-certificate allowlist")
        self.calls += 1
        if self.calls > MAX_API_CALLS:
            raise RenewalError("Cloud API call budget exhausted")
        connection = None
        try:
            secret_id, secret_key, token = self._credentials
            payload = json.dumps(parameters, ensure_ascii=True, separators=(",", ":")).encode("ascii")
            timestamp = int(time.time())
            host = service + ".tencentcloudapi.com"
            headers = {
                "Content-Type": "application/json; charset=utf-8", "Host": host,
                "X-TC-Action": action, "X-TC-Version": VERSIONS[service],
                "X-TC-Timestamp": str(timestamp), "X-TC-Token": token,
                "Authorization": _authorization(service, action, payload, secret_id, secret_key, timestamp),
            }
            if service == "scf":
                headers["X-TC-Region"] = REGION
            # HTTPSConnection validates TLS and does not follow redirects.
            connection = http.client.HTTPSConnection(host, timeout=API_TIMEOUT)
            connection.request("POST", "/", body=payload, headers=headers)
            response = connection.getresponse()
            raw = response.read(MAX_API_RESPONSE + 1)
            if response.status != 200 or len(raw) > MAX_API_RESPONSE:
                raise ValueError("HTTP failure")
            data = json.loads(raw)["Response"]
            if not isinstance(data, dict) or "Error" in data:
                raise ValueError("API failure")
            return data
        except Exception:
            # API bodies and transport exceptions may contain credentials; do not echo them.
            raise RenewalError(f"Cloud API {service}.{action} failed; inspect the cloud API audit") from None
        finally:
            if connection is not None:
                connection.close()


def _date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=CST)
    except (TypeError, ValueError):
        raise RenewalError("Certificate metadata has an invalid GMT+8 timestamp") from None


def _certificate_id(certificate):
    value = certificate.get("CertificateId")
    if not isinstance(value, str) or not value:
        raise RenewalError("Certificate metadata has no certificate ID")
    return value


def _list_certificates(client, filters):
    certificates = {}
    expected_total = None
    offset = 0
    for _ in range(MAX_PAGES):
        response = client.call("ssl", "DescribeCertificates", {
            "CertificateType": "SVR", "Limit": PAGE_SIZE, "Offset": offset, **filters,
        })
        rows, total = response.get("Certificates"), response.get("TotalCount")
        if not isinstance(rows, list) or not isinstance(total, int) or total < 0 or len(rows) > PAGE_SIZE:
            raise RenewalError("Certificate listing returned an invalid page")
        if expected_total is not None and total != expected_total:
            raise RenewalError("Certificate listing changed during pagination; retry next run")
        expected_total = total
        for certificate in rows:
            if not isinstance(certificate, dict):
                raise RenewalError("Certificate listing returned invalid metadata")
            cert_id = _certificate_id(certificate)
            if cert_id in certificates:
                raise RenewalError("Certificate listing repeated an ID; refusing an incomplete snapshot")
            certificates[cert_id] = certificate
        offset += len(rows)
        if offset == total:
            return certificates
        if not rows or offset > total:
            raise RenewalError("Certificate listing is incomplete")
    raise RenewalError("Certificate listing exceeded the bounded page limit")


def _domain_snapshot(client, domain):
    if domain not in DOMAINS:
        raise RenewalError("Custom domain is outside the allowlist")
    snapshot = client.call("scf", "GetCustomDomain", {"Domain": domain})
    snapshot = {key: copy.deepcopy(value) for key, value in snapshot.items() if key != "RequestId"}
    if (set(snapshot) - {"Domain", "Protocol", "CertConfig", "EndpointsConfig", "WafConfig", "Tags"}
            or snapshot.get("Domain") != domain
            or snapshot.get("Protocol") not in {"HTTPS", "HTTP&HTTPS"}
            or not isinstance(snapshot.get("EndpointsConfig"), list)
            or not snapshot["EndpointsConfig"]
            or not isinstance(snapshot.get("WafConfig"), dict)
            or not isinstance(snapshot.get("CertConfig"), dict)
            or set(snapshot["CertConfig"]) != {"CertificateId"}
            or not snapshot["CertConfig"]["CertificateId"]):
        raise RenewalError("Custom domain configuration is missing, unexpected, or not HTTPS-enabled")
    return snapshot


def _origin(certificate):
    extra = certificate.get("CertificateExtra") or {}
    return extra.get("OriginCertificateId") if isinstance(extra, dict) else None


def _belongs_to_cycle(certificate, old_ids):
    return _origin(certificate) in old_ids or certificate.get("Alias") in {ALIAS_PREFIX + item for item in old_ids}


def _covers_domains(certificate):
    sans = certificate.get("SubjectAltName")
    return isinstance(sans, list) and all(isinstance(item, str) for item in sans) and set(DOMAINS) <= {item.lower().rstrip(".") for item in sans}


def _deploy(client, snapshots, current, certificate):
    candidate_id = _certificate_id(certificate)
    candidate_end = _date(certificate.get("CertEndTime"))
    updated = []
    for domain in DOMAINS:
        before = snapshots[domain]
        old_id = before["CertConfig"]["CertificateId"]
        if old_id == candidate_id or candidate_end <= _date(current[old_id].get("CertEndTime")):
            continue
        # No conditional-write API exists: detect changes immediately before writing.
        if _domain_snapshot(client, domain) != before:
            raise RenewalError("Custom domain changed concurrently; refusing to overwrite it")
        expected = copy.deepcopy(before)
        expected["CertConfig"]["CertificateId"] = candidate_id
        # Replay documented mutable configuration; do not assume omitted fields are PATCHes.
        parameters = {key: expected[key] for key in ("Domain", "Protocol", "CertConfig", "EndpointsConfig", "WafConfig")}
        client.call("scf", "UpdateCustomDomain", parameters)
        if _domain_snapshot(client, domain) != expected:
            raise RenewalError("Custom domain verification failed after certificate update")
        updated.append(domain)
    return {"status": "updated", "domains": updated}


def renew(client, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise RenewalError("Current time must be timezone-aware")
    snapshots = {domain: _domain_snapshot(client, domain) for domain in DOMAINS}
    old_ids = {snapshot["CertConfig"]["CertificateId"] for snapshot in snapshots.values()}
    current = _list_certificates(client, {"CertIds": sorted(old_ids)})
    if set(current) != old_ids or any(cert.get("Status") not in {1, 3} for cert in current.values()):
        raise RenewalError("A deployed certificate is missing, revoked, or not issued")
    earliest = min(current.values(), key=lambda certificate: _date(certificate.get("CertEndTime")))
    earliest_end = _date(earliest.get("CertEndTime"))
    if earliest_end - now > RENEW_BEFORE:
        return {"status": "healthy"}
    records = _list_certificates(client, {"SearchKey": DOMAINS[0]})
    relevant = [certificate for certificate in records.values()
                if certificate.get("Domain", "").lower().rstrip(".") == DOMAINS[0]]
    candidates = []
    invalid_issued = False
    unready_issued = False
    for certificate in relevant:
        if certificate.get("Status") != 1:
            continue
        valid = (_covers_domains(certificate)
                 and _date(certificate.get("CertBeginTime")) <= now
                 and _date(certificate.get("CertEndTime")) > max(earliest_end, now + RENEW_BEFORE))
        if valid:
            # The API defines a Boolean; absence/null/truthy strings are not proof.
            if certificate.get("Deployable") is True:
                candidates.append(certificate)
            else:
                unready_issued = True
        elif _certificate_id(certificate) not in old_ids and _belongs_to_cycle(certificate, old_ids):
            invalid_issued = True
    if candidates:
        best = max(candidates, key=lambda certificate: (_date(certificate["CertEndTime"]), _certificate_id(certificate)))
        return _deploy(client, snapshots, current, best)
    if unready_issued:
        raise RenewalError("Issued certificate is not confirmed deployable; refusing a duplicate application")
    if invalid_issued:
        raise RenewalError("Issued renewal has wrong SANs, is not yet valid, or does not extend validity safely")
    pending = [certificate for certificate in relevant if certificate.get("Status") in PENDING_STATUSES]
    if pending:
        if (earliest_end - now <= timedelta(days=7)
                or any(now - _date(cert.get("InsertTime")) > PENDING_MAX_AGE for cert in pending)):
            raise RenewalError("Certificate issuance is pending too long or deployed expiry is urgent")
        return {"status": "pending", "orders": len(pending)}
    if any(certificate.get("Status") in FAILED_STATUSES and _belongs_to_cycle(certificate, old_ids) for certificate in relevant):
        raise RenewalError("Renewal order failed or was cancelled; manual review is required")
    if any(certificate.get("Status") not in {1, 2, 3, 7, 10, 14} for certificate in relevant):
        raise RenewalError("Certificate status is unknown; refusing a duplicate application")
    old_id = _certificate_id(earliest)
    parameters = {
        "DomainName": DOMAINS[0], "DvAuthMethod": "DNS_AUTO", "PackageType": "83",
        "ValidityPeriod": "3", "Alias": ALIAS_PREFIX + old_id,
    }
    if now < earliest_end <= now + timedelta(days=30):
        parameters["OldCertificateId"] = old_id
    result = client.call("ssl", "ApplyCertificate", parameters)
    _certificate_id(result)
    if earliest_end <= now:
        raise RenewalError("Replacement requested, but a deployed certificate is already expired")
    return {"status": "requested"}


def main_handler(event, context):
    # Event content cannot select domains, regions, actions, or credentials.
    try:
        return renew(CloudClient())
    except RenewalError:
        raise
    except Exception:
        raise RenewalError("Certificate maintenance failed; inspect the cloud API audit") from None
