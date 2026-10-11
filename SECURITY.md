# Security

`csv-quality-report` is a local command-line tool and a GitHub Action. It reads a CSV and writes a report. The runtime does not open a network connection and it does not store credentials.

## Reporting a problem

If you find a security issue, open a private GitHub security advisory on this repository, or email Rodrigo Pantoja Navajas through the contact on the [profile README](https://github.com/rodrix91/rodrix91). Please do not open a public issue for an unfixed vulnerability.

## Scope

In scope: unexpected crashes, path handling, and output that could be misleading in a pipeline or a GitHub Action job. Out of scope: the contents of the CSV the user chooses to read.

A local secrets scan is documented in [CONTRIBUTING.md](CONTRIBUTING.md). It is a simple pattern check, not a substitute for a dedicated scanner.
