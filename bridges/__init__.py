"""astryx bridges — one platform, one module, one wire.

Each surface (whatsapp, telegram, discord) is a package module run as
`uvicorn bridges.<platform>:app` from the repo root. Shared machinery lives
in common.py; transcribe.py is the voice engine. A bridge file contains ONLY
its platform's translation.

Layout grammar (plan-14): the package stays FLAT; a subdirectory is earned
only when the package holds two or more mechanism FAMILIES that would
otherwise interleave (not merely ≥2 files). Today: one chat family
(whatsapp/telegram/discord + common + transcribe) plus two deliberately
independent loose scripts (gateway = federation door, geoloc = sensor
intake) — flat and legible. common.py is chat-family machinery, not
package-wide; see its docstring.
"""
