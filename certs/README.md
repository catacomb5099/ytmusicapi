Drop extra root CA certificates here as `*.pem` (gitignored) and they are appended to the image's
trust bundle at build time. Only needed behind a TLS-intercepting corporate proxy; on a normal
network leave this folder as it is.
