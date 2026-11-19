# Install Alma

Alma gives your agents context; it doesn't answer for them. Notes go into a semantic index. `brain mcp` exposes that index (tool `search_brain`). `brain hook-search` is the Claude Code UserPromptSubmit hook that injects the top passages into the user's message. `brain ask` only prints that context so you can debug the search.

For an agent following this repository from a fresh clone. Do not copy a demo corpus. Do not edit `teambrain.yaml` before the first run. Do not write the crontab, `.cursor/mcp.json`, or `~/.codex/config.toml` yourself. Do not install an LLM CLI and do not set `HF_TOKEN`.

`./brain init --yes` installs nightly jobs (incremental index, stale-doc lint, a local snapshot of `raw/`) with cron on Linux or launchd on macOS, and connects Claude Code when it is already on the machine. Pass `--no-schedule` to skip the jobs. Pass `--no-connect` to skip the MCP server and the prompt hook. If cron or launchd is missing, init prints one fix line and still exits 0. If Claude Code is not detected, init prints one line, then the Cursor and Codex snippets, and still exits 0. The index does not depend on either of those.

Python 3.10 or newer must already be on `PATH` as `python3` (or `python3.10` through `python3.14`). On Debian or Ubuntu the venv module is a separate package: if `./setup.sh` fails while creating the virtualenv, install `python3-venv` and run `./setup.sh` again.

Replace `/path/to/notes` with a real directory of `.md` or `.txt` notes. A handful of files is enough.

## Commands

```sh
git clone https://github.com/ohsuvorav/alma-brain
cd alma-brain
./setup.sh
./brain init --yes /path/to/notes
# or, to import without nightly jobs or the Claude Code connection:
# ./brain init --yes --no-schedule --no-connect /path/to/notes
./brain doctor
```

Then open Claude Code and ask normally. Per-tool config: [Claude Code](docs/agents/claude-code.md), [Cursor](docs/agents/cursor.md), [Codex](docs/agents/codex.md).

`./brain` is the launcher in this checkout. The shell that ran `./setup.sh` does not see `~/.local/bin` yet. Keep using `./brain` in that shell. A new shell can use `brain` from `~/.local/bin`. Doctor fix lines are spelled `brain ...`. If that command is not found, run the same words with `./` from this checkout. The brain directory is `~/Alma` unless `ALMA_HOME` or `--brain` is set.

Non-interactive import needs `--yes`. Without it, and without a terminal, init prints the scope and exits 2 without creating a brain. `--in-place --yes` indexes the folder where it is instead of copying. A single `.md` or `.txt` file is a memory export and is copied to `raw/imports/memory/`.

## Expected output

### `./setup.sh`

- Exit 0.
- A line containing `Alma: venv ready at` and `.team-brain/venv`.
- A line containing `Alma: linked brain`.
- A line containing `Alma: next:`.
- `~/.team-brain/venv/bin/python` exists.

If venv creation fails on Debian or Ubuntu, install `python3-venv` and run `./setup.sh` again.

### `./brain init --yes /path/to/notes`

- Exit 0.
- A scope line with the word `files` or `file`, and `KB` or `MB`.
- A line `Copying into` containing `raw/imports/`.
- A line `Embedding model intfloat/multilingual-e5-small`.
- A line `Index built:`.
- A line `Next: open Claude Code and ask normally.`
- With `--yes`, one `installed` line per nightly job, including a time `HH:MM`, then `brain schedule status` and `brain schedule uninstall`.
- With `--no-schedule`, a line containing `--no-schedule` and no `installed` line.
- When Claude Code is detected, a line `Connected Claude Code: MCP server alma and the UserPromptSubmit hook.`
- When Claude Code is not detected, one line that starts with `Claude Code was not found`.
- On either of those, a Cursor block that mentions `.cursor/mcp.json` and a Codex block that mentions `config.toml`. Those files are not written.
- With `--no-connect`, a line containing `--no-connect` and no `.cursor/mcp.json` block.
- The first time, a Hugging Face warning about unauthenticated requests may appear on the way to `Index built:`. That warning is not a failure. No token is required.
- `teambrain.yaml` contains `schedule.jobs` with `index --incremental`, `lint`, and `snapshot raw`. `retro run` is included only when exactly one Claude Code project has transcripts and `claude` is installed. Codex chat import is not in this version.

An empty directory, or a path that is not notes, exits 2 and does not write `teambrain.yaml`. No path at all prints `brain init <path>` and exits 2.

### `./brain ask "..."`

- Exit 0.
- The output starts with `Context Alma would inject:`.
- The output contains a source path under `raw/imports/` (or the in-place path).
- Alma does not call `claude` to compose an answer.

### `./brain doctor`

- Exit 0 after a successful init.
- The last line is `brain doctor: ok`.
- Lines for Python, the venv, the embedding model, a fresh index, valid `teambrain.yaml`, MCP, the prompt hook, the scheduler, and sources.
- After `--yes`, the scheduler line is `ok    scheduler installed (N jobs)` with N at least 3.
- When Claude Code was connected: `ok    mcp connected (claude)` and `ok    prompt hook installed`.
- Otherwise: `ok    mcp not connected (optional)` and `ok    prompt hook not installed (optional)`, each followed by a `fix:` line. That is still exit 0.
- A scheduler line `not installed (optional)` means cron or launchd was missing. Init still exited 0.

A failed required check is two lines:

```text
fail  index missing
      fix: brain index
```

A missing model cache looks like this. The index can still be reported fresh, because the vectors are already on disk. The fix downloads the model again by rebuilding the index:

```text
fail  embedding model not downloaded (intfloat/multilingual-e5-small)
      fix: brain index
note  brain is not on PATH in this terminal. From this checkout run it as ./brain (for example ./brain index). A new terminal can use brain.
```

The `note` line is present only when `brain` is not on `PATH`. The process then exits non-zero. The last line is `brain doctor: N problem` or `brain doctor: N problems`. The fix line is a command. In this checkout, run it as `./brain index` until a new shell is opened.

## Verify

```sh
./brain doctor
```

Pass means exit code 0 and the last line is exactly `brain doctor: ok`.

Optional, still from this checkout. This prints the context a hook would inject for one prompt. It does not answer.

```sh
printf '%s\n' '{"prompt":"When does the harbor train leave?"}' | ./brain hook-search
```

Exit 0. The stdout is JSON with `hookSpecificOutput.additionalContext`, or empty when nothing is confident enough to inject.

```sh
printf 'quit\n' | ./brain review
```

Exit 0. Either `Nothing to review.` or one card and the prompt `keep / fix / archive / skip / undo`.

## Not a separate step

Nightly jobs, and the Claude Code connection when `claude` is already installed, are part of `./brain init --yes`. `brain onboard` is not required. Notion, Google Docs, and Codex chat import are not in this version.
