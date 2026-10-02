# Native runtime license originals

These are unchanged upstream files for the pinned official Python **3.13.15**
runtime and its Tcl/Tk libraries. `SOURCES.json` records the exact source URL and
SHA256 of each original. The CPython source license and documentation notices
are retained together; the installed official runtime's original `LICENSE.txt`
is also retained when available. Python is frozen without changes to its source.

The official Windows runtime provides Tcl/Tk **8.6.15**; the official macOS
runtime provides **8.6.18**. The collector reads the actual Tcl patch level and
Tk startup script before choosing their notices. Runtime updates require an
explicit source/hash update. macOS's OpenSSL **3.0.21**, SQLite **3.50.4**, XZ
**5.2.3** and NCurses **6.5** selections are documented by the original
[CPython installer recipe](https://github.com/python/cpython/blob/v3.13.15/Mac/BuildScript/build-installer.py).
The NCurses file was extracted from the official GNU archive after verifying
archive SHA256 `136d91bc269a9a5785e5f9e980bc76ab57428f604ce3e5a5a90cebc767971cc6`.
XZ's original notice distinguishes the public-domain liblzma library from tools
with other licenses; this application does not distribute the xz command tools.

`packaging/license_inventory.py` copies actual installed wheel license, copyright
and notice files without rewriting them, including nested third-party notices.
The generated `LICENSE-INVENTORY.json` lists every collected component/version,
file path, original source and SHA256. Missing component notices or changed
originals fail the build. Wheel notices cover their own bundled native libraries
independently of the Python runtime above.

The FlatBuffers **25.12.19** wheel omits its LICENSE. For this exact version,
the collector includes the hash-pinned original from the upstream release tag
and the actual wheel's unchanged copyright-bearing `flatbuffers/__init__.py`.
An unreviewed new version cannot silently reuse this exception.

Windows bundles these files under `_internal/build-info/`; macOS bundles them
under `SWUCheckin.app/Contents/Resources/build-info/`. The same inventory is
provided alongside each distribution and covered by its checksum manifest.
The project MIT `LICENSE` is bundled separately. This inventory records the
materials in the actual build, rather than substituting a generic license name.
