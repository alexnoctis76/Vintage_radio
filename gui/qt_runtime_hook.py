"""
Runtime hook for PyInstaller to fix Qt bundle detection on macOS.
This runs before Qt is imported to set up the environment properly.
"""
import os
import sys

if sys.platform == 'darwin':
    # Get the path to the .app bundle
    if hasattr(sys, '_MEIPASS'):
        # We're running from a PyInstaller bundle
        # sys.executable is the path to the executable inside the bundle
        # Go up: MacOS -> Contents -> .app bundle root
        bundle_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(sys.executable))))
        
        # Ensure we have the full .app path
        if not bundle_path.endswith('.app'):
            # Try to find the .app bundle by going up one more level
            parent = os.path.dirname(bundle_path)
            if parent.endswith('.app'):
                bundle_path = parent
        
        # Set environment variables that Qt uses to find the bundle
        # This helps Qt's CFBundleCopyBundleURL find the bundle
        if bundle_path.endswith('.app'):
            # Set the bundle identifier path
            os.environ['QT_BUNDLE_PATH'] = bundle_path
            
            # Set plugin paths (Qt will look here for plugins)
            plugin_path = os.path.join(bundle_path, 'Contents', 'MacOS', 'PyQt6', 'Qt6', 'plugins')
            if os.path.exists(plugin_path):
                os.environ.setdefault('QT_PLUGIN_PATH', plugin_path)
            
            # Help Qt find resources
            resources_path = os.path.join(bundle_path, 'Contents', 'Resources')
            if os.path.exists(resources_path):
                os.environ.setdefault('QT_RESOURCE_PATH', resources_path)

