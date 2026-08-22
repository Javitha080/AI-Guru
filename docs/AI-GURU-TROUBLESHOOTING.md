# AI Guru Troubleshooting Guide

Common issues and solutions for running AI Guru locally.

## Camera Not Detected / Permission Denied

**Symptoms**: The study session starts but the camera feed is black, or the app throws an OpenCV error.

**Solutions**:
- **Windows**: Go to Settings > Privacy & security > Camera. Ensure "Let desktop apps access your camera" is toggled ON.
- **macOS**: Go to System Settings > Privacy & Security > Camera. Ensure your terminal (or the AI Guru app) is checked.
- **Linux**: Ensure your user is in the `video` group: `sudo usermod -aG video $USER`. You must log out and log back in for this to take effect.
- **General**: Ensure no other application (Zoom, Chrome, OBS) is currently locking the camera hardware.

## Ollama Not Connecting

**Symptoms**: AI responses time out, or you see `ConnectionRefusedError` related to `127.0.0.1:11434`.

**Solutions**:
- Verify Ollama is running in the background (check your system tray or task manager).
- Open a terminal and run `ollama list`. If it fails, restart the Ollama service.
- Ensure the required model is pulled. Run `ollama pull llama3:8b` (or your chosen model).

## High CPU/GPU Usage

**Symptoms**: Computer fans spin loudly, system feels sluggish.

**Solutions**:
- Open **Settings > AI Models** and ensure you aren't running a model that exceeds your hardware tier.
- If using a laptop on battery, AI Guru's CV pipeline might strain the CPU. Plug into wall power or reduce the camera FPS in settings.
- Enable "Cloud Fallback" to offload processing to Groq or OpenAI.

## Database Locked Errors

**Symptoms**: Console shows `sqlite3.OperationalError: database is locked`.

**Solutions**:
- Ensure you are not running two instances of the backend server simultaneously.
- Close any external SQLite viewer apps (like DB Browser for SQLite) that might be locking the file.

## Remote Access Not Working

**Symptoms**: Parent dashboard URL fails to load.

**Solutions**:
- If using Cloudflare Tunnels, ensure your firewall isn't blocking outbound connections on port 7844.
- Check the backend logs for `cloudflared` process errors. You may need to manually install `cloudflared` if the auto-downloader fails.

## Frontend Build Failures

**Symptoms**: `npm run dev` fails with module errors.

**Solutions**:
- Delete the `node_modules` folder and `package-lock.json`.
- Run `npm cache clean --force`.
- Run `npm install` again. Ensure you are using Node.js v18 or newer.
