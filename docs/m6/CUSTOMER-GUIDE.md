# Start here — Photo Relief Studio

1. Download the ZIP for your computer. Choose **Windows x64** for Windows 11 on a 64-bit Intel or AMD computer. Choose **macOS arm64** for an Apple Silicon Mac with macOS 15 or later.
2. Extract the ZIP. On Windows, right-click the ZIP and choose **Extract All**, then open the extracted folder. On Mac, double-click the ZIP in Finder. Keep the extracted files together.
3. Double-click **Photo Relief Studio.exe** on Windows or **Photo Relief Studio.app** on Mac. The studio opens in your default browser.
4. Connect to the internet for first setup and have at least **4 GB free**. The setup page shows what is downloading, then verifies and installs the files. Keep the page open. If setup stops, choose **Retry setup**. You can also reopen the same launcher to resume.
5. When the studio opens, drop in a photo. You can generate depth, isolate the subject, edit the relief, save projects and export STL or OBJ offline. No Python, account or separate model download is needed.

## If your computer warns about the launcher

The Windows launcher is unsigned. Microsoft Defender SmartScreen may say it does not recognize the application. Check that the ZIP came from your seller's official download and that the version and checksum match the seller's release information. If Windows offers a continue option and you trust the download, follow its prompt. Smart App Control or a managed device policy may block opening it. Contact the seller or your administrator if that happens. [Microsoft guidance](https://learn.microsoft.com/windows/apps/package-and-deploy/smartscreen-reputation)

The Apple Silicon application is distributed without Developer ID signing or notarization. If macOS blocks it as an unidentified developer, first verify the download with the seller. After trying to open it once, go to **System Settings → Privacy & Security**, scroll to **Open Anyway**, and confirm **Open** if macOS offers those options. This exception applies to this app. If the option is missing or macOS reports damage or malware, contact the seller. [Apple's Open Anyway instructions](https://support.apple.com/102445)

## Reopen, update or keep a backup

Open the same launcher to get back to the studio, even when offline. Closing the browser tab leaves the local studio available. To stop it, open **Settings → Quit Photo Relief Studio** and wait for the confirmation.

For an update, quit the current studio, extract the new ZIP into its own folder and open its launcher. Keep the previous launcher and installed files. If setup for the new version fails, reopen the previous launcher. The project library uses the same data folder.

To back up your work, quit and copy the project data folder somewhere safe:

- Windows: `%LOCALAPPDATA%\PhotoRelief\PhotoReliefStudio\data\data`. Paste the path into the File Explorer address bar.
- Mac: `~/Library/Application Support/com.PhotoRelief.PhotoReliefStudio/data`. In Finder choose **Go → Go to Folder** and paste the path.

To remove the studio, quit it and remove the extracted launcher. To free the installed app and model space too, first back up the project data folder, then remove its parent installation folder. Keep that backup to retain your projects.
