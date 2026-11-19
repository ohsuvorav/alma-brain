# team-brain engine

Code only. One engine, many brains (instances); each instance owns its content and config.

## Hard rules

- **No instance content here.** No wiki/raw/backlog text, names, customers, internal URLs or traces from any brain.
- **Eval cases and test fixtures are synthetic.** A failure found in an instance gets rewritten with made-up data before it lands here; the real case stays in that instance's `evals/`.
- **Instance-specific behavior = config.** Add a `teambrain.yaml` key with a default in `teambrain/config.py`. Never branch on an instance name, never fork per instance.
- **Hooks never block.** Any hook failure exits 0 silently.
- **No hardcoded paths.** Code resolves from `config.find_root()`; state goes to `cfg.state_dir`.

## Layout

- `bin/brain` — launcher (venv, PYTHONPATH, subcommands)
- `teambrain/` — config, index, search, server (MCP), hooks, query, backlog, loop, evals, transcripts, retro, lint, schedule, onboard, wip, suggest, init, ask, doctor, review
- `templates/teambrain.yaml` — instance config template
- `templates/` — also working rules, retro prompt/evals/axes, suggest prompt, workflow skills, sandboxed agent (all generic: no instance content)
- `tests/` — run with `brain`'s venv: `PYTHONPATH=. ~/.team-brain/venv/bin/python -m unittest discover tests`
