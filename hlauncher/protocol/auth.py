"""Diagnostic accessory-key possession verification, not Apple CA policy validation."""

import os, pathlib, re, subprocess, tempfile


class AccessoryProof:
    def __init__(self):
        self.sections = {}
        self.maximum = None
        self.challenge = None
        self.public_key = None

    def add_section(self, section, maximum, data):
        if section == 0:
            self.sections = {}
            self.maximum = maximum
            self.public_key = None
            self.challenge = None
        if self.maximum != maximum or section > maximum:
            raise ValueError("inconsistent certificate sections")
        if section in self.sections and self.sections[section] != data:
            raise ValueError("changed certificate section")
        self.sections[section] = data
        return all(i in self.sections for i in range(maximum + 1))

    def prepare_challenge(self):
        cert = b"".join(self.sections[i] for i in range(self.maximum + 1))
        with tempfile.TemporaryDirectory(prefix="civic-iap-cert-") as td:
            root = pathlib.Path(td)
            path = root / "cert.der"
            path.write_bytes(cert)
            r = subprocess.run(
                [
                    "openssl",
                    "pkcs7",
                    "-inform",
                    "DER",
                    "-in",
                    str(path),
                    "-print_certs",
                ],
                capture_output=True,
                timeout=4,
            )
            if r.returncode:
                raise ValueError("cannot decode accessory PKCS7 certificate")
            pems = re.findall(
                b"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
                r.stdout,
                re.S,
            )
            if not pems:
                raise ValueError("no accessory certificate")
            keys = []
            for pem in pems:
                r = subprocess.run(
                    ["openssl", "x509", "-pubkey", "-noout"],
                    input=pem,
                    capture_output=True,
                    timeout=4,
                )
                if r.returncode:
                    raise ValueError("cannot extract accessory public key")
                keys.append(r.stdout)
            self.public_key = keys
            self.challenge = os.urandom(20)
        return self.challenge, len(cert), len(keys)

    def verify(self, signature):
        if not self.public_key or self.challenge is None:
            return False, "no_pending_challenge"
        with tempfile.TemporaryDirectory(prefix="civic-iap-proof-") as td:
            root = pathlib.Path(td)
            (root / "challenge").write_bytes(self.challenge)
            (root / "signature").write_bytes(signature)
            for i, key in enumerate(self.public_key):
                (root / "public.pem").write_bytes(key)
                # Auth 2.x signs a SHA-1-sized challenge; verify PKCS#1 v1.5 with that digest.
                r = subprocess.run(
                    [
                        "openssl",
                        "pkeyutl",
                        "-verify",
                        "-pubin",
                        "-inkey",
                        str(root / "public.pem"),
                        "-in",
                        str(root / "challenge"),
                        "-sigfile",
                        str(root / "signature"),
                        "-pkeyopt",
                        "digest:sha1",
                    ],
                    capture_output=True,
                    timeout=4,
                )
                if r.returncode == 0:
                    return True, "rsa_pkcs1_sha1_digest_key_" + str(i)
            return False, "signature_did_not_match_certificate_keys"
