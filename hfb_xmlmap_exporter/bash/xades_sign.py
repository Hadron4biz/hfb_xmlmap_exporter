#!/usr/bin/env python3
import base64
import sys
from datetime import datetime, timezone
from lxml import etree
from signxml import XMLSigner, methods
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.hazmat.primitives import hashes
from cryptography import x509
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.hazmat.primitives.serialization import Encoding

CERT_CRT = "Testowy_Odoo_18.crt"
CERT_KEY = "Testowy_Odoo_18.key"
CERT_PASS = open("password.txt", "rb").read().strip()


NS = {
	"ds": "http://www.w3.org/2000/09/xmldsig#",
	"xades": "http://uri.etsi.org/01903/v1.3.2#",
}


def build_challenge_xml(challenge: str) -> etree.Element:
	root = etree.Element("Challenge", nsmap={None: "urn:ksef:auth"})
	root.text = challenge
	return root


def inject_xades(signature_node: etree.Element):
	obj = etree.SubElement(signature_node, etree.QName(NS["ds"], "Object"))

	qp = etree.SubElement(
		obj,
		etree.QName(NS["xades"], "QualifyingProperties"),
		Target="#" + signature_node.get("Id"),
	)

	sp = etree.SubElement(
		qp,
		etree.QName(NS["xades"], "SignedProperties"),
		Id="SignedProperties",
	)

	ssp = etree.SubElement(
		sp, etree.QName(NS["xades"], "SignedSignatureProperties")
	)

	st = etree.SubElement(
		ssp, etree.QName(NS["xades"], "SigningTime")
	)
	st.text = datetime.now(timezone.utc).isoformat()


def sign_xml(xml_root: etree.Element) -> etree.Element:
	signer = XMLSigner(
		method=methods.enveloped,
		signature_algorithm="ecdsa-sha256",
		digest_algorithm="sha256",
		c14n_algorithm="http://www.w3.org/2001/10/xml-exc-c14n#",
	)

	with open(CERT_KEY, "rb") as f:
		key = load_pem_private_key(f.read(), password=CERT_PASS)

	with open(CERT_CRT, "rb") as f:
		cert = x509.load_pem_x509_certificate(f.read())

	signed = signer.sign(
		xml_root,
		key=key,
		cert=cert.public_bytes(Encoding.PEM),
	)

	sig = signed.find(".//ds:Signature", namespaces=NS)
	sig.set("Id", "Signature")

	inject_xades(sig)

	return signed


def xmlsig_to_cms(xml_signed: etree.Element) -> bytes:
	data = etree.tostring(xml_signed, xml_declaration=True, encoding="utf-8")

	with open(CERT_KEY, "rb") as f:
		key = load_pem_private_key(f.read(), password=CERT_PASS)

	with open(CERT_CRT, "rb") as f:
		cert = x509.load_pem_x509_certificate(f.read())

	builder = pkcs7.PKCS7SignatureBuilder().set_data(data)
	builder = builder.add_signer(cert, key, hashes.SHA256())

	return builder.sign(
		encoding=Encoding.DER,
		options=[pkcs7.PKCS7Options.Binary],
	)


def main():
	if len(sys.argv) != 2:
		print("Usage: xades_sign.py <challenge>")
		sys.exit(1)

	challenge = sys.argv[1]

	xml = build_challenge_xml(challenge)
	signed_xml = sign_xml(xml)

	with open("signed.xml", "wb") as f:
		f.write(etree.tostring(signed_xml, pretty_print=True))

	cms = xmlsig_to_cms(signed_xml)

	with open("signature.der", "wb") as f:
		f.write(cms)

	sig_b64 = base64.b64encode(cms).decode()

	with open("signature.base64", "w") as f:
		f.write(sig_b64)

	print("OK")
	print(sig_b64)


if __name__ == "__main__":
	main()

