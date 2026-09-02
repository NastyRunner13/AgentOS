---
name: browser-automation
description: Robust multi-step web workflow: persistent authentication, form filling, media uploads, and post confirmation.
allowed-tools:
  - browser
  - files
  - computer
---

# Browser Automation & Social/Portal Posting Procedure

Use this skill for multi-step browser tasks requiring authentication, media uploads, or posting content.

## 1. Session Initialization
1. Ensure the browser is configured with persistent user data (`data/browser_profile`) or attached to Chrome via CDP.
2. Navigate to the target portal: `browser(action="navigate", url="<url>")`.
3. Snapshot page state: `browser(action="snapshot")`.
4. Verify authentication:
   - If a login form or captcha is detected, HALT and prompt the user to log in once so the session saves to the profile.
   - Do NOT attempt to brute-force or guess credentials.

## 2. Interaction & File Upload
1. Wait for interactive elements to be ready: `browser(action="wait", ref="<selector>", timeout=10)`.
2. Click the composition / create button: `browser(action="click", ref="<button-ref>")`.
3. If uploading media or an image:
   - Ensure the file exists locally via `files(action="read")`.
   - Call `browser(action="upload", ref="input[type=file]", path="<absolute-path>")`.
   - Wait 2–3 seconds for preview rendering.
4. Type text into the body editor: `browser(action="type", ref="<editor-ref>", text="<content>")`.

## 3. Post & Verification
1. Click the final submit/post button: `browser(action="click", ref="<post-button-ref>")`.
2. Wait for confirmation toast or URL change: `browser(action="wait", timeout=5)`.
3. Take a verification screenshot: `browser(action="screenshot", path="data/last_action_proof.png")`.
4. Only declare the task complete after the post appears in the feed or success confirmation is verified.
