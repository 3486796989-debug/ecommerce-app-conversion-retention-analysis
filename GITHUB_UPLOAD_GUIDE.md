# GitHub Upload Guide

This project is ready to publish as a Data Analyst portfolio project.

## Recommended Repository Name

`ecommerce-app-conversion-retention-analysis`

## Files to Include

Commit these folders and files:

- `README.md`
- `requirements.txt`
- `.gitignore`
- `scripts/`
- `data/processed/`
- `report/`
- `notebooks/`

Do not commit:

- `.venv/`
- raw ZIP/CSV source files
- local logs or cache folders

## Option 1: Upload with Git

Install Git and GitHub CLI first, then run:

```powershell
git init
git add README.md requirements.txt .gitignore scripts data/processed report notebooks
git commit -m "Add e-commerce conversion and retention analysis"
git branch -M main
gh repo create ecommerce-app-conversion-retention-analysis --public --source=. --remote=origin --push
```

Use `--private` instead of `--public` if you want the repository to be private.

## Option 2: Upload from GitHub Website

1. Create a new repository on GitHub.
2. Use the repository name `ecommerce-app-conversion-retention-analysis`.
3. Choose public or private visibility.
4. Upload the project files from this folder, excluding `.venv/`.
5. Commit the uploaded files with this message:

```text
Add e-commerce conversion and retention analysis
```

## Suggested GitHub Description

```text
Data Analyst portfolio project analyzing e-commerce app user conversion, retention, revenue, product, brand, and price bucket performance using Python, pandas, NumPy, and matplotlib.
```

## Suggested Topics

```text
python pandas numpy matplotlib data-analysis ecommerce retention-analysis conversion-funnel cohort-analysis
```

