# Duke Paystub Parser

Parses Duke University/Health System monthly payroll PDFs into a pandas DataFrame, saves the data as a Parquet file, and generates a summary chart.

## What it does

- Extracts pay fields from each PDF: gross pay, net pay, taxes, pre-tax deductions, tax-deferred amounts, and 403(b) employee/employer contributions
- Saves all records to `paystubs.parquet` for easy reloading
- Prints a 403(b) contribution summary and an annual totals table
- Saves a two-panel chart (`paystub_summary.png`) showing 403(b) contributions and monthly pay trends

## Downloading your paystubs from Duke@Work

1. Go to [work.duke.edu](https://work.duke.edu) and sign in
2. Click **MyInfo** in the top navigation
3. Select **My Pay**
4. Click **View My Current and Past Statements**
5. For each month, click the **Download** button to save the PDF

Name the files in the format `Paystub_YYYYMM.pdf` (e.g. `Paystub_202601.pdf`) and place them all in this directory.

## Setup

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

```bash
python parse_paystubs.py
```

Output files (`paystubs.parquet`, `paystub_summary.png`) are git-ignored and will be created in the project directory.
