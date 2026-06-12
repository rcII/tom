# CI runner setup

CI (`.github/workflows/ci.yml`) runs on a **self-hosted runner scoped to this
repo**, on the `ubuntu-dev` label. The workflow is repo state; the runner is host
state, set up once. These are the steps.

## Prerequisites on the runner host

- Python 3.12 available to `actions/setup-python` (or system Python 3.12).
- Network access to GitHub.
- A user to own the runner (the team convention is a dedicated `github-runner`
  user with the runner under `/mnt/staging_xl/github-runner-<repo>/`).

The job installs `uv` itself and syncs the dev dependency group, so nothing
Python-specific needs preinstalling.

## Register the runner

A registration token is required (short-lived, repo-scoped). Generate it with the
GitHub CLI as a repo admin:

```sh
gh api -X POST repos/rcII/tom/actions/runners/registration-token --jq .token
```

Then, in the runner install directory:

```sh
./config.sh \
  --url https://github.com/rcII/tom \
  --token <REGISTRATION_TOKEN> \
  --labels self-hosted,linux,x64,ubuntu-dev \
  --name tom-runner \
  --unattended
```

The labels must include the four the workflow targets
(`self-hosted, linux, x64, ubuntu-dev`). Because the runner is scoped to this
repo, only this repo's jobs run on it — the shared label name is fine.

## Run it as a service

```sh
sudo ./svc.sh install <runner-user>
sudo ./svc.sh start
```

## Verify

Push a branch and open a PR; the `check` job should pick up on the runner and run
ruff + mypy --strict + pytest. `gh run list --repo rcII/tom` shows the runs.
