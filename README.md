readme_content = """# UNIFAP Student Financial Aid ETL Pipeline

A robust, automated Python-based ETL (Extract, Transform, Load) pipeline built for **UNIFAP (Universidade Federal do Amapá)**. This tool automates the process of ingestion, cleaning, cross-referencing, and generating compliance documentation for student financial assistance payroll sheets against official institutional data hosted on Metabase (`SIG-SIGAA`).

The final pipeline exports standardized audit logs, structured spreadsheets (`.xlsx`), and publication-ready, multi-page PDFs customized for the national **Portal de Transparência** (Transparency Portal).

---

## 🚀 Features

- **Robust Data Extraction & Cleaning**: 
  - Dynamic detection of assistance types and table headers from unformatted administrative CSV sheets.
  - Regex-based standardization of sensitive fields (e.g., stripping non-numeric punctuation from CPFs, handling floating-point anomalies, and padding strings with zero-fills).
- **Secure Metabase API Integration**:
  - Session-based JWT authentication via Metabase API endpoints.
  - Fail-safe configuration overriding local Windows system environment variable conflicts (e.g., standard `USERNAME` namespace collisions).
- **Smart Academic Record Resolution**:
  - Runs complex, multi-layered PostgreSQL queries directly over the `SIG-SIGAA` production database via API.
  - Built-in deduplication engine utilizing window functions (`ROW_NUMBER() OVER (PARTITION BY cpf)`) to automatically prioritize active student matriculations (`ATIVO`, `GRADUANDO`) over historical or terminal statuses (`CONCLUIDO`, `CANCELADO`, `TRANCADO`).
- **Automated Publication & Export Engine**:
  - **CSV Audit Trails**: Generates raw matching summaries for downstream system ingestion.
  - **Excel Ledger (`.xlsx`)**: Outputs styled spreadsheets featuring formatted data columns ready for financial auditing.
  - **Landscape Compliance PDF**: Generates professional, multi-page PDFs with institutional branding, a repeating dynamic table header across page boundaries, defensive string truncation (preventing table cell overflows), and real-time generation timestamps alongside automatic `X/Y` page-number counters.

---

## 🛠️ Project Structure