# AI Guru AI Models Guide

AI Guru intelligently routes queries between local and cloud-based Large Language Models (LLMs) to balance privacy, latency, and capability.

## Hardware Profiling

AI Guru automatically profiles your system on first startup and assigns a hardware tier.

- **LOW**: CPU only, <16GB RAM. Emphasizes highly quantized, small parameter models.
- **MEDIUM**: Entry-level GPU or Apple M1/M2, 16GB+ RAM. Balances speed and capability.
- **HIGH**: Dedicated high-end GPU or Apple M-series Max, 32GB+ RAM. Runs large models uncompromised.

## Recommended Ollama Models

For the best purely local experience, ensure Ollama is installed and run the following based on your tier:

| Tier | Recommended Model | Command |
|------|-------------------|---------|
| LOW | Phi-3 Mini (4-bit) | `ollama pull phi3:mini` |
| MEDIUM | Llama-3 8B | `ollama pull llama3:8b` |
| HIGH | Mistral / Mixtral | `ollama pull mistral:instruct` |

## Cloud Provider Setup

If local inference is too slow or insufficient for complex tutoring tasks, you can fallback to cloud providers:
1. Obtain an API key from OpenAI, Anthropic, or Groq.
2. Enter the key in the AI Guru **Settings > AI Models** tab.
3. Keys are stored locally and never transmitted to our servers.

## Auto-Fallback Chain

AI Guru utilizes an intelligent fallback chain:
1. **Primary**: Local Ollama (Zero latency, maximum privacy).
2. **Secondary**: Cloud Provider (e.g., Groq for high-speed inference).
3. **Tertiary**: Cloud Provider (e.g., OpenAI/Anthropic for complex reasoning).

If the local model times out or returns a malformed response, the system seamlessly retries the next provider in the chain.

## Model Quantization

To save RAM, local models run using 4-bit or 8-bit quantization by default. While this slightly reduces theoretical accuracy, it dramatically improves token generation speed and reduces thermal load on the host machine.

## Resource Governor

The internal `ResourceGovernor` monitors CPU and GPU temperatures and usage. If the system approaches thermal throttling while compiling code or running heavy apps, AI Guru will automatically down-throttle the LLM generation speed or temporary switch to the cloud provider to prevent system crashes.
