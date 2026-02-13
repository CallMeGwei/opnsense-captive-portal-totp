<?php

/*
 * SharedTOTP auth connector for captive portal guest access.
 * Validates a 6-digit TOTP code against a shared secret stored on disk.
 * Any valid code grants a 1-week session (604800 seconds).
 */

namespace OPNsense\Auth;

require_once 'base32/Base32.php';

class SharedTOTP extends Base implements IAuthConnector
{
    use TOTP {
        _authenticate as private _totpAuthenticate;
    }

    /**
     * @var string path to the shared TOTP secret file
     */
    private $configFile = '/usr/local/etc/captiveportal_totp.conf';

    /**
     * @var array auth properties returned after successful authentication
     */
    private $lastAuthProperties = [];

    /**
     * type name in configuration
     * @return string
     */
    public static function getType()
    {
        return 'sharedtotp';
    }

    /**
     * user friendly description of this authenticator
     * @return string
     */
    public function getDescription()
    {
        return gettext("Shared TOTP Guest Access");
    }

    /**
     * set connector properties
     * @param array $config connection properties
     */
    public function setProperties($config)
    {
        // 90-second grace period so guests have time to type the code
        $this->setTOTPProperties(['graceperiod' => 90]);
    }

    /**
     * return session info
     * @return array mixed named list of authentication properties
     */
    public function getLastAuthProperties()
    {
        return $this->lastAuthProperties;
    }

    /**
     * authenticate user against shared TOTP secret
     * Username is ignored — only the password (TOTP code) matters.
     * @param string $username username (ignored)
     * @param string $password 6-digit TOTP code
     * @return bool authentication status
     */
    protected function _authenticate($username, $password)
    {
        // password must be exactly 6 digits
        if (!preg_match('/^\d{6}$/', $password ?? '')) {
            return false;
        }

        // read shared secret from config file
        if (!file_exists($this->configFile)) {
            syslog(LOG_ERR, 'SharedTOTP: config file not found: ' . $this->configFile);
            return false;
        }

        $base32Secret = trim(file_get_contents($this->configFile));
        if (empty($base32Secret)) {
            syslog(LOG_ERR, 'SharedTOTP: cannot read secret (check file permissions for wwwonly user)');
            return false;
        }

        $binarySecret = \Base32\Base32::decode($base32Secret);

        if ($this->authTOTP($binarySecret, $password)) {
            // grant 1-week session
            $this->lastAuthProperties['session_timeout'] = 604800;
            return true;
        }

        return false;
    }

    /**
     * groups not applicable for shared TOTP
     * @param string $username username to check
     * @param string $gid group id
     * @return boolean
     */
    public function groupAllowed($username, $gid)
    {
        return false;
    }
}
