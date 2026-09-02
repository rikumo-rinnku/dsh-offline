================================================================================
  DeepSeek Harness - Offline Desktop Edition  (for Windows x64)
================================================================================

What is this?
-------------
A ready-to-run, "unzip and double-click" distribution of DeepSeek Harness.
No need to install Node.js, Python, pnpm or any dev tools.  No command line.
Everything runs locally on your own PC.


Minimum Requirements
--------------------
  * Windows 10 x64  (version 1903+)  or  Windows 11 x64
  * ~3 GB free disk space  (unpacked)   ~800 MB for the downloaded .7z file
  * A DeepSeek API key  (or compatible OpenAI-format API endpoint + key) -
    required by the AI features once the Web UI is open.


How to use (3 steps)
--------------------
  1. Unpack this whole folder to any location, e.g.  D:\dsh-offline\
     IMPORTANT: Do NOT move, rename or delete any of the sub-folders.
     All folders (runtime\, dsh-core\, launcher\, logs\) must live next to
     start.bat.

  2. Double-click  start.bat
     A desktop window titled "DSH启动器" will appear.
     (If nothing appears after 10 seconds, see Troubleshooting below.)

  3. Inside the launcher window:
       - Click the big green button "一键启动 DeepSeek Harness"
       - Wait 10-30 seconds.  Your default browser opens automatically when
         the Web UI is ready at  http://127.0.0.1:3080
       - Use Harness as normal in your browser.
       - When done, click "停止引擎" or just close the launcher window
         (you'll be asked whether to stop the engine or leave it running in
         the background).


Launcher Window Buttons
-----------------------
  [一键启动 DeepSeek Harness]     Starts the local engine and opens the UI.
  [停止引擎]                      Shuts down the local engine cleanly.
  [重新打开 Web UI]              Re-opens the browser to the running UI.
  [清空]                         Clears the on-screen log panel.
  [打开工作目录]                 Opens this folder in Windows Explorer.
  [查看日志文件夹]               Opens logs\ so you can inspect history.


First-Time Setup inside the Web UI
----------------------------------
After the browser opens to http://127.0.0.1:3080 :

  1. Open Settings (usually a gear icon in the lower-left corner).
  2. Go to  Model / Provider  settings.
  3. Add your DeepSeek API key.  (You can also switch to any
     OpenAI-API-compatible provider.)
  4. Save.  You are now ready to chat with the agent.

  The API key is stored locally under  logs\ / user data directory -
  nothing is ever uploaded to our servers.


Troubleshooting
---------------
* Symptom:  Nothing happens after I double-click start.bat.
  Reason:   Your antivirus blocked pythonw.exe or node.exe.
  Fix:      Open your antivirus settings and add this whole folder to
            "exclusions", then try again.  (You can also temporarily disable
            the shield and try once to confirm.)

* Symptom:  A black box pops up with "[ERROR] ... not found" and then
            pauses.
  Reason:   The folder layout is broken (a sub-folder is missing).
  Fix:      Re-unpack the .7z file into a brand new empty folder.
            Do NOT drag individual files out of the package.

* Symptom:  Launcher window appears, but clicking Start reports an error
            inside the log panel such as "Cannot find package ...".
  Reason:   Antivirus deleted parts of dsh-core\node_modules during unpack.
  Fix:      Restore quarantined items from AV history, or re-unpack with
            AV paused.

* Symptom:  Browser opens but shows page "This site can't be reached"
            (connection refused on port 3080).
  Reason:   Engine did not finish booting yet, or port 3080 is taken by
            another program.
  Fix:      Wait 30 more seconds and press "重新打开 Web UI".  The launcher
            automatically tries ports 3080, 3081, 3082...  The status card
            on the launcher always shows the actual URL.

* Symptom:  The launcher closes unexpectedly.
  Reason:   Python / Tk runtime crash on an old Windows build.
  Fix:      Make sure Windows is fully updated (at least Win 10 1903), then
            try again.


Folder Structure (for reference)
--------------------------------
  start.bat                  <- Double-click this entry point
  runtime\node\              <- Portable Node.js v22 (pre-bundled)
  runtime\python\            <- Portable Python 3.10 + customtkinter
  launcher\                  <- Tkinter GUI source code
  dsh-core\                  <- DeepSeek Harness engine + pre-built deps
  logs\                      <- Engine log files  (dsh-engine-YYYYMMDD.log)


Credits & License
-----------------
DeepSeek Harness is open source under the MIT License.
See:  https://github.com/deepseek-ai/deepseek-harness

This offline distribution packages Harness together with official
portable builds of Node.js and Python (both freely redistributable).
No source code has been modified.

================================================================================
