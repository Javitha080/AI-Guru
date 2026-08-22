# AI Guru Local Setup Guide

Welcome to the AI Guru installation and setup guide. This document covers system requirements, quick start procedures, and advanced development configurations.

## System Requirements

- **OS**: Windows 10/11, macOS 13+, or Ubuntu 22.04+
- **Python**: 3.10 or higher
- **Node.js**: 18.x or higher
- **Hardware (Minimum)**: 4 Core CPU, 8GB RAM, Webcam
- **Hardware (Recommended)**: 8 Core CPU, 16GB RAM, Dedicated GPU (NVIDIA RTX 3060+ or Apple Silicon M1/M2/M3), Webcam

## Quick Start (Production)

If you just want to run AI Guru locally:

```bash
# 1. Install via pip
pip install deeptutor

# 2. Start the server
deeptutor start
```

## Development Setup

For working on the AI Guru codebase:

```bash
# 1. Clone the repository
git clone https://github.com/example/deeptutor.git
cd deeptutor

# 2. Install Python backend dependencies
pip install -e '.[all]'

# 3. Setup Frontend
cd web
npm install

# 4. Start Development Servers
# Terminal 1: Backend
deeptutor start --dev

# Terminal 2: Frontend
npm run dev
```

## Ollama Setup (Local LLM)

AI Guru runs fully locally using Ollama.

1. Install Ollama from [ollama.com](https://ollama.com).
2. Start the Ollama background service.
3. Pull the recommended model for your hardware tier:

### Low Tier (CPU only, 8GB RAM)
```bash
ollama pull phi3:mini
```

### Medium Tier (M1/M2 or Entry GPU, 16GB RAM)
```bash
ollama pull llama3:8b
```

### High Tier (M2/M3 Max or High-end GPU, 32GB+ RAM)
```bash
ollama pull mistral:instruct
```

## OS-Specific Notes

### Windows
- Ensure you have MSVC build tools installed if building dependencies from source.
- Run terminal as Administrator if you encounter permission errors with the webcam.

### macOS
- You must grant Camera and Microphone permissions to your Terminal application (e.g., iTerm2 or Terminal.app) in System Settings > Privacy & Security.

### Linux
- Ensure your user is in the `video` group to access the webcam without root: `sudo usermod -aG video $USER`.

## Troubleshooting Common Install Issues

- **`node-gyp` errors**: Ensure Python 3 is in your path and you have build tools installed (`build-essential` on Linux, Visual Studio Build Tools on Windows).
- **Camera not detected**: Check if another application is using the camera. Close Zoom, Teams, or OBS.
- **SQLite errors**: Ensure the `deeptutor` folder has write permissions for the database creation.
