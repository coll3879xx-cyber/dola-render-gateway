# Dola Pro Engine (Chromium Extension)

This extension provides duration unlock (`15s`, `30s`) and master unwatermarked resource extraction for Dola and Doubao.

## Key Notes
1. **Incognito Mode**: If running in incognito or headless browser profiles, enable "Allow in Incognito" in `chrome://extensions/`.
2. **Prompt Guidelines**: When starting a new conversation for 30s generation, avoid putting duration words (e.g. "30s", "30 seconds") directly in the prompt text. The engine attaches duration capability via protocol.
3. **Mock Data**: `dola-skill-pack-response.json` and `doubao-skill-pack-response.json` are intercepted by the debugger to inject duration parameters.
