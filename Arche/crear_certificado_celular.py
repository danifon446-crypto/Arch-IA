"""
crear_certificado_celular.py
----------------------------
Crea el certificado HTTPS del control por celular (core/interfaz/remoto.py).

    python crear_certificado_celular.py

Resultado: core/interfaz/certificado_celular/celular.crt y celular.key
(la .key es privada: está en .gitignore, no la compartas ni la subas).

Al abrir la dirección en el celular saldrá un aviso de "conexión no privada"
porque el certificado lo firmaste tú y no una entidad pública. Es normal: acepta
la excepción una vez. Lo importante es que el PIN ya viaja cifrado.
Si cambia la IP de tu PC, vuelve a correr este script.

Necesita:  pip install cryptography
"""

import datetime
import ipaddress
import os
import socket
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)


def _ips_del_pc():
    ips = {"127.0.0.1"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    try:                                    # la IP de la red local, sin mandar nada
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(ips)


def main():
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
    except ImportError:
        print("Falta la librería cryptography:  pip install cryptography")
        return 1

    from core.interfaz import remoto
    os.makedirs(remoto.CARPETA_CERT, exist_ok=True)

    llave = ec.generate_private_key(ec.SECP256R1())
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Arche celular")])
    ips = _ips_del_pc()
    ahora = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(nombre).issuer_name(nombre)
            .public_key(llave.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(ahora - datetime.timedelta(days=1))
            .not_valid_after(ahora + datetime.timedelta(days=825))
            .add_extension(x509.SubjectAlternativeName(
                [x509.DNSName("localhost")] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]), critical=False)
            .sign(llave, hashes.SHA256()))

    with open(remoto.ARCHIVO_LLAVE, "wb") as f:
        f.write(llave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()))
    try:
        os.chmod(remoto.ARCHIVO_LLAVE, 0o600)
    except OSError:
        pass
    with open(remoto.ARCHIVO_CERT, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    print("Certificado creado para estas direcciones:", ", ".join(ips))
    print("Reinicia el acceso por celular en Arché (apágalo y préndelo) y abre  https://<ip>:<puerto>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
