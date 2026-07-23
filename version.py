"""Single source of truth for the app version."""

__version__ = "1.3.2"

#: GitHub repo the updater checks, as "owner/name".
#: Must stay public — release assets on a private repo need authentication,
#: and a token shipped inside the exe would be extractable by anyone.
GITHUB_REPO = "dabloop/nickherMacro"

#: Bump this whenever the presets.json / settings.json layout changes in a way
#: older builds cannot read, so an update can warn instead of corrupting data.
DATA_VERSION = 2
