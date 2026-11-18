#!/usr/bin/env python3
"""Port Deluge 2.2.0's daemon certificate generation off the removed pyOpenSSL API.

pyOpenSSL 26 removed OpenSSL.crypto.X509Req (and deprecated PKey/X509/dump_*),
so deluged dies on first run while creating its RPC certificate:

    Unable to start deluged: module 'OpenSSL.crypto' has no attribute 'X509Req'

The CSR in the original code was pointless anyway - it only ferried the subject
name into a self-signed certificate. This rewrites generate_ssl_keys() on top of
`cryptography`, which pyOpenSSL itself is built on, and emits byte-identical PEM
formats (PKCS#1 "RSA PRIVATE KEY" + X.509) so Twisted still loads them.

Idempotent: safe to re-run.
"""

import argparse
import os
import re
import shutil
import sys
import sysconfig

NEW_FUNC = '''def generate_ssl_keys():
    """
    This method generates a new SSL key/cert.
    """
    # Generate key pair
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # Generate a self-signed certificate. The original implementation routed the
    # subject through an X509Req, which pyOpenSSL 26 removed; a CSR is not needed
    # to self-sign, so the subject is set on the certificate directly.
    name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, 'Deluge Daemon')]
    )
    not_before = datetime.datetime.now(datetime.timezone.utc)
    not_after = not_before + datetime.timedelta(days=365 * 3)  # Three Years
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .sign(private_key, hashes.SHA256())
    )

    # Write out files
    ssl_dir = deluge.configmanager.get_config_dir('ssl')
    with open(os.path.join(ssl_dir, 'daemon.pkey'), 'wb') as _file:
        _file.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
    with open(os.path.join(ssl_dir, 'daemon.cert'), 'wb') as _file:
        _file.write(cert.public_bytes(serialization.Encoding.PEM))
    # Make the files only readable by this user
    for f in ('daemon.pkey', 'daemon.cert'):
        os.chmod(os.path.join(ssl_dir, f), stat.S_IREAD | stat.S_IWRITE)
'''

NEW_IMPORTS = '''import datetime
import os
import stat

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
'''

MARKER = 'from cryptography.x509.oid import NameOID'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--site-packages', default=sysconfig.get_path('platlib'))
    args = ap.parse_args()

    path = os.path.join(args.site_packages, 'deluge', 'crypto_utils.py')
    if not os.path.isfile(path):
        sys.exit('not found: %s' % path)

    with open(path, encoding='utf-8') as fh:
        src = fh.read()

    if MARKER in src:
        print('deluge crypto_utils: already patched')
        return

    if 'X509Req' not in src:
        sys.exit('unexpected crypto_utils.py: no X509Req to replace')

    if not os.path.exists(path + '.orig'):
        shutil.copyfile(path, path + '.orig')

    # Swap the import block.
    new_src, n = re.subn(
        r'^import os\nimport stat\n', NEW_IMPORTS, src, count=1, flags=re.M
    )
    if n != 1:
        sys.exit('could not rewrite import block')

    # generate_ssl_keys() is the last function in the module.
    idx = new_src.index('def generate_ssl_keys():')
    if 'def ' in new_src[idx + 1 :].replace('def generate_ssl_keys():', '', 1):
        pass  # nothing follows in 2.2.0; replacing to EOF is safe
    new_src = new_src[:idx] + NEW_FUNC

    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(new_src)

    # Drop stale bytecode so the patched source is what loads.
    cache = os.path.join(args.site_packages, 'deluge', '__pycache__')
    if os.path.isdir(cache):
        for f in os.listdir(cache):
            if f.startswith('crypto_utils.'):
                os.remove(os.path.join(cache, f))

    print('deluge crypto_utils: patched OK')


if __name__ == '__main__':
    main()
