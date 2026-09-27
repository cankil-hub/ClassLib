"""Local development: never connects to the production database or bucket."""
from .settings import *  # noqa: F403

STORAGE_BACKEND = 'storage_backends.local.LocalStorage'
