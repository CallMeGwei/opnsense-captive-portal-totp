#!/usr/bin/env python3
"""Installer for TOTP-based captive portal guest access on OPNsense.

Usage:
    python3 install.py              Install everything
    python3 install.py --remove     Uninstall and restore voucher auth
    python3 install.py --gen-secret Regenerate the TOTP secret
    python3 install.py --build-zip  Build portal_template.zip for manual GUI upload
"""

import argparse
import base64
import os
import shutil
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOTP_CONF = '/usr/local/etc/captiveportal_totp.conf'
CONFIG_XML = '/conf/config.xml'
AUTH_CONNECTOR_DEST = '/usr/local/opnsense/mvc/app/library/OPNsense/Auth/SharedTOTP.php'


def gen_secret():
    """Generate a TOTP secret and write it to the config file."""
    secret_bytes = os.urandom(20)
    base32_secret = base64.b32encode(secret_bytes).decode('ascii')

    with open(TOTP_CONF, 'w') as f:
        f.write(base32_secret + '\n')

    os.chmod(TOTP_CONF, 0o640)
    os.system(f'chown root:wwwonly {TOTP_CONF}')

    issuer = 'OPNsense-CaptivePortal'
    account = 'guest'
    uri = (
        f'otpauth://totp/{issuer}:{account}'
        f'?secret={base32_secret}&issuer={issuer}&digits=6&period=30'
    )

    print(f'TOTP Secret (base32): {base32_secret}')
    print()
    print('otpauth URI (add to authenticator app):')
    print(uri)


def backup_config():
    """Create a timestamped backup of config.xml."""
    shutil.copy2(CONFIG_XML, CONFIG_XML + '.bak.' + str(int(time.time())))


def update_config():
    """Add SharedTOTP auth server to config.xml and update the captive portal zone."""
    backup_config()

    tree = ET.parse(CONFIG_XML)
    root = tree.getroot()
    system = root.find('system')

    existing = False
    for authserver in system.findall('authserver'):
        t = authserver.find('type')
        if t is not None and t.text == 'sharedtotp':
            existing = True
            name_el = authserver.find('name')
            auth_name = name_el.text if name_el is not None else 'TOTP Guest Access'
            print(f'SharedTOTP authserver already exists: {auth_name}')
            break

    if not existing:
        new_auth = ET.SubElement(system, 'authserver')
        ET.SubElement(new_auth, 'refid').text = (
            format(int(time.time()), 'x') + uuid.uuid4().hex[:5]
        )
        ET.SubElement(new_auth, 'type').text = 'sharedtotp'
        ET.SubElement(new_auth, 'name').text = 'TOTP Guest Access'
        print('Added SharedTOTP authserver: TOTP Guest Access')

    cp = root.find('.//captiveportal')
    if cp is not None:
        zones = cp.find('zones')
        if zones is not None:
            for zone in zones.findall('zone'):
                authservers = zone.find('authservers')
                if authservers is not None:
                    old_val = authservers.text
                    authservers.text = 'TOTP Guest Access'
                    print(f'Updated zone authservers: {old_val} -> TOTP Guest Access')

    tree.write(CONFIG_XML, xml_declaration=True, encoding='UTF-8')
    print('config.xml updated successfully')


def embed_template():
    """Create portal template zip and embed it in config.xml."""
    with open(os.path.join(SCRIPT_DIR, 'portal', 'index.html'), 'r') as f:
        index_html = f.read()
    with open(os.path.join(SCRIPT_DIR, 'portal', 'css', 'signin.css'), 'r') as f:
        signin_css = f.read()

    buf = BytesIO()
    with zipfile.ZipFile(buf, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('index.html', index_html)
        zf.writestr('css/signin.css', signin_css)

    zip_b64 = base64.b64encode(buf.getvalue()).decode('ascii')
    template_uuid = str(uuid.uuid4())

    tree = ET.parse(CONFIG_XML)
    root = tree.getroot()
    cp = root.find('.//captiveportal')
    if cp is None:
        print('ERROR: captiveportal section not found in config.xml')
        sys.exit(1)

    templates_el = cp.find('templates')
    if templates_el is None:
        templates_el = ET.SubElement(cp, 'templates')

    for old in list(templates_el):
        templates_el.remove(old)

    template_el = ET.SubElement(templates_el, 'template')
    template_el.set('uuid', template_uuid)
    ET.SubElement(template_el, 'fileid').text = template_uuid
    ET.SubElement(template_el, 'name').text = 'TOTP Dark Portal'
    ET.SubElement(template_el, 'content').text = zip_b64

    zones = cp.find('zones')
    if zones is not None:
        for zone in zones.findall('zone'):
            tmpl = zone.find('template')
            if tmpl is not None:
                tmpl.text = template_uuid
            else:
                tmpl = ET.SubElement(zone, 'template')
                tmpl.text = template_uuid

    tree.write(CONFIG_XML, xml_declaration=True, encoding='UTF-8')
    print(f'Template embedded (UUID: {template_uuid})')


def build_zip():
    """Build portal_template.zip for manual upload via OPNsense GUI."""
    output_path = os.path.join(SCRIPT_DIR, 'portal_template.zip')
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.write(os.path.join(SCRIPT_DIR, 'portal', 'index.html'), 'index.html')
        zf.write(os.path.join(SCRIPT_DIR, 'portal', 'css', 'signin.css'), 'css/signin.css')
    print(f'Created {output_path}')


def configctl(*args):
    """Run an OPNsense configctl command."""
    subprocess.run(['configctl'] + list(args), check=True)


def do_install():
    """Full installation."""
    print('=== Captive Portal TOTP Installer ===')
    print()

    print('[1/5] Installing SharedTOTP auth connector...')
    shutil.copy2(os.path.join(SCRIPT_DIR, 'SharedTOTP.php'), AUTH_CONNECTOR_DEST)
    print(f'      -> {AUTH_CONNECTOR_DEST}')

    if os.path.exists(TOTP_CONF):
        print(f'[2/5] TOTP secret already exists at {TOTP_CONF} — skipping generation.')
        print(f'      To regenerate: python3 {__file__} --gen-secret')
    else:
        print('[2/5] Generating TOTP secret...')
        gen_secret()
    print()

    print('[3/5] Updating config.xml (adding authserver, setting zone)...')
    update_config()
    print()

    print('[4/5] Embedding custom portal template in config.xml...')
    embed_template()
    print()

    print('[5/5] Reloading templates and restarting captive portal...')
    configctl('template', 'reload', 'OPNsense/Captiveportal')
    configctl('captiveportal', 'restart')
    print()

    print('=== Installation complete ===')
    print()
    print('Verify the portal page is served:')
    print('  head -5 /var/captiveportal/zone0/htdocs/index.html')
    print()
    print('If you need to regenerate the TOTP secret later:')
    print(f'  python3 {__file__} --gen-secret')
    print()
    print('The otpauth:// URI printed above (step 2) can be manually entered')
    print('into any TOTP authenticator app (Google Authenticator, Authy, etc.).')


def do_remove():
    """Uninstall and restore voucher auth."""
    print('=== Captive Portal TOTP Uninstaller ===')
    print()

    print('[1/4] Restoring zone auth to voucher server...')
    backup_config()

    tree = ET.parse(CONFIG_XML)
    root = tree.getroot()

    cp = root.find('.//captiveportal')
    if cp is not None:
        zones = cp.find('zones')
        if zones is not None:
            for zone in zones.findall('zone'):
                a = zone.find('authservers')
                if a is not None:
                    a.text = 'voucher server'
                t = zone.find('template')
                if t is not None:
                    t.text = ''
        templates = cp.find('templates')
        if templates is not None:
            for old in list(templates):
                templates.remove(old)

    system = root.find('system')
    for authserver in list(system.findall('authserver')):
        t = authserver.find('type')
        if t is not None and t.text == 'sharedtotp':
            system.remove(authserver)

    tree.write(CONFIG_XML, xml_declaration=True, encoding='UTF-8')
    print('config.xml restored')

    print('[2/4] Removing SharedTOTP auth connector...')
    if os.path.exists(AUTH_CONNECTOR_DEST):
        os.remove(AUTH_CONNECTOR_DEST)

    print('[3/4] Removing TOTP secret...')
    if os.path.exists(TOTP_CONF):
        os.remove(TOTP_CONF)

    print('[4/4] Reloading and restarting captive portal...')
    configctl('template', 'reload', 'OPNsense/Captiveportal')
    configctl('captiveportal', 'restart')

    print()
    print('=== Uninstall complete. Captive portal restored to voucher auth. ===')


def main():
    parser = argparse.ArgumentParser(
        description='Installer for TOTP-based captive portal guest access on OPNsense.',
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        '--remove', action='store_true',
        help='uninstall and restore voucher auth',
    )
    group.add_argument(
        '--gen-secret', action='store_true',
        help='regenerate the TOTP secret',
    )
    group.add_argument(
        '--build-zip', action='store_true',
        help='build portal_template.zip for manual GUI upload',
    )

    args = parser.parse_args()

    if args.remove:
        do_remove()
    elif args.gen_secret:
        gen_secret()
    elif args.build_zip:
        build_zip()
    else:
        do_install()


if __name__ == '__main__':
    main()
