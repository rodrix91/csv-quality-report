# Reading Spanish and Latin American exports

Spreadsheet and ERP exports from Spanish- and Portuguese-speaking countries rarely look like the CSV files most tools expect: semicolons instead of commas, `1.234,56` instead of `1234.56`, `05/10/2026` meaning 5 October, `VERDADERO` instead of `true`, `s/d` for a missing value, `Gs. 50.000` in an amount column. Without the right options, those columns are reported as `string` and their ranges, means and type checks are lost.

csv-quality-report never guesses these conventions: each one is turned on with an explicit option, so a report never silently reinterprets a file. This guide shows which options to combine for each kind of export, using the files of the [end-to-end corpus](../../tests/corpus/README.md). Every command and output below is run by the test suite (`tests/test_guide.py`), so they match the current version exactly; `python scripts/update_guide.py` regenerates them.

## Which option for which problem

| What the export looks like | Option |
|---|---|
| `;`, tab or `\|` between fields | `--delimiter auto` (or the character) |
| A first line `sep=;` (Excel) | `--delimiter auto` follows it |
| Accents broken, `UnicodeDecodeError`, exit code 4 | `--encoding cp1252` (Excel on Windows) or `latin-1` |
| `10,5` | `--decimal-comma` |
| `1.234,56` or `1 234,56` | `--decimal-comma --thousands dot` (or `space`) |
| `05/10/2026`, `5/10/2026 14:30`, `10/5/2026 2:30 PM` | `--date-order dmy` (or `mdy`, `ymd`) |
| `VERDADERO`/`FALSO`, `Sí`/`No`, `S`/`N` | `--bool-words verdadero,falso --bool-words sí,no` |
| `s/d`, `N/A`, `-` for missing values | `--na s/d,N/A,-` |
| `$ 1.234,56`, `Gs. 50.000`, `12,5 kg`, `15 %` | `--number-affix '$' --number-affix Gs. ...` |
| `(1.234,56)` or `1.234,56-` for negatives | `--accounting-negatives` |
| A column that mixes currencies or units | `--max-affixes NAME=1` (with `--number-affix`) |
| An export whose columns or types changed since last time | `--baseline yesterday.json --fail-on-schema-change` |
| An export that arrived truncated, or a column that came back much emptier than last time | `--baseline yesterday.json --max-row-drop 10 --max-missing-increase 20` |
| Impossible values: negative weights, dates in 1900 | `--range Peso=0:` or `--range Fecha=2026-01-01:2026-12-31` |
| Times outside the period or shift | `--range Despacho=2026-01-01:2026-01-31` or `--range Despacho=2026-01-05T06:00:2026-01-05T22:00` |
| A wide export where only some columns matter | `--columns Remito,Despacho` |
| Very long text fields (descriptions, JSON) | `--max-field-size N` |

When a column still comes out as `string`, look at its `type_hint` (the `Mostly typed:` line in Markdown): it names the type that fits most cells and the values that block it, written exactly as they are in the file.

## A Spanish Excel export

Excel on Windows in Spanish saves "CSV (delimitado por comas)" in cp1252, with `;` separators, decimal commas and dot thousands separators. This file also uses `s/d` for missing values and has a duplicate row.

```console
$ python -m csv_quality_report tests/corpus/es_excel_cp1252.csv --encoding cp1252 --delimiter auto --decimal-comma --thousands dot --na s/d
```

```markdown
# CSV quality report: tests/corpus/es_excel_cp1252.csv

- Rows analyzed: 6
- Columns: 6
- Delimiter: semicolon (detected)
- Also counted as missing: `s/d`
- Encoding: cp1252
- Thousands separator: dot
- Duplicate rows: 1
- Untrimmed values: Cliente (1), Ciudad (1)

| Column | Type | Missing | Missing % | Distinct | Min | Max | Mean | Top 3 values |
|---|---|---|---|---|---|---|---|---|
| Fecha | date | 0 | 0.0 | 4 | 2026-01-05 | 2026-01-08 |  | 2026-01-06 (3), 2026-01-05 (1), 2026-01-07 (1) |
| Cliente | string | 0 | 0.0 | 3 |  |  |  | Comercial Peñaflor (3), Distribuidora Núñez (2), Importadora Güemes (1) |
| Ciudad | string | 0 | 0.0 | 3 |  |  |  | Asunción (3), São Paulo (2), Tarija (1) |
| Importe | float | 1 | 16.7 | 4 | 450.0 | 12345678.9 | 2469870.0 | 987,5 (2), 1.234,56 (1), 12.345.678,9 (1) |
| Unidades | int | 1 | 16.7 | 4 | 7 | 2000000 | 400255.0 | 35 (2), 1.200 (1), 2.000.000 (1) |
| Estado | string | 0 | 0.0 | 3 |  |  |  | entregado (3), en tránsito (2), demorado (1) |
```

`Importe` is a `float` with a real range and mean only because `--decimal-comma` and `--thousands dot` were given together; without `--thousands`, `1.234,56` would stay text.

## Excel's `sep=` line

Some tools write `sep=;` as the first line so that Excel opens the file with the right separator. With `--delimiter auto` the line is skipped and its separator is used; with a different delimiter the tool stops with exit code 7 instead of producing a one-column report.

```console
$ python -m csv_quality_report tests/corpus/excel_sep_hint.csv --encoding cp1252 --delimiter auto --decimal-comma --thousands dot --date-order dmy
```

```markdown
# CSV quality report: tests/corpus/excel_sep_hint.csv

- Rows analyzed: 6
- Columns: 5
- Delimiter: semicolon (declared by a sep= line)
- Encoding: cp1252
- Thousands separator: dot
- Date order: day/month/year
- Duplicate rows: 0

| Column | Type | Missing | Missing % | Distinct | Min | Max | Mean | Top 3 values |
|---|---|---|---|---|---|---|---|---|
| Depósito | string | 0 | 0.0 | 3 |  |  |  | Depósito Central (2), Sucursal Tarija (2), Sucursal Asunción (2) |
| SKU | string | 0 | 0.0 | 4 |  |  |  | A-100 (3), A-101 (1), B-200 (1) |
| Stock | int | 0 | 0.0 | 6 | 0 | 2040 | 615.833 | 1.250 (1), 80 (1), 310 (1) |
| Costo unitario | float | 0 | 0.0 | 5 | 7.25 | 1020.0 | 201.692 | 12,50 (2), 7,25 (1), 145,00 (1) |
| Última revisión | date | 0 | 0.0 | 3 | 2026-03-02 | 2026-03-09 |  | 02/03/2026 (2), 05/03/2026 (2), 09/03/2026 (2) |
```

## Day-first dates and times

`02/01/2026` is 2 January in an ERP configured for Spanish. `--date-order dmy` reads it so, also with a time (`02/01/2026 8:15`), and ISO values in the same column keep working. The range is reported in ISO 8601, which is unambiguous. An impossible date such as `30/02/2026` keeps the column as text and is named, and `--require-type` fails with that value in the message.

```console
$ python -m csv_quality_report tests/corpus/erp_day_first.csv --delimiter auto --decimal-comma --thousands dot --na s/d --date-order dmy --require-type Vencimiento=date
```

```markdown
# CSV quality report: tests/corpus/erp_day_first.csv

- Rows analyzed: 12
- Columns: 5
- Delimiter: semicolon (detected)
- Also counted as missing: `s/d`
- Thousands separator: dot
- Date order: day/month/year
- Duplicate rows: 0
- Mostly typed: Vencimiento is date except 1 value ("30/02/2026")

| Column | Type | Missing | Missing % | Distinct | Min | Max | Mean | Top 3 values |
|---|---|---|---|---|---|---|---|---|
| Remito | string | 0 | 0.0 | 12 |  |  |  | R-0001 (1), R-0002 (1), R-0003 (1) |
| Emisión | date | 0 | 0.0 | 11 | 2026-01-02 | 2026-02-14 |  | 02/01/2026 (2), 5/1/2026 (1), 12/01/2026 (1) |
| Despacho | datetime | 1 | 8.3 | 11 | 2026-01-02 08:15 | 2026-02-14 15:55 |  | 02/01/2026 8:15 (1), 02/01/2026 16:40 (1), 05/01/2026 9:05 (1) |
| Vencimiento | string | 0 | 0.0 | 11 |  |  |  | 01/02/2026 (2), 04/02/2026 (1), 11/02/2026 (1) |
| Peso kg | float | 1 | 8.3 | 11 | 75.25 | 3400.0 | 1202.45 | 1.250,5 (1), 980 (1), 2.100 (1) |

## Checks: FAILED (1 of 1 failed)

- FAIL: column 'Vencimiento' is string, expected date (1 value does not fit: "30/02/2026")
```

## `VERDADERO`/`FALSO` and `Sí`/`No`

Excel in Spanish writes logical values as `VERDADERO` and `FALSO`; many systems export flags as `Sí`/`No`. Name the words, in any case; `true`/`false` always count. One shipment is marked `Pendiente`, which keeps `Enviado` as text; the `Mostly typed` line names it, so it can be fixed at the source or added with `--na`.

```console
$ python -m csv_quality_report tests/corpus/excel_es_booleans.csv --delimiter auto --decimal-comma --thousands dot --date-order dmy --bool-words verdadero,falso --bool-words sí,no
```

```markdown
# CSV quality report: tests/corpus/excel_es_booleans.csv

- Rows analyzed: 12
- Columns: 5
- Delimiter: semicolon (detected)
- Thousands separator: dot
- Date order: day/month/year
- Boolean words (true/false): `verdadero`/`falso`, `sí`/`no`
- Duplicate rows: 0
- Mostly typed: Enviado is bool except 1 value ("Pendiente")

| Column | Type | Missing | Missing % | Distinct | Min | Max | Mean | Top 3 values |
|---|---|---|---|---|---|---|---|---|
| Pedido | string | 0 | 0.0 | 12 |  |  |  | P-101 (1), P-102 (1), P-103 (1) |
| Pagado | bool | 0 | 0.0 | 2 |  |  |  | VERDADERO (7), FALSO (5) |
| Enviado | string | 0 | 0.0 | 5 |  |  |  | Sí (6), No (3), SÍ (1) |
| Fecha | date | 0 | 0.0 | 11 | 2026-03-03 | 2026-03-17 |  | 03/03/2026 (2), 04/03/2026 (1), 05/03/2026 (1) |
| Total | float | 0 | 0.0 | 12 | 58.0 | 12800.0 | 1694.88 | 1.234,56 (1), 89,9 (1), 2.450 (1) |
```

## Currency symbols, units and mixed currencies

Invoices often write the currency or the unit next to each number. `--number-affix` removes the given texts, but only when a number remains, and reports per column how many cells had each one. Here the amounts mix guaraníes and dollars and one weight is in pounds, so their means are meaningless; `--max-affixes` turns that into a failed check (exit code 8) that a pipeline can stop on.

```console
$ python -m csv_quality_report tests/corpus/py_invoices_affixes.csv --delimiter auto --decimal-comma --thousands dot --na s/d --number-affix Gs. --number-affix 'US$' --number-affix kg --number-affix lb --number-affix % --max-affixes Monto=1 --max-affixes Peso=1
```

```markdown
# CSV quality report: tests/corpus/py_invoices_affixes.csv

- Rows analyzed: 8
- Columns: 4
- Delimiter: semicolon (detected)
- Also counted as missing: `s/d`
- Thousands separator: dot
- Duplicate rows: 0
- Number affixes: Monto (`Gs.` 6, `US$` 2); Peso (`kg` 6, `lb` 1); Descuento (`%` 7)

| Column | Type | Missing | Missing % | Distinct | Min | Max | Mean | Top 3 values |
|---|---|---|---|---|---|---|---|---|
| Factura | string | 0 | 0.0 | 8 |  |  |  | 001-0001 (1), 001-0002 (1), 001-0003 (1) |
| Monto | float | 0 | 0.0 | 8 | 25.5 | 2400000.0 | 534443.0 | Gs. 150.000 (1), Gs. 1.250.000 (1), US$ 25,50 (1) |
| Peso | float | 1 | 12.5 | 7 | 3.0 | 1200.0 | 304.179 | 12,5 kg (1), 800 kg (1), 3 lb (1) |
| Descuento | string | 0 | 0.0 | 5 |  |  |  | 10 % (2), 0 % (2), 5 % (2) |

## Checks: FAILED (2 of 2 failed)

- FAIL: column 'Monto' mixes 2 number affixes: "Gs." in 6 cells, "US$" in 2 cells (limit 1)
- FAIL: column 'Peso' mixes 2 number affixes: "kg" in 6 cells, "lb" in 1 cell (limit 1)
```

## Accounting negatives

Excel's accounting format writes negatives in parentheses and SAP writes a trailing minus. With `--accounting-negatives` both are read as negative numbers; in this trial balance, debits minus credits equal the sum of the balances, which only works out with the signs read correctly.

```console
$ python -m csv_quality_report tests/corpus/erp_balances_sap.csv --delimiter auto --decimal-comma --thousands dot --accounting-negatives
```

```markdown
# CSV quality report: tests/corpus/erp_balances_sap.csv

- Rows analyzed: 8
- Columns: 5
- Delimiter: semicolon (detected)
- Thousands separator: dot
- Accounting negatives: (5) and 5- read as -5
- Duplicate rows: 0

| Column | Type | Missing | Missing % | Distinct | Min | Max | Mean | Top 3 values |
|---|---|---|---|---|---|---|---|---|
| Cuenta | int | 0 | 0.0 | 8 | 1101 | 5301 | 3263.75 | 1101 (1), 1102 (1), 2101 (1) |
| Descripción | string | 0 | 0.0 | 8 |  |  |  | Caja (1), Bancos (1), Proveedores (1) |
| Debe | float | 0 | 0.0 | 6 | 0.0 | 250340.75 | 56341.4 | 0,00 (3), 12.500,00 (1), 250.340,75 (1) |
| Haber | float | 0 | 0.0 | 7 | 0.0 | 310000.0 | 50967.1 | 0,00 (2), 1.200,00 (1), 84.300,50 (1) |
| Saldo | float | 0 | 0.0 | 8 | -310000.0 | 249140.75 | 5374.38 | 12.500,00 (1), 249.140,75 (1), 84.300,50- (1) |
```

## In a pipeline

A daily job usually checks a few columns of a wide export, not all of them. Suppose the day-first ERP export above should hold only January dispatches. This job profiles only the delivery note, the dispatch time and the weight with `--columns`, and checks that every dispatch falls in January and no weight is negative or above a truck's load. Date bounds on a date-time column compare calendar days, so `2026-01-31` admits a dispatch at 23:59 that day. The file also holds February dispatches, so the job fails with exit code 8 and says which range was broken:

```console
$ python -m csv_quality_report tests/corpus/erp_day_first.csv --delimiter auto --decimal-comma --thousands dot --na s/d --date-order dmy --columns Remito,Despacho,'Peso kg' --range Despacho=2026-01-01:2026-01-31 --range 'Peso kg=0:5000'
```

```markdown
# CSV quality report: tests/corpus/erp_day_first.csv

- Rows analyzed: 12
- Columns: 3 of 5 (selected)
- Delimiter: semicolon (detected)
- Also counted as missing: `s/d`
- Thousands separator: dot
- Date order: day/month/year
- Duplicate rows: 0

| Column | Type | Missing | Missing % | Distinct | Min | Max | Mean | Top 3 values |
|---|---|---|---|---|---|---|---|---|
| Remito | string | 0 | 0.0 | 12 |  |  |  | R-0001 (1), R-0002 (1), R-0003 (1) |
| Despacho | datetime | 1 | 8.3 | 11 | 2026-01-02 08:15 | 2026-02-14 15:55 |  | 02/01/2026 8:15 (1), 02/01/2026 16:40 (1), 05/01/2026 9:05 (1) |
| Peso kg | float | 1 | 8.3 | 11 | 75.25 | 3400.0 | 1202.45 | 1.250,5 (1), 980 (1), 2.100 (1) |

## Checks: FAILED (1 of 2 failed)

- FAIL: column 'Despacho' has values outside 2026-01-01..2026-01-31 (min 2026-01-02 08:15, max 2026-02-14 15:55)
- pass: column 'Peso kg' is within 0..5000 (min 75.25, max 3400)
```

Date-times with a UTC offset (`2026-01-05T08:15-03:00`) are compared as instants, and their bounds need an offset too: a time without one could be in any zone, so the check fails and asks for one instead of guessing.

The same options work in the [GitHub Action](../../README.md#use-as-a-github-action) through its `args` input, and from Python as keyword arguments of `profile_file` (`decimal_comma=True`, `thousands="."`, `date_order="dmy"`, `bool_words=(("sí", "no"),)`, `number_affixes=("$",)`, `accounting_negatives=True`, `columns=("Remito", "Despacho")`), with the gates as arguments of `evaluate` (`column_ranges={"Despacho": (date(2026, 1, 1), date(2026, 1, 31))}`). Add `--json-output report.json` to keep the full report next to the Markdown summary.
