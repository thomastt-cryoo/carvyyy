# Photo Relief Studio setup

This guide accompanies test candidates. A public download service and signed application will be identified with the commercial release.

Choose the Windows x64 ZIP for an Intel or AMD 64-bit Windows 11 computer. Choose the macOS arm64 ZIP for an Apple Silicon Mac running macOS 15. Other architectures are awaiting qualification.

Extract the ZIP into a normal folder before opening it. On Windows, open Photo Relief Studio.exe. On a Mac, open Photo Relief Studio.app. Your default browser opens the setup page. Stay connected to the internet during initial setup. The page shows the current operation and actual download bytes. Setup downloads the application and the Small AI model, verifies them, and then opens your studio.

If setup is interrupted, open the same launcher again. It resumes compatible downloaded files. If an error is shown, read the message and choose Retry setup. Cancel setup keeps completed downloads and your projects available for another attempt. Allow at least 4 GB of free space for installation and recovery. Exact measured download and disk requirements will accompany the qualified candidate.

After setup, reopen the launcher to use the application offline. Opening it again while it is running opens the existing studio. Closing the browser keeps the local process running for reopening. Signing out of the computer stops it.

Photos, depth edits, masks, and saved projects stay on your computer. On Windows, saved work is in Local AppData, PhotoRelief, PhotoReliefStudio, data, data. On macOS, saved work is in your home Library, Application Support, com.PhotoRelief.PhotoReliefStudio, data. The parent installation folders also contain the downloaded components. Use the project library to reopen saved work. Keep a backup of the data subfolder before removing or reinstalling the product.

To uninstall, close the application, remove the extracted launcher folder, and remove the PhotoReliefStudio application-data folder if you also want to remove downloaded components. Keep the data subfolder elsewhere if you want to retain your projects. Permanent removal of that subfolder removes your work.

Unsigned Mac test builds may be restricted by Gatekeeper. Test candidates have not completed Finder and Gatekeeper qualification. Use signed commercial builds for ordinary customer installation.

For an authorized unsigned Mac test, first verify the source and candidate checksum. After attempting to open the app, use System Settings, Privacy & Security, and the Open Anyway control if macOS offers it. This procedure still requires native qualification for this candidate. Apple explains the controls at https://support.apple.com/102445.

The complete setup includes the lightweight subject-isolation support, so the existing U2NETP method is available offline alongside transparency and manual masking. Larger depth-model packs remain separate from this default setup.

To return to an earlier installed version, quit the studio and open that version’s launcher. Saved projects use the same persistent data location. Keep the previous launcher ZIP until the newer version has been checked.
