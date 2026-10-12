"""Offline certificate-maintenance tests; never contact Tencent Cloud."""

import contextlib
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import traceback
import unittest
from unittest.mock import Mock, patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "deployment/scf_certificate_renewal"
NOW = datetime(2026, 10, 12, 4, 0, 0, tzinfo=timezone.utc)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


m = load("velo_renewal", DIRECTORY / "handler.py")
builder = load("velo_renewal_build", DIRECTORY / "build.py")


def date(days):
    return (NOW + timedelta(days=days)).astimezone(m.CST).strftime("%Y-%m-%d %H:%M:%S")


def certificate(identifier="old", days=20, status=1, origin=None, **overrides):
    return {
        "CertificateId": identifier, "Status": status, "Domain": m.DOMAINS[0],
        "CertificateType": "SVR", "PackageType": "83", "CertBeginTime": date(-65),
        "CertEndTime": date(days), "InsertTime": date(0 if status != 1 else -65),
        "SubjectAltName": list(m.DOMAINS), "Deployable": True, "Alias": "",
        "CertificateExtra": {"OriginCertificateId": origin}, **overrides,
    }


class FakeCloud:
    def __init__(self, certificates=None, ids=("old", "old")):
        self.certificates = certificates if certificates is not None else [certificate()]
        self.domains = {domain: {
            "Domain": domain, "Protocol": "HTTP&HTTPS", "CertConfig": {"CertificateId": identifier},
            "WafConfig": {"WafOpen": "CLOSE", "WafInstanceId": ""},
            "EndpointsConfig": [{"Namespace": "default", "FunctionName": "static-website", "Qualifier": "live", "PathMatch": "/*", "PathRewrite": []}],
            "Tags": [{"Key": "purpose", "Value": "website"}],
        } for domain, identifier in zip(m.DOMAINS, ids)}
        self.calls = []
        self.fail_www = False
        self.damage_config = False

    def call(self, service, action, parameters):
        self.calls.append((service, action, copy.deepcopy(parameters)))
        if action == "GetCustomDomain":
            return {**copy.deepcopy(self.domains[parameters["Domain"]]), "RequestId": str(len(self.calls))}
        if action == "DescribeCertificates":
            rows = self.certificates
            if "CertIds" in parameters:
                rows = [row for row in rows if row["CertificateId"] in parameters["CertIds"]]
            else:
                rows = [row for row in rows if parameters.get("SearchKey", "") in row["Domain"]]
            start, size = parameters["Offset"], parameters["Limit"]
            return {"TotalCount": len(rows), "Certificates": copy.deepcopy(rows[start:start + size])}
        if action == "UpdateCustomDomain":
            if self.fail_www and parameters["Domain"] == m.DOMAINS[1]:
                raise m.RenewalError("Simulated update failure")
            self.domains[parameters["Domain"]].update(copy.deepcopy(parameters))
            if self.damage_config:
                self.domains[parameters["Domain"]]["EndpointsConfig"] = []
            return {"RequestId": "updated"}
        if action == "ApplyCertificate":
            self.certificates.append(certificate("requested", status=0, origin=parameters.get("OldCertificateId"), Alias=parameters["Alias"], CertBeginTime="", CertEndTime=""))
            return {"CertificateId": "requested", "RequestId": "requested"}
        raise AssertionError("Unexpected API action")

    def writes(self, action=None):
        return [call for call in self.calls if call[1] in {"ApplyCertificate", "UpdateCustomDomain"} and (action is None or call[1] == action)]


class RenewalTests(unittest.TestCase):
    def test_healthy_certificate_only_reads_deployed_metadata(self):
        cloud = FakeCloud([certificate(days=80)])
        self.assertEqual(m.renew(cloud, NOW), {"status": "healthy"})
        self.assertEqual(len(cloud.calls), 3)
        self.assertEqual(cloud.writes(), [])

    def test_exact_25_day_boundary_applies_one_free_renewal(self):
        cloud = FakeCloud([certificate(days=25)])
        self.assertEqual(m.renew(cloud, NOW), {"status": "requested"})
        self.assertEqual(len(cloud.writes()), 1)
        self.assertEqual(cloud.writes()[0], ("ssl", "ApplyCertificate", {
            "DomainName": "weiluai.top", "DvAuthMethod": "DNS_AUTO", "PackageType": "83",
            "ValidityPeriod": "3", "Alias": "velo-scf-tls:old", "OldCertificateId": "old",
        }))
        self.assertEqual(m.renew(cloud, NOW), {"status": "pending", "orders": 1})
        self.assertEqual(len(cloud.writes()), 1)

    def test_just_over_25_days_does_not_apply(self):
        cloud = FakeCloud([certificate(CertEndTime=(NOW + timedelta(days=25, seconds=1)).astimezone(m.CST).strftime("%Y-%m-%d %H:%M:%S"))])
        self.assertEqual(m.renew(cloud, NOW)["status"], "healthy")

    def test_expired_old_certificate_never_uses_old_certificate_id(self):
        for days in [0, -1]:
            cloud = FakeCloud([certificate(days=days, status=3)])
            with self.assertRaisesRegex(m.RenewalError, "already expired"):
                m.renew(cloud, NOW)
            self.assertNotIn("OldCertificateId", cloud.writes()[0][2])
            with self.assertRaisesRegex(m.RenewalError, "pending"):
                m.renew(cloud, NOW)
            self.assertEqual(len(cloud.writes()), 1)

    def test_all_pending_statuses_prevent_duplicate_creation(self):
        for status in m.PENDING_STATUSES:
            with self.subTest(status=status):
                cloud = FakeCloud([certificate(), certificate("pending", status=status, CertBeginTime="", CertEndTime="")])
                self.assertEqual(m.renew(cloud, NOW)["status"], "pending")
                self.assertEqual(cloud.writes(), [])

    def test_multiple_pending_orders_do_not_create_another(self):
        cloud = FakeCloud([certificate(), certificate("pending1", status=0), certificate("pending2", status=4)])
        self.assertEqual(m.renew(cloud, NOW), {"status": "pending", "orders": 2})
        self.assertEqual(cloud.writes(), [])

    def test_stale_or_urgent_pending_raises_without_writes(self):
        for old_days, inserted in [(20, -4), (7, 0), (-1, 0)]:
            cloud = FakeCloud([certificate(days=old_days), certificate("pending", status=4, InsertTime=date(inserted))])
            with self.assertRaisesRegex(m.RenewalError, "pending"):
                m.renew(cloud, NOW)
            self.assertEqual(cloud.writes(), [])

    def test_current_cycle_terminal_failures_raise_without_reapplying(self):
        for status in m.FAILED_STATUSES:
            for relation in [{"origin": "old"}, {"Alias": "velo-scf-tls:old"}]:
                cloud = FakeCloud([certificate(), certificate("failed", status=status, **relation)])
                with self.assertRaisesRegex(m.RenewalError, "failed or was cancelled"):
                    m.renew(cloud, NOW)
                self.assertEqual(cloud.writes(), [])

    def test_ancient_unrelated_failure_does_not_block_a_new_cycle(self):
        cloud = FakeCloud([certificate(), certificate("historical", status=2, origin="ancient")])
        self.assertEqual(m.renew(cloud, NOW)["status"], "requested")

    def test_unknown_status_fails_closed(self):
        cloud = FakeCloud([certificate(), certificate("mystery", status=99)])
        with self.assertRaisesRegex(m.RenewalError, "unknown"):
            m.renew(cloud, NOW)
        self.assertEqual(cloud.writes(), [])

    def test_valid_new_certificate_preserves_all_domain_configuration(self):
        cloud = FakeCloud([certificate(), certificate("new", days=90, origin="old")])
        before = copy.deepcopy(cloud.domains)
        self.assertEqual(m.renew(cloud, NOW), {"status": "updated", "domains": list(m.DOMAINS)})
        for domain in m.DOMAINS:
            before[domain]["CertConfig"]["CertificateId"] = "new"
        self.assertEqual(cloud.domains, before)
        self.assertEqual(len(cloud.writes("UpdateCustomDomain")), 2)
        self.assertEqual(cloud.writes("ApplyCertificate"), [])
        self.assertLessEqual(len(cloud.calls), m.MAX_API_CALLS)

    def test_non_deployable_longer_certificate_does_not_shadow_usable_renewal(self):
        for value in [False, None, "true", 1, "missing"]:
            with self.subTest(deployable=value):
                longer = certificate("longer", days=180, Deployable=value)
                if value == "missing":
                    longer.pop("Deployable")
                cloud = FakeCloud([certificate(), longer, certificate("usable", days=90, origin="old")])
                self.assertEqual(m.renew(cloud, NOW)["status"], "updated")
                self.assertEqual({write[2]["CertConfig"]["CertificateId"] for write in cloud.writes()}, {"usable"})
                self.assertEqual(cloud.writes("ApplyCertificate"), [])

    def test_unready_issued_certificate_never_triggers_duplicate_application(self):
        for value in [False, None, "missing"]:
            with self.subTest(deployable=value):
                newer = certificate("newer", days=90, Deployable=value)
                if value == "missing":
                    newer.pop("Deployable")
                cloud = FakeCloud([certificate(), newer])
                for _ in range(2):
                    with self.assertRaisesRegex(m.RenewalError, "not confirmed deployable"):
                        m.renew(cloud, NOW)
                self.assertEqual(cloud.writes(), [])

    def test_missing_deployability_of_partially_deployed_new_cert_blocks_reapply(self):
        newer = certificate("newer", days=90, origin="old")
        newer.pop("Deployable")
        cloud = FakeCloud([certificate(), newer], ids=("newer", "old"))
        with self.assertRaisesRegex(m.RenewalError, "not confirmed deployable"):
            m.renew(cloud, NOW)
        self.assertEqual(cloud.writes(), [])

    def test_missing_deployability_on_expiring_old_cert_does_not_prevent_request(self):
        old = certificate()
        old.pop("Deployable")
        cloud = FakeCloud([old])
        self.assertEqual(m.renew(cloud, NOW)["status"], "requested")
        self.assertEqual(len(cloud.writes("ApplyCertificate")), 1)
        self.assertEqual(cloud.writes("UpdateCustomDomain"), [])

    def test_partial_domain_update_reenters_without_reapply_or_repeat(self):
        cloud = FakeCloud([certificate(), certificate("new", days=90, origin="old")])
        cloud.fail_www = True
        with self.assertRaisesRegex(m.RenewalError, "Simulated"):
            m.renew(cloud, NOW)
        self.assertEqual(cloud.domains[m.DOMAINS[0]]["CertConfig"]["CertificateId"], "new")
        cloud.fail_www = False
        cloud.calls.clear()
        self.assertEqual(m.renew(cloud, NOW), {"status": "updated", "domains": [m.DOMAINS[1]]})
        self.assertEqual(len(cloud.writes()), 1)
        self.assertEqual(m.renew(cloud, NOW), {"status": "healthy"})

    def test_two_different_old_certificates_and_longer_current_domain(self):
        cloud = FakeCloud([certificate(), certificate("long", days=120), certificate("new", days=90, origin="old")], ids=("long", "old"))
        self.assertEqual(m.renew(cloud, NOW)["domains"], [m.DOMAINS[1]])
        self.assertEqual(cloud.domains[m.DOMAINS[0]]["CertConfig"]["CertificateId"], "long")

    def test_issued_candidate_requires_sans_valid_now_and_longer_expiry(self):
        changes = [
            {"SubjectAltName": ["weiluai.top"]}, {"SubjectAltName": ["weiluai.top", "www.weiluai.top.evil"]},
            {"SubjectAltName": ["*.weiluai.top"]}, {"CertEndTime": date(20)},
            {"CertEndTime": date(19)}, {"CertBeginTime": date(1)}, {"CertEndTime": date(-1)},
        ]
        for change in changes:
            with self.subTest(change=change):
                cloud = FakeCloud([certificate(), certificate("new", days=90, origin="old", **change)])
                with self.assertRaisesRegex(m.RenewalError, "Issued renewal"):
                    m.renew(cloud, NOW)
                self.assertEqual(cloud.writes(), [])

    def test_foreign_domain_never_deploys_even_with_fuzzy_search_match(self):
        cloud = FakeCloud([certificate(), certificate("foreign", days=365, Domain="weiluai.top.evil", origin="old")])
        self.assertEqual(m.renew(cloud, NOW)["status"], "requested")
        self.assertEqual(cloud.writes("UpdateCustomDomain"), [])
        self.assertEqual(cloud.writes()[0][2]["DomainName"], "weiluai.top")

    def test_bad_domain_snapshot_stops_before_any_write(self):
        for field, value in [("Domain", "evil.example"), ("Protocol", "HTTP"), ("EndpointsConfig", []), ("NewUnknownField", True)]:
            cloud = FakeCloud()
            cloud.domains[m.DOMAINS[0]][field] = value
            with self.assertRaises(m.RenewalError):
                m.renew(cloud, NOW)
            self.assertEqual(cloud.writes(), [])

    def test_concurrent_config_change_stops_before_update(self):
        cloud = FakeCloud([certificate(), certificate("new", days=90, origin="old")])
        original = cloud.call
        def changed(service, action, parameters):
            if action == "GetCustomDomain" and len(cloud.calls) >= 4:
                cloud.domains[parameters["Domain"]]["Protocol"] = "HTTPS"
            return original(service, action, parameters)
        cloud.call = changed
        with self.assertRaisesRegex(m.RenewalError, "concurrently"):
            m.renew(cloud, NOW)
        self.assertEqual(cloud.writes(), [])

    def test_post_update_configuration_drift_raises(self):
        cloud = FakeCloud([certificate(), certificate("new", days=90, origin="old")])
        cloud.damage_config = True
        with self.assertRaises(m.RenewalError):
            m.renew(cloud, NOW)
        self.assertEqual(len(cloud.writes()), 1)

    def test_missing_or_revoked_current_certificate_raises(self):
        for certificates in [[], [certificate(status=10)]]:
            cloud = FakeCloud(certificates)
            with self.assertRaisesRegex(m.RenewalError, "deployed certificate"):
                m.renew(cloud, NOW)
            self.assertEqual(cloud.writes(), [])

    def test_certificate_dates_are_gmt_plus_8_not_host_timezone(self):
        self.assertEqual(m._date("2026-10-12 12:00:00"), NOW)
        with self.assertRaises(m.RenewalError):
            m._date("invalid")

    def test_pagination_and_duplicate_pages_are_bounded(self):
        cloud = FakeCloud([certificate("a"), certificate("b"), certificate("c")])
        with patch.object(m, "PAGE_SIZE", 1):
            self.assertEqual(set(m._list_certificates(cloud, {"SearchKey": m.DOMAINS[0]})), {"a", "b", "c"})
        self.assertEqual([call[2]["Offset"] for call in cloud.calls], [0, 1, 2])
        duplicate = Mock()
        duplicate.call.return_value = {"TotalCount": 2, "Certificates": [certificate()]}
        with self.assertRaisesRegex(m.RenewalError, "repeated"):
            m._list_certificates(duplicate, {})
        self.assertEqual(duplicate.call.call_count, 2)
        excessive = FakeCloud([certificate(str(i)) for i in range(6)])
        with patch.object(m, "PAGE_SIZE", 1), self.assertRaisesRegex(m.RenewalError, "page limit"):
            m._list_certificates(excessive, {})
        self.assertEqual(len(excessive.calls), m.MAX_PAGES)

    def test_incomplete_or_changed_pagination_raises(self):
        for pages in [[{"TotalCount": 1, "Certificates": []}], [{"TotalCount": 2, "Certificates": [certificate()]}, {"TotalCount": 3, "Certificates": [certificate("b")]}]]:
            client = Mock()
            client.call.side_effect = pages
            with self.assertRaises(m.RenewalError):
                m._list_certificates(client, {})

    def test_event_cannot_override_domain_or_region(self):
        cloud = FakeCloud([certificate(days=80)])
        original = m.renew
        with patch.object(m, "CloudClient", return_value=cloud), patch.object(m, "renew", side_effect=lambda client: original(client, NOW)):
            result = m.main_handler({"Domain": "evil.example", "Region": "ap-beijing"}, None)
        self.assertEqual(result["status"], "healthy")
        self.assertEqual({call[2]["Domain"] for call in cloud.calls if call[1] == "GetCustomDomain"}, set(m.DOMAINS))


class ClientAndPolicyTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "TENCENTCLOUD_SECRETID": "test-secret-id", "TENCENTCLOUD_SECRETKEY": "test-secret-key", "TENCENTCLOUD_SESSIONTOKEN": "test-session-token",
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_tc3_signature_matches_official_published_fixture(self):
        payload = b'{"Limit": 1, "Filters": [{"Values": ["\\u672a\\u547d\\u540d"], "Name": "instance-name"}]}'
        canonical = m._canonical_request("cvm.tencentcloudapi.com", "DescribeInstances", payload)
        self.assertEqual(hashlib.sha256(canonical.encode()).hexdigest(), "7019a55be8395899b900fb5564e4200d984910f34794a27cb3fb7d10ff6a1e84")
        auth = m._authorization("cvm", "DescribeInstances", payload, "AKID********************************", "********************************", 1551113065)
        self.assertEqual(auth, "TC3-HMAC-SHA256 Credential=AKID********************************/2019-02-25/cvm/tc3_request, SignedHeaders=content-type;host;x-tc-action, Signature=10b1a37a7301a02ca19a647ad722d5e43b4b3cff309d421d85b46093f6ab6c4f")

    def test_client_uses_fixed_endpoints_token_and_guangzhou_only(self):
        connection = Mock()
        connection.getresponse.return_value.status = 200
        connection.getresponse.return_value.read.return_value = b'{"Response":{"RequestId":"ok"}}'
        with patch.object(m.http.client, "HTTPSConnection", return_value=connection) as constructor:
            client = m.CloudClient()
            client.call("scf", "GetCustomDomain", {"Domain": "weiluai.top"})
            constructor.assert_called_with("scf.tencentcloudapi.com", timeout=5)
            headers = connection.request.call_args.kwargs["headers"]
            self.assertEqual(headers["X-TC-Region"], "ap-guangzhou")
            self.assertEqual(headers["X-TC-Version"], "2018-04-16")
            self.assertEqual(headers["X-TC-Token"], "test-session-token")
            client.call("ssl", "DescribeCertificates", {"CertIds": ["old"]})
            self.assertNotIn("X-TC-Region", connection.request.call_args.kwargs["headers"])

    def test_disallowed_actions_domains_and_paid_parameters_never_reach_network(self):
        with patch.object(m.http.client, "HTTPSConnection") as network:
            client = m.CloudClient()
            for service, action, params in [
                ("ssl", "DownloadCertificate", {}), ("dnspod", "CreateRecord", {}),
                ("scf", "UpdateCustomDomain", {"Domain": "evil.example"}),
                ("ssl", "ApplyCertificate", {"DomainName": "weiluai.top", "PackageType": "2"}),
            ]:
                with self.assertRaises(m.RenewalError):
                    client.call(service, action, params)
            network.assert_not_called()

    def test_missing_temporary_token_is_rejected(self):
        with patch.dict(os.environ, {"TENCENTCLOUD_SESSIONTOKEN": ""}), self.assertRaises(m.RenewalError):
            m.CloudClient()

    def test_api_and_transport_errors_never_expose_secrets(self):
        connection = Mock()
        connection.getresponse.return_value.status = 200
        connection.getresponse.return_value.read.return_value = b'{"Response":{"Error":{"Message":"test-secret-key test-session-token"}}}'
        with patch.object(m.http.client, "HTTPSConnection", return_value=connection):
            with self.assertRaises(m.RenewalError) as raised:
                m.CloudClient().call("ssl", "DescribeCertificates", {})
            self.assertNotIn("test-secret", str(raised.exception))
        connection.request.side_effect = RuntimeError("test-secret-key test-session-token")
        with patch.object(m.http.client, "HTTPSConnection", return_value=connection), contextlib.redirect_stdout(io.StringIO()) as stdout, contextlib.redirect_stderr(io.StringIO()) as stderr:
            try:
                m.main_handler({}, None)
            except m.RenewalError:
                trace = traceback.format_exc()
            else:
                self.fail("Transport failure was swallowed")
            self.assertNotIn("test-secret", trace)
            self.assertNotIn("test-session", trace)
            self.assertEqual(stdout.getvalue() + stderr.getvalue(), "")

    def test_api_calls_have_a_hard_budget_and_no_automatic_retries(self):
        connection = Mock()
        connection.getresponse.return_value.status = 200
        connection.getresponse.return_value.read.return_value = b'{"Response":{}}'
        with patch.object(m.http.client, "HTTPSConnection", return_value=connection):
            client = m.CloudClient()
            for _ in range(m.MAX_API_CALLS):
                client.call("ssl", "DescribeCertificates", {})
            with self.assertRaisesRegex(m.RenewalError, "budget"):
                client.call("ssl", "DescribeCertificates", {})
            self.assertEqual(connection.request.call_count, m.MAX_API_CALLS)

    def test_permission_template_matches_only_the_four_authorized_actions(self):
        policy = json.loads((DIRECTORY / "cam-policy.json").read_text())
        grants = {action: statement["resource"] for statement in policy["statement"] for action in statement["action"]}
        self.assertEqual(set(grants), {"ssl:ApplyCertificate", "ssl:DescribeCertificates", "scf:GetCustomDomain", "scf:UpdateCustomDomain"})
        self.assertEqual(grants["ssl:ApplyCertificate"], ["*"])
        self.assertEqual(grants["ssl:DescribeCertificates"], ["qcs::ssl::uin/${ACCOUNT_UIN}:certificate/*"])
        for action in ["scf:GetCustomDomain", "scf:UpdateCustomDomain"]:
            self.assertEqual(grants[action], ["qcs::scf:ap-guangzhou:uin/${ACCOUNT_UIN}:domain/" + domain for domain in m.DOMAINS])


class PackageTests(unittest.TestCase):
    def test_build_uses_commit_ignores_dirty_files_and_unpacks_without_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            def git(*args):
                return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.PIPE)
            git("init", "-q")
            source = repo / builder.SOURCE
            source.parent.mkdir(parents=True)
            source.write_bytes((DIRECTORY / "handler.py").read_bytes())
            git("add", "--", builder.SOURCE)
            git("-c", "user.name=SCF Test", "-c", "user.email=scf-test@example.invalid", "commit", "-qm", "Isolated test fixture")
            revision = git("rev-parse", "HEAD").decode().strip()
            first, second = Path(temp) / "first.zip", Path(temp) / "second.zip"
            report = builder.build(repo, revision, first)
            source.write_text("DIRTY")
            (repo / ".env").write_text("SECRET")
            builder.build(repo, revision, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(report["zip_sha256"], hashlib.sha256(first.read_bytes()).hexdigest())
            with zipfile.ZipFile(first) as archive:
                self.assertEqual(set(archive.namelist()), {"handler.py", "deployment-manifest.json"})
                archive.extractall(Path(temp) / "unpacked")
            packaged = load("packaged_renewal", Path(temp) / "unpacked/handler.py")
            self.assertEqual(packaged.renew(FakeCloud([certificate(days=80)]), NOW), {"status": "healthy"})
            with self.assertRaises(ValueError):
                builder.build(repo, "HEAD", Path(temp) / "invalid.zip")
            with self.assertRaises(ValueError):
                builder.build(repo, revision, first)


if __name__ == "__main__":
    unittest.main()
