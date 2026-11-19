#!/usr/bin/env bash
# Alma setup. From a fresh clone: ./setup.sh && ./brain init /path/to/notes && ./brain ask "..."
set -euo pipefail

ENGINE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! "$ENGINE/bin/brain" setup; then
  echo "Alma: venv setup failed. On Debian/Ubuntu: sudo apt install python3-venv" >&2
  exit 1
fi

mkdir -p "$HOME/.local/bin"
ln -sfn "$ENGINE/bin/brain" "$HOME/.local/bin/brain"
ln -sfn bin/brain "$ENGINE/brain"

path_line='export PATH="$HOME/.local/bin:$PATH"'
for rc in "$HOME/.bashrc" "$HOME/.profile"; do
  if [ -f "$rc" ] && grep -Fqs '.local/bin' "$rc"; then
    continue
  fi
  if [ -w "$rc" ] || [ ! -e "$rc" ]; then
    printf '\n# Alma\n%s\n' "$path_line" >> "$rc"
  fi
done

echo "Alma: linked brain to $HOME/.local/bin/brain and ./brain"
echo "Alma: this terminal does not see ~/.local/bin yet. Use ./brain here. Open a new terminal to use brain."
echo 'Alma: next: ./brain init /path/to/your/notes'
