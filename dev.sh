set -e

VENV_DIR=".venv"
STAMP="$VENV_DIR/.requirements_stamp"

PYTHON_CMD="python3"
if ! command -v python3 &> /dev/null; then
    PYTHON_CMD="python"
fi

if [ ! -d "$VENV_DIR" ]; then
    echo -e "\e[36mCreating virtual environment...\e[0m"
    $PYTHON_CMD -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

if [ ! -f "$STAMP" ] || [ requirements.txt -nt "$STAMP" ]; then
    echo -e "\e[36mRequirements changed - installing...\e[0m"
    if command -v uv &> /dev/null; then
        uv pip install -r requirements.txt
    else
        pip install -r requirements.txt
    fi
    touch "$STAMP"
else
    echo -e "\e[32mRequirements up to date — skipping install.\e[0m"
fi

echo -e "\e[32mStarting backend on http://localhost:8082 ...\e[0m"
uvicorn app:app --host 0.0.0.0 --port 8082 --reload
