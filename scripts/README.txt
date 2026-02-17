========================================
Vintage Radio - macOS First Run
========================================

macOS blocks unsigned apps. Follow these steps:

STEP 1 - Remove Quarantine (Terminal):
1. Open Terminal (Press Cmd+Space, type "Terminal", press Enter)
2. Copy and paste this command (adjust path if needed):
   
   cd ~/Downloads/Vintage-Radio-macOS && xattr -dr com.apple.quarantine "Vintage Radio.app"
   
3. Press Enter

STEP 2 - Allow in System Settings:
1. Try to open "Vintage Radio.app" (double-click it)
2. You'll see: "Vintage Radio cannot be opened because the developer cannot be verified"
3. Click "OK"
4. Open System Settings (or System Preferences on older macOS)
5. Go to: Privacy & Security
6. Scroll down - you should see: "Vintage Radio was blocked..."
7. Click "Open Anyway" button next to it
8. Confirm by clicking "Open" in the dialog
9. Now double-click "Vintage Radio.app" again - it should launch!

After this one-time setup, you can just double-click the app normally.

TROUBLESHOOTING - If the app crashes:
1. Open Terminal
2. Navigate to the app folder: cd ~/Downloads/Vintage-Radio-macOS
3. Run the app from Terminal to see error messages:
   "./Vintage Radio.app/Contents/MacOS/Vintage Radio"
4. Share the error message for support

Note: This is required because the app isn't code-signed by Apple.
Code signing requires an Apple Developer account ($99/year).

========================================

