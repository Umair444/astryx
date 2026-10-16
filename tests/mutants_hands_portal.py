"""Authored mutants for the desk's display and portals (seed #57131), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_hands_portal.py

CONTAINMENT: a mutant that drops the owner-display scrub reddens a PURE arm, and the oracle then never requests a
chooser (one would land on the owner's screen). The mutants that keep the scrub are the only ones the live arm sees.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "src" / "astryx" / "hands" / "hands_desktop.py"
ORACLE = REPO / "tests" / "test_hands_portal.py"
ENV = "DESK_SRC"
TIMEOUT = 240

MUTANTS = {
    "the desk unit unsets nothing (the owner's display is inherited again)":
        ('           "-p", "UnsetEnvironment=" + " ".join(OWNER_SESSION_ENV),\n', ""),
    "WAYLAND_DISPLAY is left out of the scrub":
        ('OWNER_SESSION_ENV = ("WAYLAND_DISPLAY", "DISPLAY",', 'OWNER_SESSION_ENV = ("DISPLAY",'),
    "the desk counts as up before sway's display reaches its bus":
        ("exec sh -c 'dbus-update-activation-environment WAYLAND_DISPLAY SWAYSOCK && printf",
         "exec sh -c 'printf"),
    "the desk's config dir is not on its XDG_CONFIG_DIRS":
        ('''        "XDG_CONFIG_DIRS": f"{sd / 'xdg'}:/etc/xdg",\n''', ""),
    "FileChooser is not pinned to gtk":
        ("org.freedesktop.impl.portal.FileChooser=gtk\n", ""),
    "hyprland serves ScreenCast again":
        ("org.freedesktop.impl.portal.ScreenCast=none\n", "org.freedesktop.impl.portal.ScreenCast=hyprland\n"),
    "the portals.conf is never written (the pure text is right, the desk never reads it)":
        ('    (sd / "xdg" / "xdg-desktop-portal" / "sway-portals.conf").write_text(PORTALS_CONF)\n', ""),
}
