"""Licensed under the Business Source License 1.1 — see ./LICENSE.

Bodycam team server (formerly the PrivacyHook control plane). Settings are
read as PRIVACYHOOK_CONTROLPLANE_*; BODYCAM_SERVER_* and BODYCAM_* work too."""

import os as _os

for _key, _value in list(_os.environ.items()):
    if _key.startswith("BODYCAM_SERVER_"):
        _os.environ.setdefault("PRIVACYHOOK_CONTROLPLANE_" + _key[len("BODYCAM_SERVER_"):], _value)
    elif _key.startswith("BODYCAM_"):
        _os.environ.setdefault("PRIVACYHOOK_" + _key[len("BODYCAM_"):], _value)
