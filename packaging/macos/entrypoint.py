"""macOS app entry; launch is local-only and never performs a check-in."""

from swu_checkin.desktop import main

raise SystemExit(main())
