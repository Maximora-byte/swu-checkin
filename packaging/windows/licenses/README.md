# Tcl license included in portable archives

`Tcl-8.6.15-LICENSE.txt` is the unchanged license from the upstream Tcl 8.6.15 tag:
https://github.com/tcltk/tcl/blob/core-8-6-15/license.terms

SHA256: `c0a69a2bfd757361ec7e6143973b103c90409316b49e9c88db26ad6388e79f16`

The pinned Windows Python 3.13.15 build supplies Tcl 8.6.15. The published v2.0.0
release provided this license as a separate asset. Portable ZIPs built from the
current source include it inside their root so it travels with the application;
that does not change the contents of the existing v2.0.0 release. New builds
also include actual runtime and wheel originals under `_internal/build-info/`,
with an auditable `LICENSE-INVENTORY.json` supplied inside the application and
alongside its distribution. The shared collector includes Tk 8.6.15 separately,
preserves the official Python 3.13.15 license and nested wheel notices, and fails
when a component has no original notice. See the
[native license sources](../../licenses/README.md) and
[release readiness](../../../docs/releases/release-readiness.md). This file
does not replace original third-party licenses or change historical assets.
