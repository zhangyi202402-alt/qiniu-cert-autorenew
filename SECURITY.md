# Security Policy

## Reporting a Vulnerability

Please **do not** open public GitHub issues for security vulnerabilities.

Use [GitHub Private vulnerability reporting](https://github.com/security/advisories) on this repository, or contact the maintainers privately.

## Handling Secrets

- Do **not** paste AccessKey, SecretKey, or webhook URLs in issues or pull requests.
- Keep credentials in `.env` (gitignored) or environment variables referenced as `${VAR}` in YAML.
- Never commit `config.yaml`, `config.docker.yaml`, or `.env`.

## Recommended Practices

- Use Qiniu RAM sub-accounts with minimum required permissions.
- Rotate keys if you suspect exposure.
- Test with Let's Encrypt staging (`letsencrypt_test`) before switching to production CA.
