# Candy Description Generator - Quick Start

## First-time setup

```bash
cd ~/claude-code/tools/candy-description-generator
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Every time you open a new terminal

```bash
cd ~/claude-code/tools/candy-description-generator
source venv/bin/activate
```

## Running the generator

```bash
# Test on first 10 products
doppler run -- python generate.py --limit 10

# Test on first 50 products
doppler run -- python generate.py --limit 50

# Process all products
doppler run -- python generate.py

# Resume from where you left off
doppler run -- python generate.py --resume

# Custom input/output files
doppler run -- python generate.py --input input/my_products.csv --output output/my_results.csv
```

## Troubleshooting

- **`ModuleNotFoundError: No module named 'anthropic'`** - You forgot to activate the venv. Run `source venv/bin/activate`.
- **`externally-managed-environment`** - You're installing packages without the venv active. Run `source venv/bin/activate` first, then `pip install -r requirements.txt`.
