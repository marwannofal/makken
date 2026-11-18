"""Authenticated SMTP with mandatory TLS and public-only, pinned connections."""
import base64
import hashlib
import ipaddress
import re
import smtplib
import socket
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.template.loader import render_to_string
from django.views.decorators.debug import sensitive_variables

# Content is deliberately pre-set; provider responses and exception strings
# are never returned to browsers or saved in the delivery table.
REASONS = {
    'config': 'إعدادات البريد غير مكتملة أو مفتاح التشفير غير صالح.',
    'resolution': 'تعذّر العثور على خادم البريد.',
    'network': 'خادم البريد غير متاح، أو الاتصال خارج نطاق المسموح.',
    'tls': 'تعذّر التحقق من اتصال TLS بخادم البريد.',
    'auth': 'رفض مزود البريد بيانات المصادقة.',
    'temporary': 'رفض خادم البريد الرسالة مؤقتًا.',
    'recipient': 'رفض مزود البريد عنوان المستلم.',
    'provider': 'رفض مزود البريد إعدادات الاتصال أو الإرسال.',
    'uncertain': 'انقطع الاتصال أثناء الإرسال؛ لم يُعد الإرسال تفاديًا للتكرار.',
    'internal': 'تعذّر تجهيز الرسالة أو إرسالها.',
    'eligibility': 'لم تعد قاعدة التوجيه أو الصلاحية أو البريد صالحة.',
    'expired': 'انتهت صلاحية الإشعار قبل إرساله.',
    'reminder_obsolete': 'لم يعد تذكير الشراكة صالحًا؛ تغيّر تاريخ الانتهاء أو لم تعد الشراكة نشطة.',
    'claim_expired': 'توقفت محاولة إرسال سابقة دون تسجيل نتيجة مؤكدة.',
}


class SendFailure(Exception):
    def __init__(self, code, retry=False, unknown=False):
        self.code, self.retry, self.unknown = code, retry, unknown
        super().__init__(code)


@sensitive_variables()
def crypto():
    configured = settings.MAKKEN_MAIL_ENCRYPTION_KEY
    if configured:
        try:
            return Fernet(configured.encode('ascii'))
        except (ValueError, UnicodeError) as exc:
            raise SendFailure('config') from exc
    # Application-domain separation; this material is never stored in MySQL.
    keys = [settings.SECRET_KEY, *settings.SECRET_KEY_FALLBACKS]
    return MultiFernet([Fernet(base64.urlsafe_b64encode(hashlib.sha256(
        b'makken.smtp.password.v1\0' + secret.encode()).digest())) for secret in keys])


@sensitive_variables()
def encrypt(secret):
    return crypto().encrypt(secret.encode()).decode('ascii')


@sensitive_variables()
def decrypt(secret):
    if not secret:
        return ''
    try:
        return crypto().decrypt(secret.encode('ascii')).decode()
    except (InvalidToken, UnicodeError) as exc:
        raise SendFailure('config') from exc


def clean_host(value):
    raw = value.strip().rstrip('.')
    try:
        name = raw.encode('idna').decode('ascii').lower()
    except UnicodeError as exc:
        raise ValidationError('أدخل اسم خادم بريد صالحًا.') from exc
    labels = name.split('.')
    if (len(name) > 253 or len(labels) < 2 or
        not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in labels) or
        not any(c.isalpha() for c in labels[-1])):
        raise ValidationError('أدخل اسم خادم بريد عام دون رابط أو عنوان IP.')
    return name


def smtp_endpoints(host, port):
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise SendFailure('resolution', retry=True) from exc
    result = []
    for family, kind, proto, _, sockaddr in answers:
        try:
            address = ipaddress.ip_address(sockaddr[0])
        except ValueError as exc:
            raise SendFailure('network') from exc
        if address.version == 6:
            if address.ipv4_mapped or address.sixtofour or address.teredo or address in ipaddress.ip_network('64:ff9b::/96') or address in ipaddress.ip_network('64:ff9b:1::/48'):
                raise SendFailure('network')
        if not address.is_global or address.is_multicast or address.is_reserved or getattr(address, 'is_site_local', False):
            raise SendFailure('network')
        endpoint = (family, kind, proto, sockaddr)
        if endpoint not in result:
            result.append(endpoint)
    if not result:
        raise SendFailure('resolution', retry=True)
    return result[:3]


class PinnedSocket:
    def _get_socket(self, host, port, timeout):
        for family, kind, proto, address in self.endpoints:
            sock = socket.socket(family, kind, proto)
            try:
                sock.settimeout(timeout)
                sock.connect(address)
                return sock
            except OSError:
                sock.close()
        raise OSError('SMTP connection failed')


class PublicStartTLS(PinnedSocket, smtplib.SMTP):
    pass


class PublicTLS(PinnedSocket, smtplib.SMTP_SSL):
    def _get_socket(self, host, port, timeout):
        sock = super()._get_socket(host, port, timeout)
        try:
            return self.context.wrap_socket(sock, server_hostname=host)
        except BaseException:
            sock.close()
            raise


def ready(config):
    return bool(config and config.host and config.sender and
                config.security in {'tls', 'starttls'} and config.port in {465, 587, 2525, 25} and
                (not config.username or config.secret))


def message_link(path):
    if not path or not path.startswith('/') or path.startswith('//'):
        return ''
    base = settings.MAKKEN_MAIL_BASE_URL.rstrip('/')
    link = urlsplit(base)
    if link.scheme != 'https' or not link.hostname or link.username or link.password or link.path or link.query or link.fragment:
        return ''
    return base + path


def build_message(config, address, context, message_id):
    context = {**context, 'logo': 'cid:makken-brand', 'sender_name': config.sender_name}
    msg = EmailMessage()
    msg['Subject'] = 'مكّن | ' + context['title']
    msg['From'] = formataddr((config.sender_name, config.sender))
    msg['To'] = address
    msg['Message-ID'] = message_id
    msg.set_content(render_to_string('makken_mail/email.txt', context))
    msg.add_alternative(render_to_string('makken_mail/email.html', context), subtype='html')
    logo = (Path(__file__).parent / 'static/makken_mail/logo-email.png').read_bytes()
    msg.get_payload()[-1].add_related(logo, maintype='image', subtype='png', cid='<makken-brand>',
                                    filename='makken.png', disposition='inline')
    return msg


@sensitive_variables()
def send(config, address, context, message_id):
    if not ready(config):
        raise SendFailure('config')
    try:
        host = clean_host(config.host)
        validate_email(config.sender)
        validate_email(address)
    except ValidationError as exc:
        raise SendFailure('config') from exc
    secret = decrypt(config.secret)
    if config.username and not secret:
        raise SendFailure('config')
    endpoints = smtp_endpoints(host, config.port)
    server = None
    in_delivery = False
    try:
        message = build_message(config, address, context, message_id)
        cert = ssl.create_default_context()
        cert.minimum_version = ssl.TLSVersion.TLSv1_2
        server = (PublicTLS(context=cert, timeout=8) if config.security == 'tls' else PublicStartTLS(timeout=8))
        server.endpoints = endpoints
        # connect() without a constructor host does not set smtplib's SNI
        # name; keep the configured name while the socket uses a pinned IP.
        server._host = host
        code, _ = server.connect(host, config.port)
        if code != 220:
            raise smtplib.SMTPConnectError(code, b'')
        server.ehlo_or_helo_if_needed()
        if config.security == 'starttls':
            server.starttls(context=cert)
            server.ehlo()
        if config.username:
            server.login(config.username, secret)
        in_delivery = True
        server.send_message(message, from_addr=config.sender, to_addrs=[address])
    except ssl.SSLError as exc:
        raise SendFailure('uncertain' if in_delivery else 'tls', unknown=in_delivery) from exc
    except smtplib.SMTPAuthenticationError as exc:
        raise SendFailure('auth', retry=400 <= exc.smtp_code < 500) from exc
    except smtplib.SMTPRecipientsRefused as exc:
        status = next(iter(exc.recipients.values()), (550, b''))[0]
        raise SendFailure('temporary' if 400 <= status < 500 else 'recipient', retry=400 <= status < 500) from exc
    except smtplib.SMTPResponseException as exc:
        temporary = 400 <= exc.smtp_code < 500
        raise SendFailure('temporary' if temporary else 'provider', retry=temporary) from exc
    except smtplib.SMTPNotSupportedError as exc:
        raise SendFailure('tls' if not in_delivery and config.security == 'starttls' else 'provider') from exc
    except OSError as exc:
        raise SendFailure('uncertain' if in_delivery else 'network', retry=not in_delivery, unknown=in_delivery) from exc
    finally:
        if server:
            try:
                server.close()
            except OSError:
                pass
