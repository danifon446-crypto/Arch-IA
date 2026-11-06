"""certificados.py  Certificado HTTPS propio para el banco de pruebas del perro.

Por que existe:
  El iPhone solo deja usar la camara (y solo instala la app en la pantalla de inicio
  con todas sus funciones) si la pagina llega por HTTPS con un certificado en el que
  confia. El certificado "adhoc" de antes cambiaba en cada arranque y el iPhone nunca
  lo aceptaba como app.

Como funciona:
  * Se crea UNA sola vez una "autoridad" local (ca.crt + ca.key). Esa es la que se
    instala en el iPhone (una sola vez).
  * Con esa autoridad se firma el certificado del servidor, con las IP del PC
    (WiFi, Tailscale, localhost). Si cambia la IP del PC, se vuelve a firmar solo,
    y el iPhone lo sigue aceptando sin reinstalar nada.

Todo queda en la carpeta certificados/ (que NO se sube a GitHub: tiene llaves privadas).

Necesita: pip install cryptography
"""

import datetime
import ipaddress
import json
import os
import socket
import ssl
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
CARPETA = os.path.join(HERE, "certificados")
CA_CRT = os.path.join(CARPETA, "ca.crt")
CA_KEY = os.path.join(CARPETA, "ca.key")
SRV_CRT = os.path.join(CARPETA, "servidor.crt")
SRV_KEY = os.path.join(CARPETA, "servidor.key")
SRV_INFO = os.path.join(CARPETA, "servidor.json")

NOMBRE_CA = "Arche perro (certificado local)"
DIAS_SERVIDOR = 390          # el iPhone rechaza certificados de servidor de mas de 398 dias


def ip_tailscale():
    """IP de Tailscale del PC (100.x.x.x), o None si Tailscale no esta instalado/encendido."""
    rutas = ["tailscale", r"C:\Program Files\Tailscale\tailscale.exe"]
    for exe in rutas:
        try:
            r = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=4,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            continue
        for linea in r.stdout.split():
            try:
                if ipaddress.ip_address(linea.strip()) in ipaddress.ip_network("100.64.0.0/10"):
                    return linea.strip()
            except ValueError:
                pass
    return None


def ips_del_pc(ip_principal=None):
    """Todas las IPv4 del PC: WiFi/cable, Tailscale (100.x) y localhost."""
    ips = {"127.0.0.1"}
    if ip_principal:
        ips.add(ip_principal)
    ts = ip_tailscale()
    if ts:
        ips.add(ts)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    validas = set()
    for ip in ips:
        try:
            if not ipaddress.ip_address(ip).is_link_local:
                validas.add(ip)
        except ValueError:
            pass
    return sorted(validas)


def _nombres():
    n = {"localhost"}
    try:
        h = socket.gethostname()
        if h:
            n.update({h, h.lower(), h.lower() + ".local"})
    except OSError:
        pass
    return sorted(n)


def _guardar(ruta, datos, privado=False):
    with open(ruta, "wb") as f:
        f.write(datos)
    if privado:
        try:
            os.chmod(ruta, 0o600)
        except OSError:
            pass


def _crear_ca():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    llave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, NOMBRE_CA),
                        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Arche")])
    ahora = datetime.datetime.now(datetime.timezone.utc)
    pub = llave.public_key()
    cert = (x509.CertificateBuilder()
            .subject_name(nombre).issuer_name(nombre).public_key(pub)
            .serial_number(x509.random_serial_number())
            .not_valid_before(ahora - datetime.timedelta(days=1))
            .not_valid_after(ahora + datetime.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                         content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(pub), critical=False)
            .sign(llave, hashes.SHA256()))
    _guardar(CA_KEY, llave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                         serialization.NoEncryption()), privado=True)
    _guardar(CA_CRT, cert.public_bytes(serialization.Encoding.PEM))


def _crear_servidor(ips, nombres):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    with open(CA_KEY, "rb") as f:
        ca_llave = serialization.load_pem_private_key(f.read(), password=None)
    with open(CA_CRT, "rb") as f:
        ca_cert = x509.load_pem_x509_certificate(f.read())

    llave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ahora = datetime.datetime.now(datetime.timezone.utc)
    san = [x509.DNSName(n) for n in nombres] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Banco de pruebas Arche")]))
            .issuer_name(ca_cert.subject).public_key(llave.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(ahora - datetime.timedelta(days=1))
            .not_valid_after(ahora + datetime.timedelta(days=DIAS_SERVIDOR))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=True, key_cert_sign=False,
                                         crl_sign=False, content_commitment=False, data_encipherment=False,
                                         key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(llave.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_llave.public_key()), critical=False)
            .sign(ca_llave, hashes.SHA256()))
    _guardar(SRV_KEY, llave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                          serialization.NoEncryption()), privado=True)
    _guardar(SRV_CRT, cert.public_bytes(serialization.Encoding.PEM))
    vence = (ahora + datetime.timedelta(days=DIAS_SERVIDOR)).isoformat()
    _guardar(SRV_INFO, json.dumps({"ips": ips, "nombres": nombres, "vence": vence}, indent=2).encode("utf-8"))


def _servidor_vigente(ips, nombres):
    try:
        with open(SRV_INFO, "r", encoding="utf-8") as f:
            info = json.load(f)
        vence = datetime.datetime.fromisoformat(info["vence"])
    except (OSError, ValueError, KeyError):
        return False
    if not (os.path.exists(SRV_CRT) and os.path.exists(SRV_KEY)):
        return False
    if vence - datetime.datetime.now(datetime.timezone.utc) < datetime.timedelta(days=15):
        return False
    return set(ips) <= set(info.get("ips", [])) and set(nombres) <= set(info.get("nombres", []))


def preparar(ip_principal=None):
    """Deja listos los certificados y devuelve (ruta_crt, ruta_key)."""
    os.makedirs(CARPETA, exist_ok=True)
    gi = os.path.join(CARPETA, ".gitignore")
    if not os.path.exists(gi):
        _guardar(gi, b"# llaves privadas: nunca a GitHub\n*\n")
    if not (os.path.exists(CA_CRT) and os.path.exists(CA_KEY)):
        _crear_ca()
        for r in (SRV_CRT, SRV_KEY, SRV_INFO):
            if os.path.exists(r):
                os.remove(r)
    ips, nombres = ips_del_pc(ip_principal), _nombres()
    if not _servidor_vigente(ips, nombres):
        _crear_servidor(ips, nombres)
    return SRV_CRT, SRV_KEY


def contexto_ssl(ip_principal=None):
    crt, key = preparar(ip_principal)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(crt, key)
    return ctx


def ca_der():
    """La autoridad en formato DER (.cer): es el que el iPhone instala mas facil."""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    with open(CA_CRT, "rb") as f:
        return x509.load_pem_x509_certificate(f.read()).public_bytes(serialization.Encoding.DER)
