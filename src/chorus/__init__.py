"""chorus -- program Logitech Harmony remotes without Logitech.

An open-source replacement for the retired MyHarmony desktop software and
the Harmony cloud service.

Quick start::

    from chorus.usb.transport import open_remote
    from chorus.usb.remote import HarmonyRemote

    with open_remote() as transport:
        remote = HarmonyRemote(transport)
        print(remote.identify().summary())
        backup = remote.read_config()
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
