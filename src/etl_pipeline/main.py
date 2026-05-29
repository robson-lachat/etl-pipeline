# src/etl_pipeline/main.py
import pandas as pd
import requests
import os
from dotenv import load_dotenv

load_dotenv()


def clean_raw_data(file_path):
    print(f"Read raw file: {file_path}")
    # Change to pd.read_excel if downloading as .xlsx
    df = pd.read_csv(file_path, header=None, dtype=str)

    # Initial exploration of the raw data
    print(f"Initial rows in raw data: {len(df)}")
    print("Columns in raw data:", df.columns.tolist())

    # --- STEP A: EXTRACT THE TYPE OF ASSISTANCE ---
    mask_auxilio = df[0].str.contains('TIPO DE AUXÍLIO:', case=False, na=False)
    df.loc[mask_auxilio, 'tipo_auxilio'] = df.loc[mask_auxilio,
                                                  0].str.replace(r'(?i)TIPO DE AUXÍLIO:\s*', '', regex=True)
    df['tipo_auxilio'] = df['tipo_auxilio'].ffill()

    mask_header = df[2] == 'CPF'

    if not mask_header.any():
        print("Error: No header row with 'CPF' found. Please check the input file format.")
        return [], None

    header_index = df[mask_header].index[0]

    header_names = df.iloc[header_index].tolist()

    # Ensure the last column is named 'tipo_auxilio'
    header_names[-1] = 'tipo_auxilio'
    df.columns = header_names

    df = df.iloc[header_index + 1:].copy()

    # --- STEP B: FORMAT CPFS ---
    df['cpf_limpo'] = df['CPF'].astype(str).str.replace(
        r'\.0$', '', regex=True).str.zfill(11)

    df = df[~df['cpf_limpo'].str.contains('nan|None', regex=True, na=False)]

    print(f"Cleaning completed! {len(df)} valid CPFs found.")
    return df['cpf_limpo'].tolist(), df


def fetch_metabase_data(missing_cpfs):
    if not missing_cpfs:
        print("No missing CPFs. Skipping Metabase.")
        return None

    print(f"Fetching {len(missing_cpfs)} students from Metabase...")
    base_url = "http://132.255.99.40:3001"

    # 1. Authentication to get the session token
    auth_payload = {
        # ./env file should have USERNAME and PASSWORD
        "username": os.getenv("USERNAME"),
        "password": os.getenv("PASSWORD")
    }
    session_res = requests.post(f"{base_url}/api/session", json=auth_payload)
    token = session_res.json().get("id")

    headers = {
        "Content-Type": "application/json",
        "X-Metabase-Session": token
    }

    # 2. Format CPFs for SQL ('0400...','0571...')
    cpfs_formatted = ",".join([f"'{cpf}'" for cpf in missing_cpfs])

    # 3. A Query
    sql_query = f"""
        SELECT pessoa.nome, pessoa.cpf_cnpj, aluno.matricula
        FROM comum.pessoa
        INNER JOIN academico.aluno ON aluno.id_pessoa = pessoa.id_pessoa
        WHERE pessoa.cpf_cnpj IN ({cpfs_formatted})
    """

    # 4. Send the query
    query_payload = {
        "database": 1,  # PAY ATTENTION: This is the ID of the database in Metabase, it might be different in your setup
        "type": "native",
        "native": {"query": sql_query}
    }

    data_res = requests.post(
        f"{base_url}/api/dataset", json=query_payload, headers=headers)

    # Convert the response from Metabase into a Pandas DataFrame
    rows = data_res.json().get("data", {}).get("rows", [])
    cols = [col["name"]
            for col in data_res.json().get("data", {}).get("cols", [])]

    metabase_df = pd.DataFrame(rows, columns=cols)
    print("Data from Metabase downloaded successfully!")
    return metabase_df


def run_pipeline():
    print("="*40)
    print("Initializing ETL Pipeline - UNIFAP")
    print("="*40)

    # Configure directories
    base_dir = os.getcwd()
    input_dir = os.path.join(base_dir, 'input')
    out_dir = os.path.join(base_dir, 'out')

    # Create directories if they don't exist
    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    # Configure the path to the raw data file
    # Put the Sheets spreadsheet here
    raw_file = os.path.join(input_dir, 'PAGAMENTO - FOLHA JANEIRO26.csv')

    # Check if the raw file exists before proceeding
    if not os.path.exists(raw_file):
        print(f"File not found: {raw_file}")
        return

    # 1. Clean the data
    list_cpfs, df_limpo = clean_raw_data(raw_file)
    cpfs_missing = list_cpfs

    # 2. Search in Metabase
    df_novos_alunos = fetch_metabase_data(cpfs_missing)

    if df_novos_alunos is not None:
        print("\nPreview finded news tudents:")
        print(df_novos_alunos.head())  # Show 5 first lines in the terminal


if __name__ == "__main__":
    run_pipeline()
