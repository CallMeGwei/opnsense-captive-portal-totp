# Captive Portal: TOTP-based Guest Access for OPNsense

Replaces OPNsense's built-in voucher system with a shared TOTP (Time-based One-Time Password) authenticator. An admin adds a single TOTP secret to their phone; guests ask for the current 6-digit code and enter it on a clean, dark, unbranded portal page. A valid code grants 1 week of network access.

## How it works

1. A shared TOTP secret is stored on the firewall at `/usr/local/etc/captiveportal_totp.conf`.
2. The admin adds this secret to any standard authenticator app (Google Authenticator, Authy, etc.).
3. When a guest connects to the network, the captive portal presents a minimal dark page with a single 6-digit code input.
4. The guest asks the admin for the current code, enters it, and gets 1 week (604,800 seconds) of access.
5. The code changes every 30 seconds (standard TOTP), so a code can't be reused after it expires.

## Files

```
captive-portal-totp/
  get.py                  # Bootstrap script for curl-pipe install
  install.py              # Installer (install, remove, gen-secret, build-zip)
  SharedTOTP.php          # OPNsense auth connector (the core logic)
  portal/
    index.html            # Custom captive portal page
    css/
      signin.css          # Dark minimal stylesheet
```

## Installation

One-liner (downloads files to a temp directory and runs the installer):

```sh
curl -sL https://raw.githubusercontent.com/CallMeGwei/captive-portal-totp/main/get.py | python3
```

Or clone and run manually:

```sh
cd /tmp
git clone https://github.com/CallMeGwei/captive-portal-totp.git
cd captive-portal-totp
python3 install.py
```

The installer will:

1. Copy `SharedTOTP.php` into OPNsense's auth connector directory.
2. Generate a TOTP secret (if one doesn't already exist) and print the `otpauth://` URI.
3. Add a `sharedtotp` auth server entry to `/conf/config.xml`.
4. Update the captive portal zone to use the new auth server.
5. Embed the custom portal page as a template overlay in `config.xml` (survives template reloads and upgrades).
6. Reload templates and restart the captive portal.

After installation, add the printed `otpauth://` URI to your authenticator app. You can enter it manually — the secret is a standard base32 string.

## Uninstallation

```sh
python3 install.py --remove

# Or via curl:
curl -sL https://raw.githubusercontent.com/CallMeGwei/captive-portal-totp/main/get.py | python3 - --remove
```

This restores the zone to `voucher server` auth, removes the auth connector, template, and TOTP secret, and restarts the captive portal.

## Regenerating the TOTP secret

```sh
python3 install.py --gen-secret
```

This generates a new random secret, overwrites the config file, and prints the new `otpauth://` URI. You'll need to update your authenticator app with the new secret.

## Building a template zip for the GUI

If you prefer to upload the portal template manually through the OPNsense web UI instead of using the installer:

```sh
python3 install.py --build-zip
```

This creates `portal_template.zip` in the project directory, which can be uploaded under **Services > Captive Portal > Templates**.

## Architecture

### Auth connector: `SharedTOTP.php`

- Extends `OPNsense\Auth\Base`, implements `IAuthConnector`
- Uses the existing `TOTP` trait for RFC 6238 code validation (`authTOTP()`, `calculateToken()`, `timesToCheck()`)
- Type: `sharedtotp` (auto-discovered by `AuthenticationFactory` via filesystem glob)
- Ignores the username field — only validates the password as a 6-digit TOTP code
- Reads the shared secret from `/usr/local/etc/captiveportal_totp.conf`
- On success, sets `session_timeout = 604800` in auth properties (1 week)
- The captive portal's `AccessController` picks up `session_timeout` and passes it to the session manager

### Portal template

The custom HTML/CSS is embedded as a base64-encoded zip file in `config.xml` under `<captiveportal><templates>`. On every captive portal restart, OPNsense:

1. Deploys the default template from `htdocs_default/`
2. Overlays any user template from the config on top

This means the custom page **survives OPNsense upgrades and template reloads**, unlike directly modifying files in `htdocs_default/`.

### config.xml changes

Two changes are made:

1. A new `<authserver>` under `<system>`:
   ```xml
   <authserver>
     <refid>...</refid>
     <type>sharedtotp</type>
     <name>TOTP Guest Access</name>
   </authserver>
   ```

2. The captive portal zone's `<authservers>` changed from `voucher server` to `TOTP Guest Access`, and its `<template>` set to the UUID of the embedded template.

## Important notes

### File permissions

The TOTP secret file **must be readable by the `wwwonly` user** (uid 789). The captive portal's PHP-CGI processes run as `wwwonly`, not `www`. If the file is unreadable, authentication will silently fail (the auth connector logs `SharedTOTP: cannot read secret` to syslog).

Correct permissions:
```
-rw-r----- root wwwonly /usr/local/etc/captiveportal_totp.conf
```

The installer sets this automatically.

### Security considerations

- The TOTP secret is a shared secret — anyone with access to it can generate valid codes. Protect the config file.
- TOTP codes are valid for ~30 seconds (with a 10-second grace period for clock drift), so a stolen code has a very short window.
- The same code can be used by multiple guests within its validity window. This is by design — you give guests the current code and it works for anyone who enters it in time.
- Sessions last 1 week. After that, the guest must get a new code.
- OPNsense's `Base::authenticate()` applies a 2-second timing penalty on failed attempts to resist brute-force attacks.

### Debugging

Check the portal auth log:
```sh
cat /var/log/portalauth/latest.log
```

Check for PHP/auth errors:
```sh
grep SharedTOTP /var/log/system/latest.log
```

Test the auth connector from the command line:
```sh
php -r "
require_once '/usr/local/opnsense/mvc/script/load_phalcon.php';
\$f = new OPNsense\Auth\AuthenticationFactory();
\$a = \$f->get('TOTP Guest Access');
\$code = \$a->testToken(trim(file_get_contents('/usr/local/etc/captiveportal_totp.conf')));
echo 'Code: ' . \$code . '\n';
echo 'Auth: ' . (\$a->authenticate('guest', \$code) ? 'OK' : 'FAIL') . '\n';
"
```

### Compatibility

Developed and tested on OPNsense 26.1 (FreeBSD 14.3). The auth connector follows OPNsense's standard `IAuthConnector` interface and should work on any OPNsense version that uses the same auth framework.
