# Security policy

## Supported version

Security fixes are applied to the latest release on the default branch.

## Reporting

Use GitHub Private Vulnerability Reporting when it is enabled for the repository. Do not publish exploit details or sensitive sample files in a public issue.

## Input risks

The CLI processes fonts, raster images, JSON/CSV/TXT, and large canvases through Pillow and FreeType. Treat fonts and images from unknown sources as untrusted. Run them in a constrained environment, keep Pillow updated within the tested range, and retain the existing canvas/font-count limits.

The bundled font loader checks path containment, registered-file membership, font SHA-256, license SHA-256, and duplicate IDs before rendering. Runtime code does not download fonts or send text to an external service.

Never include personal datasets or proprietary fonts in a vulnerability report. Reduce a reproducer to public-domain poetry and redistributable assets first.
