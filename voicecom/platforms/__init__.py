import platform

from .base import Automation, DryRun, Element


def get_automation(warn: bool = True) -> Automation:
    system = platform.system()
    if system == "Darwin":
        from .macos import MacAutomation

        return MacAutomation(warn)
    raise SystemExit(
        f"voicecom-jev only has a macOS automation layer so far (detected {system}). "
        "Add one by implementing voicecom/platforms/base.py:Automation."
    )


def check_permissions(prompt: bool = True, open_settings: bool = True) -> bool:
    """Print which OS permissions are granted, requesting missing ones. True if all are granted."""
    if platform.system() == "Darwin":
        from .macos_permissions import report

        return report(prompt, open_settings)
    print("No permission check for this OS.")
    return True


__all__ = ["Automation", "DryRun", "Element", "check_permissions", "get_automation"]
