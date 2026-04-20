# How to setup the project

1. Create python virtual env and install all packages from `requirements.txt`
```bash
python3 -m venv .venv/
```

```bash
pip3 install -r requirements.txt
```

2. Initialize pre-commit hooks

```bash
pre-commit install
```

Now pre-commit hooks will run before every commit. You can also run them manually using command `pre-commit run --files <file>` or `pre-commit run --all-files`
