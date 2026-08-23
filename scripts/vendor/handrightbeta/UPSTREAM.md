# Vendored upstream

- Package: `handrightbeta`
- Version: `8.7.0`
- Upstream repository: <https://github.com/Gsllchb/Handright>
- License: BSD 3-Clause (`LICENSE.txt`)
- Local modifications to the vendored runtime modules: none

The runtime modules were vendored so the Skill does not depend on the continued availability of a package index or reference web service. Project-specific orchestration and post-processing live outside this directory.

File integrity is recorded in `vendor-lock.json`. If a vendored file is changed, document the patch and update the lock instead of continuing to claim an unmodified copy.
