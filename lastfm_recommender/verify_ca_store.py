"""Fail the image build if Python still trusts the affected emSign G3 root."""
import ssl


context = ssl.create_default_context()
certificates = context.get_ca_certs()
if not certificates:
    raise RuntimeError("Python's default CA store is empty")

for certificate in certificates:
    for rdn in certificate.get("subject", ()):
        for attribute, value in rdn:
            if attribute == "commonName" and value == "emSign ECC Root CA - G3":
                raise RuntimeError("Python still trusts the affected emSign ECC Root CA - G3")

print(f"Python TLS CA store verified: {len(certificates)} roots; affected emSign G3 root absent")
