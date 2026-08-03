# Security Review Notes

## Removed Pinmux Tool metadata

The imported `boards/hpm5321_custom/tool_config.hpmpc` contained plaintext
fields named `clientKey` and `secretKey` and described an unrelated/stale
HPM5361 SDK 1.12.0 project. The file was removed rather than sanitized because
it was neither an authoritative regeneration source nor required to build.

The values were not committed by this repository change. Their service and
validity cannot be determined locally. If they are real credentials, revoke or
rotate them in the system that issued them; repository deletion alone does not
invalidate a credential.
