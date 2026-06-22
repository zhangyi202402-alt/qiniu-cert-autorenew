# Security Policy

## Reporting a Vulnerability

Please **do not** open public GitHub issues for security vulnerabilities.

Use [GitHub Private vulnerability reporting](https://github.com/security/advisories) on this repository, or contact the maintainers at [Kalading](https://www.kalading.com)（北京卡拉丁汽车技术服务有限公司, author: zhangyi）.

## Handling Secrets

- Do **not** paste AccessKey, SecretKey, or webhook URLs in issues or pull requests.
- Keep credentials in `.env` (gitignored) or environment variables referenced as `${VAR}` in YAML.
- Never commit `config.yaml`, `.env`, or `.local/` (contains ACME private keys).

## Recommended Practices

- Use Qiniu RAM sub-accounts with minimum required permissions.
- Rotate keys if you suspect exposure.
- Test with Let's Encrypt staging (`letsencrypt_test`) before switching to production CA.
