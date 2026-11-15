.PHONY: dependencies python-dependencies native-dependencies

dependencies: python-dependencies native-dependencies

python-dependencies:
	uv sync

ifeq ($(OS),Windows_NT)
native-dependencies:
	@winget list --id charmbracelet.glow --exact --accept-source-agreements | findstr /I /C:"charmbracelet.glow" || winget install --id charmbracelet.glow --exact --accept-source-agreements --accept-package-agreements
	@winget list --id Ollama.Ollama --exact --accept-source-agreements | findstr /I /C:"Ollama.Ollama" || winget install --id Ollama.Ollama --exact --accept-source-agreements --accept-package-agreements
else
native-dependencies:
	@command -v glow >/dev/null 2>&1 || { echo "Install Glow with your package manager."; exit 1; }
	@command -v ollama >/dev/null 2>&1 || { echo "Install Ollama with your package manager."; exit 1; }
endif
