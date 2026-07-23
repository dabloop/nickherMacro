"""Single source of truth for the app version."""

__version__ = "1.1.0"

#: GitHub repo the updater checks, as "owner/name".
#: Set this once you have pushed the project; until then update checks are off.
GITHUB_REPO = ""

#: Bump this whenever the presets.json / settings.json layout changes in a way
#: older builds cannot read, so an update can warn instead of corrupting data.
DATA_VERSION = 2
