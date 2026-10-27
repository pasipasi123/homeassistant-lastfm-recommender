import contextlib
import io
from pathlib import Path
import runpy
import unittest
from unittest.mock import Mock, patch


CHECK = Path(__file__).resolve().parents[1] / "lastfm_recommender" / "verify_ca_store.py"


class CertificateBuildCheckTests(unittest.TestCase):
    def verify(self, names):
        certificates = [{"subject": ((("commonName", name),),)} for name in names]
        context = Mock()
        context.get_ca_certs.return_value = certificates
        with patch("ssl.create_default_context", return_value=context), contextlib.redirect_stdout(io.StringIO()):
            runpy.run_path(str(CHECK))

    def test_rejects_affected_root_among_other_roots(self):
        with self.assertRaisesRegex(RuntimeError, "still trusts"):
            self.verify(["Example Root CA", "emSign ECC Root CA - G3"])

    def test_keeps_unaffected_roots_usable(self):
        self.verify(["Example Root CA", "emSign Root CA - G1", "emSign ECC Root CA - G1"])

    def test_rejects_empty_trust_store(self):
        with self.assertRaisesRegex(RuntimeError, "empty"):
            self.verify([])
