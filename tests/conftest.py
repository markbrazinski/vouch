"""Suite-wide test configuration.

The retry path backs off before re-calling a throttled model. That is right in
production and pure wall-clock in a test, so the backoff is zero here. The
value is read through `vouch.config.env_var`, so this needs no clock patching
and leaves the real default in place everywhere else.
"""

import os

os.environ.setdefault("VOUCH_THROTTLE_BACKOFF_SECONDS", "0")
